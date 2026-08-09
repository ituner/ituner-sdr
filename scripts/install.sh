#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo: sudo ./scripts/install.sh' >&2; exit 1; }
grep -aq 'Raspberry Pi 5' /proc/device-tree/model 2>/dev/null || { echo 'This installer is for Raspberry Pi 5 only.' >&2; exit 1; }

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
app_user=${SUDO_USER:-}
[[ -n ${app_user} && ${app_user} != root ]] || { echo 'Run sudo from the desktop/console user who will run the SDR UI.' >&2; exit 1; }
id "${app_user}" >/dev/null
[[ ${app_user} =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo 'Unsupported local user name.' >&2; exit 1; }
app_uid=$(id -u "${app_user}")

boot_dir=/boot/firmware
[[ -d ${boot_dir} ]] || boot_dir=/boot
config_txt=${boot_dir}/config.txt
overlays_dir=${boot_dir}/overlays
state_dir=/var/lib/ituner-sdr

[[ -f ${config_txt} && -d ${overlays_dir} ]] || { echo 'Required Raspberry Pi boot paths are missing.' >&2; exit 1; }
echo 'Installing the Waveshare 8-DSI-TOUCH-A profile, OpenGL SDR UI, and boot services. A reboot will be required.'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  python3-pygame python3-opengl python3-pil python3-pip python3-venv \
  libportaudio2 libspeexdsp1 pipewire pipewire-audio wireplumber rtkit \
  build-essential cmake autoconf automake libtool pkg-config git curl unzip xz-utils ca-certificates

install -d -m 0755 /opt/ituner-sdr/UI /opt/ituner-sdr/vendor/python /usr/local/lib/ituner-sdr "${state_dir}"

tmp_file=$(mktemp)
trap 'rm -f "${tmp_file}"' EXIT
awk '/^# BEGIN ITUNER SDR$/ {skip=1; next} /^# END ITUNER SDR$/ {skip=0; next} !skip {print}' "${config_txt}" >"${tmp_file}"
{
  cat "${tmp_file}"
  printf '\n# BEGIN ITUNER SDR\n'
  printf 'dtparam=i2c_csi_dsi=on\n'
  printf 'dtoverlay=vc4-kms-v3d\n'
  printf 'dtoverlay=vc4-kms-dsi-waveshare-panel-v2,8_0_inch_a\n'
  printf 'disable_fw_kms_setup=1\n'
  printf '# END ITUNER SDR\n'
} >"${config_txt}"

cp -a "${repo_dir}/UI/." /opt/ituner-sdr/UI/
ITUNER_SDR_PREFIX=/opt/ituner-sdr "${repo_dir}/scripts/install-ai-runtime.sh"
install -m 0755 "${repo_dir}/scripts/start-opengl.sh" /usr/local/lib/ituner-sdr/start-opengl.sh
install -m 0755 "${repo_dir}/scripts/start-wayland.sh" /usr/local/lib/ituner-sdr/start-wayland.sh
install -m 0755 "${repo_dir}/scripts/install-ai-runtime.sh" /usr/local/lib/ituner-sdr/install-ai-runtime.sh
install -m 0755 "${repo_dir}/scripts/ituner_fan_curve.py" /usr/local/lib/ituner-sdr/ituner_fan_curve.py
install -m 0755 "${repo_dir}/scripts/touch-ready.sh" /usr/local/lib/ituner-sdr/touch-ready.sh
install -m 0755 "${repo_dir}/touch-driver/src/sdr_touch_dot_fb.py" /usr/local/lib/ituner-sdr/touch-test.py
install -m 0755 "${repo_dir}/scripts/configure.sh" /usr/local/sbin/ituner-sdr-configure
install -m 0755 "${repo_dir}/scripts/uninstall.sh" /usr/local/sbin/ituner-sdr-uninstall
install -m 0755 "${repo_dir}/scripts/touch-test.sh" /usr/local/bin/ituner-sdr-touch-test
[[ -f /etc/ituner-sdr.conf ]] || install -m 0644 "${repo_dir}/config/ituner-sdr.conf" /etc/ituner-sdr.conf
sed -e "s/__ITUNER_SDR_USER__/${app_user}/g" -e "s/__ITUNER_SDR_UID__/${app_uid}/g" "${repo_dir}/systemd/ituner-sdr.service" >/etc/systemd/system/ituner-sdr.service
sed "s/__ITUNER_SDR_UID__/${app_uid}/g" "${repo_dir}/systemd/ituner-sdr-lcd.service" >/etc/systemd/user/ituner-sdr-lcd.service
sed "s/__ITUNER_SDR_USER__/${app_user}/g" "${repo_dir}/systemd/ituner-fan-curve.service" >/etc/systemd/system/ituner-fan-curve.service
install -m 0644 "${repo_dir}/systemd/ituner-sdr-touch-ready.service" /etc/systemd/system/ituner-sdr-touch-ready.service
sed "s/__ITUNER_SDR_USER__/${app_user}/g" "${repo_dir}/systemd/ituner-sdr-health.service" >/etc/systemd/system/ituner-sdr-health.service
usermod -aG video,input,render,audio "${app_user}"
loginctl enable-linger "${app_user}"
systemctl daemon-reload
systemctl --global disable ituner-sdr-lcd.service || true
systemctl disable --now ituner-sdr.service || true
systemctl enable --now rtkit-daemon.service
systemctl enable ituner-sdr-touch-ready.service ituner-sdr-health.service ituner-fan-curve.service
systemctl enable ituner-sdr.service
echo 'Installation complete. Reboot now so the display and touch overlays can load: sudo reboot'
