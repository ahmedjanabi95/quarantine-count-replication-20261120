#!/usr/bin/env bash
set -euo pipefail
out=$1
base=$2
test "$(readlink /proc/self/ns/net)" != "$(readlink /proc/1/ns/net)"
export OVS_RUNDIR
OVS_RUNDIR=$(mktemp -d /run/measurement-XXXXXXXX)
ip link set lo up
cleanup() {
  if test -S "$OVS_RUNDIR/switch.ctl"; then ovs-appctl -t "$OVS_RUNDIR/switch.ctl" exit || true; fi
  if test -S "$OVS_RUNDIR/db.ctl"; then ovs-appctl -t "$OVS_RUNDIR/db.ctl" exit || true; fi
}
trap cleanup EXIT
ovsdb-tool create "$OVS_RUNDIR/conf.db" /usr/share/openvswitch/vswitch.ovsschema
ovsdb-server "$OVS_RUNDIR/conf.db" --remote="punix:$OVS_RUNDIR/db.sock" --pidfile="$OVS_RUNDIR/db.pid" --unixctl="$OVS_RUNDIR/db.ctl" --detach --no-chdir --log-file="$out/ovsdb.log"
ovs-vsctl --timeout=8 --no-wait init
ovs-vswitchd "unix:$OVS_RUNDIR/db.sock" --pidfile="$OVS_RUNDIR/ovs-vswitchd.pid" --unixctl="$OVS_RUNDIR/switch.ctl" --detach --no-chdir --log-file="$out/vswitch.log"
case "$(cat /var/lib/cloud/data/instance-id)" in
  adaptive-local01) site=local ;;
  adaptive-remote01) site=hosted ;;
  *) exit 2 ;;
esac
python3 "$base/run.py" "$out" "$site"
