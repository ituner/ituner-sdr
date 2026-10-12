# WSPR history and WSPRnet reporting

Stopping, restarting or removing a WSPR decoder does not delete its spots.
History is indexed by receiver address and band, independently of the decoder
card's ID. Recreating a card for the same receiver and band restores its recent
spots. Each Start creates a new session for filtering, without discarding earlier
sessions. Local and remote receivers both retain history; remote receiver views
default to the current/latest session, while local views default to 24 hours.

On the touchscreen, open a WSPR card's expanded log. Choose This session,
Today UTC, Last 24 hours or All history, then page through the results. Other
receiver cycles through saved receiver archives, including removed decoders.
The screen displays 12 rows at 1280 × 800. The normal card retains a 96-spot
recent view; this is not the archive's retention limit.

Open `http://<SDR-host>:8073/wspr` for receiver, band, period and UTC date-range
filters, pagination and Export CSV. The export follows the selected filters and
includes all matching rows, not only the displayed page. SSTV remains at `/sstv`.
Both pages retain Add/Edit/Start/Stop/Remove receiver controls.

## Uploading spots

Open **WSPRnet uploads** on either the touchscreen history page or the web page.
Choose a receiver, enter a reporter callsign or unique SWL identifier and the
receiving antenna's four- or six-character Maidenhead grid. Confirm that you own
or have permission to report for that receiver and that its location is correct.
Turn uploads on and save. Each receiver has an independent reporting profile;
your local identity is never automatically copied to a remote receiver.

Uploading is off by default. Enabling it affects only new, complete spots from
capture periods beginning after enabling. Importing old logs, browsing history
or restarting the application does not submit the archive. WSPRnet reports
include the receiving identity/grid and decoded transmitting callsign/grid,
frequency, power, SNR, timing, drift and capture time. No WSPRnet password is
required. Do not enable this and another uploader for the same receiver/band.

The durable outbox shows queued, sent, rejected, uncertain, skipped, cancelled
and expired counts. A positive WSPRnet acknowledgement is required for `sent`.
Timeouts and interrupted requests are marked `uncertain` and are **not retried
automatically**, because the server may already have accepted them. Spots older
than 24 hours expire from the upload queue but remain in local history. Unresolved
callsign/grid messages are retained locally and skipped for reporting. Turning
off uploads or changing reporting identity cancels unsent queued reports; a
request already in flight can still finish.

The implementation uses HTTPS and the WSPR-2 form fields used by
[WSJT-X's WSPRnet client](https://github.com/WSJTX/wsjtx/blob/master/Network/wsprnet.cpp).
Tests use an isolated fake endpoint; no synthetic spots are posted to WSPRnet.

## Storage and recovery

The existing JSONL log remains the raw archive. Alongside it, an SQLite file named
`<log-stem>-history.sqlite3` holds indexed history, sessions, reporting profiles
and upload state. For the default log this is
`~/.local/state/kiwi-wspr-local-history.sqlite3`. On first start, existing and
rotated JSONL logs are imported in the background, ignoring malformed records
and deduplicating repeated spots. There is no automatic history deletion.
Back up both the logs and database using SQLite's backup API or with the app
stopped; a live database may also have WAL/SHM files.

Receiver identity normalizes URL hostname case, default ports and trailing
slashes. A hostname and its numeric IP remain separate sources: use the same
receiver address consistently. Existing imported records lack new session IDs,
so find them with All history or date filters rather than This session.

No extra Python package or display driver is required: SQLite is in Python's
standard library. Both app installers include the history modules and web assets.
The web controls are intended for your trusted LAN, like the existing receiver
controls; they should not be exposed as an unauthenticated public admin service.
