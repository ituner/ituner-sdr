#!/usr/bin/env python3
"""Record a receiver stream from OpenWebRX or OpenWebRX+.

This is intentionally a small, dependency-free companion to Kiwi's
``kiwirecorder.py``. It speaks the OpenWebRX browser WebSocket protocol and
writes decoded narrow-band audio as a WAV file plus waterfall FFT rows as
little-endian float32 data with a JSON sidecar.

The protocol is browser-facing rather than a versioned public API, so this
tool reports its negotiated configuration in the sidecar. That makes captures
auditable and gives callers enough information to replay the waterfall.
"""

from __future__ import annotations

import argparse
import array
import base64
import hashlib
import json
import math
import os
import socket
import ssl
import struct
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


WEBSOCKET_ACCEPT_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
FFT_ADPCM_PAD_SAMPLES = 10


class RecorderConfigurationError(RuntimeError):
    """A server accepted the socket but cannot satisfy this capture request."""


def read_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError("socket closed")
        data.extend(chunk)
    return bytes(data)


def read_http_header(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(1)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 16_384:
            raise RuntimeError("HTTP response header is too large")
    return bytes(data)


def websocket_path(endpoint: str) -> tuple[str, str, int, str, bool]:
    if "://" not in endpoint:
        endpoint = "http://" + endpoint
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https", "ws", "wss") or not parsed.hostname:
        raise ValueError(f"bad OpenWebRX endpoint: {endpoint}")

    secure = parsed.scheme in ("https", "wss")
    port = parsed.port or (443 if secure else 80)
    path = parsed.path or "/"
    if path.rstrip("/").endswith("/ws"):
        ws_path = path if path.endswith("/") else path + "/"
    elif path.endswith("/"):
        ws_path = path + "ws/"
    else:
        ws_path = path.rsplit("/", 1)[0] + "/ws/"
    return parsed.scheme, parsed.hostname, port, ws_path, secure


class WebSocket:
    """Minimal RFC 6455 client suitable for the OpenWebRX receiver stream."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._fragment_opcode: Optional[int] = None
        self._fragments = bytearray()

    @classmethod
    def connect(cls, endpoint: str, timeout: float = 10.0) -> "WebSocket":
        scheme, host, port, path, secure = websocket_path(endpoint)
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            raw.settimeout(timeout)
            sock: socket.socket = raw
            if secure:
                sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)

            key = base64.b64encode(os.urandom(16)).decode("ascii")
            origin_scheme = "https" if secure else "http"
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Origin: {origin_scheme}://{host}:{port}\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "User-Agent: iTuner-OpenWebRX-Recorder/0.1\r\n"
                "\r\n"
            ).encode("ascii")
            sock.sendall(request)
            response = read_http_header(sock)
            status = response.split(b"\r\n", 1)[0]
            expected = base64.b64encode(
                hashlib.sha1((key + WEBSOCKET_ACCEPT_GUID).encode("ascii")).digest()
            )
            if b" 101 " not in status or expected not in response:
                detail = status.decode("latin1", "replace")
                raise RuntimeError(f"OpenWebRX WebSocket upgrade failed: {detail}")
            sock.settimeout(1.0)
            return cls(sock)
        except Exception:
            raw.close()
            raise

    def close(self) -> None:
        try:
            self.send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def send_text(self, message: str) -> None:
        self.send_frame(0x1, message.encode("utf-8"))

    def send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65_536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv(self) -> tuple[int, bytes]:
        while True:
            first, second = read_exact(self.sock, 2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", read_exact(self.sock, 2))[0]
            elif length == 127:
                length = struct.unpack("!Q", read_exact(self.sock, 8))[0]
            mask = read_exact(self.sock, 4) if masked else b""
            payload = read_exact(self.sock, length) if length else b""
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

            if opcode == 0x8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                reason = payload[2:].decode("utf-8", "replace") if len(payload) > 2 else ""
                suffix = f" code={code}" if code is not None else ""
                if reason:
                    suffix += f" reason={reason[:120]}"
                raise EOFError("websocket closed" + suffix)
            if opcode == 0x9:
                self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x0:
                if self._fragment_opcode is None:
                    raise RuntimeError("unexpected WebSocket continuation frame")
                self._fragments.extend(payload)
                if not final:
                    continue
                complete_opcode = self._fragment_opcode
                complete_payload = bytes(self._fragments)
                self._fragment_opcode = None
                self._fragments.clear()
                return complete_opcode, complete_payload
            if not final:
                self._fragment_opcode = opcode
                self._fragments = bytearray(payload)
                continue
            return opcode, payload


class ImaAdpcmDecoder:
    """The IMA ADPCM variant used by OpenWebRX browser audio and FFT frames."""

    INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)
    STEP_TABLE = (
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
        50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
        253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
        1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
        3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
        12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
    )

    def reset(self) -> None:
        self.step_index = 0
        self.predictor = 0
        self.step = 0

    def __init__(self) -> None:
        self.reset()

    def decode_nibble(self, nibble: int) -> int:
        self.step_index = max(0, min(88, self.step_index + self.INDEX_TABLE[nibble]))
        difference = self.step >> 3
        if nibble & 1:
            difference += self.step >> 2
        if nibble & 2:
            difference += self.step >> 1
        if nibble & 4:
            difference += self.step
        if nibble & 8:
            difference = -difference
        self.predictor = max(-32768, min(32767, self.predictor + difference))
        self.step = self.STEP_TABLE[self.step_index]
        return self.predictor

    def decode(self, data: bytes) -> list[int]:
        output: list[int] = []
        for value in data:
            output.append(self.decode_nibble(value & 0x0F))
            output.append(self.decode_nibble((value >> 4) & 0x0F))
        return output


class SyncedImaAdpcmDecoder(ImaAdpcmDecoder):
    """OpenWebRX audio ADPCM with its periodic SYNC state marker."""

    def __init__(self) -> None:
        super().__init__()
        self.phase = 0
        self.match_count = 0
        self.sync_buffer = bytearray()
        self.sync_counter = 0

    def reset(self) -> None:
        super().reset()
        self.phase = 0
        self.match_count = 0
        self.sync_buffer = bytearray()
        self.sync_counter = 0

    def decode(self, data: bytes) -> list[int]:
        output: list[int] = []
        for value in data:
            if self.phase == 0:
                expected = b"SYNC"[self.match_count]
                self.match_count = self.match_count + 1 if value == expected else 0
                if self.match_count == 4:
                    self.sync_buffer.clear()
                    self.phase = 1
                continue
            if self.phase == 1:
                self.sync_buffer.append(value)
                if len(self.sync_buffer) == 4:
                    self.step_index, self.predictor = struct.unpack("<hh", self.sync_buffer)
                    self.step_index = max(0, min(88, self.step_index))
                    self.step = self.STEP_TABLE[self.step_index]
                    self.sync_counter = 1000
                    self.phase = 2
                continue
            output.append(self.decode_nibble(value & 0x0F))
            output.append(self.decode_nibble(value >> 4))
            if self.sync_counter == 0:
                self.phase = 0
                self.match_count = 0
            else:
                self.sync_counter -= 1
        return output


DEFAULT_FILTERS = {
    "am": (-5000, 5000),
    "cw": (400, 1000),
    "lsb": (-3000, -300),
    "nfm": (-6000, 6000),
    "usb": (300, 3000),
    "wfm": (-75000, 75000),
}


@dataclass
class RecorderStats:
    audio_samples: int = 0
    audio_packets: int = 0
    waterfall_rows: int = 0
    reconnects: int = 0
    control_messages: int = 0
    hd_audio_packets: int = 0
    errors: list[str] = field(default_factory=list)


class OpenWebRxRecorder:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.config: dict[str, Any] = {}
        self.stats = RecorderStats()
        self.dial_frequency_hz: Optional[float] = args.frequency_hz
        self.audio_decoder = SyncedImaAdpcmDecoder()
        self.wave_writer: Optional[wave.Wave_write] = None
        self.audio_rate: Optional[int] = None
        self.waterfall_file = None
        self.started = False
        self.announced_config = False
        self._open_outputs()

    def _open_outputs(self) -> None:
        if self.args.waterfall:
            output = Path(self.args.waterfall)
            output.parent.mkdir(parents=True, exist_ok=True)
            self.waterfall_file = output.open("wb")

    def close(self) -> None:
        if self.args.audio and self.wave_writer is None:
            # Keep the CLI contract predictable even when a server rejects a
            # demodulator before it emits its first audio packet.
            self._open_audio_writer(self.args.output_rate)
        if self.wave_writer is not None:
            self.wave_writer.close()
            self.wave_writer = None
        if self.waterfall_file is not None:
            self.waterfall_file.close()
            self.waterfall_file = None
        if self.args.waterfall:
            self._write_waterfall_preview()
            metadata_path = Path(self.args.waterfall_metadata) if self.args.waterfall_metadata else Path(
                str(self.args.waterfall) + ".json"
            )
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(
                json.dumps(
                    {
                        "format": "ituner-openwebrx-waterfall-f32le-v1",
                        "server": self.args.server,
                        "frequency_hz": self.dial_frequency_hz,
                        "mode": self.selected_mode(),
                        "rows": self.stats.waterfall_rows,
                        "fft_size": self.config.get("fft_size"),
                        "center_freq_hz": self.config.get("center_freq"),
                        "sample_rate_hz": self.config.get("samp_rate"),
                        "server_config": self.config,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    def _open_audio_writer(self, rate: int) -> None:
        if self.wave_writer is not None:
            return
        output = Path(self.args.audio)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.wave_writer = wave.open(str(output), "wb")
        self.wave_writer.setnchannels(1)
        self.wave_writer.setsampwidth(2)
        self.wave_writer.setframerate(rate)
        self.audio_rate = rate

    def _write_waterfall_preview(self) -> None:
        """Render a portable grayscale preview without adding an image dependency."""
        if not self.args.waterfall_preview or not self.stats.waterfall_rows:
            return
        width = int(self.config.get("fft_size") or 0)
        if width <= 0:
            raise RuntimeError("cannot render waterfall preview without an FFT width")
        source = Path(self.args.waterfall)
        expected_bytes = width * self.stats.waterfall_rows * 4
        if source.stat().st_size != expected_bytes:
            raise RuntimeError("waterfall row width changed during capture; preview not written")
        levels = self.config.get("waterfall_levels") or {}
        floor = float(levels.get("min", -110.0))
        ceiling = float(levels.get("max", -10.0))
        if ceiling <= floor:
            floor, ceiling = -110.0, -10.0
        preview_width = max(1, int(self.args.waterfall_preview_width))
        output = Path(self.args.waterfall_preview)
        output.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as raw, output.open("wb") as image:
            image.write(f"P5\n{preview_width} {self.stats.waterfall_rows}\n255\n".encode("ascii"))
            for _ in range(self.stats.waterfall_rows):
                row = raw.read(width * 4)
                if len(row) != width * 4:
                    raise RuntimeError("waterfall capture ended before its declared row count")
                samples = struct.unpack("<{}f".format(width), row)
                if preview_width != width:
                    # Preserve narrow signals when reducing the receiver FFT to
                    # the display's 1024-pixel radio canvas.
                    samples = tuple(
                        max(samples[int(x * width / preview_width):max(int((x + 1) * width / preview_width), int(x * width / preview_width) + 1)])
                        for x in range(preview_width)
                    )
                pixels = bytearray(
                    0
                    if not math.isfinite(value) or value <= floor
                    else 255
                    if value >= ceiling
                    else int((value - floor) * 255.0 / (ceiling - floor))
                    for value in samples
                )
                image.write(pixels)

    def send_handshake(self, ws: WebSocket) -> None:
        ws.send_text("SERVER DE CLIENT client=ituner-openwebrx-recorder.py type=receiver")
        ws.send_text(
            json.dumps(
                {
                    "type": "connectionproperties",
                    "params": {"output_rate": self.args.output_rate, "hd_output_rate": self.args.hd_output_rate},
                },
                separators=(",", ":"),
            )
        )

    def selected_mode(self) -> str:
        requested = self.args.mode or self.config.get("start_mod") or "am"
        mode = str(requested).lower()
        if mode not in DEFAULT_FILTERS:
            raise RecorderConfigurationError(f"unsupported OpenWebRX modulation: {mode}")
        return mode

    def _start_dsp(self, ws: WebSocket) -> None:
        if self.started or "center_freq" not in self.config:
            return
        center = float(self.config["center_freq"])
        sample_rate = float(self.config.get("samp_rate", 0))
        if self.dial_frequency_hz is None:
            # This matches the browser's initial-demodulator path. ``start_freq``
            # is a source-side property and can describe a different profile;
            # ``start_offset_freq`` is the receiver client's actual dial offset.
            start_offset = float(self.config.get("start_offset_freq", 0))
            # Some multi-profile servers send a stale start offset while
            # changing profile. The browser discards an out-of-window offset;
            # use the center frequency in that case rather than retrying a
            # request the active profile can never serve.
            if sample_rate and abs(start_offset) > sample_rate / 2:
                start_offset = 0
            self.dial_frequency_hz = center + start_offset
        offset = self.dial_frequency_hz - center
        if sample_rate and abs(offset) > sample_rate / 2:
            raise RecorderConfigurationError(
                f"{self.dial_frequency_hz:.0f} Hz is outside this profile's "
                f"{sample_rate:.0f} Hz capture window centered at {center:.0f} Hz"
            )
        mode = self.selected_mode()
        low_cut, high_cut = DEFAULT_FILTERS[mode]
        if self.args.low_cut is not None:
            low_cut = self.args.low_cut
        if self.args.high_cut is not None:
            high_cut = self.args.high_cut
        params = {
            "mod": mode,
            "offset_freq": round(offset),
            "low_cut": low_cut,
            "high_cut": high_cut,
            "squelch_level": self.args.squelch_level,
        }
        ws.send_text(json.dumps({"type": "dspcontrol", "params": params}, separators=(",", ":")))
        ws.send_text(json.dumps({"type": "dspcontrol", "action": "start"}, separators=(",", ":")))
        self.started = True
        print(
            f"recording {mode.upper()} {self.dial_frequency_hz / 1000:.3f} kHz "
            f"from OpenWebRX center {center / 1000:.3f} kHz",
            flush=True,
        )

    def handle_text(self, ws: WebSocket, payload: bytes) -> None:
        text = payload.decode("utf-8", "replace")
        if text.startswith("CLIENT DE SERVER"):
            self.stats.control_messages += 1
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            self.stats.errors.append("unrecognized text frame")
            return
        self.stats.control_messages += 1
        if message.get("type") == "config" and isinstance(message.get("value"), dict):
            self.config.update(message["value"])
            if self.args.verbose:
                visible = {key: value for key, value in message["value"].items() if key != "waterfall_colors"}
                if "waterfall_colors" in message["value"]:
                    visible["waterfall_colors"] = f"{len(message['value']['waterfall_colors'])} entries"
                print("OpenWebRX config update: " + json.dumps(visible, sort_keys=True), flush=True)
            if not self.announced_config and "center_freq" in self.config:
                self.announced_config = True
                print(
                    "OpenWebRX config: "
                    f"center={self.config.get('center_freq')} Hz "
                    f"rate={self.config.get('samp_rate')} Hz "
                    f"audio={self.config.get('audio_compression', 'none')} "
                    f"fft={self.config.get('fft_compression', 'none')}",
                    flush=True,
                )
            self._start_dsp(ws)
            return
        if message.get("type") in ("sdr_error", "demodulator_error", "backoff"):
            raise RuntimeError(str(message.get("value") or message.get("reason") or message["type"]))

    def handle_binary(self, payload: bytes) -> None:
        if not payload:
            return
        frame_type, data = payload[0], payload[1:]
        if frame_type == 1:
            self._handle_waterfall(data)
        elif frame_type == 2:
            self._handle_audio(data, self.args.output_rate)
        elif frame_type == 4:
            self._handle_audio(data, self.args.hd_output_rate)
            self.stats.hd_audio_packets += 1

    def _handle_audio(self, data: bytes, rate: int) -> None:
        compression = self.config.get("audio_compression", "none")
        if compression == "adpcm":
            samples = self.audio_decoder.decode(data)
            raw = array.array("h", samples)
            if sys.byteorder != "little":
                raw.byteswap()
            pcm = raw.tobytes()
        elif compression == "none":
            pcm = data
            if len(pcm) % 2:
                raise ValueError("odd uncompressed audio packet")
            samples = None
        else:
            raise RuntimeError(f"unsupported OpenWebRX audio compression: {compression}")
        if self.args.audio and self.wave_writer is None:
            self._open_audio_writer(rate)
        if self.wave_writer is not None:
            if self.audio_rate != rate:
                raise RuntimeError("server switched between narrow and HD audio during one WAV capture")
            self.wave_writer.writeframesraw(pcm)
        self.stats.audio_packets += 1
        self.stats.audio_samples += len(samples) if samples is not None else len(pcm) // 2

    def _handle_waterfall(self, data: bytes) -> None:
        compression = self.config.get("fft_compression", "none")
        if compression == "none":
            if len(data) % 4:
                raise ValueError("malformed uncompressed FFT packet")
            row = data
        elif compression == "adpcm":
            decoder = ImaAdpcmDecoder()
            samples = decoder.decode(data)
            if len(samples) <= FFT_ADPCM_PAD_SAMPLES:
                return
            row = struct.pack("<{}f".format(len(samples) - FFT_ADPCM_PAD_SAMPLES), *(
                value / 100.0 for value in samples[FFT_ADPCM_PAD_SAMPLES:]
            ))
        else:
            raise RuntimeError(f"unsupported OpenWebRX FFT compression: {compression}")
        if self.waterfall_file is not None:
            self.waterfall_file.write(row)
        self.stats.waterfall_rows += 1

    def record(self) -> int:
        deadline = time.monotonic() + self.args.duration
        attempt = 0
        try:
            while time.monotonic() < deadline:
                ws: Optional[WebSocket] = None
                self.started = False
                self.audio_decoder.reset()
                try:
                    ws = WebSocket.connect(self.args.server, timeout=self.args.connect_timeout)
                    self.send_handshake(ws)
                    attempt = 0
                    while time.monotonic() < deadline:
                        try:
                            opcode, payload = ws.recv()
                        except socket.timeout:
                            continue
                        if opcode == 0x1:
                            self.handle_text(ws, payload)
                        elif opcode == 0x2:
                            self.handle_binary(payload)
                except RecorderConfigurationError as exc:
                    message = f"configuration: {exc}"
                    self.stats.errors.append(message)
                    print(message, file=sys.stderr, flush=True)
                    break
                except (EOFError, OSError, RuntimeError, ValueError) as exc:
                    if time.monotonic() >= deadline:
                        break
                    attempt += 1
                    self.stats.reconnects += 1
                    message = f"connection {attempt}: {exc}"
                    self.stats.errors.append(message)
                    print(message, file=sys.stderr, flush=True)
                    time.sleep(min(self.args.reconnect_delay * attempt, 10.0))
                finally:
                    if ws is not None:
                        ws.close()
        finally:
            self.close()
        print(
            f"complete: audio={self.stats.audio_samples} samples, "
            f"waterfall={self.stats.waterfall_rows} rows, reconnects={self.stats.reconnects}",
            flush=True,
        )
        return 0 if self.stats.audio_samples or self.stats.waterfall_rows else 2


def self_test() -> None:
    decoder = SyncedImaAdpcmDecoder()
    sync_packet = b"SYNC" + struct.pack("<hh", 0, 0) + bytes((0x00, 0x88))
    assert decoder.decode(sync_packet) == [0, 0, 0, 0]
    fft = ImaAdpcmDecoder()
    assert fft.decode(bytes((0x00, 0xFF))) == [0, 0, -11, -41]
    assert websocket_path("http://receiver.local:8073")[3] == "/ws/"
    assert websocket_path("https://receiver.local/rx/")[3] == "/rx/ws/"
    print("openwebrx_recorder self-test passed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record audio and waterfall data from an OpenWebRX/OpenWebRX+ receiver."
    )
    parser.add_argument("--server", help="OpenWebRX base URL, e.g. http://lcd.local:8073")
    parser.add_argument("--frequency-hz", type=float, help="Dial frequency in Hz; defaults to the server profile's start frequency")
    parser.add_argument("--mode", choices=sorted(DEFAULT_FILTERS), help="Demodulation mode; defaults to the server profile")
    parser.add_argument("--low-cut", type=int, help="Passband low edge in Hz relative to dial")
    parser.add_argument("--high-cut", type=int, help="Passband high edge in Hz relative to dial")
    parser.add_argument("--squelch-level", type=int, default=-150)
    parser.add_argument("--duration", type=float, default=30.0, help="Capture duration in seconds")
    parser.add_argument("--audio", type=Path, help="Output mono 16-bit WAV file")
    parser.add_argument("--waterfall", type=Path, help="Output raw little-endian float32 FFT rows")
    parser.add_argument("--waterfall-metadata", type=Path, help="Optional JSON sidecar path")
    parser.add_argument("--waterfall-preview", type=Path, help="Optional grayscale PGM waterfall image")
    parser.add_argument("--waterfall-preview-width", type=int, default=1024, help="Preview width in pixels")
    parser.add_argument("--output-rate", type=int, default=12_000, help="Requested narrow-band audio rate")
    parser.add_argument("--hd-output-rate", type=int, default=48_000, help="Requested HD audio rate")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--reconnect-delay", type=float, default=1.0)
    parser.add_argument("--verbose", action="store_true", help="Print server configuration updates")
    parser.add_argument("--self-test", action="store_true", help="Run protocol-unit tests and exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.server:
        raise SystemExit("--server is required unless --self-test is used")
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if not args.audio and not args.waterfall:
        raise SystemExit("choose at least one output: --audio and/or --waterfall")
    return OpenWebRxRecorder(args).record()


if __name__ == "__main__":
    raise SystemExit(main())
