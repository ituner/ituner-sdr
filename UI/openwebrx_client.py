"""Reusable OpenWebRX/OpenWebRX+ live receiver transport.

This module owns only the browser-facing OpenWebRX WebSocket protocol.  It
deliberately has no display, audio-device, or file-output dependency so the
recorder and the OpenGL radio can consume the same decoded audio and FFT
events.  OpenWebRX has no stable versioned receiver API; config is therefore
merged exactly as the browser receives it and every client can report the
negotiated source properties to its own UI.
"""

from __future__ import annotations

import array
import json
import math
import struct
import sys
from dataclasses import dataclass
from typing import Any, Optional

# The recorder introduced the tested, dependency-free RFC 6455 and ADPCM
# primitives.  Keep one decoder implementation while this transport is being
# promoted into the live UI; a later cleanup can move these primitives here
# without changing either consumer's public surface.
from openwebrx_recorder import (
    DEFAULT_FILTERS,
    FFT_ADPCM_PAD_SAMPLES,
    ImaAdpcmDecoder,
    RecorderConfigurationError,
    SyncedImaAdpcmDecoder,
    WebSocket,
)
from receiver_catalog import ReceiverCapabilities


class OpenWebRxError(RuntimeError):
    """A receiver stream could not be configured or decoded."""


def is_openwebrx_endpoint(endpoint: str) -> bool:
    """Whether an iTuner source string explicitly selects OpenWebRX.

    Plain ``http(s)`` URLs remain KiwiSDR-compatible because the existing
    directory stores those.  ``owrx://`` and ``owrxs://`` make the source
    protocol explicit without adding an ambiguous probe to every tune.
    """
    return str(endpoint).lower().startswith(("owrx://", "owrxs://"))


def endpoint_url(endpoint: str) -> str:
    value = str(endpoint)
    if value.lower().startswith("owrxs://"):
        return "https://" + value[8:]
    if value.lower().startswith("owrx://"):
        return "http://" + value[7:]
    return value


def mode_for_openwebrx(mode: str) -> str:
    """Translate the shared Home labels to honest OpenWebRX demodulators."""
    requested = str(mode).lower()
    aliases = {
        "nbfm": "nfm",
        "sam": "am",
        "drm": "am",
        "iq": "am",
    }
    requested = aliases.get(requested, requested)
    if requested not in DEFAULT_FILTERS:
        return "am"
    return requested


