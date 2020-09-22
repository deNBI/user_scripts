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
  echo "IP already exists in workers!"
    continue 1

fi
cp ~/"$IP".yml ~/playbook/vars
if test -f "$IP".yml; then
    echo "$IP".yml exists.
else
  echo "$IP".yml does not exists.
  exit 1
fi

HOST_NAME=$($yq r "$IP".yml hostname)
CORES=$($yq r "$IP".yml cores)
MEMORY=$($yq r "$IP".yml memory)
EPHEMERAL=$($yq r "$IP".yml ephemerals.*)
if test -z "$CORES"
then
      echo "\$CORES is empty"
       exit 1
else
      echo "\$CORES: $CORES"

fi

if test -z "$HOST_NAME"
then
      echo "\$HOST_NAME is empty"
       exit 1
else
      echo "\$HOST_NAME: $HOST_NAME"

fi


if test -z "$MEMORY"
then
      echo "\$MEMORY is empty"
      exit 1
else
      echo "\$MEMORY: $MEMORY"

fi



touch "$IP"_tmp.yml


$yq w -i "$IP"_tmp.yml workers[0].ip "$IP"
$yq w -i "$IP"_tmp.yml workers[0].cores "$CORES"
$yq w -i "$IP"_tmp.yml workers[0].hostname "$HOST_NAME"
$yq w -i "$IP"_tmp.yml workers[0].memory "$MEMORY"

if [ -z "$EPHEMERAL" ]
then
      $yq w -i "$IP"_tmp.yml workers[0].epheremals "[]"
else
      $yq w -i "$IP"_tmp.yml workers[0].epheremals[+] "$EPHEMERAL"
fi

$yq m -i -a instances.yml "$IP"_tmp.yml
rm "$IP"_tmp.yml.yml

cd ~/playbook || exit
echo  "$IP" ansible_connection=ssh ansible_python_interpreter=/usr/bin/python3 ansible_user=ubuntu >> ansible_hosts
done

ansible-playbook -v -i ansible_hosts  site.yml

