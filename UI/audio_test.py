"""Timed sine-wave measurements through the existing SDR output backend."""
import copy
import math
import threading
import time

import numpy as np
from decoder_style import DecoderStyle

FREQUENCIES = (100, 250, 500, 1000, 2000, 5000)
LEVELS = (-40, -30, -20, -12, -9, -6, -3, 0)
DURATIONS = (5, 10, 30, 60)
RATE = 48000
BLOCK = 960
FADE = 960


def sine_pcm(frequency, level_dbfs, start, count, total):
    """Identical L/R, signed 16-bit PCM; level describes peak digital amplitude."""
    if not (0 < frequency < RATE / 2 and -80 <= level_dbfs <= 0):
        raise ValueError('Invalid sine-wave frequency or level')
    index = np.arange(start, start + count, dtype=np.float64)
    envelope = np.minimum(1.0, np.minimum(index / FADE, (total - 1 - index) / FADE))
    wave = np.sin(2 * math.pi * frequency * index / RATE)
    samples = np.rint(32767 * 10 ** (level_dbfs / 20) * wave * np.maximum(0, envelope))
    return np.repeat(samples.astype('<i2'), 2).tobytes()


class SineTest:
    def __init__(self, ui, args, state, available=lambda: True):
        self.ui, self.args, self.state, self.available = ui, args, state, available
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.status = 'Ready'
        self.remaining = 0.0

    def snapshot(self):
        with self.lock:
            return dict(running=bool(self.thread and self.thread.is_alive()),
                        status=self.status, remaining=self.remaining)

    def start(self, frequency, level, seconds):
        if self.snapshot()['running']:
            return
        if frequency not in FREQUENCIES or level not in LEVELS or seconds not in DURATIONS:
            raise ValueError('Choose a listed frequency, level and duration')
        if not self.args.audio:
            raise ValueError('Audio output is disabled')
        if not self.available():
            raise ValueError('Stop dual listening before starting a tone')
        controls, _ = self.state.audio_controls_snapshot()
        if controls.get('mute'):
            raise ValueError('Unmute Audio before starting a tone')
        with self.state.lock:
            if self.state.external_audio:
                raise ValueError('Another tool owns audio; stop its playback first')
            self.state.external_audio = True
            self.state.external_audio_sink_released = False
            self.state.external_audio_generation = getattr(self.state, 'external_audio_generation', 0) + 1
            token = self.state.external_audio_generation
        self.stop_event = threading.Event()
        with self.lock:
            self.status, self.remaining = 'Waiting for radio audio to release', float(seconds)
            self.thread = threading.Thread(target=self._run, args=(frequency, level, seconds, token),
                                           name='audio-sine-test', daemon=True)
            self.thread.start()

    def stop(self):
        # UI Stop/Back must never wait for an audio device or subprocess.
        self.stop_event.set()

    def _run(self, frequency, level, seconds, token):
        player = None
        result = 'Stopped; radio audio restored'
        try:
            deadline = time.monotonic() + 4
            while not self.state.external_audio_sink_released_snapshot():
                if self.stop_event.wait(.02):
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError('Audio output is busy; try again')
            if self.stop_event.is_set():
                return
            args = copy.copy(self.args)
            args.audio_rate, args.output_volume = RATE, None
            player = self.ui.BufferedAudioPlayer(args, 2)
            if player.poll() is not None:
                raise RuntimeError('Could not open audio output')
            total = round(seconds * RATE)
            started = time.monotonic()
            with self.lock:
                self.status = 'Playing sine; radio DSP bypassed'
            for start in range(0, total, BLOCK):
                if self.stop_event.is_set():
                    # Continue the phase into a short ramp, then flush the
                    # local reserve. This runs on the worker, never the UI.
                    player.submit(sine_pcm(frequency, level, start, FADE, start + FADE))
                    player.submit(bytes(RATE // 5 * 4), silence=True)
                    time.sleep(.25)
                    break
                with self.state.lock:
                    if not self.state.external_audio or self.state.external_audio_generation != token:
                        break
                controls, _ = self.state.audio_controls_snapshot()
                if controls.get('mute'):
                    result = 'Muted; test stopped'
                    break
                if player.poll() is not None:
                    raise RuntimeError('Audio output disconnected')
                count = min(BLOCK, total - start)
                player.submit(sine_pcm(frequency, level, start, count, total))
                with self.lock:
                    self.remaining = max(0, seconds - (start + count) / RATE)
                self.stop_event.wait(max(0, started + (start + count) / RATE - time.monotonic()))
            else:
                # Drain the short local playback reserve, including the fade-out.
                self.stop_event.wait(.35)
                result = 'Finished; radio audio restored'
        except Exception as exc:
            result = str(exc)[:120]
        finally:
            try:
                if player:
                    self.ui.stop_audio_player(player)
            except Exception as exc:
                result = 'Audio stop error: ' + str(exc)[:90]
            finally:
                with self.state.lock:
                    if self.state.external_audio_generation == token:
                        self.state.external_audio = False
                        self.state.external_audio_sink_released = True
                with self.lock:
                    self.status, self.remaining = result, 0.0


class AudioTestWorkspace(DecoderStyle):
    def __init__(self, ui, args, state, available=lambda: True):
        self.ui, self.args = ui, args
        self.test = SineTest(ui, args, state, available)
        self.open = False
        self.frequency, self.level, self.duration = 1000, -30, 10
        self.actions = []
        self.message = ''

    def close(self):
        self.test.stop()
        self.open = False

    def tap(self, x, y):
        for box, (kind, value) in self.actions:
            if not self.ui.contains(box, x, y):
                continue
            if kind == 'back':
                self.close()
            elif kind == 'stop':
                self.test.stop()
            elif kind == 'start':
                try:
                    self.test.start(self.frequency, self.level, self.duration)
                    self.message = ''
                except ValueError as exc:
                    self.message = str(exc)
            elif not self.test.snapshot()['running']:
                setattr(self, kind, value)
                self.message = ''
            return

    def draw(self, cache, output_volume=None):
        ui = self.ui
        self.actions = []
        snapshot = self.test.snapshot()
        running = snapshot['running']
        ui.draw_logical_rect(0, 0, 1280, 800, self.BG)

        def text(x, y, label, size=20, color=None):
            ui.draw_text(cache, x, y, label, color or self.TEXT, size,
                         size >= 22, False, 'lm', family='Liberation Sans')

        text(26, 35, 'AUDIO TEST - SINE WAVE', 28)
        text(26, 72, 'Both channels carry the same tone. Radio audio pauses during the test.', 20, self.MUTED)
        text(26, 115, 'FREQUENCY', 22)
        for i, hz in enumerate(FREQUENCIES):
            x = 26 + i * 207
            self.decoder_button(cache, (x, 136, x + 195, 204), f'{hz} Hz', ('frequency', hz),
                                active=self.frequency == hz, enabled=not running, font_size=22)
        text(26, 241, 'DIGITAL SIGNAL LEVEL (dBFS)', 22)
        for i, db in enumerate(LEVELS):
            x, y = 26 + (i % 4) * 310, 263 + (i // 4) * 86
            self.decoder_button(cache, (x, y, x + 296, y + 74), f'{db} dBFS', ('level', db),
                                subtitle=f'{100 * 10 ** (db / 20):.1f}% peak amplitude',
                                active=self.level == db, enabled=not running, font_size=22)
        text(26, 456, 'AUTO STOP', 22)
        for i, seconds in enumerate(DURATIONS):
            x = 26 + i * 158
            self.decoder_button(cache, (x, 480, x + 145, 544), f'{seconds} sec', ('duration', seconds),
                                active=self.duration == seconds, enabled=not running, font_size=22)
        self.decoder_button(cache, (690, 480, 1252, 558), 'STOP TONE' if running else 'PLAY TONE',
                            ('stop' if running else 'start', None), active=running, font_size=27)
        volume = 'unknown' if output_volume is None else f'{round(output_volume * 100)}%'
        text(26, 588, f'Output volume: {volume} (unchanged)  |  48 kHz / 16-bit  |  EQ bypassed', 20)
        text(26, 623, 'Digital level is not speaker watts or volts. Codec / system volume still applies.', 19, self.MUTED)
        text(26, 655, 'Start low. Use a dummy load for high-level tests; stop before clipping.', 19, self.GOLD)
        text(26, 685, 'Change settings while stopped. Back stops the tone. Headphone detection stays active.', 18, self.MUTED)
        self.draw_back(cache)
        status = self.message or snapshot['status']
        if running:
            status += f" - {snapshot['remaining']:.1f} s remaining"
        self.draw_status(cache, status, f'{self.frequency} Hz / {self.level} dBFS', full_width=True)
