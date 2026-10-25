# RTL-SDR dongle registry

Open **Receiver → Dongles / Rename** on the native ADS-B touchscreen, or **USB receiver → Dongles / Rename** in VHF/UHF. Web receiver panels link to `/dongles` on either port 8090 or 8092. The same inventory and names are used by both.

Connected receivers are marked **DUPLICATE SERIAL** when their serial is shared. Missing descriptors never make another receiver appear uniquely identified. Linux sysfs descriptors are matched to librtlsdr indices using libusb enumeration order and bus/address, not alphabetical USB port order. Unverified mappings cannot be programmed.

A friendly nickname is a software setting. Unique serials follow a dongle across ports. For factory duplicates, names follow the physical port; physically swapping identical dongles cannot be detected. Known shared serials remain flagged when the other dongle is disconnected. Unique serials remain required for SoapySDR decoder selection.

All observed dongles are retained in `~/.local/share/ituner-sdr/dongles/registry.json` (under `XDG_DATA_HOME` if set), including disconnected receivers, first/last detection times, nicknames and EEPROM test outcomes. Names update in decoder selectors on the next inventory refresh.

## Quick ID assignment

A connected duplicate shows **Assign new ID**. Its dialog contains only **Nickname · optional** and **Assign new ID**. The next unused eight-digit serial is generated automatically. Keep only that receiver connected. Reception pauses and resumes automatically while the app backs up, validates and updates the EEPROM. Reconnect the receiver afterward. Existing decoder selections follow its new identity.

Unique receivers show **Rename**, which edits only the optional friendly nickname. EEPROM tests and manual serial inputs are not part of the normal rename flow. Readability, backup and serial-only write verification run automatically during ID assignment; vendor configuration bytes remain unchanged. Failed USB/EEPROM access is reported without claiming write support.

The versioned registry keeps shared-serial history separate from individual receiver flags, so a newly assigned serial cannot inherit an old duplicate warning. Verified legacy records are merged during migration. Disconnected dongles remain saved.
