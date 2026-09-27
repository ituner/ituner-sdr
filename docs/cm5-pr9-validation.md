# CM5 staged application test — 2026-09-27

Tested application/installer commit: `c96bb9e757117853d5cf558a5db61f961ab7a91a`.
Subsequent validation-document changes do not change that installed application.
PR: https://github.com/ituner/ituner-sdr/pull/9

## Installation and runtime

- Used the public `scripts/install.sh --cm5-existing-display` entry point on the
  existing prepared CM5 OS. This is not a fresh SD-card/OS installation test.
- Backed up application files, services and local settings before installation.
  Rollback archive on CM5:
  `/home/ituner/cm5-pr9-test/backup-20260927-164818/application-and-settings.tar.gz`.
  The adjacent paths manifest records which managed paths previously existed.
  Vendor dependencies/models were retained in place, not duplicated or replaced.
- Deliberately changed the existing instrument preference from expanded to
  compact. Existing receiver preferences otherwise survived installation.
- All 51 tracked UI and asset files matched the installed copies byte for byte.
  Renderer SHA-256 matches the captured LCD reference, and Fontconfig resolves
  Oxanium to the newly installed bundled font.
- App, directory-health and GT911-readiness units passed systemd validation and
  were enabled. App ran with zero automatic restarts, normal orientation and
  touch flags `--swap-x-y --no-invert-x --invert-y`.
- Captured screenshot shows the compact right-side S-meter and UTC clock.
- The previously selected external receiver refused connections independently
  of the application. Selected the reachable repository-default receiver for
  testing; the app then logged successful sound and waterfall setup.
- Repeated installation succeeded and preserved existing settings.
- Reboot passed: app and health services automatically started, GT911 readiness
  passed, normal orientation was retained, and sound/waterfall setup succeeded.
  No automatic app restarts were observed; all eight protected hashes still
  matched after reboot.

## Display protection

All eight protected files matched their pre-install SHA-256 values: boot config,
JD9365 kernel module, CM5 display/touch/audio overlays, labwc and kanshi settings.
No display driver, boot overlay or orientation configuration was replaced.
The legacy ST7701 dependency path was explicitly omitted.

## Remaining validation boundaries

The user confirmed the on-device screen looked correct after the reboot test.
The established touch mapping is preserved; no new physical driver was installed.
OpenWebRX, local Airspy/RTL hardware, Wi-Fi reconnect, optional speech models and
onboard speaker output were not comprehensively exercised in this test. The
known onboard audio wiring repair remains separate. Existing optional runtime
packages/models were reused, so this does not establish their reproducibility
on a blank OS image. Complete download/checksum manifests before claiming that.

Original LCD remains unchanged. The user accepted the CM5 test and requested
a fresh application install from GitHub main. This validation supports promoting
the shared application baseline; it does not remove the optional-feature and
fresh-OS limitations above.

## Official baseline acceptance

PR #9 merged as `b548509f0bbdb0986794ec435e0501fb13403196`. CM5 application
files, services and UI settings were backed up and removed, CM5 rebooted, and
a fresh main checkout installed. Compact/Oxanium defaults and normal orientation
were created automatically. All 51 UI/assets matched; all eight protected display
files remained unchanged. A second reboot automatically started the application,
detected touch and connected the receiver streams. Existing OS packages and
vendor models/runtimes were retained.

On 2026-09-27 the waterfall settings on both machines were matched to Classic,
floor 142, ceiling 245, speed 4, auto levelling off, spectrum enabled. The owner
confirmed all tests were OK and designated main as the official application
source. The same settings are now recorded in fresh-install defaults.
