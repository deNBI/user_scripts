#!/usr/bin/python3
import filecmp
import os
import re
import socket
import sys
from getpass import getpass
from pathlib import Path

import requests
import yaml

VERSION = "0.5.0"
HOME = str(Path.home())
PLAYBOOK_DIR = HOME + '/playbook'
PLAYBOOK_VARS_DIR = HOME + '/playbook/vars'
ANSIBLE_HOSTS_FILE = PLAYBOOK_DIR + '/ansible_hosts'
INSTANCES_YML = PLAYBOOK_VARS_DIR + '/instances.yml'
COMMON_CONFIGURATION_YML = PLAYBOOK_VARS_DIR + '/common_configuration.yml'
CLUSTER_INFO_URL = "https://cloud.denbi.de/portal/public/clusters/"
CLUSTER_OVERVIEW = "https://cloud.denbi.de/portal/webapp/#/virtualmachines/clusterOverview"
WRONG_PASSWORD_MSG = f"The password seems to be wrong. Please verify it again, otherwise you can generate a new one for the cluster on the Cluster Overview ({CLUSTER_OVERVIEW})"
OUTDATED_SCRIPT_MSG = "Your script is outdated [VERSION: {SCRIPT_VERSION} - latest is {LATEST_VERSION}] -  please download the current script and run it again!"


def update_all_yml_files(password):
    print("initiate scaling")
    data = get_cluster_data(password)
    replace_cidr_for_nsf_mount()
    if data is None:
        print("get scaling  data: None")
        return False
    master_data = data["master"]
    cluster_data = [
        worker
        for worker in data["active_worker"]
        if worker is not None
           and worker["status"] == "ACTIVE"
           and worker["ip"] is not None
    ]

    valid_upscale_ips = [cl["ip"] for cl in cluster_data]
    print(f"Current Worker IPs: {valid_upscale_ips}")

    delete_workers_ip_yaml(valid_upscale_ips=valid_upscale_ips)

    if cluster_data:
        workers_data = create_worker_yml_file(cluster_data=cluster_data)

    else:
        print("No active worker found!")
        workers_data = []
    workers_file_changed = update_workers_yml(
        worker_data=workers_data, master_data=master_data
    )
    host_file_changed = add_ips_to_ansible_hosts(valid_upscale_ips=valid_upscale_ips)
    return host_file_changed or workers_file_changed


def get_cluster_data(password):
    res = requests.post(url=get_cluster_info_url(),
                        json={"scaling": "scaling_up", "password": password, "version": VERSION})
    if res.status_code in [405, 400]:
        print(res.json()["error"])
        sys.exit(1)
    elif res.status_code == 200:

        data_json = res.json()
        version = data_json["VERSION"]
        if version != VERSION:
            print(OUTDATED_SCRIPT_MSG.format(SCRIPT_VERSION=VERSION, LATEST_VERSION=version))
            sys.exit(1)
    elif res.status_code == 401:

        print(WRONG_PASSWORD_MSG)
        sys.exit(1)
    elif res.status_code == 400:
        print("An error occured please contact cloud support")
    return res.json()


def update_workers_yml(master_data, worker_data, dummy_worker):
    print("Update Worker YAML")
    print(f"Update Worker Yaml with data: - {worker_data}")
    new_file = ANSIBLE_HOSTS_FILE + ".tmp"  # Temporary file to store modified contents

    instances_mod = {
        "workers": worker_data,
        "deletedWorkers": [],
        "master": master_data,
    }
    if dummy_worker is not None:
        instances_mod["workers"].append(dummy_worker)
    worker_ips = set()
    unique_workers = []

    for worker in worker_data:
        ip = worker["ip"]
        if ip not in worker_ips:
            unique_workers.append(worker)
            worker_ips.add(ip)
    instances_mod["workers"] = unique_workers
    print(f"New Instance YAML:\n  {instances_mod}")

    with open(new_file, "w", encoding="utf8") as in_file:
        try:
            yaml.dump(instances_mod, in_file)
        except yaml.YAMLError as exc:
            print("YAML Error: %s", exc)
            sys.exit(1)
    workers_file_changed = not filecmp.cmp(INSTANCES_YML, new_file)

    if workers_file_changed:
        print("Workers  file has changed!")
        # Replace the original file with the modified file
        os.replace(new_file, INSTANCES_YML)
    else:
        # Remove the temporary file
        print("Workers  file has NOT changed!")

        os.remove(new_file)

    return workers_file_changed


