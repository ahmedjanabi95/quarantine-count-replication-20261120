#!/usr/bin/env bash
set -euo pipefail
mkdir -p /mnt/journal /mnt/studyinput
mount -L EVIDENCE /mnt/journal
out=/mnt/journal/campaign
mkdir "$out"
exec > >(tee -a "$out/setup.log" /dev/ttyS0) 2>&1
end() {
  status=$?
  echo "$status" > "$out/exit_status.txt"
  echo "LEASE_GUEST_EXIT $status"
  sync
  systemctl --no-block poweroff
}
trap end EXIT
mount -o ro /dev/disk/by-label/cidata /mnt/studyinput
mkdir -p /opt/lease-study
tar -xzf /mnt/studyinput/study.tgz -C /opt/lease-study
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=2 -qq update
apt-get -o Acquire::Retries=2 install -y --no-install-recommends openvswitch-switch iproute2 python3-venv ca-certificates
python3 -m venv /opt/ids-venv
/opt/ids-venv/bin/pip --disable-pip-version-check install --retries=2 'os-ken==3.1.1'
for mod in openvswitch tun cls_flower sch_ingress act_gact; do modprobe "$mod"; done
cd /opt/lease-study
{ cat /etc/os-release; uname -srvmo; nproc; grep MemTotal /proc/meminfo; dpkg-query -W openvswitch-switch openvswitch-common iproute2; sha256sum /usr/bin/ovs-ofctl /usr/sbin/ovs-vswitchd; /opt/ids-venv/bin/pip freeze; } > "$out/environment.txt"
sha256sum review_evidence_v6/*.py review_evidence_v7/*.py review_evidence_v9/*.py review_evidence_v10/* review_evidence_v11/* review_evidence_v16/* > "$out/guest_sources.sha256"
unshare --net -- bash review_evidence_v16/guest_switch.sh "$out" /opt/lease-study/review_evidence_v16

