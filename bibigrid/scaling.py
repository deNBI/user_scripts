#!/usr/bin/python3
import filecmp
import os
import shutil
import socket
import sys
from getpass import getpass
from pathlib import Path
import requests
import yaml
import argparse

VERSION = "0.8.0"
HOME = str(Path.home())
PLAYBOOK_DIR = os.path.join(HOME, "playbook")
PLAYBOOK_VARS_DIR = os.path.join(PLAYBOOK_DIR, "vars")
COMMON_VARS_FILE = os.path.join(PLAYBOOK_VARS_DIR, "common_configuration.yaml")

ANSIBLE_HOSTS_FILE = os.path.join(PLAYBOOK_DIR, "ansible_hosts")
ANSIBLE_HOSTS_ENTRIES = os.path.join(PLAYBOOK_VARS_DIR, "hosts.yaml")
PLAYBOOK_GROUP_VARS_DIR = os.path.join(PLAYBOOK_DIR, "group_vars")
HOST_VARS_DIR = os.path.join(PLAYBOOK_DIR, "host_vars")
SCALING_TYPE = "manualscaling"
CLUSTER_INFO_URL = (
    "https://simplevm-dev.bi.denbi.de/portal/api/autoscaling/{cluster_id}/scale-data/"
)
SCALING_SCRIPT_LINK = (
    "https://raw.githubusercontent.com/deNBI/user_scripts/master/bibigrid/scaling.py"
)
CLUSTER_OVERVIEW = "https://simplevm.denbi.de/portal/webapp/#/clusters/overview"
WRONG_PASSWORD_MSG = f"The password seems to be wrong. Please verify it again, otherwise you can generate a new one on the Cluster Overview ({CLUSTER_OVERVIEW})"
OUTDATED_SCRIPT_MSG = f"Your script is outdated [VERSION: {{SCRIPT_VERSION}} - latest is {{LATEST_VERSION}}] - please download the current script and run it again!\nYou can download the current script via:\n\nwget -O scaling.py {SCALING_SCRIPT_LINK}"


def main():
    args = parse_arguments()
    if args.version:
        print(f"Version: {VERSION}")
        sys.exit()
    if args.password:
        print("Password provided via arg..")
        password = args.password
    else:
        password = get_password()
    if args.force:
        print(f"Force Parameter Provided... Force Playbook Run")

    file_changed = update_all_yml_files(password)

    if file_changed:
        print("Files changed. Running playbook...")
        run_ansible_playbook()
    elif args.force:
        print("Force run requested. Running playbook...")
        run_ansible_playbook()
    else:
        print(
            "No changes detected and no force run requested. Skipping playbook execution."
        )


def parse_arguments():
    parser = argparse.ArgumentParser(description="Cluster Scaling Script")
    parser.add_argument(
        "-v", "--version", action="store_true", help="Show the version and exit"
    )
    parser.add_argument("-f", "--force", action="store_true", help="Force Playbook Run")
    parser.add_argument(
        "-p", "--password", type=str, required=False, help="Provide Password via Arg"
    )
    return parser.parse_args()


def get_password():
    password = getpass("Please enter your cluster password (input will be hidden): ")
    if not password:
        print("Password must not be empty!")
        sys.exit(1)
    return password


def update_all_yml_files(password):
    print("Initiating scaling...")
    data = get_cluster_data(password)

    if not data:
        print("Failed to retrieve scaling data.")
        return False
    groups_vars = data.get("groups_vars", {})
    hosts_entries = data.get("host_entries", {})
    ansible_hosts = data.get("ansible_hosts", {})
    cluster_cidrs = data.get("cluster_cidrs", [])
    workers_vars = data.get("workers")
    try:
        changed_hosts = replace_ansible_hosts(ansible_hosts)
        print(f"changed hosts --> {changed_hosts}")
        changed_host_entries = replace_host_entries(hosts_entries)
        print(f"changed changed_host_entries --> {changed_host_entries}")

        changed_groups = replace_group_vars(groups_vars)
        print(f"changed changed_groups --> {changed_groups}")

        changed_cidrs = replace_cluster_cidrs(new_cidrs=cluster_cidrs)
        print(f"changed cidr --> {changed_cidrs}")

        changed_volumes = replace_volumes_entries(workers_vars)
        print(f"changed volumes --> {changed_volumes}")

        return (
            changed_hosts
            or changed_host_entries
            or changed_groups
            or changed_cidrs
            or changed_volumes
        )

    except:
        print(f"Could not get hosts entries! -- {data}")
        sys.exit(1)
    return False


