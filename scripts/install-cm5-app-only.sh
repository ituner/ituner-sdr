#!/usr/bin/env bash
# Preserve the working display; audio hardware is an explicitly selected profile.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cm5_audio=0
for option in "$@"; do
    case "$option" in
        --cm5-audio) cm5_audio=1 ;;
        --*) echo "Unknown CM5 option: $option" >&2; exit 2 ;;
        *) repo=$option ;;
    esac
done
# Reinstall/update an already selected audio profile; never auto-select it on LCD.
if [[ -f /etc/systemd/system/ituner-sdr.service.d/cm5-audio.conf ]]; then cm5_audio=1; fi
app_user=${SUDO_USER:?Run sudo as the application user}
app_uid=$(id -u "$app_user")
app_home=$(getent passwd "$app_user" | cut -d: -f6)
[[ -f "$repo/UI/kiwi_gl_display.py" ]]
bash "$repo/scripts/install-dependencies.sh"
DEBIAN_FRONTEND=noninteractive apt-get install -y plymouth plymouth-themes swaybg
PYGAME_HIDE_SUPPORT_PROMPT=1 python3 -c 'import pygame, OpenGL, PIL'

# Stop the old process before copying source and assets. Enabling an already
# active service does not restart it, so an update must explicitly relaunch it.
for unit in ituner-sdr.service ituner-sdr-health.service; do
    if systemctl is-active --quiet "$unit"; then
        systemctl stop "$unit"
    fi
done

install -d /opt/ituner-sdr /usr/local/lib/ituner-sdr /usr/local/share/ituner-sdr /var/lib/ituner-sdr
cp -a "$repo/UI" "$repo/assets" "$repo/licenses" /opt/ituner-sdr/
chown -R root:root /opt/ituner-sdr/UI /opt/ituner-sdr/assets
install -m 0644 "$repo/assets/boot-splash/ituner-sdr-native.png" /usr/local/share/ituner-sdr/boot-splash.png
[[ -f /etc/ituner-sdr.conf ]] || install -m 0644 "$repo/config/cm5-existing-display.conf" /etc/ituner-sdr.conf
install -d /usr/local/share/fonts/ituner-sdr
install -m 0644 "$repo/assets/fonts/oxanium/Oxanium.ttf" /usr/local/share/fonts/ituner-sdr/
fc-cache -f /usr/local/share/fonts/ituner-sdr
runuser -u "$app_user" -- python3 "$repo/scripts/seed-ui-defaults.py" \
    --home "$app_home" --config /etc/ituner-sdr.conf \
    --defaults "$repo/config/lcd-ui-defaults.json"

