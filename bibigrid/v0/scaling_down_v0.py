#!/usr/bin/python3
import os
import re
import sys
from pathlib import Path

import yaml

HOME = str(Path.home())
PLAYBOOK_DIR = HOME + '/playbook'
PLAYBOOK_VARS_DIR = HOME + '/playbook/vars'
ANSIBLE_HOSTS_FILE = PLAYBOOK_DIR + '/ansible_hosts'
INSTANCES_YML = PLAYBOOK_VARS_DIR + '/instances.yml'


def validate_ip(ip):
    print("Validate  IP: ", ip)
    return re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)


def remove_worker_from_instances(ips):
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


def delete_ip_yaml(ips):
    print("Delte yaml file")
    for ip in ips:
        yaml_file = PLAYBOOK_VARS_DIR + '/' + ip + '.yml'
        if os.path.isfile(yaml_file):
            print("Found: ", yaml_file)
            os.remove(yaml_file)
            print("Deleted: ", yaml_file)
        else:
            print("No file found: ", yaml_file)


def remove_ip_from_ansible_hosts(ips):
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


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("To few arguments")
        sys.exit(1)
    ips = sys.argv[1:]
    valid_ips = []
    for ip in ips:
        if not validate_ip(ip):
            print("{} is no valid Ip! SKIPPING".format(ip))
            continue
        else:
            valid_ips.append(ip)
    remove_worker_from_instances(ips=valid_ips)
    delete_ip_yaml(ips=valid_ips)
    os.chdir(PLAYBOOK_DIR)
    remove_ip_from_ansible_hosts(ips=valid_ips)
    os.system('ansible-playbook -v -i ansible_hosts  site.yml')