def replace_volumes_entries(workers_vars):
    changed = False

    expected_files = set()

    for worker in workers_vars:
        hostname = worker.get("hostname")
        volumes = worker.get("volumes")

        if not hostname or volumes is None:
            continue  # Skip malformed entries

        file_name = f"{hostname}.yaml"
        file_path = os.path.join(HOST_VARS_DIR, file_name)
        expected_files.add(file_name)

        # Serialize the volumes into YAML format
        yaml_data = yaml.dump({"volumes": volumes}, default_flow_style=False)

        # Replace the file if content has changed
        file_changed = replace_if_changed(file_path, yaml_data)

        if file_changed:
            changed = True

    # Remove unexpected files
    for file in os.listdir(HOST_VARS_DIR):
        if file.endswith(".yaml") and file not in expected_files:
            full_path = os.path.join(HOST_VARS_DIR, file)
            os.remove(full_path)
            changed = True

    return changed

def replace_group_vars(groups_vars):
    changed = False
    expected_files = set()

    for key, value in groups_vars.items():
        if key == "master":
            continue  # Do not manage master.yaml

        file_name = f"{key}.yaml"
        file_path = os.path.join(PLAYBOOK_GROUP_VARS_DIR, file_name)
        expected_files.add(file_name)

        yaml_data = yaml.dump(value, default_flow_style=False)

        file_changed = replace_if_changed(file_path, yaml_data)
        if file_changed:
            changed = True

    # Clean up unexpected files, except master.yaml
    for file in os.listdir(PLAYBOOK_GROUP_VARS_DIR):
        if file.endswith(".yaml") and file not in expected_files and file != "master.yaml":
            full_path = os.path.join(PLAYBOOK_GROUP_VARS_DIR, file)
            os.remove(full_path)
            changed = True

    return changed

def replace_host_entries(hosts_entries):
    return replace_if_changed(
        ANSIBLE_HOSTS_ENTRIES, yaml.dump(hosts_entries, default_flow_style=False)
    )


def replace_ansible_hosts(ansible_hosts):
    return replace_if_changed(
        ANSIBLE_HOSTS_FILE, yaml.dump(ansible_hosts, default_flow_style=False)
    )


def replace_cluster_cidrs(new_cidrs: list[str]) -> bool:
    with open(COMMON_VARS_FILE, "r") as f:
        data = yaml.safe_load(f)

    changed = False
    for cluster in data.get("cluster_cidrs", []):
        current_cidrs = cluster.get("provider_cidrs", [])
        if current_cidrs != new_cidrs:
            cluster["provider_cidrs"] = new_cidrs
            changed = True

    if changed:
        yaml_content = yaml.safe_dump(data, default_flow_style=False)
        return replace_if_changed(COMMON_VARS_FILE, yaml_content)
    return False


def replace_if_changed(file_path, new_content):
    is_new_file = not os.path.exists(file_path)

    if not is_new_file:
        with open(file_path, "r") as f:
            current_content = f.read()
        has_changed = current_content != new_content
    else:
        has_changed = True

    with open(file_path, "w") as f:
        f.write(new_content)

    os.chmod(file_path, 0o770)

    return has_changed


def get_cluster_data(password):
    try:
        res = requests.post(
            url=get_cluster_info_url(),
            json={
                "scaling": "scaling_up",
                "scaling_type": SCALING_TYPE,
                "password": password,
                "version": VERSION,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"HTTP Request failed: {e}")
        sys.exit(1)

    if res.status_code == 200:
        data_json = res.json()
        if data_json.get("VERSION") != VERSION:
            print(
                OUTDATED_SCRIPT_MSG.format(
                    SCRIPT_VERSION=VERSION, LATEST_VERSION=data_json["VERSION"]
                )
            )
            sys.exit(1)
        return data_json

    handle_http_errors(res)
    return None


def handle_http_errors(response):
    if response.status_code == 401:
        print(WRONG_PASSWORD_MSG)
    elif response.status_code in [400, 405]:
        error_msg = response.json().get("error", "An unspecified error occurred.")
        print(error_msg)
    else:
        print(f"Unexpected HTTP error: {response.status_code}")

    sys.exit(1)


def get_cluster_info_url():
    cluster_id = socket.gethostname().split("-")[-1]
    print(f"clsuter id {cluster_id}")
    return CLUSTER_INFO_URL.format(cluster_id=cluster_id)


def run_ansible_playbook():
    os.chdir(PLAYBOOK_DIR)
    forks = os.cpu_count() * 4
    ansible_command = (
        f"bibiplay --forks {forks} --limit '!bibigrid-worker-autoscaling-dummy'"
    )
    print(f"Running Ansible Command:\n{ansible_command}")
    os.system(ansible_command)


if __name__ == "__main__":
    main()
