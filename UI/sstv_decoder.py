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
import sstv_modes  # Registers the additional conventional VIS modes.
from PIL import Image

decode.log_message = lambda *a, **k: None
decode.progress_bar = lambda *a, **k: None
RATE = 12000


class IncompleteHeader(ValueError):
    pass


class PixelDecoder(decode.SSTVDecoder):
    def _find_header(self):
        # The upstream finder samples only 10 ms of each leader. Validate
        # sustained leaders too, so random HF noise isn't called a new mode.
        samples = self._samples
        offset = 0
        self.header_leader_samples = round(.640*self._sample_rate)
        self.header_narrow = False
        try:
            while True:
                self._samples = samples[offset:]
                end = super()._find_header()
                if end is None:
                    break
                start = end-round(spec.HDR_SIZE*self._sample_rate)
                valid = True
                for seconds in (.05, .14, .23, .36, .45, .54):
                    at = start+round(seconds*self._sample_rate)
                    data = self._samples[at:at+round(.025*self._sample_rate)]
                    power = np.abs(np.fft.rfft(data*np.hanning(len(data))))**2
                    if abs(self._peak_fft_freq(data)-1900)>50 or power.max() < .35*max(power.sum(), 1e-15):
                        valid = False
                        break
                if valid:
                    return offset+end
                offset += start+round(.002*self._sample_rate)
        finally:
            self._samples = samples
        # Narrowband uses 1900/2100 Hz and a 24-bit, 22 ms/bit header.
        rate = self._sample_rate
        window = round(.010*rate)
        for start in range(0, len(samples)-round(.422*rate), round(.002*rate)):
            valid = True
            for seconds, target in ((.05,1900),(.18,1900),(.28,1900),(.300,2100),(.385,2100),(.401,1900)):
                at = start+round(seconds*rate)
                data = samples[at:at+window]
                power = np.abs(np.fft.rfft(data*np.hanning(len(data))))**2
                if abs(self._peak_fft_freq(data)-target)>35 or power.max()<.35*max(power.sum(),1e-15):
                    valid = False
                    break
            if valid:
                self.header_narrow = True
                self.header_leader_samples = round(.422*rate)
                return start+self.header_leader_samples
        return None

    def _decode_vis(self, start):
        if getattr(self, 'header_narrow', False):
            size = round(.022*self._sample_rate)
            self.vis_samples = size*24
            if len(self._samples)<start+self.vis_samples:
                raise IncompleteHeader('Incomplete narrowband VIS header')
            tones = [self._peak_fft_freq(self._samples[start+i*size:start+(i+1)*size]) for i in range(24)]
            if any(min(abs(t-1900),abs(t-2100))>45 for t in tones):
                raise ValueError('Invalid narrowband VIS tones')
            bits = [int(t<2000) for t in tones]
            values = [sum(bits[n+j]<<(5-j) for j in range(6)) for n in range(0,24,6)]
            if values[:2]!=[0x2d,0x15] or values[3] != (values[2]^0x15):
                raise ValueError('Invalid narrowband VIS checksum')
            mode = sstv_modes.NARROW_VIS_MAP.get(values[2])
            if mode is None:
                raise ValueError(f'Unsupported narrowband VIS: {values[2]}')
            return mode
        size = round(.03*self._sample_rate)
        self.vis_samples = size*9
        if len(self._samples) < start+9*size:
            raise IncompleteHeader('Incomplete VIS header')
        tones = [self._peak_fft_freq(self._samples[start+i*size:start+(i+1)*size]) for i in range(9)]
        if any(min(abs(t-1100), abs(t-1300))>65 for t in tones[:8]):
            raise ValueError('Invalid VIS tones')
        first = sum(int(t<1200)<<i for i,t in enumerate(tones[:8]))
        if first == 0x23:
            self.vis_samples = size*17
            if len(self._samples)<start+self.vis_samples:
                raise IncompleteHeader('Incomplete extended VIS header')
            tones = [self._peak_fft_freq(self._samples[start+i*size:start+(i+1)*size]) for i in range(17)]
            if any(min(abs(t-1100),abs(t-1300))>65 for t in tones[:16]) or abs(tones[16]-1200)>65:
                raise ValueError('Invalid extended VIS tones')
            code = sum(int(t<1200)<<i for i,t in enumerate(tones[:16]))
            mode = sstv_modes.EXTENDED_VIS_MAP.get(code)
            if mode is None:
                raise ValueError(f'Unsupported extended VIS: {code:04x}')
            return mode
        if abs(tones[8]-1200)>65:
            raise ValueError('Invalid VIS stop bit')
        return super()._decode_vis(start)

    def decode(self, skip=0.0):
        if skip:
            self._samples = self._samples[round(skip*self._sample_rate):]
        header = self._find_header()
        if header is None:
            return None
        self.mode = self._decode_vis(header)
        return self._draw_image(self._decode_image_data(header+self.vis_samples))

    def _align_sync(self, start, start_of_sync=True):
        if not getattr(self.mode, 'NARROW', False):
            return super()._align_sync(start, start_of_sync)
        window = round(self.mode.SYNC_PULSE*1.4*self._sample_rate)
        # Search only around the expected pulse, never into the next line.
        stop = min(len(self._samples)-window, start+round(.03*self._sample_rate))
        for pos in range(max(0,start),stop):
            if self._peak_fft_freq(self._samples[pos:pos+window])>1972:
                end = pos+window//2
                return end-round(self.mode.SYNC_PULSE*self._sample_rate) if start_of_sync else end
        return None

    def _decode_image_data(self, image_start):
        if not getattr(self.mode, 'BATCH_SCAN', False):
            return super()._decode_image_data(image_start)
        mode, rate = self.mode, self._sample_rate
        result = np.zeros((mode.LINE_COUNT, mode.CHAN_COUNT, mode.LINE_WIDTH), dtype=np.uint8)
        # Decode a whole scan in one NumPy FFT batch; PD290 has ~1M samples
        # of image data and must not monopolize a small CM5 CPU.
        window = max(48 if getattr(mode,'NARROW',False) else 24, round(mode.PIXEL_TIME*mode.WINDOW_FACTOR*rate))
        nfft = max(128, 1 << (window*4-1).bit_length())
        win = np.hanning(window)
        seq = image_start
        for line in range(mode.LINE_COUNT):
            if line:
                seq += round(mode.LINE_TIME*rate)
            aligned = self._align_sync(seq)
            if aligned is None:
                break
            seq = aligned
            for channel, channel_offset in enumerate(mode.CHAN_OFFSETS):
                pixel_time = getattr(mode,'CHANNEL_PIXEL_TIMES',[mode.PIXEL_TIME]*mode.CHAN_COUNT)[channel]
                centers = seq+(channel_offset+(np.arange(mode.LINE_WIDTH)+.5)*pixel_time)*rate
                indices = np.rint(centers[:,None]-window/2+np.arange(window)).astype(int)
                if indices[-1,-1] >= len(self._samples):
                    return result
                data = self._samples[np.maximum(indices,0)]*win
                spectrum = np.abs(np.fft.rfft(data,n=nfft,axis=1))
                peaks = spectrum.argmax(axis=1)
                rows = np.arange(mode.LINE_WIDTH)
                left = spectrum[rows,np.maximum(peaks-1,0)]
                mid = spectrum[rows,peaks]
                right = spectrum[rows,np.minimum(peaks+1,spectrum.shape[1]-1)]
                denominator = left-2*mid+right
                shift = np.divide(.5*(left-right),denominator,out=np.zeros_like(mid),where=abs(denominator)>1e-15)
                frequencies = (peaks+shift)*rate/nfft
                black, span = (2044,256) if getattr(mode,'NARROW',False) else (1500,800)
                result[line,channel] = np.clip(np.rint((frequencies-black)*255/span),0,255).astype(np.uint8)
        return result

    def _draw_image(self, data):
        if getattr(self.mode, 'PAIRED_LINES', False):
            a = np.asarray(data,dtype=np.uint8)
            pixels = np.empty((self.mode.LINE_COUNT*2,self.mode.LINE_WIDTH,3),dtype=np.uint8)
            pixels[::2,:,0], pixels[1::2,:,0] = a[:,0], a[:,3]
            pixels[::2,:,1] = pixels[1::2,:,1] = a[:,2]
            pixels[::2,:,2] = pixels[1::2,:,2] = a[:,1]
            return Image.fromarray(pixels, 'YCbCr').convert('RGB')
        if self.mode.COLOR == spec.COL_FMT.BW:
            return Image.fromarray(np.asarray(data,dtype=np.uint8)[:,0], 'L').convert('RGB')
        return super()._draw_image(data)

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

    emit(pcm, metadata) receives a preview after 10 seconds, then every 30 seconds, and a final
    frame. A disconnect resets framing so unrelated audio is never spliced.
    """
    def __init__(self, emit, status=lambda *a: None, progress=lambda *a: None):
        self.emit, self.status, self.progress = emit, status, progress
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.mode = None
        self.frame_id = None
        self.expected = 0
        self.scan_after = RATE * 2
        self.preview_after = RATE * 2 * 10
        self.progress(None)

    def feed(self, pcm):
        self.buffer.extend(pcm)
        while True:
            if self.mode is None:
                if len(self.buffer) < self.scan_after:
                    return
                decoder = decoder_for(self.buffer)
                header = decoder._find_header()
                # Need all VIS bits, parity and stop before committing a frame.
                if header is not None:
                    try:
                        mode = decoder._decode_vis(header)
                    except IncompleteHeader:
                        self.scan_after = len(self.buffer)+round(.1*RATE)*2
                        return
                    except ValueError as exc:
                        self.status('LISTENING', str(exc))
                        del self.buffer[:(header + decoder.vis_samples) * 2]
                        self.scan_after = RATE * 2
                        continue
                    start = max(0, header - decoder.header_leader_samples)
                    del self.buffer[:start * 2]
                    self.mode = mode
                    import uuid
                    self.frame_id = uuid.uuid4().hex
                    # Include a small tail for sync alignment and Scottie's initial sync.
                    self.expected = (decoder.header_leader_samples+decoder.vis_samples+round((mode.LINE_TIME*mode.LINE_COUNT+.3)*RATE))*2
                    self.preview_after = RATE * 2 * 10
                    self.status('RECEIVING', mode.NAME)
                else:
                    # Retain 1.3 seconds: a header crossing the next chunk remains whole.
                    keep = round(1.3 * RATE) * 2
                    if len(self.buffer) > keep:
                        del self.buffer[:-keep]
                    self.scan_after = len(self.buffer) + RATE * 2
                    return
            full = len(self.buffer) >= self.expected
            self.progress({
                'id': self.frame_id, 'mode': self.mode.NAME,
                'kind': 'processing' if full else 'receiving',
                'progress_pct': min(100, int(100 * len(self.buffer) / self.expected)),
                'elapsed_seconds': min(len(self.buffer), self.expected) / (RATE * 2),
                'duration_seconds': self.expected / (RATE * 2),
            })
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
