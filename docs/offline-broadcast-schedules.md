# Offline broadcast schedules

Smart Scan and the tuned-frequency identity display match names from a local
frequency index. Automatic lookups never request a per-frequency web page. The explicit Research button on an Unknown row is an opt-in online exception; it does not update the offline cache or change audio.
`UI/offline_schedules.py` imports two public schedule providers:

- EiBi: semicolon CSV plus its README country, language and transmitter codes.
  The provider explicitly permits download, use, copying, distribution and
  incorporation into third-party software. The cache keeps its README terms.
  Provider: http://www.eibispace.de/ and
  http://www.eibispace.de/dx/README.TXT.
- HFCC: the current seasonal ZIP, including fixed-width schedules and reference
  tables for broadcasters, countries, languages and transmitting sites.
  Provider: https://new.hfcc.org/data/.

Downloads live in `~/.cache/ituner/broadcast-schedules/`, overridable with
`ITUNER_SCHEDULE_DIR`. The downloaded data is not committed to the repository.
Each provider has an independently replaced JSON file with its source URL,
season, fetch time and normalized rows. Writes are atomic; one failing provider
cannot replace a good file with an empty or corrupt response. Downloads are
bounded, as is expanded ZIP size. Existing data remains usable without a network.
A background worker checks age, downloads only stale or missing providers, and
never blocks audio or touch. Successful files are refreshed no more than daily;
failed attempts are retried no more than hourly during application use.

The index filters by frequency tolerance, UTC time, dates and source-specific
weekday numbering. Overnight broadcasts use their starting UTC day. EiBi utility
and inactive entries and HFCC digital/DRM requirements are excluded from AM
matches. Unknown complex day codes are handled conservatively. Expired-season
rows are not shown as current broadcasts. If the current EiBi season is not yet
published (HTTP 404), the previous season may be downloaded and explicitly
labelled old, but it still cannot identify current signals after its expiry.

Matching broadcaster/site rows can enrich missing fields across sources.
Different broadcasters, sites or countries remain separate choices. The sources
overlap (EiBi uses some HFCC information), so agreement is not independent RF
identification. Metadata remains a schedule suggestion, not reception proof.

Validation uses synthetic importer, date, midnight, cache, failure and merge
fixtures in `UI/test_offline_schedules.py`, plus an import of real provider files.

## Carrier-to-channel matching

The measured FFT carrier and a schedule's nominal broadcast frequency are
kept separate. Lookup first uses the configured direct tolerance (normally
1 kHz), preserving genuine off-channel schedule entries. If that yields no
active matches, shortwave lookup tries the nearest 5 kHz channel within 2.25
kHz of the measurement. A quarter-kHz region near a 5 kHz midpoint is left
unresolved rather than assigning the signal to an arbitrary neighbour.
The fallback accepts schedule frequencies within 0.25 kHz of that channel,
but never more than 2.25 kHz from the measured signal. LW/MW fallback uses
actual listed frequencies within 2.25 kHz instead of imposing a regional
9/10 kHz grid. The nearest listed frequency wins; near-equal alternatives
remain visible as possible matches.

Time, weekday and season checks still apply. Rounding cannot supply a name
when the database has no appropriate current entry. Lookup remains offline;
Research is still an explicit online action for unresolved signals.
