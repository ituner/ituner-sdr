# RTL-SDR dongle registry

Open **Receiver → Dongles / Rename** on the native ADS-B touchscreen, or **USB receiver → Dongles / Rename** in VHF/UHF. Web receiver panels link to `/dongles` on either port 8090 or 8092. The same inventory and names are used by both.

Connected receivers are marked **DUPLICATE SERIAL** when their serial is shared. Missing descriptors never make another receiver appear uniquely identified. Linux sysfs descriptors are matched to librtlsdr indices using libusb enumeration order and bus/address, not alphabetical USB port order. Unverified mappings cannot be programmed.

A friendly nickname is a software setting. Unique serials follow a dongle across ports. For factory duplicates, names follow the physical port; physically swapping identical dongles cannot be detected. Duplicate warnings describe connected receivers only. Saved or disconnected records do not create a conflict; a sole factory `00000001` is usable without rewriting it. If another connected receiver shares it later, both are flagged and addressed by their physical ports. SoapySDR selection requires unique IDs among connected receivers.

All observed dongles are retained in `~/.local/share/ituner-sdr/dongles/registry.json` (under `XDG_DATA_HOME` if set), including disconnected receivers, first/last detection times, nicknames and EEPROM test outcomes. Names update in decoder selectors on the next inventory refresh.

## Quick ID assignment

A connected duplicate or factory `00000000` / `00000001` receiver shows **Assign new ID**. Its dialog contains only **Nickname · optional** and **Assign new ID**. The next unused eight-digit serial is generated automatically. Other receivers may remain connected, including on the same hub. The dialog identifies the selected physical USB port. Reception pauses and resumes automatically while the app backs up, validates and updates the EEPROM. Reconnect the receiver afterward. Existing decoder selections follow its new identity.

Unique receivers show **Rename**, which edits only the optional friendly nickname. EEPROM tests and manual serial inputs are not part of the normal rename flow. Readability, backup and serial-only write verification run automatically during ID assignment; vendor configuration bytes remain unchanged. Failed USB/EEPROM access is reported without claiming write support.

The versioned registry keeps shared-serial history separate from individual receiver flags, so a newly assigned serial cannot inherit an old duplicate warning. Verified legacy records are merged during migration. Disconnected dongles remain saved.

The EEPROM helper verifies libusb enumeration against the requested bus/address,
then checks the newly opened Linux USB file descriptor against that exact device.
It revalidates the handle and physical port before each read or write. A changed
index, address, port or handle cancels the operation. It writes only the serial
string descriptor and compares the full 256-byte image against the expected
update; all vendor configuration bytes must remain unchanged.

A USB reset does not necessarily reload the EEPROM identity. After verification,
reconnect the programmed dongle itself; the hub can stay connected. The tested
05e3:0610 USB2.1 hub reports ganged power switching, so individual SDR power
cycles cannot be performed without affecting the other ports.

## Automatic plug-in and startup notices

The native application and its Airspace, Signal Observatory, Spectrum, Settings
and HF companion pages show one shared receiver notice. Linux kernel USB hotplug
messages wake a background discovery worker; a five-second fallback scan also
checks inventory. The watcher reads descriptors without claiming an RF stream.
Hub enumeration bursts are grouped. Names alone do not cause another popup.

A normal connected-receiver list has a Close button and disappears after ten
seconds. Shared IDs stay visible with a short explanation and **Yes, assign a
new ID / Cancel**. Yes targets the displayed physical port and uses the same
backed-up, serial-only EEPROM verification as the Dongles page. Nothing is written
on detection or Cancel. Each row has its own **Assign ID** selector and status. Select a receiver, then
**Yes, assign a new ID**; additional requests can be queued while earlier changes
finish. Writes run sequentially, rechecking the approved physical attachment
before each operation. A disconnect or changed USB address cancels that request.
Queued approvals are held in memory and are not replayed after a restart.

A successful write marks only that receiver **Reconnect → new ID**. The list
continues updating for new plug-ins, including during an EEPROM operation
(descriptor-only sysfs/libusb discovery) and while reconnects are pending.
Pending reconnects are restored from verified registry records after reboot.
Unplug/reconnect that dongle only, leaving the hub powered. Failed or unverified
USB access never claims success. Dismissal lasts for that detection event, so a
new plug-in or application/CM5 restart shows a fresh notice. No USB power switching
is implemented by these prompts.

### Hub power-cycle recovery

Unique IDs preserve receiver assignments when Linux changes USB indices/addresses.
The primary ADS-B receiver, UAT, comparison workers and running VHF sessions retain
their enabled intent during USB loss and retry when the assigned receiver returns.
A changed USB address is treated as a fresh attachment even if the device's serial
never disappears from a scan. Explicit assignments wait for their own receiver;
Auto may use another available receiver. Shared leases prevent two decoders from
claiming the same device. Failures have backoff (typically 10–30 seconds).

This is recovery, not uninterrupted recording: a hub power cycle drops every
receiver on it, loses samples and can split satellite captures. Interrupted
comparison windows are marked invalid. Spectrum surveys/watch/investigation stop
with an error and require Start; partial measurements remain available. A complete
application restart has a separate policy: ADS-B/UAT/comparison saved enabled
states, continuous Meteor and enabled installed sensor sessions can resume; other
VHF sessions and surveys do not automatically restart. HF network receivers are
not affected by removing the local SDR hub (a USB audio device on that hub may be).

The same `librtlsdr` EEPROM API is used for supported RTL2832-family dongles,
including Blog V4/V4L, NESDR and filtered ADS-B variants. `rtl_eeprom -r` saves
the backup; the verified-handle helper performs the serial-only write and full
read-back comparison. A common interface does not guarantee every unit has a
writable EEPROM: nonstandard layouts, access failures and read-back mismatches
are reported individually. No manufacturer/product descriptors or tuner
configuration bytes are rewritten.


## USB-Radios management and shared selectors

Open **System → USB-Radios**, or **System → System → USB-Radios** from the
hardware panel, on the CM5 touchscreen. The native page shows six receiver rows
per page, with a compact connection line to the decoder that currently holds the
receiver lease. **Connected** is the default; **Saved radios** includes unplugged
hardware. Solid lines represent current leases, while dashed lines show idle or
disconnected receivers. A saved selection awaiting USB is labelled as waiting,
not drawn as an active decoder. Rows keep physical-port order as activity changes; cached descriptor failures
and pending replacement IDs do not appear as extra radios. The page reads the existing shared inventory and
broker; browsing and refreshing do not claim radios or change decoders.

The same management page is available at `/usb-radios` on ports 8090 and 8092;
`/dongles` remains an alias. `/api/usb-radios` and `/api/dongles` share the same
inventory, current lease owners, status, frequency and optional nicknames. Select
a radio to edit its nickname; factory/duplicate ID assignment is a separate,
deliberate action. Reconnect-pending receivers cannot be programmed again.

USB receiver pickers in ADS-B/1090, UAT/978, AIS, APRS, rtl_433, Meteor-M,
CubeSat, radiosonde and Spectrum Analyzer share compact naming and availability
labels. They retain explicit disconnected selections and preserve an open web
choice during refresh. SoapySDR modes show identity conflicts as disabled choices
and link to USB-Radios. Auto chooses through the existing receiver broker; no
handoff behavior is changed. ADS-B web selection applies immediately, with a
single Start or Stop action and automatically refreshed discovery. The receiver
location form is collapsed under Receiver location. HF network-source pickers
remain KiwiSDR/network selectors, since those decoders do not own local USB radios.
