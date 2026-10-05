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