cat > /usr/local/lib/ituner-sdr/start-cm5.sh <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# Use the existing compositor, preserving display/touch drivers and settings.
export SDL_VIDEODRIVER=wayland WAYLAND_DISPLAY=wayland-0
export SDL_AUDIODRIVER=dummy PYGAME_HIDE_SUPPORT_PROMPT=1
rm -f "${ITUNER_BOOT_READY_FILE:-/run/ituner-sdr/ready}"
for ((attempt=0; attempt<90; attempt++)); do
    [[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] && break
    sleep 1
done
[[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]]
touch_args=(--swap-x-y --invert-x --no-invert-y)
if [[ ${ITUNER_SDR_ORIENTATION:-flipped} == normal ]]; then
    touch_args=(--swap-x-y --no-invert-x --invert-y)
fi
exec /usr/bin/python3 /opt/ituner-sdr/UI/kiwi_gl_display.py \
    --server "${ITUNER_SDR_SERVER:?}" \
    --freq-khz "${ITUNER_SDR_FREQUENCY_KHZ:-7075.794}" \
    --orientation "${ITUNER_SDR_ORIENTATION:-flipped}" \
    --fps "${ITUNER_SDR_FPS:-30}" --wf-row-pixels 1 "${touch_args[@]}"
EOF
chmod 0755 /usr/local/lib/ituner-sdr/start-cm5.sh

cat > /usr/local/lib/ituner-sdr/touch-ready.sh <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
for ((attempt=0; attempt<30; attempt++)); do
    for name in /sys/class/input/event*/device/name; do
        if [[ -r $name ]] && grep -q '0-005d Goodix Capacitive TouchScreen' "$name"; then
            exit 0
        fi
    done
    sleep 1
done
echo 'CM5 GT911 input device on I2C0 was not found.' >&2
exit 1
EOF
chmod 0755 /usr/local/lib/ituner-sdr/touch-ready.sh

cat > /etc/systemd/system/ituner-sdr-touch-ready.service <<'EOF'
[Unit]
Description=iTuner SDR CM5 existing GT911 readiness check
After=systemd-udev-trigger.service
[Service]
Type=oneshot
ExecStart=/usr/local/lib/ituner-sdr/touch-ready.sh
RemainAfterExit=yes
NoNewPrivileges=true
ProtectSystem=full
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ituner-sdr.service <<EOF
[Unit]
Description=iTuner SDR on CM5 (preserves verified display drivers)
After=display-manager.service ituner-sdr-touch-ready.service
Wants=ituner-sdr-touch-ready.service
[Service]
Type=simple
User=$app_user
SupplementaryGroups=video input render audio
WorkingDirectory=/opt/ituner-sdr/UI
EnvironmentFile=/etc/ituner-sdr.conf
Environment=PYTHONUNBUFFERED=1
Environment=XDG_RUNTIME_DIR=/run/user/$app_uid
Environment=ITUNER_BOOT_READY_FILE=/run/ituner-sdr/ready
RuntimeDirectory=ituner-sdr
RuntimeDirectoryMode=0755
ExecStart=/usr/local/lib/ituner-sdr/start-cm5.sh
Restart=always
RestartSec=5
[Install]
WantedBy=graphical.target
EOF

# Continue the branded Plymouth screen as a matching Wayland background.
# Raspberry Pi OS launches Labwc with merge mode, which executes both system
# and user autostarts. Replace and back up both levels so pcmanfm/wf-panel
# cannot cover the splash while Python creates its first frame.
system_labwc_autostart=/etc/xdg/labwc/autostart
if [[ -f "$system_labwc_autostart" && ! -f /var/lib/ituner-sdr/labwc-system-autostart.before-appliance ]]; then
    cp -a "$system_labwc_autostart" /var/lib/ituner-sdr/labwc-system-autostart.before-appliance
fi
cat > "$system_labwc_autostart" <<'EOF'
#!/bin/sh
/usr/bin/swaybg -i /usr/local/share/ituner-sdr/boot-splash.png -m stretch &
/usr/bin/kanshi &
EOF
chmod 0755 "$system_labwc_autostart"

labwc_dir="$app_home/.config/labwc"
install -d -o "$app_user" -g "$app_user" "$labwc_dir"
if [[ -f "$labwc_dir/autostart" && ! -f /var/lib/ituner-sdr/labwc-autostart.before-appliance ]]; then
    cp -a "$labwc_dir/autostart" /var/lib/ituner-sdr/labwc-autostart.before-appliance
fi
cat > "$labwc_dir/autostart" <<'EOF'
#!/bin/sh
# Managed by the iTuner SDR CM5 appliance installer. The system Labwc
# autostart owns the single splash background and output configuration.
EOF
chown "$app_user:$app_user" "$labwc_dir/autostart"
chmod 0755 "$labwc_dir/autostart"

# Install the early-boot Plymouth half of the same visual handoff.
plymouth_theme=/usr/share/plymouth/themes/ituner-sdr
install -d "$plymouth_theme"
install -m 0644 "$repo/assets/boot-splash/ituner-sdr-native.png" "$plymouth_theme/splash.png"
install -m 0644 "$repo/assets/boot-splash/ituner-sdr.plymouth" "$plymouth_theme/ituner-sdr.plymouth"
install -m 0644 "$repo/assets/boot-splash/ituner-sdr.script" "$plymouth_theme/ituner-sdr.script"
plymouth-set-default-theme -R ituner-sdr

# Keep the local console visually quiet. Preserve every board-specific boot
# argument and append only missing presentation flags.
cmdline=/boot/firmware/cmdline.txt
if [[ -f "$cmdline" ]]; then
    if [[ ! -f /var/lib/ituner-sdr/cmdline.before-appliance ]]; then
        cp -a "$cmdline" /var/lib/ituner-sdr/cmdline.before-appliance
    fi
    for flag in quiet splash logo.nologo vt.global_cursor_default=0 systemd.show_status=false rd.systemd.show_status=false loglevel=3; do
        grep -qw -- "$flag" "$cmdline" || sed -i "1 s|$| $flag|" "$cmdline"
    done
fi
config_txt=/boot/firmware/config.txt
if [[ -f "$config_txt" ]] && ! grep -Eq '^disable_splash=1([[:space:]]|$)' "$config_txt"; then
    if [[ ! -f /var/lib/ituner-sdr/config.before-appliance ]]; then
        cp -a "$config_txt" /var/lib/ituner-sdr/config.before-appliance
    fi
    cat >> "$config_txt" <<'EOF'

# BEGIN ITUNER SDR APPLIANCE BOOT
disable_splash=1
# END ITUNER SDR APPLIANCE BOOT
EOF
fi

install -m 0755 "$repo/scripts/configure.sh" /usr/local/sbin/ituner-sdr-configure
install -m 0755 "$repo/systemd/ituner-network" /usr/local/sbin/ituner-network
sudoers_file=$(mktemp)
sed "s/^ituner ALL=/$app_user ALL=/" "$repo/systemd/90-ituner-network" > "$sudoers_file"
visudo -cf "$sudoers_file"
install -m 0440 "$sudoers_file" /etc/sudoers.d/90-ituner-network
rm -f "$sudoers_file"
install -m 0644 "$repo/systemd/99-ituner-rc28.rules" /etc/udev/rules.d/99-ituner-rc28.rules
udevadm control --reload-rules
install -d /etc/systemd/system/ituner-sdr.service.d
install -m 0644 "$repo/systemd/ituner-sdr-lcd-kms-audio-realtime.conf" /etc/systemd/system/ituner-sdr.service.d/audio-realtime.conf
git -C "$repo" -c safe.directory="$repo" rev-parse HEAD > /var/lib/ituner-sdr/installed-commit
cat > /var/lib/ituner-sdr/CM5-INSTALL-NOTES.txt <<'EOF'
Application-only CM5 installation. Do not run the repository's stock installer
or uninstaller: they target a different ST7701 display and touch wiring.
Omitted ST7701 module, YX45011 display overlay, GT911 CAM/DISP1 overlay,
display boot changes, and old 400x960 framebuffer touch-test utility.
Existing JD9365 driver, CM5 overlays, labwc and kanshi settings are preserved.
Application renders at native 800x1280 through the existing Wayland desktop.
Application-only launcher swaps touch axes for the landscape interface.
The branded Plymouth and Wayland splash hides the desktop until the first UI frame.
Raspberry Pi OS panel and PCManFM desktop autostarts are disabled for appliance boot.
The cloned upstream repository remains unchanged.
EOF
systemd-analyze verify /etc/systemd/system/ituner-sdr.service /etc/systemd/system/ituner-sdr-touch-ready.service
# Retire the old scanner on upgrades as well as fresh installations.
systemctl disable --now ituner-sdr-health.service 2>/dev/null || true
rm -f /etc/systemd/system/ituner-sdr-health.service
ln -s /dev/null /etc/systemd/system/ituner-sdr-health.service
systemctl daemon-reload
if ((cm5_audio)); then
    bash "$repo/scripts/install-cm5-audio.sh" --no-restart
fi
systemctl enable ituner-sdr-touch-ready.service ituner-sdr.service
systemctl restart ituner-sdr-touch-ready.service
systemctl restart ituner-sdr.service
