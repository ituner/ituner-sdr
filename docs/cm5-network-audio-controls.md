# Network, mute and receiver controls

SYSTEM → Wi-Fi / ETHERNET shows the two interface cards. Tap a card to read
its saved settings, choose DHCP or Static IPv4, or turn that interface off/on.
Static addresses include a prefix (for example `192.168.86.50/24`); gateway is
optional and DNS accepts comma-separated IPv4 addresses. Ethernet also exposes
autonegotiation, speed and duplex. Changes require confirmation and may interrupt
connections on that interface. Opening the screen never changes the connection.
The current 100 Mbps Ethernet profile is preserved until explicitly edited.

Saved Wi-Fi networks have a **Change password** action. An entered password
updates the saved profile before activation. Connecting to another access point
first disconnects the current AP; a failed activation attempts to reconnect the
previous AP. Wi-Fi profiles retain route metric 50, keeping Wi-Fi preferred.
NetworkManager commands run on the existing network-config worker, not the UI.

The persistent AUDIO MUTED badge is visible only on HOME with no menu overlay.
On CM5, mute controls the ES8316 left/right headphone DAC mixer switches and the
speaker gate on the codec-control worker. The PCM stream and remote audio remain
running, avoiding playback-buffer latency. Other platforms retain software mute.

Selecting a USB receiver starts it immediately and returns to HOME on successful
start. A startup failure leaves the existing receiver details visible. Tapping
the receiver portion of HOME's bottom status stripe opens the receiver picker.
USB discovery does not reset USB power or interrupt another decoder's device.

## Image power-off test default

`hardware/cm5/v4/config.ini` supplies `POWER_OFF_ON_HALT=0`. This is an **EEPROM
configuration fragment**, not `/boot/firmware/config.txt`. Merge this setting
with the target's existing EEPROM configuration, preserving its boot order and
other settings, and apply using the matching installed firmware image. Do not
replace the entire EEPROM configuration with this fragment or downgrade firmware.

On the test CM5, `sudo rpi-eeprom-update -a` on 2026-11-24 reported up to date:
installed firmware 2025-11-27; default package 2025-11-05. No flash or downgrade
was performed. The live EEPROM already has `POWER_OFF_ON_HALT=0`; quiet halt and
physical-button restart were confirmed previously by the user.
