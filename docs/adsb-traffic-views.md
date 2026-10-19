# Live traffic and saved reception

Both Airspace interfaces open in **Live**, with five-minute trails. Live
contacts and map positions have separate 15-second freshness limits. A speed
message refreshes radio contact, never an older position. Aircraft symbols fade
as their positions age and leave Live after 15 seconds without a fresh position.

**Since opened** displays radio contacts and position samples received after
entering the ADS-B screen (or loading the web page). Its trail starts exactly
at that time, without joining a previous position across the boundary. The
window is capped by the existing 24-hour trail retention. Contacts without
coordinates remain available in the list. Leaving the native workspace and
returning begins a new visit in Live; switching its drawers does not.

**Start fresh** starts a new viewing window and switches to Since opened. It
does not stop/restart the decoder, truncate files, clear trails, or modify
coverage. The previous observations remain accessible in **History**. History
defaults to 24 hours and retains the existing trail-duration selector.

**Past trails** optionally draws stored tracks faintly behind Live or Since
opened. It adds no historical aircraft icons to Live and does not affect the
live counters. In Since opened, the faint backdrop ends at the visit boundary.

The counters distinguish **Live contacts**, **Fresh positions**, and **New this
visit**. Aircraft present in the initial snapshot form the baseline; an ICAO
address first encountered afterward is a new arrival. Its row and map symbol
are highlighted for 12 seconds, and a returning aircraft is not counted again
within the visit. Display contact memory is bounded at 4,096 aircraft / 24 hours.

Lists and target details show contact age separately from position age. History
endpoints show **Recorded** age: the position archive does not establish the
time of the aircraft's last non-position message. Server observation timestamps
keep cached replies from making stale traffic look fresh. Browser time is
aligned to the receiver for view filtering; labels use the browser's local time.

These are per-screen display choices. The decoder, flight logs, reception dome
and their retention continue independently. Remote VHF maps use the shared globe
renderer without opting into ADS-B traffic filtering.
