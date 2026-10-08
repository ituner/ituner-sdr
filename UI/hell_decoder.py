"""Streaming Hell raster receiver. GPL-3.0-or-later.

Based on fldigi's feld.cxx receive design and mode timings:
Copyright (C) 2006–2014 Dave Freese W1HKJ; contributions Joe Veldhuis N8FQ;
gmfsk Copyright 2001–2003 Tomi Manninen OH2BNS, 2004 Lawrence Glaister VE7IT.
Python/NumPy adaptation: iTuner contributors, 2026.
See licenses/fldigi-GPL-3.txt and docs/HELL.md. No warranty.

Complex downconversion, streaming FIR, envelope/FM discrimination and a
free-running 28-pixel column clock. Adjacent columns are duplicated vertically
so asynchronous lines remain readable (there is no frame/header or OCR).
"""
import numpy as np
from hell_modes import MODES

RATE = 12000
HEIGHT = 28


class HellDecoder:
    def __init__(self, mode='HELL', tone_hz=1500, reverse=False):
        self.spec = MODES[mode]
        self.tone, self.reverse = tone_hz, reverse
        self.pixel_rate = HEIGHT*self.spec['columns']
        cutoff = self.spec['bandwidth']/2
        taps = min(2049, max(33, int(4*RATE/cutoff) | 1))
        x = np.arange(taps)-(taps-1)/2
        self.fir = 2*cutoff/RATE*np.sinc(2*cutoff/RATE*x)*np.hamming(taps)
        self.fir /= self.fir.sum()
        self.reset()

    def reset(self):
        self.tail = np.zeros(len(self.fir)-1, dtype=complex)
        self.samples = self.pixels = 0
        self.prev = 0j
        self.peak = 1e-8
        self.pending = np.array([], dtype=np.uint8)
        self.previous_column = np.full(HEIGHT, 255, dtype=np.uint8)
        self.level = -120.0

    def feed(self, pcm):
        samples = np.frombuffer(pcm, '<i2').astype(float)/32768
        if not len(samples):
            return np.empty((2*HEIGHT, 0), dtype=np.uint8)
        t = np.arange(len(samples)) + self.samples
        mixed = samples * np.exp(-2j*np.pi*self.tone/RATE*t)
        joined = np.concatenate((self.tail, mixed))
        z = np.convolve(joined, self.fir, mode='valid')
        self.tail = joined[-len(self.tail):]
        amplitude = np.abs(z)
        self.level = float(20*np.log10(max(1e-8, np.sqrt(np.mean(amplitude**2))*2)))
        end = self.samples+len(samples)
        # Absolute sample clock makes packet boundaries irrelevant.
        last_pixel = int(end*self.pixel_rate/RATE)
        indices = np.ceil(np.arange(self.pixels+1, last_pixel+1)*RATE/self.pixel_rate).astype(int)-1-self.samples
        indices = np.clip(indices, 0, len(z)-1)
        if self.spec['shift']:
            previous = np.concatenate(([self.prev], z[:-1]))
            hz = np.angle(z*np.conj(previous))*RATE/(2*np.pi)
            # Fldigi maps lower tone to ink; keep normal and reverse selectable.
            values = np.clip(.5+hz[indices]/self.spec['shift'], 0, 1)
            if self.reverse:
                values = 1-values
        else:
            values = []
            for ix in indices:
                value = amplitude[ix]
                self.peak = max(value, self.peak*(1-.02/HEIGHT), 1e-8)
                values.append(1-min(1, value/self.peak))
            values = np.asarray(values)
            if self.reverse:
                values = 1-values
        self.prev = z[-1]
        self.samples, self.pixels = end, last_pixel
        self.pending = np.concatenate((self.pending, (values*255).astype(np.uint8)))
        count = len(self.pending)//HEIGHT
        result = np.empty((2*HEIGHT, count), dtype=np.uint8)
        for i in range(count):
            column = self.pending[i*HEIGHT:(i+1)*HEIGHT][::-1]
            result[:, i] = np.concatenate((column, self.previous_column))
            self.previous_column = column
        self.pending = self.pending[count*HEIGHT:]
        return result
