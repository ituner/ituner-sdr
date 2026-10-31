# Experimental Long Scan

Tap the **SMART SCAN** title to open the hidden setup. It offers a dedicated
Kiwi receiver address, **Use listening receiver**, **Start Long Scan**,
**Stop Long Scan**, and **View history**. Receiver entry uses the same shared
full-screen keyboard, colors and touch layout as Wi-Fi setup. Back retraces
history → setup → Smart Scan; changing these views never tunes listening audio.

Long Scan opens its own uniquely identified, paired Kiwi SND/W/F session.
Its SND packets are discarded and never enter the listening audio sink.
The receiver needs an additional available listener channel. Capacity or
authentication failures back off for a minute; other connection failures
retry with bounded exponential backoff. Closing setup or Smart Scan leaves
Long Scan running until Stop is pressed. Saved enabled settings resume after
an app restart, with a short startup delay to let the listening session start
first. The feature is disabled until the user starts it the first time.

The scan visits all supported broadcast allocations, using the same carrier
and AM-modulation detector and response handling as Smart Scan. Each pass
finishes all overlapping detailed windows of a band. A complete cycle targets
six minutes, about ten observations per frequency per hour. If the receiver
or network is slower, the cycle finishes before beginning the next one; it
does not discard unfinished work merely to meet that target.

A broad activity survey now prioritizes busy bands on connection rather than
always starting at LW. Later cycles learn from confirmed yield. Both scanners
use guarded wider-window trials, periodic narrow audits, and targeted narrow rechecks
for uncertain signals; every band remains covered. Unchanged waterfall settings
are cached per connection, and Long Scan pauses unused FFT rows between cycles.
See [scan efficiency and verification](scan-efficiency.md) for the policy,
benchmark, limits and geometric guarantees.

The separate activity viewer has **1 h**, **6 h**, **12 h**, and **24 h**
windows, defaulting to twelve hours. Broadcast bands occupy labelled blocks
from LW through 11 m. Within a block, frequency runs left to right. Time runs
downward, newest at the top, with UTC labels. Strength controls trace
brightness. A tap near a trace shows its frequency and possible station/country
matches from the local schedule index at the tapped historical time.

Each measured full-band sweep records its accepted frequencies and strengths.
Persistent lines join detections across successive sweeps. One measured miss
can recover without splitting a line; two measured misses end that activity
track at its last positive observation. A dim provisional tail can extend
toward now while another check is due. An unmeasured or failed sweep is not
an empty band: it creates an uncertainty gap and cannot establish absence.
Long gaps are not joined into invented continuous transmissions.

History is stored in a local SQLite database, separate from Smart Scan's
in-memory two-hour catalogue, and retains 48 hours for the 24-hour viewer.
Receiver addresses are recorded with every sweep; observations from different
receivers are never combined into one RF history. Switching receiver source
selects that source's retained history. Stop does not erase saved activity.

For this first prototype, both scanners reuse the detector and offline
schedule lookup. They do not exchange live RF observations or station counts.
This keeps the dedicated experiment independent of normal listening and
avoids silently mixing measurements from different receiver locations.
