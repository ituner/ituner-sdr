#!/usr/bin/env bash
# Audio only: never install a panel/touch driver or change display orientation.
set -Eeuo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
restart=1
hardware=1
for option in "$@"; do
    case "$option" in
        --no-restart) restart=0 ;;
        --software-only) hardware=0 ;;
        *) echo "Unknown audio option: $option" >&2; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo 'Run with sudo as the application user.' >&2; exit 1; }
app_user=${SUDO_USER:?Run sudo as the application user}
[[ $app_user != root ]] || { echo 'Run sudo from the SDR user account.' >&2; exit 1; }
grep -aq 'Raspberry Pi Compute Module 5' /proc/device-tree/model || {
    echo 'This profile is only for the custom CM5 ES8316/TPA3113 carrier.' >&2; exit 1;
}
grep -q 'import cm5_audio_control' /opt/ituner-sdr/UI/kiwi_gl_display.py || {
    echo 'Install the updated application first with --cm5-existing-display.' >&2; exit 1;
}
app_home=$(getent passwd "$app_user" | cut -d: -f6)
command -v pinctrl >/dev/null
getent group gpio >/dev/null

# Install only audio/build tools; --no-upgrade preserves existing OS packages.
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade --no-install-recommends alsa-utils libasound2-plugins
if ((hardware)); then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade --no-install-recommends build-essential device-tree-compiler
    krel=$(uname -r)
    if ! modinfo snd_soc_es8316 >/dev/null 2>&1; then
        if [[ ! -d /lib/modules/$krel/build ]]; then
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade --no-install-recommends "linux-headers-$krel"
        fi
        [[ -d /lib/modules/$krel/build ]] || { echo "Matching headers missing for $krel; no boot settings changed." >&2; exit 1; }
        source_dir=/usr/local/src/ituner-sdr-es8316
        install -d "$source_dir"
        install -m 0644 "$repo/hardware/cm5/audio/driver/"* "$source_dir/"
        make -C "/lib/modules/$krel/build" M="$source_dir" modules
        install -D -m 0644 "$source_dir/snd-soc-es8316.ko" "/lib/modules/$krel/extra/snd-soc-es8316.ko"
        depmod -a "$krel"
    fi
    dtbo=$(mktemp)
    trap 'rm -f "$dtbo"' EXIT
    dtc -@ -I dts -O dtb -o "$dtbo" "$repo/hardware/cm5/audio/cm5-main-es8316-overlay.dts"
    [[ -f /boot/firmware/config.txt && -d /boot/firmware/overlays ]]
else
    grep -qx 'CM5ES8316' /sys/class/sound/card*/id || {
        echo 'Software-only setup requires the working CM5ES8316 card.' >&2; exit 1;
    }
fi

backup=/var/lib/ituner-sdr/cm5-audio-backup-$(date +%Y%m%d-%H%M%S)
install -d "$backup" /etc/ituner-sdr /usr/local/lib/ituner-sdr /etc/systemd/system/ituner-sdr.service.d
# Stop before updating controls/preferences, so the UI cannot overwrite them.
systemctl stop ituner-sdr.service
pinctrl set 13 op dl
for name in cm5-speaker-test.conf cm5-headphone-auto-mute.conf cm5-audio.conf; do
    path=/etc/systemd/system/ituner-sdr.service.d/$name
    [[ ! -f $path ]] || mv "$path" "$backup/"
done
if ((hardware)); then
    cp -a /boot/firmware/config.txt "$backup/config.txt"
    [[ ! -f /boot/firmware/overlays/cm5-main-es8316.dtbo ]] || cp -a /boot/firmware/overlays/cm5-main-es8316.dtbo "$backup/"
    install -m 0644 "$dtbo" /boot/firmware/overlays/cm5-main-es8316.dtbo
    python3 "$repo/scripts/configure-cm5-audio.py" --boot-config /boot/firmware/config.txt
fi
install -m 0644 "$repo/UI/cm5_audio_control.py" /opt/ituner-sdr/UI/
install -m 0644 "$repo/config/cm5-audio-alsa.conf" /etc/ituner-sdr/cm5-audio-alsa.conf
install -m 0755 "$repo/scripts/cm5-jack-monitor.py" /usr/local/lib/ituner-sdr/
install -m 0644 "$repo/systemd/cm5-headphone-monitor.service" /etc/systemd/system/
install -m 0644 "$repo/systemd/cm5-audio.conf" /etc/systemd/system/ituner-sdr.service.d/
preferences=$app_home/.local/state/kiwi-gl-display-receiver.json
[[ ! -f $preferences ]] || cp -a "$preferences" "$backup/preferences.json"
runuser -u "$app_user" -- python3 "$repo/scripts/configure-cm5-audio.py" --preferences "$preferences"
systemd-analyze verify /etc/systemd/system/cm5-headphone-monitor.service /etc/systemd/system/ituner-sdr.service
systemctl daemon-reload
systemctl enable cm5-headphone-monitor.service
systemctl restart cm5-headphone-monitor.service
if ((restart)); then systemctl restart ituner-sdr.service; fi
echo "CM5 audio profile installed. Previous settings: $backup"
if ((hardware)); then echo 'Reboot to apply any newly installed audio overlay/module. No display/touch driver was installed.'; fi
