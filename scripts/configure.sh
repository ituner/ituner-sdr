#!/usr/bin/env bash
set -Eeuo pipefail

config=/etc/ituner-sdr.conf

usage() {
  echo 'Usage: sudo ituner-sdr-configure --server http://host:port [--frequency-khz 7075.794] [--orientation flipped|normal]'
}

[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ -f ${config} ]] || { echo 'ituner-sdr is not installed.' >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) server=${2:-}; shift 2 ;;
    --frequency-khz) frequency=${2:-}; shift 2 ;;
    --orientation) orientation=${2:-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

replace_setting() {
  local key=$1 value=$2
  [[ ${value} != *$'\n'* && ${value} != *' '* ]] || { echo "Invalid ${key}: spaces are not allowed." >&2; exit 2; }
  local temporary
  temporary=$(mktemp)
  awk -v key="${key}" -v value="${value}" '
    index($0, key "=") == 1 { print key "=" value; found=1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "${config}" >"${temporary}"
  install -m 0644 "${temporary}" "${config}"
  rm -f "${temporary}"
}

if [[ -n ${server:-} ]]; then
  [[ ${server} =~ ^https?://[^[:space:]]+$ ]] || { echo 'Server must begin with http:// or https://.' >&2; exit 2; }
  replace_setting ITUNER_SDR_SERVER "${server}"
fi
if [[ -n ${frequency:-} ]]; then
  [[ ${frequency} =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo 'Frequency must be a positive number in kHz.' >&2; exit 2; }
  replace_setting ITUNER_SDR_FREQUENCY_KHZ "${frequency}"
fi
if [[ -n ${orientation:-} ]]; then
  [[ ${orientation} == flipped || ${orientation} == normal ]] || { echo 'Orientation must be flipped or normal.' >&2; exit 2; }
  replace_setting ITUNER_SDR_ORIENTATION "${orientation}"
fi

systemctl try-restart ituner-sdr.service || true
echo 'Configuration saved. The OpenGL SDR service was restarted if it was running.'
