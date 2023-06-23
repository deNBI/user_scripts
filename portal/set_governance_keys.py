#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import requests

home = str(Path.home())
AUTHORIZED_KEYS = f"{home}/.ssh/authorized_keys"
OLD_AUTHORIZED_KEYS = f"{home}/.ssh/old.authorized_keys"
MEMBER_LIST_URL = "https://raw.githubusercontent.com/deNBI/user_scripts/master/portal/governance_members.txt"


def get_team_members():
    print("Getting Team Members")
    r = requests.get(url=MEMBER_LIST_URL)
    team_members = r.text.splitlines()
    print(f"Found Team Members: {team_members}")
    return team_members


def check_for_errors(resp, *args, **kwargs):
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(e)
        print(f"Request failed! Content:{resp.content} ")


def get_ssh_keys_user(user):
    print(f"Getting SSH Keys {user}")
    url = f"https://github.com/{user}.keys"
    r = requests.get(url=url)
    return r.text


def append_keys_to_authorized_keys(key):
    with open(AUTHORIZED_KEYS, "a") as key_file:
        key_file.write(key)
        key_file.write("\n")

        print(f"Added Key [{key}] to authorized keys!")


if __name__ == "__main__":
    replace = len(sys.argv) == 2 and sys.argv[1] == "-replace"
    keys = []
    for member in get_team_members():
        for key in get_ssh_keys_user(member).split("\n"):
            if key:
                key = f"{key} {member}\n"
                keys.append(key)
    if len(keys) > 0:
        if replace:
            print("Rename old authorized keys file")
            os.rename(AUTHORIZED_KEYS, OLD_AUTHORIZED_KEYS)
        try:
            for key in keys:
                print(key)
                append_keys_to_authorized_keys(key)
        except Exception as e:
            print(e)
            if replace:
                print("Reuse old authorized key file")
                os.rename(OLD_AUTHORIZED_KEYS, AUTHORIZED_KEYS)

