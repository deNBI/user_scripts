#!/usr/bin/python3
import os
import re
import socket
import sys
from getpass import getpass
from pathlib import Path

import requests
import yaml

VERSION = "0.2.0"
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
        ips = self.get_private_ips()
        valid_ips = []
        for ip in ips:
            if not self.validate_ip(ip):
                print("{} is no valid Ip! SKIPPING".format(ip))
                continue
            else:
                valid_ips.append(ip)
        if len(valid_ips) > 0:

            self.remove_worker_from_instances(ips=valid_ips)
            self.delete_ip_yaml(ips=valid_ips)
            self.remove_ip_from_ansible_hosts(ips=valid_ips)
        else:
            print("No valid Ips found!")

    def get_private_ips(self):
        global CLUSTER_INFO_URL
        res = requests.post(url=CLUSTER_INFO_URL,
                            json={"scaling": "scaling_down", "password": self.password},
                            )
        if res.status_code == 200:
            res = res.json()
            version = res["VERSION"]
            if version != VERSION:
                print(OUTDATED_SCRIPT_MSG.format(SCRIPT_VERSION=VERSION, LATEST_VERSION=version))
                sys.exit(1)
            ips = [ip for ip in res["private_ips"] if ip is not None]
            return ips
        else:
            print(OUTDATED_SCRIPT_MSG)
            sys.exit(1)

    def validate_ip(self, ip):
        print("Validate  IP: ", ip)
        return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)

    def remove_worker_from_instances(self, ips):
        print("Removing workers from instances")
        with open(INSTANCES_YML, 'r+') as stream:
            try:
                instances = yaml.safe_load(stream)
                instances_copy = instances.copy()
                for idx, worker in enumerate(instances['workers']):
                    if worker['ip'] in ips:
                        instances_copy['deletedWorkers'].append(worker)
                        instances_copy['workers'].pop(idx)
                stream.seek(0)
                stream.truncate()
                yaml.dump(instances, stream)
            except yaml.YAMLError as exc:
                print(exc)
                sys.exit(1)

    def delete_ip_yaml(self, ips):
        print("Delete yaml file")
        for ip in ips:
            yaml_file = PLAYBOOK_VARS_DIR + '/' + ip + '.yml'
            if os.path.isfile(yaml_file):
                print("Found: ", yaml_file)
                os.remove(yaml_file)
                print("Deleted: ", yaml_file)
            else:
                print("Yaml already deleted: ", yaml_file)

    def remove_ip_from_ansible_hosts(self, ips):

        print("Remove ips from ansible_hosts")
        lines = []
        with open(ANSIBLE_HOSTS_FILE, 'r+') as ansible_hosts:
            for line in ansible_hosts:
                if not any(bad_word in line for bad_word in ips):
                    lines.append(line)
            ansible_hosts.seek(0)
            ansible_hosts.truncate()
            for line in lines:
                ansible_hosts.write(line)


class ScalingUp:

    def __init__(self, password):
        self.password = password
        data, valid_ips = self.get_cluster_data()
        if len(data) > 0:
            workers_data = self.create_yml_file(cluster_data=data)
            self.add_new_workers_to_instances(worker_data=workers_data)
            self.add_ips_to_ansible_hosts(ips=valid_ips)
        else:
            print("No active worker found!")

    def get_cluster_data(self):
        global CLUSTER_INFO_URL

        res = requests.post(url=CLUSTER_INFO_URL,
                            json={"scaling": "scaling_up", "password": self.password})
        if res.status_code == 200:
            res = res.json()
            version = res["VERSION"]
            if version != VERSION:
                print(OUTDATED_SCRIPT_MSG.format(SCRIPT_VERSION=VERSION, LATEST_VERSION=version))
                sys.exit(1)
            ips = []

            cluster_data = [data for data in res["active_worker"] if data is not None]
            for cl in cluster_data:
                ips.append(cl['ip'])
            return cluster_data, ips
        else:
            print(OUTDATED_SCRIPT_MSG)
            sys.exit(1)

    def validate_ip(self, ip):
        print("Validate  IP: ", ip)
        return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)

    def add_new_workers_to_instances(self, worker_data):
        print("Add workers to instances")
        with open(INSTANCES_YML, 'r+') as stream:
            try:
                instances = yaml.safe_load(stream)
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

    def create_yml_file(self, cluster_data):
        workers_data = []
        for data in cluster_data:
            yaml_file_target = PLAYBOOK_VARS_DIR + '/' + data['ip'] + '.yml'
            if not os.path.exists(yaml_file_target):
                with  open(yaml_file_target, 'w+') as target:
                    try:
                        yaml.dump(data, target)
                        workers_data.append(data)
                    except yaml.YAMLError as exc:
                        print(exc)
                        sys.exit(1)
            else:
                print("Yaml for worker with IP {} already exists".format(data['ip']))

        return workers_data

    def add_ips_to_ansible_hosts(self, ips):
        print("Add ips to ansible_hosts")
        with open(ANSIBLE_HOSTS_FILE, "r") as in_file:
            buf = in_file.readlines()

        with open(ANSIBLE_HOSTS_FILE, "w") as out_file:
            for line in buf:
                if "[workers]" in line:
                    for ip in ips:
                        ip_line = "{} ansible_connection=ssh ansible_python_interpreter=/usr/bin/python3 ansible_user=ubuntu".format(
                            ip)
                        if not ip_line in buf:
                            line = line + ip_line + "\n"
                out_file.write(line)



def get_version():
    print("Version: ", VERSION)

def get_cluster_id_by_hostname():
    global CLUSTER_INFO_URL
    hostname = socket.gethostname()
    cluster_id = hostname.split('-')[-1]
    CLUSTER_INFO_URL = CLUSTER_INFO_URL + cluster_id + "/"


def run_ansible_playbook():
    os.chdir(PLAYBOOK_DIR)
    os.system('ansible-playbook -v -i ansible_hosts  site.yml')


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
        get_cluster_id_by_hostname()
        ScalingDown(password=password)
        ScalingUp(password=password)
        run_ansible_playbook()
