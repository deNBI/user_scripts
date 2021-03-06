#!/usr/bin/python3
import os
import re
import socket
import sys
from pathlib import Path

import requests
import yaml

VERSION = "0.1.2"
HOME = str(Path.home())
PLAYBOOK_DIR = HOME + '/playbook'
PLAYBOOK_VARS_DIR = HOME + '/playbook/vars'
ANSIBLE_HOSTS_FILE = PLAYBOOK_DIR + '/ansible_hosts'
INSTANCES_YML = PLAYBOOK_VARS_DIR + '/instances.yml'
CLUSTER_INFO_URL = "https://cloud.denbi.de/portal/public/clusters/"


class ScalingDown:

    def __init__(self):
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
            print("No machines found for down scaling!")

    def get_private_ips(self):
        global CLUSTER_INFO_URL
        res = requests.get(url=CLUSTER_INFO_URL, params={"scaling": "scaling_down"})
        ips = [ip for ip in res.json()["private_ips"] if ip is not None]
        return ips

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

    def __init__(self):
        data, valid_ips = self.get_cluster_data()
        if len(data) > 0:
            self.create_yml_file(cluster_data=data)
            self.add_new_workers_to_instances(worker_data=data)
            self.add_ips_to_ansible_hosts(ips=valid_ips)
        else:
            print("No active worker found!")

    def get_cluster_data(self):
        global CLUSTER_INFO_URL
        res = requests.get(url=CLUSTER_INFO_URL, params={"scaling": "scaling_up"})
        ips = []

        cluster_data = [data for data in  res.json()["active_worker"] if data is not None]
        for cl in cluster_data:
            ip = cl.get("ip", None)
            hostname = cl['hostname']

            if ip :
                if self.validate_ip(ip):
                    ips.append(ip)
                else:
                    print(f"{ip} is no valid Ip! SKIPPING worker {hostname}")
            else:
                status= cl['status']
                print(f"No IP set for Worker {hostname}  - Worker Status [{status}]\n Worker needs to be ACTIVE for Scaling Up!\n Please restart this Script when the VM is ACTIVE - SKIPPING this Worker...")
        return cluster_data, ips

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


    def validate_ip(self, ip):
        print("Validate  IP: ", ip)
        return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)

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
        get_cluster_id_by_hostname()
        ScalingDown()
        ScalingUp()
        run_ansible_playbook()

