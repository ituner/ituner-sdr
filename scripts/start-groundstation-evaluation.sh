#!/usr/bin/env bash
# Isolated ARM64 evaluation; does not change the native display or SDR broker.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
image=ghcr.io/sgoudelis/ground-station@sha256:e71abef10c10207b3c7cddd9b81b01681c4cb2235395735b5205178aea0220eb
docker image inspect "$image" >/dev/null
install -d -m 0700 /var/lib/ituner-groundstation
if docker container inspect ituner-groundstation >/dev/null 2>&1; then
    docker start ituner-groundstation
else
    limits=(--cpus 2 --pids-limit 256)
    if grep -qw memory /sys/fs/cgroup/cgroup.controllers; then
        limits+=(--memory 900m --memory-swap 1400m)
    fi
    # The application directly supports RTL USB. It needs neither a privileged
    # container nor the stock launcher's unrelated UHD FPGA downloads/daemons.
    docker run -d --name ituner-groundstation --restart unless-stopped \
        --publish 7000:7000 "${limits[@]}" \
        --cap-drop ALL --security-opt no-new-privileges \
        --device-cgroup-rule 'c 189:* rmw' \
        --mount type=bind,source=/dev/bus/usb,target=/dev/bus/usb \
        --mount type=bind,source=/var/lib/ituner-groundstation,target=/app/backend/data \
        --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
        --entrypoint /app/venv/bin/python "$image" \
        app.py --log-level=INFO --host=0.0.0.0 --port=7000
fi
echo 'Ground Station: http://cm5.local:7000/'
echo 'Stop the existing decoder before assigning its USB dongle in Ground Station.'
