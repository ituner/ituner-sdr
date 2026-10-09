# SSTV on the existing CM5 PR #12 installation

CM5 was updated on 2026-10-05 with the SSTV source from commit `4083d38` while
retaining its installed PR #12 (`de457b1b2889d12fd25f4ad8c87c5f453bb04088`) UI,
FM-DX support, audio setup and display/touch configuration.

PR #12 replaced the Digital tools rail page with the Modes drawer. The two
navigation merge conflicts were resolved by retaining PR #12's Settings labels
and navigation-parent handling, and adding **SSTV beside WSPR in Modes**.
The full-width 15-image gallery and all decoder modules are unchanged from
PR #13.

`pr12-ui.patch` records the exact changes applied to CM5's existing
`UI/kiwi_gl_display.py`. It is an alternative to the main-based UI changes in
PR #13, not a second patch to apply on top of them. Other SSTV files come from
PR #13 (`UI/sstv_*.py`, `UI/sstv_gallery.html`, `UI/sstv_vendor/`).

Expected SHA-256 before applying this compatibility patch:
`affd593b5498a33a23ef823c27b155de6f5d533badb024cc34800f8c8503c17e`

Installed UI SHA-256:
`9bb890a12acfd78144674c0613c12ad27c7653b40ba4f4a3b65e4b564adbadc6`

The original file, deployment manifest and patch are retained on CM5 in:
`/var/backups/ituner-sdr/before-sstv-20261005-033631/`.
Staging files and the checksum-guarded deployment script are in
`/home/ituner/sstv-cm5-stage/`.

Validation on CM5:
- 11 SSTV tests passed; the test-only PySSTV encoder round trip was skipped
  because that encoder is not installed in the production runtime.
- Separately decoded an independently generated Martin M2 WAV on CM5.
- Imported the combined PR #12 + SSTV app and verified both Modes launcher
  hit targets.
- Service restarted with no automatic restarts; logs confirm OpenGL, touch,
  receiver audio and waterfall startup, with the existing normal orientation.
- Checked that boot configuration, application configuration and audio/display
  startup script checksums were unchanged.

No live SSTV transmission was needed for these checks. Over-the-air reception
still needs a receiver tuned to an active transmission. No test images or
sample decoder sessions were added to the user's gallery.

## Progress and additional modes update (2026-10-05)

Updated only `sstv_decoder.py`, `sstv_modes.py`, `sstv_monitor.py`,
`sstv_workspace.py` and `sstv_gallery.html`. The PR #12-compatible main UI
above is unchanged. The five-file update adds 48 analog modes and live
receiving/processing previews, with no new production dependencies.

Backup: `/var/backups/ituner-sdr/before-sstv-progress-20261005-040023/`.
Staging and manifest: `/home/ituner/sstv-progress-stage/`.

Validation: 17 on-device tests passed, with two test-only encoder cases
skipped. A separately generated PD120 waveform decoded successfully on CM5
(row correlation 0.9732). Development validation passed all 19 SSTV tests,
including the independent encoder cases, plus 13 audio/bootstrap regressions.
Rendered both OpenGL views at 1280 × 800 and exercised browser placeholders,
preview replacement, completion and live enlarged-image updates.

The three user's Kiwi sessions and their frequencies were retained. Short
18-second samples from 14.230, 18.117 and 21.340 MHz had nonzero PCM and no
clipping, but no valid SSTV headers; the 20 m spectrogram showed broadband
noise. No successful over-the-air image is claimed from these checks.

## WSPR browser and shared receiver controls (2026-10-05)

Both `/sstv` and `/wspr` now offer Start/Stop for configured receivers.
WSPR includes receiver status, capture progress, filtering and recent spots.
Commands execute on the UI thread and persist through the existing settings.
The shared server starts even when no SSTV sessions have been configured.

For the PR #12 installation above, apply `digital-web-ui.patch` **after**
`pr12-ui.patch`, and install `UI/digital_web.py`, `UI/wspr_gallery.html` and
the current `UI/sstv_monitor.py` / `UI/sstv_gallery.html` from this branch.
Do not replace the PR #12 main UI with this branch's main-based version.

Installed combined UI SHA-256: `59f0f2d1538f95cbed571dbaca6e62db5bec501a0e1369241d457f56da48df16`.
Backup: `/var/backups/ituner-sdr/before-digital-web-20261005-121554/`.
Staging: `/home/ituner/digital-web-stage/` (manifest and guarded installer).
The backup's `restore.json` records which files existed before installation;
restore those files and remove only the newly added files to roll back, with
the service stopped, then restart it.

Validation: five new control/API tests passed both locally and on CM5;
17 existing SSTV tests and 13 audio/bootstrap tests passed locally (two
optional SSTV encoder cases skipped). Browser checks covered both pages,
Stop/Start round trips, cross-links and phone-width layout. Live SSTV
Stop/Start was confirmed on CM5 and its original running state restored.
No WSPR receivers were configured on CM5 during deployment; WSPR control
behavior was tested with session fixtures. Display/touch/audio startup
configuration checksums were preserved; the service is active with no
automatic restarts.

