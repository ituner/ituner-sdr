# Whisper Base on CM5

Both standard installation profiles provision multilingual Whisper Base Q5_1
and CPU-only whisper.cpp 1.9.4. The exact upstream commit, model revision and
SHA-256 checksums are pinned in `config/whisper-runtime.json`. Model weights
are downloaded, not committed to Git. No cloud service or API key is required.

To add or repair only Whisper on an existing CM5:

```sh
sudo apt-get install -y --no-install-recommends cmake build-essential
sudo python3 scripts/install-whisper.py
```

Then select WHISPER in the ASR controls. Restart the application after the first
installation so its startup model discovery sees the new files. Installation
itself does not select an engine, stop receivers or change display/audio drivers.

The installer checks both downloads before building, uses one compilation job,
and verifies transcription of the upstream JFK sample before publishing the
runtime. Existing copies are retained for rollback. Repeat installation skips
verified files; `--verify-only` validates the model and installed binary without
network access. `--vendor PATH` and `--cache PATH` support isolated validation.
The main dependency bootstrap passes its own vendor/cache paths through.
Its `--models-only` option also provisions the native Whisper runtime needed
to use this model; CMake and a C++ toolchain must therefore be present.

The app prefers `ggml-base-q5_1.bin`, retaining existing Tiny models as fallbacks.
`ITUNER_WHISPER_MODEL` selects another installed model filename explicitly.
Language detection defaults to automatic (`ITUNER_WHISPER_LANGUAGE=auto`).
The multilingual model supports original-language transcription and the app's
English translation modes; `base.en` is not installed.

Live decoding keeps the existing two-thread, low-priority CPU guard. Audio is
decoded in overlapping windows, with a fresh CLI process for each decode;
this is not a persistent streaming model. Actual speed and accuracy depend on
language, noise and other active decoders. The 60 MB model download is not an
estimate of total runtime RAM. On the 2 GB CM5, multiple fldigi workers may
compete for memory; benchmark under the intended workload before adding more.

Upstream sources: [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and
[GGML model files](https://huggingface.co/ggerganov/whisper.cpp).

## CM5 validation

The installer was exercised on the 2 GB CM5: the pinned download checks, native
build, JFK speech transcription and repeat `--verify-only` all passed. Live
Base Q5_1 inference used automatic language detection and two CPU threads.
Under that workload, the app measured a real-time factor of about 2.8 (slower
than real time) and a full audio queue. Total CPU use was about 62%, with
approximately 1.24 GiB of available RAM; temperature reached 83–84°C and the
firmware reported a soft temperature limit, with the CPU observed at 2.26 GHz.
The existing caption font rendered Chinese glyphs as boxes; CJK font coverage
needs separate UI work. This validates installation and
execution, not uninterrupted real-time captions or Chinese recognition accuracy.
Reduce model/workload demands or improve performance before relying on
continuous Base captions on this hardware.