def replace_cidr_for_nsf_mount():
    print("Get CIDR from common configuration")
    with open(COMMON_CONFIGURATION_YML, "r", encoding="utf8") as stream:

        try:
            common_configuration_data = yaml.safe_load(stream)
            cidr = common_configuration_data["CIDR"]
            print(f"Current CIDR: {cidr}")
            new_cidr = cidr[:7] + ".0.0/16"
            if cidr == new_cidr:
                print("CIDR is already fixed!")
                return
            common_configuration_data["CIDR"] = new_cidr

        except yaml.YAMLError as exc:
            print(exc)
            sys.exit(1)
    with open(COMMON_CONFIGURATION_YML, "w", encoding="utf8") as f:
        print(f"Replace old CIDR with: {new_cidr}")
        yaml.dump(common_configuration_data, f)


def validate_ip(ip):
    print("Validate  IP: ", ip)
    return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)


def create_worker_yml_file(cluster_data):
    workers_data = []
    for data in cluster_data:
        yaml_file_target = PLAYBOOK_VARS_DIR + "/" + data["ip"] + ".yml"
        if not os.path.exists(yaml_file_target):
            with open(yaml_file_target, "w+", encoding="utf8") as target:
                try:
                    yaml.dump(data, target)
                except yaml.YAMLError as exc:
                    print("YAMLError ", exc)
                    sys.exit(1)
        else:
            print(f"Yaml for worker with IP {data['ip']} already exists")
        workers_data.append(data)

    return workers_data


def delete_workers_ip_yaml(valid_upscale_ips):
    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    files = os.listdir(PLAYBOOK_VARS_DIR)
    ip_addresses = []
    for file in files:
        match = re.search(ip_pattern, file)
        if match:
            ip_addresses.append(match.group())
    for ip in ip_addresses:
        if ip not in valid_upscale_ips:
            yaml_file = PLAYBOOK_VARS_DIR + "/" + ip + ".yml"
            if os.path.isfile(yaml_file):
                os.remove(yaml_file)
                print("Deleted YAML ", yaml_file)

            else:
                print("Yaml already deleted: ", yaml_file)


def add_ips_to_ansible_hosts(valid_upscale_ips) -> bool:
    print("Add IPs to ansible_hosts")

    original_file = ANSIBLE_HOSTS_FILE
    new_file = ANSIBLE_HOSTS_FILE + ".tmp"  # Temporary file to store modified contents

    with open(original_file, "r", encoding="utf8") as in_file:
        lines = in_file.readlines()

    with open(new_file, "w", encoding="utf8") as out_file:
        found_workers = False
        for line in lines:
            if "[workers]" in line:
                found_workers = True
                out_file.write(line)
                for ip in valid_upscale_ips:
                    ip_line = f"{ip} ansible_connection=ssh ansible_python_interpreter=/usr/bin/python3 ansible_user=ubuntu\n"
                    out_file.write(ip_line)
            elif not found_workers:
                out_file.write(line)

    hosts_file_changed = not filecmp.cmp(original_file, new_file)

    if hosts_file_changed:
        print("Ansible Host file has changed!")
        # Replace the original file with the modified file
        os.replace(new_file, original_file)
    else:
        # Remove the temporary file
        print("Ansible Host file has NOT changed!")

        os.remove(new_file)

    return hosts_file_changed


def get_version():
    print("Version: ", VERSION)


def get_cluster_id_by_hostname():
    hostname = socket.gethostname()
    cluster_id = hostname.split('-')[-1]
    return cluster_id


def get_cluster_info_url():
    cluster_id = get_cluster_id_by_hostname()

    full_info_url = f"{CLUSTER_INFO_URL}{cluster_id}/"
    return full_info_url


def run_ansible_playbook():
    os.chdir(PLAYBOOK_DIR)
    forks = os.cpu_count() * 4
    ansible_command = f"ansible-playbook -v  --forks {forks} -i ansible_hosts  site.yml"
    print(f"Run Ansible Command:\n{ansible_command}")
    os.system(ansible_command)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ["-v", "--v", "-version", "--version"]:
            get_version()
        else:
            print("No usage found for param: ", arg)
    else:
        print("Please enter your cluster password:")
        password = getpass()
        if not password:
            print("Password must not be empty!")
            sys.exit(1)
        file_changed = update_all_yml_files(password=password)
        if file_changed:
            print("Files changed running playbook")

            run_ansible_playbook()
        else:
            print("No changes -- skipping playbook")
