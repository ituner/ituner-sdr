#!/usr/bin/env python3
"""One SoapySDR RX stream: PCM for Dire Wolf, IQ for telemetry, RTL-TCP for SatDump.

Runs out of process so decoder shutdown always releases USB. All radio commands
are receive-only. No shell command or user-provided executable is accepted.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', required=True)
    parser.add_argument('--frequency', type=float, required=True)
    parser.add_argument('--format', choices=('pcm', 'iq', 'iq16', 'tcp'), required=True)
    parser.add_argument('--status', required=True)
    parser.add_argument('--tuning')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--gain', type=float, default=38.6)
    parser.add_argument('--ppm', type=float, default=0)
    args = parser.parse_args()
    import numpy as np
    from scipy import signal as dsp
    import SoapySDR
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    sdr = SoapySDR.Device(args.device)
    rate = 1024000 if args.format == 'tcp' else 240000
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, rate)
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, args.frequency)
    sdr.setGainMode(SoapySDR.SOAPY_SDR_RX, 0, False)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, args.gain)
    if args.ppm: sdr.setFrequencyCorrection(SoapySDR.SOAPY_SDR_RX, 0, args.ppm)
    stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [0])
    connection = server = udp = None
    try:
        if args.format == 'tcp':
            server = socket.socket()
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', args.port)); server.listen(1); server.settimeout(.5)
            while not stopped.is_set():
                try: connection, _ = server.accept(); break
                except socket.timeout: continue
            if stopped.is_set(): return
            connection.settimeout(2)
            connection.sendall(struct.pack('!4sII', b'RTL0', 5, 0))
            def commands():
                pending = b''
                while not stopped.is_set():
                    try:
                        data = connection.recv(1024)
                        if not data: stopped.set(); break
                        pending += data
                        while len(pending) >= 5:
                            command, value = struct.unpack('!BI', pending[:5]); pending = pending[5:]
                            # Rate is fixed by the pipeline; accept its matching request.
                            if command == 1 and 30000000 <= value <= 1700000000:
                                sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, value)
                    except socket.timeout: continue
                    except OSError: stopped.set()
            threading.Thread(target=commands, daemon=True).start()
        sdr.activateStream(stream)
        taps = dsp.firwin(129, 8500 if args.format == 'pcm' else 20500, fs=rate)
        zi = np.zeros(len(taps)-1, dtype=np.complex64)
        audio_taps = dsp.firwin(65, 3500, fs=48000)
        audio_zi = np.zeros(len(audio_taps)-1)
        phase, previous, count, last = 0, complex(1), 0, 0
        buffer = np.empty(16384, np.complex64)
        path = Path(args.status)
        while not stopped.is_set():
            result = sdr.readStream(stream, [buffer], len(buffer), timeoutUs=500000)
            if result.ret <= 0:
                if result.ret == SoapySDR.SOAPY_SDR_TIMEOUT: continue
                if result.ret == SoapySDR.SOAPY_SDR_OVERFLOW: continue
                raise RuntimeError('SoapySDR read failed: '+str(result.ret))
            samples = buffer[:result.ret]; count += len(samples)
            now = time.time()
            if now-last >= 1:
                if args.tuning:
                    try:
                        tuning = json.loads(Path(args.tuning).read_text())
                        if now-tuning['time']<5 and 30000000<=tuning['frequency']<=1700000000:
                            sdr.setFrequency(SoapySDR.SOAPY_SDR_RX,0,tuning['frequency'])
                    except (OSError,ValueError,KeyError): pass
                power = float(10*np.log10(max(float(np.mean(np.abs(samples)**2)), 1e-12)))
                fft = 20*np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(samples[:1024]*np.hanning(1024))))/512,1e-6))
                spectrum = np.max(fft.reshape(64,16),axis=1).round(1).tolist()
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(dict(time=now, samples=count, rate=rate, power_dbfs=round(power,1), spectrum=spectrum)))
                temporary.replace(path); last = now
            if args.format == 'tcp':
                raw = np.clip(samples.view(np.float32)*127+127.5,0,255).astype(np.uint8)
                connection.sendall(raw.tobytes()); continue
            filtered, zi = dsp.lfilter(taps, [1.0], samples, zi=zi)
            iq = filtered[(-phase)%5::5]; phase = (phase+len(samples))%5
            if not len(iq): continue
            if args.format == 'pcm':
                demod = np.angle(iq*np.conj(np.concatenate(([previous],iq[:-1])))); previous = iq[-1]
                audio, audio_zi = dsp.lfilter(audio_taps, [1.0], demod, zi=audio_zi)
                sys.stdout.buffer.write(np.clip(audio*12000,-32767,32767).astype('<i2').tobytes())
                sys.stdout.buffer.flush()
            elif args.format == 'iq16':
                sys.stdout.buffer.write(np.clip(iq.astype('<c8').view('<f4')*26000,-32767,32767).astype('<i2').tobytes())
                sys.stdout.buffer.flush()
            else:
                sys.stdout.buffer.write(iq.astype('<c8').tobytes())
                sys.stdout.buffer.flush()
    finally:
        sdr.deactivateStream(stream)
        sdr.closeStream(stream)
        for item in (connection, server, udp):
            if item: item.close()


if __name__ == '__main__':
    try: main()
    except BrokenPipeError: pass
    except Exception as exc:
        print('Receiver error: '+str(exc), file=sys.stderr)
        sys.exit(1)
