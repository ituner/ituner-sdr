# Dependency bootstrap validation — 2026-09-27

Platform: CM5, 64-bit Raspberry Pi OS Trixie, Python 3.13.5, aarch64.
The live application and its working vendor directory were preserved.

- Captured all 40 package versions from the accepted CM5 vendor runtime.
- Downloaded every pinned wheel, recorded SHA-256, then downloaded/installed
  them again into a completely empty test vendor directory using a fresh cache
  and the new installer. No copy from the live vendor directory was used.
- Retrieved Vosk Small English 0.15, Moonshine Base/Tiny INT8 and Parakeet 110M
  INT8 from official upstream URLs. Archive and extracted-file hashes verified.
  Runtime model files also match the original accepted copies byte for byte.
- Bundled HF-enhancement ONNX asset matches the live CM5 checksum.
- Fresh Python import and transitive dependency checks passed.
- Separate model-load processes successfully initialized Vosk English, Moonshine
  Base, Moonshine Tiny, Parakeet 110M and HF enhancement from the fresh directory.
- OS dependency helper executed successfully. Required packages resolved; only
  the previously absent Airspy HF+ library needed installation. No package
  upgrades/removals or kernel/display changes were made.
- Repeated provisioning reused the verified Python runtime and all models.
  Live SDR remained active with zero automatic restarts; all eight protected
  display/boot checksums were unchanged.
- Five safety tests passed: ZIP traversal rejection, TAR symlink rejection,
  corrupted-download rejection, preservation of an existing model on failed
  replacement, and no network download for a verified existing model.
- Python compilation, shell syntax and whitespace checks passed.

This proves fresh application-runtime/model provisioning on the prepared OS.
It is not an SD-card reimage, a new display-driver bring-up, an accuracy benchmark,
or validation of every optional experimental engine and external radio device.
