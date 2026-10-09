# October 2026 shared application consolidation

This source combines the completed decoder work and the previously separate
board interface into one application for future builds from `main`.

| Pull request | Disposition |
| --- | --- |
| #15 | Hell, QRSS, CW/GGMorse, optional fldigi, searchable histories, gallery gestures and local Kiwi address recovery |
| #12 | Board interface, receiver catalog, FM-DX, display reference kit and optional hang recorder merged into the shared source |
| #11 | Fully contained in #12's Git history; no second implementation is needed |
| #4 | Superseded by the live LCD baseline accepted in #9 and subsequent shared-source improvements |

PR #4 predates the accepted live-file consolidation. Reapplying its older
installer, UI and machine startup configuration would regress the protected
display profiles and reproducible dependency setup. The provenance and
checksums of its replacement are recorded in `consolidated-baseline.md`,
`cm5-pr9-validation.md` and `config/lcd-baseline-manifest.json`.
The previously excluded PR #8 knob interface remains excluded.

The PR #12 merge retains its newer receiver/browser controls and navigation,
and puts WSPR, SSTV, Hell, QRSS and CW together in the Modes drawer. Both drawing
and touch handling use the same non-overlapping launcher rectangles. WSPR
history/runtime fixes and all decoder lifecycle, web control and search hooks
remain present. Historical patches in `hardware/cm5/sstv` are provenance only;
do not apply them to this combined source.

Both `scripts/install.sh --cm5-existing-display` and the explicitly selected
legacy installer copy the shared local receiver recovery module automatically.
It needs no additional dependency or flag. The shared dependency installer
includes FFmpeg for FM-DX, WSJT-X for WSPR and Tesseract for OCR, and builds the
pinned GGMorse bridge. Full fldigi remains an optional explicit installation
through `scripts/install-fldigi.sh`. Display/audio hardware profiles remain
separate from application features.

Validation of the combined source:

- 244 UI/receiver/navigation tests passed, including launcher touch targets for
  all five decoders and exclusion from non-Kiwi mode controls.
- 155 application/decoder/runtime tests completed: 151 passed and four optional
  dependency/platform tests skipped.
- Installer shell syntax and Python compilation checked.
- Local receiver fallback was tested on CM5 with name lookup deliberately
  disabled, followed by a successful reconnect after removing the temporary
  `/etc/hosts` workaround.

This consolidation updates the repository. It does not itself reinstall either
machine, alter saved receiver sessions or apply display/boot configuration.
CM5 already runs the decoder and local receiver recovery changes, layered on
its earlier PR #12 installation; newer board-branch changes require a subsequent
application update to make its entire installed tree match this source.
