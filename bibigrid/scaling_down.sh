#!/bin/bash

if [ $# -eq 0 ]; then
    echo "No arguments provided!"
    echo "Todo FIll"
    exit 1
fi

YQ_DIR=/home/ubuntu
if ! [[ -f "$YQ_DIR"/yq_linux_amd64 ]];
then
 wget https://github.com/mikefarah/yq/releases/download/3.3.4/yq_linux_amd64 -P "$YQ_DIR"
fi
chmod +x "$YQ_DIR"/yq_linux_amd64

yq="$YQ_DIR"/yq_linux_amd64
for var in "$@"
do
    IP="$var"

if [[ $IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Valid IP $IP"
else
  echo "No valid ip: $IP"
  exit 1
fi

cd ~/playbook/vars || exit

EXISTING_WORKER=$($yq r instances.yml   workers.*.ip)
if [[ $EXISTING_WORKER == *"$IP"* ]]; then
  echo "$IP  found in workers!"
else
    echo "$IP not found in workers!"
    echo " Skipping"
    continue
fi

if test -f "$IP".yml; then
    echo "$IP".yml exists.
    echo "Deleting yaml"
    rm ~/playbook/vars/"$IP".yml
else
DEL_EXISTING_WORKER=$($yq r instances.yml   deletedWorkers.*.ip)
if [[ $DEL_EXISTING_WORKER == *"$IP"* ]]; then
  echo "IP already exists in deleted workers!"
    continue 1

fi

  echo "$IP".yml does not exists.
fi

$yq r instances.yml "workers.(ip==$IP)" > "$IP"_tmp_del.yml
$yq d -i instances.yml "workers.(ip==$IP)" 
HOST_NAME=$($yq r "$IP"_tmp_del.yml hostname)
CORES=$($yq r "$IP"_tmp_del.yml cores)
MEMORY=$($yq r "$IP"_tmp_del.yml memory)
EPHEMERAL=$($yq r "$IP"_tmp_del.yml ephemerals.*)
touch "$IP"_tmp.yml

$yq w -i "$IP"_tmp.yml deletedWorkers[0].ip "$IP"
$yq w -i "$IP"_tmp.yml deletedWorkers[0].cores "$CORES"
$yq w -i "$IP"_tmp.yml deletedWorkers[0].hostname "$HOST_NAME"
$yq w -i "$IP"_tmp.yml deletedWorkers[0].memory "$MEMORY"

if [ -z "$EPHEMERAL" ]
then
      $yq w -i "$IP"_tmp.yml deletedWorkers[0].epheremals "[]"
else
      $yq w -i "$IP"_tmp.yml deletedWorkers[0].epheremals[+] "$EPHEMERAL"
fi

$yq m -i -a instances.yml "$IP"_tmp.yml
rm "$IP"_tmp.yml
rm "$IP"_tmp_del.yml
cd ~/playbook || exit
sed -i "/$IP/d" ansible_hosts
done

ansible-playbook -v -i ansible_hosts  site.yml

