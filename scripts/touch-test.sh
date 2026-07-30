#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo: sudo ituner-sdr-touch-test' >&2; exit 1; }
exec /usr/bin/python3 /usr/local/lib/ituner-sdr/touch-test.py

