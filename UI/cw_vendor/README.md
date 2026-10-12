# GGMorse CW engine

Vendored from https://github.com/ggerganov/ggmorse at
`7b4822a8cfdbb1addfe497f3ae8186f142a4ee79` (MIT; see licenses/ggmorse-MIT.txt).
Only the library sources and public header are included. The four stdout text
prints/flush in ggmorse.cpp are suppressed; text is consumed via takeRxData.
No decoding algorithm changes. `bridge.cpp` is iTuner's bounded streaming C ABI.

Build with `python3 scripts/build-cw.py`. No model downloads, SDL, network access,
or compiler at application runtime. Each architecture builds its own library.
