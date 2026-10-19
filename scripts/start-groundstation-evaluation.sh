#!/usr/bin/env bash
# Isolated ARM64 evaluation; does not change the native display or SDR broker.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
image=ghcr.io/sgoudelis/ground-station@sha256:e71abef10c10207b3c7cddd9b81b01681c4cb2235395735b5205178aea0220eb
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
docker image inspect "$image" >/dev/null
install -d -m 0700 /var/lib/ituner-groundstation
backup=
if [[ ${1:-} == --recreate ]]; then
    backup="ituner-groundstation-backup-$(date +%Y%m%d%H%M%S)"
    docker stop ituner-groundstation
    docker rename ituner-groundstation "$backup"
    # Retain an easily restored container, but prevent it claiming the port at boot.
    docker update --restart=no "$backup" >/dev/null
fi
if docker container inspect ituner-groundstation >/dev/null 2>&1; then
    docker start ituner-groundstation
else
    limits=(--cpus 2 --pids-limit 256)
    if grep -qw memory /sys/fs/cgroup/cgroup.controllers; then
        limits+=(--memory 900m --memory-swap 1400m)
    fi
    access=()
    entrypoint=app.py
    credentials=/home/ituner/.config/ituner-sdr/groundstation-evaluation.json
    if [[ -f $credentials ]]; then
        # Container root has no DAC_OVERRIDE capability; give it a root-owned
        # private copy rather than weakening the user's credential permissions.
        install -D -o root -g root -m 0600 "$credentials" /etc/ituner-groundstation/login.json
        install -D -m 0644 "$script_dir/groundstation-access.py" /usr/local/lib/ituner-sdr/groundstation-access.py
        access+=(--mount type=bind,source=/usr/local/lib/ituner-sdr/groundstation-access.py,target=/app/backend/ituner_access.py,readonly
            --mount type=bind,source=/etc/ituner-groundstation/login.json,target=/run/ituner-groundstation-login.json,readonly)
        entrypoint=ituner_access.py
    fi
    # The application directly supports RTL USB. It needs neither a privileged
    # container nor the stock launcher's unrelated UHD FPGA downloads/daemons.
    docker run -d --name ituner-groundstation --restart unless-stopped \
        --publish 7000:7000 "${limits[@]}" "${access[@]}" \
        --cap-drop ALL --security-opt no-new-privileges \
        --device-cgroup-rule 'c 189:* rmw' \
        --mount type=bind,source=/dev/bus/usb,target=/dev/bus/usb \
        --mount type=bind,source=/var/lib/ituner-groundstation,target=/app/backend/data \
        --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
        --entrypoint /app/venv/bin/python "$image" \
        "$entrypoint" --log-level=INFO --host=0.0.0.0 --port=7000
fi
[[ -z $backup ]] || echo "Previous container retained stopped as $backup"
echo 'Ground Station: http://cm5.local:7000/'
echo 'Stop the existing decoder before assigning its USB dongle in Ground Station.'