## Receiver selection and image enlargement (2026-10-05)

Both browser pages now have Add decoder and Edit receiver / band controls,
using the local Kiwi/current receiver/directory list and the same band
presets as the touchscreen. Search covers receiver name, location and URL.
Start/Stop and Remove use the same live and persisted configurations.
Editing preserves paused state; adding can either start or save stopped.
SSTV's local Decoders page also gains Edit. Gallery images and receiver
thumbnails open a large, aspect-preserving browser image viewer.

For PR #12, apply `digital-editor-ui.patch` after `pr12-ui.patch` and
`digital-web-ui.patch`, and install the current SSTV modules plus
`digital_web.py`, `digital_controls.js` and both web HTML files.
The main-based branch's main UI is still not a replacement for PR #12's UI.

Installed UI SHA-256: `40069f295b11faba159c97898678e5b54e86f71b9760c2a818a0bf5fa996733e`.
Backup: `/var/backups/ituner-sdr/before-digital-editor-20261005-123004/`.
Staging: `/home/ituner/digital-editor-stage/`.

Ten control/editor tests passed locally and on CM5 (staged tests use
`PYTHONPATH=UI:/opt/ituner-sdr/UI` for unchanged dependencies). Seventeen
SSTV tests passed locally, with two optional encoder tests skipped. Browser
checks covered Add, receiver/band choice, Start, Stop, Edit and Remove in
both modes, both image enlargement entry points, and mobile dialog sizing.
The local Decoders and Edit views were rendered at 1280 × 800.

Live CM5 browser testing created temporary stopped decoders, started them,
changed their bands while stopped and removed them. WSPR reached LIVE/ARMED;
SSTV reached LISTENING. The picker contained 1,377 receivers at validation.
Original decoder IDs, source addresses, frequencies and paused states were
verified unchanged afterward. The service remained active with zero
automatic restarts; protected display, touch and audio setup checksums were
unchanged. No successful over-the-air WSPR decode is claimed by this test.

## WSPR runtime repair (2026-10-08)

Apply `wspr-runtime-ui.patch` after the three UI patches above. It preserves
PR #12's navigation while repairing the same WSPR code as the main branch.
The root-owned `/opt/ituner-sdr/UI` directory is intentionally not writable by
`ituner`; the old decoder exited with `Error: inaccessible data directory: '.'`.
Each decode now runs in its writable capture directory, drains process output,
reaps stopped/timed-out processes, and reports the underlying error during retry.
New capture/retry states clear the previous cycle's progress.

Installed UI SHA-256: `bb41fc379ecec9d7fe61f740e92955fdcb8a623eff672334e579c19fd3d204df`.
Backup: `/var/backups/ituner-sdr/before-wspr-runtime-20261008-101941/`.
Staging: `/home/ituner/wspr-fix-stage/`. The guarded installer retained the
boot configuration, app configuration and CM5 audio/display launcher hashes.
The application started with zero automatic restarts.

Validation: 47 local tests completed (45 passed, two optional encoder cases
skipped). All five new subprocess/progress regressions also passed on CM5.
The installed worker ran the real `/usr/bin/wsprd` against a 120-second silent
12 kHz, 16-bit mono WAV while the calling process remained in the unwritable
application directory. It completed successfully with no spots and created its
auxiliary files only in the temporary capture directory.

The user's 40 m WSPR receiver at 7038.6 kHz and both existing SSTV receivers
were restarted with their IDs, sources and frequencies retained. At validation,
`kiwisdr.local:8073` accepted TCP but returned no HTTP status or audio, including
while all our digital receivers were stopped. The receivers now accurately
report RETRY with zero stale progress. Live WSPR reception cannot be verified
until that separate Kiwi service recovers; no over-the-air decode is claimed.
PR #12 remains a separate, unmerged PR; this deployment preserves its installed
features without merging it into main.

## Persistent WSPR history and optional reporting (2026-10-08)

Apply `wspr-history-ui.patch` after `wspr-runtime-ui.patch`, and install
`wspr_history.py`, `wspr_history_view.py`, `wspr_history.js`, `wspr_gallery.html`,
`sstv_monitor.py` and `digital_web.py` from the corresponding main update.
This preserves the installed PR #12 navigation and features. It does not merge
PR #12 into main or change display, touch, audio or boot configuration.

Expected original UI SHA-256:
`bb41fc379ecec9d7fe61f740e92955fdcb8a623eff672334e579c19fd3d204df`.
Installed UI SHA-256:
`4b04b49fe7b08edb287dec0b794dee3c1fe222483e93a4cf67dcf48b11c75b11`.

See [WSPR history and reporting](../../../docs/WSPR_HISTORY.md) for retained
logs, local/web filters, CSV export, receiver identities and upload behaviour.

