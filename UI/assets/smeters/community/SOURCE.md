# Community meter artwork

Retrieved 2026-10-14. The image files in this directory retain the original
bytes from the publishers' downloadable ZIP archives. The application crops
unused margins and resamples to final screen dimensions at runtime; it adds no
grey gallery frame or meter bezel. Distinctive Magic Eye glass and housings are
part of the original designs and remain visible.

## Ernst, OE3IDE

Source: https://www.oe3ide.com/meter-graphics-thetis-2-9-0-8-and-newer/

The gallery is published by Ernst, OE3IDE; analog faces carry an OE3IDE watermark.
Title credits identify the artwork collection's publisher. The gallery credits
Richie, MW0LGE, for the Thetis meter engine and skin server, separately from the
artwork. Imported faces:

| Face | Download ID | Original file |
| --- | --- | --- |
| Matrix | 3029 | ananMM-dark-large.png |
| Star Trek | 3034 | ananMM-dark-large.png |
| FTDX-5000 | 3038 | ananMM-dark-large.png |
| FTDX-9000 | 3042 | ananMM-dark-large.png |
| High Vis | 3259 | ananMM-large.png |
| Magic Eye Plain Black | 3056 | eye-bezel.png |

Download URLs use `https://www.oe3ide.com/?sdm_process_download=1&download_id=ID`.
Analog S-scale reference coordinates were checked against the published
Thetis MeterManager.cs AddAnanMM data:
https://github.com/ramdor/Thetis/blob/master/Project%20Files/Source/Console/MeterManager.cs
The new Python animation and renderer are independently implemented. Only the
S scale follows receiver RSSI; printed PO/SWR/ID/COMP/ALC/Vd scales are decorative
source artwork. Cross-needle ZIPs were downloaded to the research record but
are not RX S-meter choices because they depict forward/reflected power and SWR.

## Retired TR7 tribute

The previously imported KE9NS TR7 tribute (`ke9ns_tr7.jpg`) and its calibration
were removed on 2026-10-15 at the user's request. Legacy selections fall back
to the original LED Bar. The prior download remains only in the external
research record and is not shipped with the application.

## License status

The downloaded artwork archives contain no separate license text. Source and
callsign attribution are recorded; no permission or open-source artwork license
is inferred from a free download or from the license of the host software.

On 2026-10-15 the Silver, Black, Brass, Aero and Retro round-eye faces were
removed from the gallery and shipped assets at the user's request. Only Plain
Black remains. Legacy selections migrate to `oe3ide_eye_plain`.
