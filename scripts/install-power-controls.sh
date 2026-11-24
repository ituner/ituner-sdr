#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
app_user=${1:-ituner}
[[ "$app_user" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo 'Invalid application user' >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
getent passwd "$app_user" >/dev/null
candidate=$(mktemp)
trap 'rm -f "$candidate"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/ituner-power reboot, /usr/local/sbin/ituner-power poweroff\n' "$app_user" > "$candidate"
visudo -cf "$candidate"
install -o root -g root -m 0755 "$repo/scripts/ituner-power" /usr/local/sbin/ituner-power
install -o root -g root -m 0440 "$candidate" /etc/sudoers.d/90-ituner-power