Deployed with backup
`/var/backups/ituner-sdr/before-wspr-history-20261008-111236/`.
The timestamp follows CM5's configured local timezone; its UTC clock was
NTP-synchronized. Staging: `/home/ituner/wspr-history-deploy/`.

Validation: 71 local tests completed (69 passed, two optional encoder cases
skipped); all 24 history, reporting, HTTP and integration cases passed on CM5.
The native history and settings screens were rendered at 1280 × 800. Browser
checks verified the confirmation guard, save/off settings, actual CM5 history
and Stop/Start. The archive imported 51 real spots, kept all 51 across the live
40 m decoder restart, and exported all 51 CSV rows. The existing SSTV receiver
states remained one running and one stopped. The app had zero automatic
restarts and unchanged protected boot/display/audio configuration hashes.
Uploads remained disabled; no synthetic spots were sent to WSPRnet.

## Hell RX (2026-10-08)

Apply `hell-ui.patch` after `wspr-history-ui.patch`. Install `UI/hell_*.py`,
`UI/hell_gallery.html`, `UI/digital_web.py`, `UI/sstv_monitor.py`, both updated
SSTV/WSPR HTML pages and `licenses/fldigi-GPL-3.txt`. The patch preserves PR #12
and adds **HELL RX** below WSPR/SSTV in the Modes drawer. Main's normal Digital
tools menu receives the same feature through its own UI changes.

Expected input UI SHA-256:
`4b04b49fe7b08edb287dec0b794dee3c1fe222483e93a4cf67dcf48b11c75b11`.
Final installed UI SHA-256:
`b6b12ec88cbd632f0c478f5cadd3c6583f0ac7dc276dce9e37d43898eb9c75ed`.

Original pre-Hell backup:
`/var/backups/ituner-sdr/before-hell-20261008-123928/`.
Staging: `/home/ituner/hell-deploy/`. The installer checks the live UI and every
payload checksum, backs up changed files, preserves protected configuration
hashes, and restores the previous application if startup fails.

Validation: 81 local tests completed (79 passed, two optional SSTV encoder tests
skipped); all ten new Hell cases passed on CM5. Seven independently modulated
signals exercised the actual receive DSP. Local gallery/editor/report screens
were rendered at 1280×800; the PR #12 Modes launcher and hit targets were
verified separately. Browser tests covered settings, live audio/image reception,
Stop, image retention, enlargement and the explicit report form. No synthetic
reports were sent to PSK Reporter. No readable on-air Hell transmission is
claimed from the short live audio check.

A local 40 m Feld Hell decoder (7083.5 kHz USB + 1500 Hz audio) was created for
the live test and left stopped. Its captured strips remain. The user's two
WSPR and two SSTV decoder configurations and active states were retained.
The running service had no automatic restarts and unchanged boot configuration,
app configuration and display/audio launcher checksums. See
[Hell operation and reporting](../../../docs/HELL.md).

QRSS adds visual captures and tentative CW / FSKCW text. For a PR12 UI already
carrying `hell-ui.patch`, apply `qrss-ui.patch` next. Copy the `UI/qrss_*` files,
updated `digital_web.py`, `sstv_monitor.py`, digital gallery pages and
`licenses/qrsspig-GPL-3.txt`. The main-branch UI has these hooks directly.
See [QRSS operation](../../../docs/QRSS.md). No display or audio driver changes
are involved.

QRSS was validated on CM5 with eight passing tests, including generated
CW/FSKCW at all five dot speeds and saved-text/image continuity. The live 30 m
check receives a waterfall using one additional Kiwi audio session; stopping
retains its capture. Existing two WSPR, two SSTV and seven-mode Hell receiver
sessions resumed. Backup: `/var/backups/ituner-sdr/before-qrss-20261008-135223`.
The service remained active without automatic restarts and installed hashes
matched the deployment manifest. No on-air Morse text is claimed from this test.

Automatic QRSS acquisition updates the `qrss_*` modules without changing the
main UI launcher. The 30 m receiver was switched to AUTO through the shared
control API. Final backup:
`/var/backups/ituner-sdr/before-qrss-auto-20261008-230553`.
All five automatic-acquisition tests pass on CM5, including the saved-raster
regression and a short real PCM spectrum fixture. The full local suite runs
99 tests, with 96 passing and three optional dependency skips. Boot/display/audio
configuration remains unchanged; the application has no automatic restarts.


The multi-signal QRSS update replaces the same `qrss_*` modules and follows up
to six independent signals from one audio stream. The CM5 backup is
`/var/backups/ituner-sdr/before-qrss-multi-20261009-025826`. Sixteen QRSS tests
passed on CM5, including concurrent unequal-level CW/FSKCW, independent
cadences, track limits, signal loss, and saved multi-track text. The full local
suite passed 102 tests with three optional dependency skips. The 1280×800
enlarged view shows six separate text rows, with paging for recent tracks.
