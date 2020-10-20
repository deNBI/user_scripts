#!/usr/bin/python3
import os
import re
import socket
import sys
from pathlib import Path

import requests
import yaml

HOME = str(Path.home())
PLAYBOOK_DIR = HOME + '/playbook'
PLAYBOOK_VARS_DIR = HOME + '/playbook/vars'
ANSIBLE_HOSTS_FILE = PLAYBOOK_DIR + '/ansible_hosts'
INSTANCES_YML = PLAYBOOK_VARS_DIR + '/instances.yml'

CLUSTER_INFO_URL = "https://cloud.denbi.de/portal/public/clusters/"


def get_cluster_data():
    global CLUSTER_INFO_URL
    hostname = socket.gethostname()
    hostname = hostname.split('-')[-1]
    CLUSTER_INFO_URL = CLUSTER_INFO_URL + hostname + "/"
    res = requests.get(url=CLUSTER_INFO_URL, params={"scaling": "scaling_up"})
    ips = []

    cluster_data = res.json["active_worker"]
    for cl in cluster_data:
        ips.append(cluster_data['ip'])
    return cluster_data, ips


def validate_ip(ip):
    print("Validate  IP: ", ip)
    return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)


def add_new_workers_to_instances(worker_data):
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


def check_yml_data(data, file):
    keys = ['memory', 'ip', 'ephemerals', 'cores', 'hostname']
    for key in keys:
        if not key in data:
            print(
                "Missing Key [{}] in yaml file {}. Please fill in and then restart the script".format(
                    key, file))
            sys.exit(1)


def create_yml_file(cluster_data):
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


def add_ips_to_ansible_hosts(ips):
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


if __name__ == '__main__':
    data, valid_ips = get_cluster_data()
    if len(data) > 0:
        workers_data = create_yml_file(cluster_data=data)
        add_new_workers_to_instances(worker_data=workers_data)
        os.chdir(PLAYBOOK_DIR)
        add_ips_to_ansible_hosts(ips=valid_ips)
        os.system('ansible-playbook -v -i ansible_hosts  site.yml')
    else:
        print("No active worker found!")
