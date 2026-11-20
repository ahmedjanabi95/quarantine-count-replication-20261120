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
sha256sum review_evidence_v6/{gateway_agent,wireless_trial}.py review_evidence_v7/gateway_agent.py review_evidence_v9/{trial,campaign}.py review_evidence_v10/audit_transfer.py review_evidence_v11/{PROTOCOL.md,guest_trial.py,audit_guest.py} review_evidence_v16/{protocol,study}.py review_evidence_v17/{PROTOCOL.md,adaptive.py,trial_v17.py,run.py,audit.py,design.py,guest_switch.sh} > "$out/guest_sources.sha256"
unshare --net -- bash review_evidence_v17/guest_switch.sh "$out" /opt/lease-study/review_evidence_v17
