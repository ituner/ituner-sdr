"""Continuous PCM16 SSTV framing and isolated image decoder.

The P4 trusted-mode and row-correlation checks are retained. Header scanning
is bounded to newly arrived audio; full images are decoded outside the UI.
"""
import io
import json
import os
from pathlib import Path
import sys
import wave

vendor = Path(__file__).resolve().parent.parent / 'vendor' / 'python'
if vendor.is_dir():
    sys.path.insert(0, str(vendor))
import numpy as np
from sstv_vendor import decode, spec

decode.log_message = lambda *a, **k: None
decode.progress_bar = lambda *a, **k: None
RATE = 12000


class PixelDecoder(decode.SSTVDecoder):
    def _peak_fft_freq(self, data):
        # Pixel windows can be only 13 samples at 12 kHz. Interpolating the
        # unpadded FFT (P4/upstream) biases the 1500–2300 Hz color range.
        # Zero padding plus a quadratic peak estimate preserves color levels.
        count = len(data)
        if count < 3:
            return 0.0
        nfft = max(128, 1 << (count*4-1).bit_length())
        spectrum = np.abs(np.fft.rfft(data*np.hanning(count), n=nfft))
        peak = int(np.argmax(spectrum))
        offset = 0.0
        if 0 < peak < len(spectrum)-1:
            a, b, c = spectrum[peak-1:peak+2]
            den = a-2*b+c
            if abs(den) > 1e-15:
                offset = .5*(a-c)/den
        return (peak+offset)*self._sample_rate/nfft


def decoder_for(pcm):
    decoder = PixelDecoder.__new__(PixelDecoder)
    decoder._audio_file = None
    decoder._sample_rate = RATE
    decoder._samples = np.frombuffer(pcm, dtype='<i2').astype(float) / 32768.0
    decoder.mode = None
    return decoder


class FrameAssembler:
    """Keep complete headers across chunks and never stop capturing to decode.

    emit(pcm, metadata) receives a partial preview every 30 seconds and a final
    frame. A disconnect resets framing so unrelated audio is never spliced.
    """
    def __init__(self, emit, status=lambda *a: None):
        self.emit, self.status = emit, status
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.mode = None
        self.frame_id = None
        self.expected = 0
        self.scan_after = RATE * 2
        self.preview_after = RATE * 2 * 30

    def feed(self, pcm):
        self.buffer.extend(pcm)
        while True:
            if self.mode is None:
                if len(self.buffer) < self.scan_after:
                    return
                decoder = decoder_for(self.buffer)
                header = decoder._find_header()
                # Need all VIS bits, parity and stop before committing a frame.
                if header is not None and len(decoder._samples) >= header + round(.27 * RATE):
                    try:
                        mode = decoder._decode_vis(header)
                        bit_size = round(.03 * RATE)
                        tones = [decoder._peak_fft_freq(decoder._samples[header+i*bit_size:header+(i+1)*bit_size]) for i in range(8)]
                        if any(min(abs(t-1100), abs(t-1300)) > 65 for t in tones):
                            raise ValueError('Invalid VIS tones')
                    except ValueError as exc:
                        self.status('UNSUPPORTED / INVALID', str(exc))
                        del self.buffer[:(header + round(.27 * RATE)) * 2]
                        self.scan_after = RATE * 2
                        continue
                    start = max(0, header - round(spec.HDR_SIZE * RATE))
                    del self.buffer[:start * 2]
                    self.mode = mode
                    import uuid
                    self.frame_id = uuid.uuid4().hex
                    # Include a small tail for sync alignment and Scottie's initial sync.
                    self.expected = round((.91 + mode.LINE_TIME * mode.LINE_COUNT + .3) * RATE) * 2
                    self.preview_after = RATE * 2 * 30
                    self.status('RECEIVING', mode.NAME)
                else:
                    # Retain 1.3 seconds: a header crossing the next chunk remains whole.
                    keep = round(1.3 * RATE) * 2
                    if len(self.buffer) > keep:
                        del self.buffer[:-keep]
                    self.scan_after = len(self.buffer) + RATE * 2
                    return
            full = len(self.buffer) >= self.expected
            if full or len(self.buffer) >= self.preview_after:
                size = self.expected if full else len(self.buffer)
                self.emit(bytes(self.buffer[:size]), {
                    'id': self.frame_id, 'mode': self.mode.NAME,
                    'kind': 'full' if full else 'partial',
                    'progress_pct': min(100, round(100 * size / self.expected)),
                })
                self.preview_after = len(self.buffer) + RATE * 2 * 30
            if not full:
                return
            # Retain the guard tail: it may contain the next transmission's leader.
            consumed = self.expected - round(.3 * RATE) * 2
            tail = bytes(self.buffer[consumed:])
            self.reset()
            self.buffer.extend(tail)
            self.status('LISTENING', 'Waiting for the next SSTV transmission')


def image_quality(image, progress=100):
    # P4's adjacent-row correlation check, vectorized and excluding undecoded rows.
    gray = np.asarray(image.convert('L'), dtype=float)
    gray = gray[:max(2, int(len(gray) * progress / 100) - 3)]
    a, b = gray[:-1], gray[1:]
    a = a - a.mean(axis=1, keepdims=True)
    b = b - b.mean(axis=1, keepdims=True)
    den = np.sqrt((a*a).sum(axis=1) * (b*b).sum(axis=1))
    good = den > 1e-9
    return float(((a*b).sum(axis=1)[good] / den[good]).mean()) if good.any() else 0.0


def decode_file(wav_path, png_path, progress=100):
    with open(wav_path, 'rb') as stream:
        decoder = PixelDecoder(stream)
        image = decoder.decode()
    if image is None:
        raise ValueError('No SSTV header')
    quality = image_quality(image, progress)
    if quality < .08:
        raise ValueError('Rejected noise-like image (row correlation < 0.08)')
    image.save(png_path, format='PNG')
    return {'mode': decoder.mode.NAME, 'row_corr_mean': quality}


if __name__ == '__main__':
    # A subprocess prevents pixel FFTs from competing with the render thread's GIL.
    if hasattr(os, 'nice'):
        os.nice(10)
    try:
        result = decode_file(sys.argv[1], sys.argv[2], float(sys.argv[3]))
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
