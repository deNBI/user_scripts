#!/usr/bin/python3
import os
import re
import socket
import sys
from getpass import getpass
from pathlib import Path

import requests
import yaml

VERSION = "0.3.0"
HOME = str(Path.home())
PLAYBOOK_DIR = HOME + '/playbook'
PLAYBOOK_VARS_DIR = HOME + '/playbook/vars'
ANSIBLE_HOSTS_FILE = PLAYBOOK_DIR + '/ansible_hosts'
INSTANCES_YML = PLAYBOOK_VARS_DIR + '/instances.yml'
CLUSTER_INFO_URL = "https://cloud.denbi.de/portal/public/clusters/"
CLUSTER_OVERVIEW = "https://cloud.denbi.de/portal/webapp/#/virtualmachines/clusterOverview"
WRONG_PASSWORD_MSG = f"The password seems to be wrong. Please verify it again, otherwise you can generate a new one for the cluster on the Cluster Overview ({CLUSTER_OVERVIEW})"
OUTDATED_SCRIPT_MSG = "Your script is outdated [VERSION: {SCRIPT_VERSION} - latest is {LATEST_VERSION}] -  please download the current script and run it again!"


class ScalingDown:

    def __init__(self, password):
        self.password = password
        self.data = self.get_scaling_down_data()
        self.valid_delete_ips = [ip for ip in self.data["private_ips"] if ip is not None and self.validate_ip(ip)]
        self.master_data = self.data["master"]

        if len(self.valid_delete_ips) > 0:

            self.remove_worker_from_instances()
            self.delete_ip_yaml()
            self.remove_ip_from_ansible_hosts()
        else:
            print("No valid Ips found!")

    def get_scaling_down_data(self):
        res = requests.post(url=get_cluster_info_url(),
                            json={"scaling": "scaling_down", "password": self.password},
                            )
        if res.status_code == 200:
            data_json = res.json()
            version = data_json["VERSION"]
            if version != VERSION:
                print(OUTDATED_SCRIPT_MSG.format(SCRIPT_VERSION=VERSION, LATEST_VERSION=version))
                sys.exit(1)
        else:
            print(WRONG_PASSWORD_MSG)
            sys.exit(1)
        return res.json()

    def validate_ip(self, ip):
        print("Validate  IP: ", ip)
        valid = re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)
        if not valid:
            print("{} is no valid Ip! SKIPPING".format(ip))
        return valid

    def remove_worker_from_instances(self):
        print("Removing workers from instances")
        with open(INSTANCES_YML, 'a+') as stream:
            stream.seek(0)
            try:
                instances = yaml.safe_load(stream)
                if not instances:
                    instances = {"workers": [], "deletedWorkers": [], "master": self.master_data}
                instances_copy = instances.copy()
                for idx, worker in enumerate(instances['workers']):
                    if worker['ip'] in self.valid_delete_ips:
                        instances_copy['deletedWorkers'].append(worker)
                        instances_copy['workers'].pop(idx)
                stream.seek(0)
                stream.truncate()
                yaml.dump(instances, stream)
            except yaml.YAMLError as exc:
                print(exc)
                sys.exit(1)

    def delete_ip_yaml(self):
        print("Delete yaml file")
        for ip in self.valid_delete_ips:
            yaml_file = PLAYBOOK_VARS_DIR + '/' + ip + '.yml'
            if os.path.isfile(yaml_file):
                print("Found: ", yaml_file)
                os.remove(yaml_file)
                print("Deleted: ", yaml_file)
            else:
                print("Yaml already deleted: ", yaml_file)

    def remove_ip_from_ansible_hosts(self):

        print("Remove ips from ansible_hosts")
        lines = []
        with open(ANSIBLE_HOSTS_FILE, 'r+') as ansible_hosts:
            for line in ansible_hosts:
                if not any(bad_word in line for bad_word in self.valid_delete_ips):
                    lines.append(line)
            ansible_hosts.seek(0)
            ansible_hosts.truncate()
            for line in lines:
                ansible_hosts.write(line)


class ScalingUp:

    def __init__(self, password):
        self.password = password
        self.data = self.get_cluster_data()
        self.master_data = self.data["master"]
        self.cluster_data = [worker for worker in self.data["active_worker"] if
                             worker is not None and worker["status"] == "ACTIVE" and worker["ip"] is not None]
        self.valid_upscale_ips = [cl["ip"] for cl in self.cluster_data]
        if len(self.cluster_data) > 0:
            workers_data = self.create_yml_file()
            self.add_new_workers_to_instances(worker_data=workers_data)
            self.add_ips_to_ansible_hosts()
        else:
            print("No active worker found!")

    def get_cluster_data(self):

        res = requests.post(url=get_cluster_info_url(),
                            json={"scaling": "scaling_up", "password": self.password})
        if res.status_code == 200:
            res = res.json()
            version = res["VERSION"]
            if version != VERSION:
                print(OUTDATED_SCRIPT_MSG.format(SCRIPT_VERSION=VERSION, LATEST_VERSION=version))
                sys.exit(1)
            return res
        else:
            print(WRONG_PASSWORD_MSG)
            sys.exit(1)

    def validate_ip(self, ip):
        print("Validate  IP: ", ip)
        return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)

    def add_new_workers_to_instances(self, worker_data):
        print("Add workers to instances")
        with open(INSTANCES_YML, 'a+') as stream:
            stream.seek(0)

            try:
                instances = yaml.safe_load(stream)
                if not instances:
                    instances = {"workers": [], "deletedWorkers": [], "master": self.master_data}
                worker_ips = [worker['ip'] for worker in instances['workers']]
                for new_worker in worker_data:
                    if not new_worker['ip'] in worker_ips:
                        instances['workers'].append(new_worker)
                    else:
                        print("Worker with IP {} already registered!".format(new_worker['ip']))
                stream.seek(0)
                stream.truncate()
                yaml.dump(instances, stream)
            except yaml.YAMLError as exc:
                print(exc)
                sys.exit(1)

    def create_yml_file(self):
        workers_data = []
        for data in self.cluster_data:
            yaml_file_target = PLAYBOOK_VARS_DIR + '/' + data['ip'] + '.yml'
            if not os.path.exists(yaml_file_target):
                with  open(yaml_file_target, 'w+') as target:
                    try:
                        yaml.dump(data, target)
                    except yaml.YAMLError as exc:
                        print(exc)
                        sys.exit(1)
            else:
                print("Yaml for worker with IP {} already exists".format(data['ip']))
            workers_data.append(data)

        return workers_data

    def add_ips_to_ansible_hosts(self):
        print("Add ips to ansible_hosts")
        with open(ANSIBLE_HOSTS_FILE, "r") as in_file:
            buf = in_file.readlines()

        with open(ANSIBLE_HOSTS_FILE, "w") as out_file:
            for line in buf:
                if "[workers]" in line:
                    for ip in self.valid_upscale_ips:
                        ip_line = f"{ip} ansible_connection=ssh ansible_python_interpreter=/usr/bin/python3 ansible_user=ubuntu\n"
                        if not ip_line in buf:
                            line = line + ip_line + "\n"
                out_file.write(line)


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
    os.system(f'ansible-playbook -v -i ansible_hosts  --forks {forks}  site.yml')


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
        ScalingDown(password=password)
        ScalingUp(password=password)
        run_ansible_playbook()
