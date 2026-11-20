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
test -x /opt/ids-venv/bin/osken-manager
for mod in openvswitch tun cls_flower sch_ingress act_gact; do modprobe "$mod"; done
cd /opt/lease-study
{ cat /etc/os-release; uname -srvmo; nproc; grep MemTotal /proc/meminfo; dpkg-query -W openvswitch-switch openvswitch-common iproute2; sha256sum /usr/bin/ovs-ofctl /usr/sbin/ovs-vswitchd; /opt/ids-venv/bin/pip freeze; } > "$out/environment.txt"
find review_evidence_v{6,7,9,10,11,16} -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum > "$out/guest_sources.sha256"
unshare --net -- bash review_evidence_v16/fine_switch.sh "$out" /opt/lease-study/review_evidence_v16
