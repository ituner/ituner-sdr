# HF enhancement inference asset

`hf-enhance-tiny.onnx` is the project-specific HF enhancement model already
running on the accepted CM5 setup. SHA-256:
`4fd0c2191f7fba410ab7fee80564ec303de98519e95d2a9d7dfdaba6629f48be`.

It is copied into `vendor/hf-enhance-tiny` by the dependency installer. The
application runs it through the pinned ONNX Runtime; training-only PyTorch
checkpoints and private training data are not needed and are not included.
The standard Vosk/Moonshine/Parakeet model downloads and checksums are in
`config/runtime-models.json` rather than large Git objects.
