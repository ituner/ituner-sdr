#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo: sudo ituner-sdr-uninstall' >&2; exit 1; }

purge_config=false
[[ ${1:-} == --purge-config ]] && purge_config=true
[[ $# -le 1 ]] || { echo 'Usage: sudo ituner-sdr-uninstall [--purge-config]' >&2; exit 2; }

krel=$(uname -r)
boot_dir=/boot/firmware
[[ -d ${boot_dir} ]] || boot_dir=/boot
config_txt=${boot_dir}/config.txt
module_dst=/lib/modules/${krel}/kernel/drivers/gpu/drm/panel/panel-sitronix-st7701.ko
backup=/var/lib/ituner-sdr/panel-sitronix-st7701.${krel}.ko.original

echo 'Stopping ituner-sdr services and removing the bundled display/touch/UI files.'
systemctl disable --now ituner-sdr.service ituner-sdr-health.service ituner-sdr-touch-ready.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/ituner-sdr.service /etc/systemd/system/ituner-sdr-health.service /etc/systemd/system/ituner-sdr-touch-ready.service
rm -f /usr/local/bin/ituner-sdr-touch-test /usr/local/sbin/ituner-sdr-configure /usr/local/sbin/ituner-sdr-uninstall
rm -rf /usr/local/lib/ituner-sdr /usr/local/src/ituner-sdr-display /opt/ituner-sdr
rm -f "${boot_dir}/overlays/yousee-yx45011act2.dtbo" "${boot_dir}/overlays/gt911-camdisp1.dtbo"
if [[ -f ${backup} ]]; then
  install -m 0644 "${backup}" "${module_dst}"
  depmod -a "${krel}"
fi
if [[ -f ${config_txt} ]]; then
  tmp_file=$(mktemp)
  trap 'rm -f "${tmp_file}"' EXIT
  awk '/^# BEGIN ITUNER SDR$/ {skip=1; next} /^# END ITUNER SDR$/ {skip=0; next} !skip {print}' "${config_txt}" >"${tmp_file}"
  cat "${tmp_file}" >"${config_txt}"
fi
${purge_config} && rm -f /etc/ituner-sdr.conf
systemctl daemon-reload
echo 'Uninstall complete. Reboot to return the Pi to its previous display/touch boot configuration.'

