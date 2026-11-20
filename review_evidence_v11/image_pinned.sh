#!/usr/bin/env bash
set -euo pipefail
dir=/var/tmp/counter-guest-v11
mkdir -p "$dir"
cd "$dir"
local_image=debian-12-generic-amd64.qcow2
digest=d597a8b422a0fa7f7cf1a0477d23be7f7514f32e57ccb8d0c69156e1be4a7e1712fb64aee6298520d70aa573b801d0cfe3392ab5de39829728760c0cf99ef4ec
test ! -e "$local_image" || test "$(sha512sum "$local_image" | cut -d' ' -f1)" = "$digest"
if test ! -e "$local_image"; then
  curl -fLsS --retry 2 --max-time 300 https://cloud.debian.org/images/cloud/bookworm/20261117-2665/debian-12-generic-amd64-20261117-2665.qcow2 -o "$local_image.download"
  printf '%s  %s\n' "$digest" "$local_image.download" | sha512sum --check
  mv "$local_image.download" "$local_image"
fi
printf '%s  %s\n' "$digest" "$local_image" > selected.sha512
sha512sum --check selected.sha512

