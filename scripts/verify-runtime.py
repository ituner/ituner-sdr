#!/usr/bin/env python3
"""Verify all pinned dependencies, then load each model in a separate process."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--vendor", type=Path, default=Path("/opt/ituner-sdr/vendor"))
args = parser.parse_args()
subprocess.run([sys.executable, str(Path(__file__).with_name("bootstrap-runtime.py")),
                "--vendor", str(args.vendor), "--verify-only"], check=True)
env = dict(os.environ, PYTHONPATH=str(args.vendor.resolve() / "python"), OMP_NUM_THREADS="2")
checks = {
    "Vosk English": """
import vosk
vosk.SetLogLevel(-1)
model = vosk.Model(str(root / 'vosk-model-small-en-us-0.15'))
recognizer = vosk.KaldiRecognizer(model, 16000)
recognizer.AcceptWaveform(bytes(3200))
""",
    "Moonshine Base": """
import sherpa_onnx
p = root / 'sherpa-onnx-moonshine-base-en-int8'
recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine(
    preprocessor=str(p/'preprocess.onnx'), encoder=str(p/'encode.int8.onnx'),
    uncached_decoder=str(p/'uncached_decode.int8.onnx'),
    cached_decoder=str(p/'cached_decode.int8.onnx'), tokens=str(p/'tokens.txt'), num_threads=2)
""",
    "Moonshine Tiny": """
import sherpa_onnx
p = root / 'sherpa-onnx-moonshine-tiny-en-int8'
recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine(
    preprocessor=str(p/'preprocess.onnx'), encoder=str(p/'encode.int8.onnx'),
    uncached_decoder=str(p/'uncached_decode.int8.onnx'),
    cached_decoder=str(p/'cached_decode.int8.onnx'), tokens=str(p/'tokens.txt'), num_threads=2)
""",
    "Parakeet 110M": """
import sherpa_onnx
p = root / 'sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8'
recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
    model=str(p/'model.int8.onnx'), tokens=str(p/'tokens.txt'),
    num_threads=2, sample_rate=16000, feature_dim=80)
""",
    "HF enhancement": """
import onnxruntime as ort
options = ort.SessionOptions()
options.intra_op_num_threads = 2
session = ort.InferenceSession(str(root/'hf-enhance-tiny/hf-enhance-tiny.onnx'),
    sess_options=options, providers=['CPUExecutionProvider'])
assert session.get_inputs() and session.get_outputs()
""",
}
for name, code in checks.items():
    prefix = "from pathlib import Path\nimport sys\nroot=Path(sys.argv[1])\n"
    subprocess.run([sys.executable, "-c", prefix + code, str(args.vendor.resolve())],
                   env=env, check=True, timeout=120)
    print(f"Loaded successfully: {name}", flush=True)
