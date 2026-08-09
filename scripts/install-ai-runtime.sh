#!/usr/bin/env bash
# Install every local AI feature used by the SDR UI into its portable vendor
# tree. This runs from install.sh but can also repair an existing installation.
set -Eeuo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${ITUNER_SDR_PREFIX:-"${repo_dir}"}
vendor_dir="${prefix}/vendor"
python_dir="${vendor_dir}/python"
work_dir=$(mktemp -d)
trap 'rm -rf "${work_dir}"' EXIT

install -d -m 0755 "${vendor_dir}" "${python_dir}"

echo 'Installing bundled HF Enhance listening models…'
hf_model_source="${repo_dir}/vendor/hf-enhance-tiny"
hf_model_destination="${vendor_dir}/hf-enhance-tiny"
install -d -m 0755 "${hf_model_destination}"
for hf_model in hf-enhance-tiny-v1.onnx hf-enhance-tiny.onnx; do
  [[ -f "${hf_model_source}/${hf_model}" ]] || { echo "Bundled HF Enhance model is missing: ${hf_model}" >&2; exit 1; }
  install -m 0644 "${hf_model_source}/${hf_model}" "${hf_model_destination}/${hf_model}"
done

fetch_archive() {
  local url=$1 archive=$2 destination=$3
  [[ -d "${vendor_dir}/${destination}" ]] && return
  curl --fail --location --retry 3 --retry-delay 2 --output "${work_dir}/${archive}" "${url}"
  case ${archive} in
    *.zip) unzip -q "${work_dir}/${archive}" -d "${vendor_dir}" ;;
    *.tar.bz2) tar -xjf "${work_dir}/${archive}" -C "${vendor_dir}" ;;
    *) echo "Unsupported model archive: ${archive}" >&2; exit 1 ;;
  esac
}

echo 'Installing Python audio, ASR, and inference wheels…'
python3 -m pip install --disable-pip-version-check --no-warn-script-location --upgrade \
  --target "${python_dir}" \
  -r "${repo_dir}/requirements-runtime.txt" \
  -r "${repo_dir}/requirements-asr-optional.txt"

echo 'Downloading local ASR models…'
fetch_archive \
  'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' \
  'vosk-model-small-en-us-0.15.zip' 'vosk-model-small-en-us-0.15'
fetch_archive \
  'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-moonshine-base-en-int8.tar.bz2' \
  'sherpa-onnx-moonshine-base-en-int8.tar.bz2' 'sherpa-onnx-moonshine-base-en-int8'
fetch_archive \
  'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8.tar.bz2' \
  'sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8.tar.bz2' 'sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8'

if [[ ! -x "${vendor_dir}/whisper.cpp/build/bin/whisper-cli" ]]; then
  echo 'Building Whisper.cpp for this Raspberry Pi…'
  rm -rf "${work_dir}/whisper.cpp"
  git init -q "${work_dir}/whisper.cpp"
  git -C "${work_dir}/whisper.cpp" remote add origin https://github.com/ggerganov/whisper.cpp.git
  git -C "${work_dir}/whisper.cpp" fetch -q --depth 1 origin 592feef04a1802b18cbeffd0fd0eb5d02570c2ec
  git -C "${work_dir}/whisper.cpp" checkout -q --detach FETCH_HEAD
  cmake -S "${work_dir}/whisper.cpp" -B "${work_dir}/whisper.cpp/build" \
    -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON
  cmake --build "${work_dir}/whisper.cpp/build" --target whisper-cli -j"$(nproc)"
  rm -rf "${vendor_dir}/whisper.cpp"
  cp -a "${work_dir}/whisper.cpp" "${vendor_dir}/whisper.cpp"
  "${vendor_dir}/whisper.cpp/models/download-ggml-model.sh" tiny
fi

if [[ ! -f "${vendor_dir}/rnnoise-install/lib/librnnoise.so" ]]; then
  echo 'Building the RNNoise neural voice cleaner…'
  git init -q "${work_dir}/rnnoise"
  git -C "${work_dir}/rnnoise" remote add origin https://github.com/xiph/rnnoise.git
  git -C "${work_dir}/rnnoise" fetch -q --depth 1 origin 70f1d256acd4b34a572f999a05c87bf00b67730d
  git -C "${work_dir}/rnnoise" checkout -q --detach FETCH_HEAD
  (
    cd "${work_dir}/rnnoise"
    ./autogen.sh
    ./configure --prefix="${vendor_dir}/rnnoise-install"
    make -j"$(nproc)"
    make install
  )
fi

PYTHONPATH="${python_dir}${PYTHONPATH:+:${PYTHONPATH}}" python3 - <<'PY'
import importlib
for module in ("sounddevice", "vosk", "sherpa_onnx", "moonshine_voice", "onnxruntime", "deepgram"):
    importlib.import_module(module)
print("Python AI runtime verified")
PY

for required in \
  "${vendor_dir}/vosk-model-small-en-us-0.15/am/final.mdl" \
  "${vendor_dir}/sherpa-onnx-moonshine-base-en-int8/preprocess.onnx" \
  "${vendor_dir}/sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8/model.int8.onnx" \
  "${vendor_dir}/whisper.cpp/build/bin/whisper-cli" \
  "${vendor_dir}/whisper.cpp/models/ggml-tiny.bin" \
  "${vendor_dir}/rnnoise-install/lib/librnnoise.so" \
  "${vendor_dir}/hf-enhance-tiny/hf-enhance-tiny-v1.onnx" \
  "${vendor_dir}/hf-enhance-tiny/hf-enhance-tiny.onnx"; do
  [[ -e ${required} ]] || { echo "Missing installed runtime file: ${required}" >&2; exit 1; }
done

echo "AI runtime installed in ${vendor_dir}"