def _resample_s16le(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Small bounded mono resampler for a single OpenWebRX frame.

    Narrow OpenWebRX audio is normally already 12 kHz.  WFM uses the server's
    HD lane (typically 48 kHz), so retain a usable Home audio path rather than
    accidentally clocking 48 kHz PCM into a 12 kHz sink.  This intentionally
    simple interpolation is a compatibility bridge, not a replacement for a
    full DSP resampler.
    """
    if source_rate <= 0 or target_rate <= 0 or source_rate == target_rate or not pcm:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) - (len(pcm) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < 2:
        return b""
    target_count = max(1, int(round(len(samples) * target_rate / source_rate)))
    output = array.array("h")
    scale = (len(samples) - 1) / max(1, target_count - 1)
    for index in range(target_count):
        position = index * scale
        left = int(position)
        right = min(len(samples) - 1, left + 1)
        fraction = position - left
        output.append(int(samples[left] * (1.0 - fraction) + samples[right] * fraction))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


@dataclass(frozen=True)
class OpenWebRxEvent:
    kind: str
    audio: bytes = b""
    audio_rate: int = 0
    waterfall: tuple[float, ...] = ()
    config: Optional[dict[str, Any]] = None


class OpenWebRxSession:
    """One live OpenWebRX receiver WebSocket with mutable DSP controls."""

    def __init__(
        self,
        endpoint: str,
        *,
        output_rate: int = 12_000,
        hd_output_rate: int = 48_000,
        connect_timeout: float = 10.0,
        user_agent: str = "iTuner-SDR/0.1",
    ):
        self.endpoint = endpoint_url(endpoint)
        self.output_rate = int(output_rate)
        self.hd_output_rate = int(hd_output_rate)
        self.connect_timeout = float(connect_timeout)
        self.user_agent = user_agent
        self.ws: Optional[WebSocket] = None
        self.config: dict[str, Any] = {}
        self.audio_decoder = SyncedImaAdpcmDecoder()
        self.started = False
        self.frequency_hz: Optional[float] = None
        self.mode = "am"
        self.low_cut: Optional[int] = None
        self.high_cut: Optional[int] = None
        self.squelch_level = -150
        self._last_control: Optional[tuple[Any, ...]] = None

    @property
    def center_frequency_hz(self) -> Optional[float]:
        try:
            return float(self.config["center_freq"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def sample_rate_hz(self) -> Optional[float]:
        try:
            return float(self.config["samp_rate"])
        except (KeyError, TypeError, ValueError):
            return None

    def advertised_modes(self) -> tuple:
        """Map the server's advertised demodulators onto implemented modes."""
        advertised = self.config.get("modes")
        if isinstance(advertised, (list, tuple)):
            mapped = tuple(
                str(mode).lower() for mode in advertised
                if str(mode).lower() in DEFAULT_FILTERS
            )
            if mapped:
                return mapped
        return tuple(sorted(DEFAULT_FILTERS))

    def negotiated_capabilities(self) -> ReceiverCapabilities:
        """Describe what this OpenWebRX server actually negotiated.

        The profile window (``center_freq`` +/- ``samp_rate``/2) bounds tuning
        and the waterfall pan; passband stays per-session. Until the config
        arrives the range is empty rather than guessed.
        """
        center = self.center_frequency_hz
        sample_rate = self.sample_rate_hz or 0.0
        if center is None or sample_rate <= 0:
            ranges = ()
        else:
            ranges = (((center - sample_rate / 2.0) / 1000.0,
                       (center + sample_rate / 2.0) / 1000.0),)
        return ReceiverCapabilities.openwebrx(
            modes=self.advertised_modes(),
            frequency_ranges_khz=ranges,
            source_span_khz=sample_rate / 1000.0,
        )

    def connect(self) -> None:
        self.close()
        self.ws = WebSocket.connect(self.endpoint, timeout=self.connect_timeout)
        self.ws.send_text(f"SERVER DE CLIENT client={self.user_agent} type=receiver")
        self.ws.send_text(json.dumps({
            "type": "connectionproperties",
            "params": {"output_rate": self.output_rate, "hd_output_rate": self.hd_output_rate},
        }, separators=(",", ":")))
        self.audio_decoder.reset()
        self.started = False
        self._last_control = None

    def close(self) -> None:
        if self.ws is not None:
            self.ws.close()
        self.ws = None
        self.started = False

    def set_controls(
        self,
        frequency_hz: Optional[float] = None,
        mode: Optional[str] = None,
        low_cut: Optional[int] = None,
        high_cut: Optional[int] = None,
        squelch_level: Optional[int] = None,
    ) -> None:
        if frequency_hz is not None:
            self.frequency_hz = float(frequency_hz)
        if mode is not None:
            self.mode = mode_for_openwebrx(mode)
        if low_cut is not None:
            self.low_cut = int(low_cut)
        if high_cut is not None:
            self.high_cut = int(high_cut)
        if squelch_level is not None:
            self.squelch_level = int(squelch_level)
        if self.started:
            self._send_dsp_control()

    def _effective_frequency_hz(self) -> float:
        center = self.center_frequency_hz
        if center is None:
            raise OpenWebRxError("receiver did not provide center_freq")
        if self.frequency_hz is not None:
            return self.frequency_hz
        sample_rate = self.sample_rate_hz or 0.0
        start_offset = float(self.config.get("start_offset_freq", 0.0) or 0.0)
        if sample_rate and abs(start_offset) > sample_rate / 2:
            start_offset = 0.0
        return center + start_offset

    def _send_dsp_control(self) -> None:
        if self.ws is None:
            raise OpenWebRxError("receiver WebSocket is not connected")
        frequency_hz = self._effective_frequency_hz()
        center = self.center_frequency_hz
        sample_rate = self.sample_rate_hz or 0.0
        offset = frequency_hz - center
        if sample_rate and abs(offset) > sample_rate / 2:
            raise RecorderConfigurationError(
                f"{frequency_hz:.0f} Hz is outside this profile's {sample_rate:.0f} Hz window"
            )
        default_low, default_high = DEFAULT_FILTERS[self.mode]
        low = default_low if self.low_cut is None else self.low_cut
        high = default_high if self.high_cut is None else self.high_cut
        control = (round(offset), self.mode, low, high, self.squelch_level)
        if control == self._last_control:
            return
        self.ws.send_text(json.dumps({
            "type": "dspcontrol",
            "params": {
                "mod": self.mode,
                "offset_freq": control[0],
                "low_cut": low,
                "high_cut": high,
                "squelch_level": self.squelch_level,
            },
        }, separators=(",", ":")))
        self._last_control = control

    def _start(self) -> None:
        if self.started or self.center_frequency_hz is None:
            return
        self._send_dsp_control()
        assert self.ws is not None
        self.ws.send_text(json.dumps({"type": "dspcontrol", "action": "start"}, separators=(",", ":")))
        self.started = True

    def _decode_audio(self, data: bytes, rate: int) -> OpenWebRxEvent:
        compression = str(self.config.get("audio_compression", "none"))
        if compression == "adpcm":
            samples = self.audio_decoder.decode(data)
            raw = array.array("h", samples)
            if sys.byteorder != "little":
                raw.byteswap()
            pcm = raw.tobytes()
        elif compression == "none":
            if len(data) % 2:
                raise OpenWebRxError("odd uncompressed audio packet")
            pcm = data
        else:
            raise OpenWebRxError(f"unsupported OpenWebRX audio compression: {compression}")
        return OpenWebRxEvent("audio", _resample_s16le(pcm, rate, self.output_rate), self.output_rate)

    def _decode_waterfall(self, data: bytes) -> OpenWebRxEvent:
        compression = str(self.config.get("fft_compression", "none"))
        if compression == "none":
            if len(data) % 4:
                raise OpenWebRxError("malformed uncompressed FFT packet")
            samples = struct.unpack("<{}f".format(len(data) // 4), data)
        elif compression == "adpcm":
            decoder = ImaAdpcmDecoder()
            decoded = decoder.decode(data)
            samples = tuple(value / 100.0 for value in decoded[FFT_ADPCM_PAD_SAMPLES:])
        else:
            raise OpenWebRxError(f"unsupported OpenWebRX FFT compression: {compression}")
        values = tuple(value for value in samples if math.isfinite(value))
        return OpenWebRxEvent("waterfall", waterfall=values)

    def recv_event(self) -> Optional[OpenWebRxEvent]:
        if self.ws is None:
            raise OpenWebRxError("receiver WebSocket is not connected")
        opcode, payload = self.ws.recv()
        if opcode == 0x1:
            text = payload.decode("utf-8", "replace")
            if text.startswith("CLIENT DE SERVER"):
                return None
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                return None
            if message.get("type") == "config" and isinstance(message.get("value"), dict):
                self.config.update(message["value"])
                self._start()
                return OpenWebRxEvent("config", config=dict(self.config))
            if message.get("type") in ("sdr_error", "demodulator_error", "backoff"):
                raise OpenWebRxError(str(message.get("value") or message.get("reason") or message["type"]))
            return None
        if opcode != 0x2 or not payload:
            return None
        frame_type, data = payload[0], payload[1:]
        if frame_type == 1:
            return self._decode_waterfall(data)
        if frame_type == 2:
            return self._decode_audio(data, self.output_rate)
        if frame_type == 4:
            return self._decode_audio(data, self.hd_output_rate)
        return None


def self_test() -> None:
    assert is_openwebrx_endpoint("owrx://receiver.local:8073")
    assert endpoint_url("owrxs://receiver.local/rx/") == "https://receiver.local/rx/"
    assert mode_for_openwebrx("NBFM") == "nfm"
    assert mode_for_openwebrx("SAM") == "am"
    source = struct.pack("<hhhh", -1000, 0, 1000, 2000)
    assert len(_resample_s16le(source, 48_000, 12_000)) == 2 * 1


if __name__ == "__main__":
    self_test()
    print("openwebrx_client self-test passed")
