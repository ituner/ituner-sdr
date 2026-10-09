# Callsign search across decoder history

Open `/search` on the SDR's web server, or choose **Search saved history** on any WSPR, SSTV, Hell, QRSS or CW page. The touch display has a **FIND** button in each decoder's title area and in WSPR history. Its mode selector cycles through individual modes and All.

Search accepts a callsign or part of one, ignoring case. Portable suffixes work: `S52AB` also matches `S52AB/P`. Matching is literal, so `%` and `_` are not wildcards. WSPR matches the transmitter callsign, not the receiver's identity. CW/QRSS search received tentative text; Hell searches OCR text and human-confirmed reception reports. SSTV searches text recognized in saved images by local Tesseract OCR. OCR can miss or misread a callsign and is never treated as verified reception or automatically uploaded.

Results show decode type, UTC time, receiver, band/frequency, text and an expandable image where retained. WSPR uses its entire SQLite spot archive, CW its entire text archive, not the old 200-entry view. Per-mode search links open the same paginated search with the decoder preselected. The WSPR history table and its CSV export also accept the Callsign filter alongside the existing receiver, band and time filters.

Image text is indexed in `image-search.sqlite3` beside the SSTV images directory. One background worker refreshes metadata every ten seconds. SSTV OCR uses a single thread and a ten-second per-image timeout; live partial frames are deferred until complete or unchanged for thirty seconds. Previously saved images are indexed on first startup; the page reports the initial scan until it finishes. Missing Tesseract is reported without blocking other searches. Existing installer dependencies already include Tesseract.

Image text already indexed remains searchable when gallery retention removes the original image; the result then says its image is no longer retained. This cannot recover files deleted before indexing began. The search cache does not change the galleries or their retention limits. CW archives text, not its live waterfall, so past CW entries have no image link. Search results refresh only on a user action, keeping scrolling and open images stable.

API: `GET /api/logs/search?q=S52AB&mode=all&offset=0&limit=30`, with modes `all`, `wspr`, `sstv`, `hell`, `qrss`, `cw`; limit is capped at 100. No receiver channels, settings, audio, display drivers or upload configuration are changed by searching.
