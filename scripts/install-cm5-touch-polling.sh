#!/usr/bin/env bash
# Opt-in only for the verified iTuner CM5 carrier and GT911 at I2C0/0x5d.
# Installs a polling-capable upstream driver for the currently running kernel.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
grep -aq 'Compute Module 5' /proc/device-tree/model
node=/sys/bus/i2c/devices/0-005d/of_node
[[ $(readlink -f "$node") == /sys/firmware/devicetree/base/axi/pcie@1000120000/rp1/i2c@70000/touchscreen@5d ]]
grep -aq 'goodix,gt911' "$node/compatible"
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
kernel=$(uname -r)
[[ -f /lib/modules/$kernel/build/Makefile ]]
for command in curl make dtc depmod; do command -v "$command" >/dev/null; done
stage=$(mktemp -d /tmp/ituner-goodix-build.XXXXXX)
trap 'rm -rf "$stage"' EXIT
revision=2569533d6c33c15231fbc21704c87fcebc67173c
for file in goodix.c goodix.h goodix_fwupload.c; do
    curl -fsSL --max-time 30 "https://raw.githubusercontent.com/raspberrypi/linux/$revision/drivers/input/touchscreen/$file" -o "$stage/$file"
done
(
    cd "$stage"
    sha256sum -c <<'SUMS'
37f2e4ccde0bb039165333a1fc86df801f1caf8e89c0f9490f4b9c6c94aaf9aa  goodix.c
85344fc53ade364f9ed0251e8507488048d39768b35f0019995eb2cf786d368f  goodix.h
1eead7b45cdc944da548615925dc52be228527d70fe905c7523a0514da1e98f5  goodix_fwupload.c
SUMS
)
printf 'obj-m += goodix_ts.o\ngoodix_ts-y := goodix.o goodix_fwupload.o\n' > "$stage/Makefile"
make -C "/lib/modules/$kernel/build" M="$stage" modules -j2
dtc -@ -Wno-interrupts_property -I dts -O dtb \
    -o "$stage/cm5-gt911-polling.dtbo" \
    "$repo/hardware/cm5/touch/cm5-gt911-polling-overlay.dts"
[[ $(modinfo -F vermagic "$stage/goodix_ts.ko") == "$kernel "* ]]

backup=/var/backups/ituner-sdr/touch-polling-$(date -u +%Y%m%dT%H%M%SZ)
install -d "$backup" "/lib/modules/$kernel/updates" /boot/firmware/overlays
cp -a /boot/firmware/config.txt "$backup/config.txt"
cp -a /usr/local/lib/ituner-sdr/touch-ready.sh "$backup/touch-ready.sh"
install -m 0755 "$repo/scripts/cm5-touch-ready.sh" /usr/local/lib/ituner-sdr/touch-ready.sh
for file in "/lib/modules/$kernel/updates/goodix_ts.ko" \
    /boot/firmware/overlays/cm5-gt911-polling.dtbo \
    /etc/udev/rules.d/99-ituner-cm5-touch-polling.rules; do
    [[ ! -f $file ]] || cp -a "$file" "$backup/"
done
install -m 0644 "$stage/goodix_ts.ko" "/lib/modules/$kernel/updates/goodix_ts.ko"
install -m 0644 "$stage/cm5-gt911-polling.dtbo" /boot/firmware/overlays/
depmod -a "$kernel"
# Ensure initramfs also uses the new module if a system includes Goodix there.
if command -v update-initramfs >/dev/null; then
    update-initramfs -u -k "$kernel"
fi
cat > /etc/udev/rules.d/99-ituner-cm5-touch-polling.rules <<'RULE'
# Poll at the GT911 maximum nominal report rate; retain native input handling.
ACTION=="add", SUBSYSTEM=="input", KERNELS=="0-005d", ATTR{name}=="*Goodix Capacitive TouchScreen", TEST=="poll", ATTR{poll}="10"
RULE
udevadm control --reload-rules
if ! grep -q '^dtoverlay=cm5-gt911-polling$' /boot/firmware/config.txt; then
    cat >> /boot/firmware/config.txt <<'BOOT'

# BEGIN ITUNER CM5 TOUCH POLLING
[cm5]
# Must follow cm5-main-fpc2-gt911. Requires polling-capable Goodix driver.
dtoverlay=cm5-gt911-polling
[all]
# END ITUNER CM5 TOUCH POLLING
BOOT
fi
# Supersede the ineffective once-per-boot rebind workaround.
legacy=/etc/systemd/system/ituner-sdr-touch-ready.service.d/cold-start.conf
if [[ -f $legacy ]]; then mv "$legacy" "$backup/cold-start.conf"; fi
systemctl daemon-reload
printf 'Installed for kernel %s. Backup: %s\nReboot to activate and verify poll=10.\n' "$kernel" "$backup"
