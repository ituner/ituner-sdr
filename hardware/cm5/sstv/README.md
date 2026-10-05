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
