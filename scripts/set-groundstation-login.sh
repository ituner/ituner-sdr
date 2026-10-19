#!/usr/bin/env bash
# Preserve accounts/passwords and restart only Ground Station to drop old sockets.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
case "${1:-}" in
    open) required=false ;;
    required) required=true ;;
    *) echo 'Usage: sudo scripts/set-groundstation-login.sh open|required' >&2; exit 2 ;;
esac
docker inspect --format '{{range .Mounts}}{{println .Destination}}{{end}}' ituner-groundstation |
    grep -qx '/app/backend/ituner_access.py' || {
        echo 'Install the access wrapper with start-groundstation-evaluation.sh --recreate first.' >&2
        exit 1
    }
install -d -m 0700 /var/lib/ituner-groundstation/configs
config=/var/lib/ituner-groundstation/configs/ituner_access.json
temporary=$(mktemp "${config}.XXXXXX")
trap 'rm -f "$temporary"' EXIT
printf '{"login_required": %s}\n' "$required" > "$temporary"
chmod 0600 "$temporary"
mv "$temporary" "$config"
docker restart ituner-groundstation
echo "Ground Station login_required=$required"
