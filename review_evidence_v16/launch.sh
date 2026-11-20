#!/usr/bin/env bash
set -euo pipefail
name=$1
case "$name" in (*[!a-zA-Z0-9_-]*|'') exit 2;; esac
here=$(cd "$(dirname "$0")" && pwd)
image_dir=/var/tmp/counter-guest-v11
prefix=$(mktemp -d /var/tmp/lease-vm-XXXXXXXX)
result="$here/$name"
test ! -e "$result"
mkdir -p "$result"
printf '%s\n' "$prefix" > "$result/host_path.txt"
cd "$image_dir"
sha512sum --check selected.sha512
cp selected.sha512 "$result/image.sha512"
qemu-system-x86_64 --version | head -1 > "$result/hypervisor.txt"
mkdir -p "$prefix/seed"
cd "$here/.."
tar -czf "$prefix/seed/study.tgz" review_evidence_v6/{gateway_agent,wireless_trial}.py review_evidence_v7/gateway_agent.py review_evidence_v9/{trial,campaign}.py review_evidence_v10/audit_transfer.py review_evidence_v11/{PROTOCOL.md,guest_trial.py,audit_guest.py} review_evidence_v16/{PROTOCOL.md,study.py,audit.py,protocol.py,guest_switch.sh}
cp "$here/guest_setup.sh" "$prefix/seed/user-data"
printf 'instance-id: %s\nlocal-hostname: lease-bench\n' "$name" > "$prefix/seed/meta-data"
cd "$prefix"
genisoimage -quiet -output seed.iso -volid cidata -joliet -rock seed
qemu-img create -q -f qcow2 -F qcow2 -b "$image_dir/debian-12-generic-amd64.qcow2" guest.qcow2 10G
truncate -s 160M evidence.img
mkfs.ext4 -q -L EVIDENCE evidence.img
set +e
timeout 1500 qemu-system-x86_64 -accel kvm -cpu host -m 2304 -smp 2 -nodefaults -display none -serial file:"$result/serial.log" -monitor none -no-reboot -drive file=guest.qcow2,format=qcow2,if=virtio -drive file=evidence.img,format=raw,if=virtio -drive file=seed.iso,format=raw,media=cdrom,readonly=on -nic user,model=virtio-net-pci -boot order=c >"$result/launch.log" 2>&1
status=$?
set -e
printf '%s\n' "$status" > "$result/qemu_status.txt"
debugfs -R "rdump /campaign $result" evidence.img > "$result/extract.log" 2>&1
test "$status" = 0
test "$(cat "$result/campaign/exit_status.txt")" = 0

