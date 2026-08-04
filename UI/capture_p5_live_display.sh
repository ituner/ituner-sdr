#!/bin/zsh
# Capture the exact frame currently drawn by the Pi OpenGL display service.
set -euo pipefail

ROOT="${0:A:h:h}"
HOST="${P5_HOST:-10.0.0.151}"
USER="${P5_USER:-ituner}"
KEY="${P5_KEY:-$HOME/.ssh/id_ed25519_p4}"
REMOTE_DIR="${P5_SDR_DIR:-/home/ituner/codex-sdr-display}"
OUT_DIR="$ROOT/renders"
RAW="$OUT_DIR/p5-live-reference-400x960.png"
VIEW="$OUT_DIR/p5-live-reference-960x400.png"

mkdir -p "$OUT_DIR"

ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$KEY" "$USER@$HOST" \
  "pid=\$(systemctl show -p MainPID --value kiwi-gl-display.service); test \"\$pid\" -gt 0; kill -USR1 \"\$pid\"; sleep 1; test -s /tmp/kiwi-gl-display.png"

scp -q -o BatchMode=yes -o ConnectTimeout=8 -i "$KEY" \
  "$USER@$HOST:/tmp/kiwi-gl-display.png" "$RAW"

sips -r 90 "$RAW" --out "$VIEW" >/dev/null

print "Live OpenGL capture: $VIEW"
open "$VIEW"
