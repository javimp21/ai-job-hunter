#!/usr/bin/env bash
# Install the systemd units from a release directory (does not enable or start them).
# Usage: sudo install-units.sh <dir containing the *.service/*.timer files>
# Idempotent; only touches /etc/systemd/system when a unit actually changed.
# deploy.sh enables and starts them, so nothing runs (or polls Telegram) before cut-over.
set -euo pipefail
src="${1:?usage: install-units.sh <systemd dir>}"
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
changed=0
for unit in "$src"/*.service "$src"/*.timer; do
    dest="/etc/systemd/system/$(basename "$unit")"
    if ! cmp -s "$unit" "$dest"; then
        install -m 0644 "$unit" "$dest"
        changed=1
    fi
done
[ "$changed" -eq 1 ] && systemctl daemon-reload
echo "systemd units installed (changed=$changed)"
