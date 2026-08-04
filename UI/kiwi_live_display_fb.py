#!/usr/bin/env python3
import argparse
import base64
from collections import deque
import errno
import hashlib
import math
import mmap
import os
import select
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw

import render_sdr_frontend_mockup as sdr_ui


FB = Path("/dev/fb0")
SYS = Path("/sys/class/graphics/fb0")
EVENT_ROOT = Path("/sys/class/input")
LOGICAL_W = 960
LOGICAL_H = 320
WATERFALL_Y0 = sdr_ui.TOP_H + sdr_ui.RULER_H
WATERFALL_Y1 = 292
EVENT_STRUCT = struct.Struct("qqHHi")
EV_KEY = 0x01
EV_ABS = 0x03
EV_SYN = 0x00
SYN_REPORT = 0x00
BTN_TOUCH = 0x14A
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
SND_FLAG_COMPRESSED = 0x10
SND_FLAG_STEREO = 0x08
SND_FLAG_LITTLE_ENDIAN = 0x80
GEAR_BOX = (910, 244, 956, 290)
ZOOM_PLUS_BOX = (10, 108, 72, 170)
ZOOM_MINUS_BOX = (10, 190, 72, 252)
WATERFALL_TUNE_X0 = 88
WATERFALL_TUNE_X1 = 872
ZOOM_OSD_SECONDS = 1.6
ZOOM_OSD_BOX = (126, 106, 922, 204)
PICKER_BOX = (24, 76, 936, 284)
PICKER_COLS = 3
PICKER_ROWS = 3
STATIONS = [
    ("KX4AZ-2", "Alabama, US", "http://kx4az2.proxy.kiwisdr.com:8073"),
    ("K7ABJ", "Montana, US", "http://k7abj.proxy.kiwisdr.com:8073"),
    ("DE6CDA", "Germany", "http://de6cda.proxy.kiwisdr.com:8073"),
    ("KPH", "California, US", "http://kphsdr.com:8073"),
    ("N2YO", "US east", "http://kiwisdr.n2yo.net:8073"),
    ("KK6PR", "Oregon, US", "http://kk6pr.ddns.net:8076"),
    ("Wessex", "England", "http://wessex.zapto.org:8073"),
    ("Proxy 21662", "Public Kiwi", "http://21662.proxy2.kiwisdr.com:8073"),
    ("Proxy 21762", "Public Kiwi", "http://21762.proxy2.kiwisdr.com:8073"),
    ("0-30 MHz", "Fallback A", "http://kx4az2.proxy.kiwisdr.com:8073"),
    ("40m USB", "Fallback B", "http://k7abj.proxy.kiwisdr.com:8073"),
    ("HF DX", "Fallback C", "http://de6cda.proxy.kiwisdr.com:8073"),
]


class KiwiWebSocket:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()

    @staticmethod
    def connect(endpoint, stream_name, timeout=8.0):
        scheme, host, port = parse_endpoint(endpoint)
        ws_scheme = "wss" if scheme in ("https", "wss") else "ws"
        raw = socket.create_connection((host, port), timeout=timeout)
        raw.settimeout(timeout)
        if ws_scheme == "wss":
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = f"/{int(time.time())}/{stream_name}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: http://{host}:{port}\r\n"
            "User-Agent: Codex-KiwiSDR-display\r\n"
            "\r\n"
        ).encode("ascii")
        raw.sendall(request)

        response = read_http_header(raw)
        status = response.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise RuntimeError(f"websocket handshake failed for {stream_name}: {status.decode('latin1', 'replace')}")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        if expected not in response:
            raise RuntimeError(f"websocket accept check failed for {stream_name}")

        raw.settimeout(1.0)
        return KiwiWebSocket(raw)

    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def send_close(self):
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass

    def recv(self):
        while True:
            header = recv_exact(self.sock, 2)
            if not header:
                raise EOFError("websocket closed")
            b0, b1 = header
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", recv_exact(self.sock, 2))[0]
            elif length == 127:
                length = struct.unpack(">Q", recv_exact(self.sock, 8))[0]

            mask = recv_exact(self.sock, 4) if masked else None
            payload = recv_exact(self.sock, length) if length else b""
            if mask:
                payload = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))

            if opcode == 0x8:
                raise EOFError("websocket closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            return payload

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        masked = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
        with self.lock:
            self.sock.sendall(header + mask + masked)


def zoom_to_span_khz(zoom):
    return 30000.0 / (2 ** clamp(int(zoom), 0, 14))


def span_to_zoom(span_khz):
    if span_khz <= 0:
        return 9
    best_zoom = 0
    best_error = float("inf")
    for zoom in range(15):
        error = abs(zoom_to_span_khz(zoom) - span_khz)
        if error < best_error:
            best_zoom = zoom
            best_error = error
    return best_zoom


class LiveState:
    def __init__(self, server, freq_khz, zoom, smeter_dbm):
        self.lock = threading.Lock()
        self.server = server
        self.freq_khz = freq_khz
        self.zoom = clamp(int(zoom), 0, 14)
        self.span_khz = zoom_to_span_khz(self.zoom)
        self.smeter_dbm = smeter_dbm
        self.waterfall = Image.new("RGB", (LOGICAL_W, LOGICAL_H - sdr_ui.TOP_H), (1, 5, 12))
        self.waterfall_queue = deque(maxlen=160)
        self.dirty = True
        self.tune_generation = 0
        self.view_generation = 0
        self.server_generation = 0
        self.error = None
        self.last_snd_at = 0

    def snapshot(self):
        with self.lock:
            self.dirty = False
            return self.server, self.freq_khz, self.span_khz, self.smeter_dbm, self.waterfall.copy(), self.error

    def mark_dirty(self):
        with self.lock:
            self.dirty = True

    def needs_render(self):
        with self.lock:
            return self.dirty

    def set_error(self, error):
        with self.lock:
            self.error = str(error)
            self.dirty = True

    def clear_error(self):
        with self.lock:
            if self.error is None:
                return
            self.error = None
            self.dirty = True

    def set_smeter(self, smeter_dbm, source="snd"):
        with self.lock:
            if source == "snd":
                self.last_snd_at = time.monotonic()
            self.smeter_dbm = 0.82 * self.smeter_dbm + 0.18 * smeter_dbm
            self.dirty = True

    def allow_wf_smeter_fallback(self):
        with self.lock:
            return time.monotonic() - self.last_snd_at > 3.0

    def set_freq(self, freq_khz):
        with self.lock:
            self.freq_khz = freq_khz
            self.waterfall_queue.clear()
            self.tune_generation += 1
            self.view_generation += 1
            self.dirty = True
            return self.tune_generation

    def preview_freq(self, freq_khz):
        with self.lock:
            self.freq_khz = freq_khz
            self.dirty = True

    def get_freq(self):
        with self.lock:
            return self.freq_khz

    def get_tune(self, seen_generation):
        with self.lock:
            if self.tune_generation == seen_generation:
                return seen_generation, None
            return self.tune_generation, self.freq_khz

    def set_zoom(self, zoom):
        with self.lock:
            zoom = clamp(int(zoom), 0, 14)
            if zoom == self.zoom:
                return self.view_generation
            self.zoom = zoom
            self.span_khz = zoom_to_span_khz(zoom)
            self.waterfall_queue.clear()
            self.view_generation += 1
            self.dirty = True
            return self.view_generation

    def set_freq_zoom(self, freq_khz, zoom):
        with self.lock:
            self.freq_khz = freq_khz
            self.zoom = clamp(int(zoom), 0, 14)
            self.span_khz = zoom_to_span_khz(self.zoom)
            self.waterfall_queue.clear()
            self.tune_generation += 1
            self.view_generation += 1
            self.dirty = True
            return self.view_generation

    def get_view(self, seen_generation):
        with self.lock:
            if self.view_generation == seen_generation:
                return seen_generation, None
            return self.view_generation, (self.freq_khz, self.zoom)

    def get_zoom(self):
        with self.lock:
            return self.zoom

    def get_span(self):
        with self.lock:
            return self.span_khz

    def set_server(self, server, zoom=None):
        with self.lock:
            self.server = server
            self.server_generation += 1
            if zoom is not None:
                self.zoom = clamp(int(zoom), 0, 14)
                self.span_khz = zoom_to_span_khz(self.zoom)
            self.view_generation += 1
            self.error = None
            self.smeter_dbm = -110.0
            self.waterfall = Image.new("RGB", (LOGICAL_W, LOGICAL_H - sdr_ui.TOP_H), (1, 5, 12))
            self.waterfall_queue.clear()
            self.dirty = True
            return self.server_generation

    def get_server(self, seen_generation):
        with self.lock:
            if self.server_generation == seen_generation:
                return seen_generation, None
            return self.server_generation, self.server

    def current_server(self):
        with self.lock:
            return self.server

    def update_waterfall(self, line, row_pixels=1):
        with self.lock:
            y0 = sdr_ui.RULER_H
            h = self.waterfall.height
            row_pixels = clamp(int(row_pixels), 1, max(1, h - y0))
            for _ in range(row_pixels):
                self.waterfall_queue.append(line)

    def advance_waterfall(self):
        with self.lock:
            if not self.waterfall_queue:
                return False
            line = self.waterfall_queue.popleft()
            y0 = sdr_ui.RULER_H
            h = self.waterfall.height
            region = self.waterfall.crop((0, y0, LOGICAL_W, h - 1))
            self.waterfall.paste(region, (0, y0 + 1))
            self.waterfall.paste(line, (0, y0))
            self.dirty = True
            return True

    def has_pending_waterfall(self):
        with self.lock:
            return bool(self.waterfall_queue)

    def pending_waterfall_count(self):
        with self.lock:
            return len(self.waterfall_queue)


def parse_endpoint(endpoint):
    if "://" not in endpoint:
        endpoint = "http://" + endpoint
    parsed = urlparse(endpoint)
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    if not host:
        raise ValueError(f"bad KiwiSDR endpoint: {endpoint}")
    port = parsed.port or (443 if scheme in ("https", "wss") else 8073)
    return scheme, host, port


def read_http_header(sock):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
        if len(data) > 16384:
            raise RuntimeError("HTTP header too large")
    return bytes(data)


def recv_exact(sock, count):
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError("socket closed")
        data += chunk
    return bytes(data)


def send_kiwi_setup(ws, client_type, user):
    ws.send_text(f"SET auth t={client_type} p=")
    ws.send_text(f"SET ident_user={user}")
    ws.send_text("SET geo=Ituner receiver")


def send_wf_setup(ws, freq_khz, zoom, wf_speed):
    ws.send_text(f"SET zoom={zoom} cf={freq_khz:.3f}")
    ws.send_text("SET maxdb=-10 mindb=-110")
    ws.send_text(f"SET wf_speed={wf_speed}")
    ws.send_text("SET wf_comp=0")
    ws.send_text("SET interp=13")


def send_snd_setup(ws, freq_khz, mode, low_cut, high_cut):
    ws.send_text("SET compression=0")
    ws.send_text(f"SET mod={mode} low_cut={low_cut} high_cut={high_cut} freq={freq_khz:.3f}")
    ws.send_text("SET agc=1 hang=0 thresh=-100 slope=6 decay=1000 manGain=50")
    ws.send_text("SET squelch=0 max=0")


def parse_msg_params(message):
    if len(message) <= 4:
        return {}
    body = message[4:].decode("ascii", "replace")
    params = {}
    for item in body.split():
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value
    return params


def make_waterfall_mapper():
    r_lut, g_lut, b_lut = [], [], []
    for i in range(256):
        if i < 32:
            r = 0
            g = 0
            b = i * 255 / 31
        elif i < 72:
            r = 0
            g = (i - 32) * 255 / 39
            b = 255
        elif i < 96:
            r = 0
            g = 255
            b = 255 - (i - 72) * 255 / 23
        elif i < 116:
            r = (i - 96) * 255 / 19
            g = 255
            b = 0
        elif i < 184:
            r = 255
            g = 255 - (i - 116) * 255 / 67
            b = 0
        else:
            r = 255
            g = 0
            b = (i - 184) * 128 / 70
        r_lut.append(clamp(int(round(r)), 0, 255))
        g_lut.append(clamp(int(round(g)), 0, 255))
        b_lut.append(clamp(int(round(b)), 0, 255))
    return r_lut, g_lut, b_lut


class WaterfallLeveler:
    def __init__(self, floor, ceiling, auto=True):
        self.floor = floor
        self.ceiling = ceiling
        self.auto = auto

    def levels_for(self, samples):
        if not self.auto or not samples:
            return self.floor, self.ceiling

        ordered = sorted(samples)
        median = ordered[len(ordered) // 2]
        p98 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.98))]
        target_floor = clamp(median - 8, 40, 230)
        target_ceiling = clamp(max(p98 + 72, target_floor + 95), target_floor + 55, 255)
        self.floor = 0.92 * self.floor + 0.08 * target_floor
        self.ceiling = 0.92 * self.ceiling + 0.08 * target_ceiling
        return self.floor, self.ceiling


def waterfall_line(samples, mapper, floor, ceiling):
    if not samples:
        return Image.new("RGB", (LOGICAL_W, 1), (0, 0, 16))
    scale = 255.0 / max(1, ceiling - floor)
    normalized = bytes(max(0, min(255, int((value - floor) * scale))) for value in samples)
    gray = Image.frombytes("L", (len(normalized), 1), normalized).resize((LOGICAL_W, 1), Image.Resampling.BILINEAR)
    r_lut, g_lut, b_lut = mapper
    return Image.merge("RGB", (gray.point(r_lut), gray.point(g_lut), gray.point(b_lut)))


def contains(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def draw_gear_button(draw, active=False):
    x0, y0, x1, y1 = GEAR_BOX
    fill = (8, 15, 22, 205) if not active else (18, 72, 62, 235)
    outline = (106, 126, 136, 230) if not active else (62, 246, 185, 255)
    draw.rounded_rectangle(GEAR_BOX, radius=7, fill=fill, outline=outline, width=1)
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    color = (226, 236, 240, 255)
    for angle in range(0, 360, 45):
        if angle % 90 == 0:
            dx, dy = (0, -13) if angle == 0 else ((13, 0) if angle == 90 else ((0, 13) if angle == 180 else (-13, 0)))
        else:
            dx = 9 if angle in (45, 135) else -9
            dy = -9 if angle in (45, 315) else 9
        draw.line((cx, cy, cx + dx, cy + dy), fill=color, width=3)
    draw.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), outline=color, width=3)
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=color)


def draw_zoom_buttons(draw):
    for box, label in ((ZOOM_PLUS_BOX, "+"), (ZOOM_MINUS_BOX, "-")):
        draw.rounded_rectangle(box, radius=8, fill=(3, 9, 14, 132), outline=(134, 225, 232, 168), width=1)
        sdr_ui.text_box(
            draw,
            ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2 - 1),
            label,
            (222, 246, 249, 226),
            32,
            True,
            mono=True,
            anchor="mm",
        )


def draw_zoom_osd(draw, zoom, span_khz, alpha=220):
    alpha = clamp(int(alpha), 0, 255)
    if alpha <= 0:
        return

    x0, y0, x1, y1 = ZOOM_OSD_BOX
    green = (72, 255, 122, alpha)
    soft_green = (72, 255, 122, int(alpha * 0.30))
    dim_green = (72, 255, 122, int(alpha * 0.16))
    black = (0, 8, 4, int(alpha * 0.42))

    draw.rectangle((x0, y0, x1, y1), fill=black)
    for offset, line_alpha in ((0, 0.42), (32, 0.20), (64, 0.12)):
        y = y0 + offset
        draw.line((x0 + 4, y, x1 - 4, y), fill=(72, 255, 122, int(alpha * line_alpha)), width=1)

    sdr_ui.text_box(draw, (x0 + 20, y0 + 28), "ZOOM", green, 28, True, mono=True, anchor="lm")
    sdr_ui.text_box(draw, (x0 + 176, y0 + 28), f"{zoom:02d}", green, 36, True, mono=True, anchor="lm")
    sdr_ui.text_box(draw, (x1 - 20, y0 + 28), f"{span_khz:.1f} kHz", green, 24, True, mono=True, anchor="rm")

    track_x0 = x0 + 28
    track_x1 = x1 - 28
    base_y = y0 + 80
    top_y = y0 + 52
    draw.line((track_x0, base_y, track_x1, base_y), fill=soft_green, width=3)

    bar_w = 24
    for level in range(15):
        x = int(round(track_x0 + (track_x1 - track_x0) * level / 14))
        is_current = level == zoom
        is_filled = level <= zoom
        fill = green if is_filled else dim_green
        h = 43 if is_current else 31
        draw.rectangle((x - bar_w // 2, base_y - h, x + bar_w // 2, base_y - 1), fill=fill)
        if level in (0, 7, 14):
            draw.line((x, top_y, x, top_y + 10), fill=soft_green, width=2)


def station_page_max(stations):
    visible = PICKER_COLS * PICKER_ROWS
    return max(0, len(stations) - visible)


def station_tile(index, scroll):
    visible_index = index - scroll
    if visible_index < 0 or visible_index >= PICKER_COLS * PICKER_ROWS:
        return None
    x0, y0, x1, y1 = PICKER_BOX
    pad = 12
    header_h = 30
    gap = 8
    grid_x0 = x0 + pad
    grid_y0 = y0 + header_h + pad
    cell_w = (x1 - x0 - 2 * pad - (PICKER_COLS - 1) * gap) // PICKER_COLS
    cell_h = (y1 - grid_y0 - pad - (PICKER_ROWS - 1) * gap) // PICKER_ROWS
    col = visible_index % PICKER_COLS
    row = visible_index // PICKER_COLS
    left = grid_x0 + col * (cell_w + gap)
    top = grid_y0 + row * (cell_h + gap)
    return left, top, left + cell_w, top + cell_h


def station_at(x, y, stations, scroll):
    for idx, _station in enumerate(stations):
        box = station_tile(idx, scroll)
        if box and contains(box, x, y):
            return idx
    return None


def draw_station_picker(draw, stations, scroll, selected_server):
    x0, y0, x1, y1 = PICKER_BOX
    draw.rounded_rectangle(PICKER_BOX, radius=8, fill=(3, 8, 13, 238), outline=(102, 124, 132, 245), width=1)
    sdr_ui.text_box(draw, (x0 + 14, y0 + 20), "PUBLIC KIWI SDR", (232, 242, 245, 255), 17, True, mono=True, anchor="lm")
    sdr_ui.text_box(draw, (x1 - 18, y0 + 20), f"{scroll + 1}-{min(len(stations), scroll + PICKER_COLS * PICKER_ROWS)} / {len(stations)}", (126, 225, 232, 255), 14, True, mono=True, anchor="rm")

    for idx, (name, location, server) in enumerate(stations):
        box = station_tile(idx, scroll)
        if not box:
            continue
        selected = server == selected_server
        fill = (17, 31, 42, 235) if not selected else (18, 79, 66, 245)
        outline = (52, 67, 78, 255) if not selected else (72, 248, 186, 255)
        draw.rounded_rectangle(box, radius=6, fill=fill, outline=outline, width=1)
        sdr_ui.text_box(draw, (box[0] + 10, box[1] + 15), name[:18], (238, 247, 249, 255), 15, True, mono=True, anchor="lm")
        sdr_ui.text_box(draw, (box[0] + 10, box[1] + 35), location[:24], (142, 225, 218, 255), 12, True, mono=False, anchor="lm")
        parsed = urlparse(server if "://" in server else "http://" + server)
        host = (parsed.hostname or server)[:26]
        sdr_ui.text_box(draw, (box[2] - 10, box[1] + 35), host, (136, 154, 166, 255), 11, False, mono=True, anchor="rm")

    if scroll > 0:
        draw.polygon(((x1 - 42, y0 + 32), (x1 - 30, y0 + 18), (x1 - 18, y0 + 32)), fill=(228, 239, 242, 210))
    if scroll < station_page_max(stations):
        draw.polygon(((x1 - 42, y1 - 18), (x1 - 30, y1 - 4), (x1 - 18, y1 - 18)), fill=(228, 239, 242, 210))


def waterfall_worker(args, state, stop_event):
    mapper = make_waterfall_mapper()
    leveler = WaterfallLeveler(args.wf_floor, args.wf_ceil, auto=args.wf_auto_levels)
    seen_view = -1
    seen_server = -1
    reported_first_frame = False
    while not stop_event.is_set():
        ws = None
        try:
            seen_server, server = state.get_server(seen_server)
            server = server or state.current_server()
            ws = KiwiWebSocket.connect(server, "W/F")
            send_kiwi_setup(ws, "kiwi", args.user)
            seen_view, view = state.get_view(seen_view)
            freq, zoom = view or (state.get_freq(), state.get_zoom())
            print(f"wf setup: {server} {freq:.3f} kHz zoom {zoom} span {zoom_to_span_khz(zoom):.1f} kHz", flush=True)
            send_wf_setup(ws, freq, zoom, args.wf_speed)
            last_keepalive = 0
            while not stop_event.is_set():
                server_generation, new_server = state.get_server(seen_server)
                if new_server is not None:
                    seen_server = server_generation
                    break

                view_generation, new_view = state.get_view(seen_view)
                if new_view is not None:
                    seen_view = view_generation
                    freq, zoom = new_view
                    send_wf_setup(ws, freq, zoom, args.wf_speed)

                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now

                try:
                    message = ws.recv()
                except socket.timeout:
                    continue
                if message[:3] == b"W/F" and len(message) > 16:
                    samples = message[16:]
                    floor, ceiling = leveler.levels_for(samples)
                    line = waterfall_line(samples, mapper, floor, ceiling)
                    state.update_waterfall(line, args.wf_row_pixels)
                    if not reported_first_frame:
                        print(f"waterfall live: {len(samples)} bins", flush=True)
                        reported_first_frame = True
                    state.clear_error()
                    if args.wf_smeter_fallback and samples and state.allow_wf_smeter_fallback():
                        sorted_samples = sorted(samples)
                        p95 = sorted_samples[min(len(sorted_samples) - 1, int(len(sorted_samples) * 0.95))]
                        state.set_smeter(p95 - 268, source="wf")
                elif message[:3] == b"MSG":
                    continue
        except Exception as exc:
            state.set_error(f"WF {exc}")
            if stop_event.wait(2.0):
                break
        finally:
            if ws:
                ws.send_close()


def snd_worker(args, state, stop_event):
    seen_tune = -1
    seen_server = -1
    player = None
    reported_first_snd = False
    if args.audio:
        player = subprocess.Popen(
            ["aplay", "-q", "-f", "S16_BE", "-r", str(args.audio_rate), "-c", "1"],
            stdin=subprocess.PIPE,
        )
    while not stop_event.is_set():
        ws = None
        try:
            seen_server, server = state.get_server(seen_server)
            server = server or state.current_server()
            ws = KiwiWebSocket.connect(server, "SND")
            send_kiwi_setup(ws, "kiwi", args.user)
            seen_tune, freq = state.get_tune(seen_tune)
            current_freq = freq or state.get_freq()
            configured = False
            last_keepalive = 0
            while not stop_event.is_set():
                server_generation, new_server = state.get_server(seen_server)
                if new_server is not None:
                    seen_server = server_generation
                    break

                generation, new_freq = state.get_tune(seen_tune)
                if new_freq is not None:
                    seen_tune = generation
                    current_freq = new_freq
                    if configured:
                        send_snd_setup(ws, current_freq, args.mode, args.low_cut, args.high_cut)

                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now

                try:
                    message = ws.recv()
                except socket.timeout:
                    continue
                if message[:3] == b"MSG":
                    params = parse_msg_params(message)
                    if "audio_rate" in params:
                        ws.send_text(f"SET AR OK in={int(float(params['audio_rate']))} out=44100")
                    if "badp" in params and params["badp"] != "0":
                        raise RuntimeError(f"badp={params['badp']}")
                    if "too_busy" in params:
                        raise RuntimeError(f"too_busy={params['too_busy']}")
                    if "sample_rate" in params and not configured:
                        send_snd_setup(ws, current_freq, args.mode, args.low_cut, args.high_cut)
                        configured = True
                    continue

                if message[:3] != b"SND" or len(message) < 10:
                    continue

                body = message[3:]
                flags, _seq = struct.unpack("<BI", body[:5])
                smeter, = struct.unpack(">H", body[5:7])
                rssi = 0.1 * smeter - 127
                state.set_smeter(rssi, source="snd")
                if not reported_first_snd:
                    print(f"s-meter live: {rssi:.1f} dBm", flush=True)
                    reported_first_snd = True
                audio = body[7:]
                if player and player.stdin and not (flags & SND_FLAG_COMPRESSED) and not (flags & SND_FLAG_STEREO):
                    if flags & SND_FLAG_LITTLE_ENDIAN:
                        audio = swap_s16_bytes(audio)
                    try:
                        player.stdin.write(audio)
                    except BrokenPipeError:
                        player = None
        except Exception as exc:
            state.set_error(f"SND {exc}")
            if stop_event.wait(2.0):
                break
        finally:
            if ws:
                ws.send_close()
    if player:
        try:
            player.terminate()
        except OSError:
            pass


def swap_s16_bytes(data):
    out = bytearray(len(data))
    out[0::2] = data[1::2]
    out[1::2] = data[0::2]
    return bytes(out)


def fb_info():
    w, h = map(int, (SYS / "virtual_size").read_text().strip().split(","))
    bpp = int((SYS / "bits_per_pixel").read_text())
    stride = int((SYS / "stride").read_text())
    if bpp != 32:
        raise SystemExit(f"expected 32bpp framebuffer, got {w}x{h}x{bpp}")
    if (w, h) != (400, 960):
        raise SystemExit(f"expected framebuffer {(400, 960)}, got {(w, h)}")
    return w, h, stride


def logical_to_native_bytes(logical, fb_w, fb_h, stride):
    native = sdr_ui.to_framebuffer_400x960(logical)
    packed = native.tobytes("raw", "BGRX")
    tight_stride = fb_w * 4
    if stride == tight_stride:
        return packed

    raw = bytearray(stride * fb_h)
    for y in range(fb_h):
        raw[y * stride:y * stride + tight_stride] = packed[y * tight_stride:(y + 1) * tight_stride]
    return bytes(raw)


def render_live_frame(state, cursor_x=None, picker_open=False, station_scroll=0, stations=None, zoom_osd_alpha=0):
    server, freq_khz, span_khz, smeter_dbm, waterfall, error = state.snapshot()
    frame = sdr_ui.render(freq_khz=freq_khz, span_khz=span_khz, smeter_dbm=smeter_dbm, waterfall=waterfall)
    d = ImageDraw.Draw(frame, "RGBA")
    zoom = state.get_zoom()
    if cursor_x is not None:
        d.line((cursor_x, WATERFALL_Y0, cursor_x, WATERFALL_Y1), fill=(74, 240, 255, 120), width=2)
    if zoom_osd_alpha:
        draw_zoom_osd(d, zoom, span_khz, zoom_osd_alpha)
    draw_zoom_buttons(d)
    draw_gear_button(d, active=picker_open)
    if picker_open:
        shade = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        sd.rectangle((0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H), fill=(0, 0, 0, 118))
        frame = Image.alpha_composite(frame.convert("RGBA"), shade).convert("RGB")
        d = ImageDraw.Draw(frame, "RGBA")
        draw_station_picker(d, stations or STATIONS, station_scroll, server)
        draw_gear_button(d, active=True)
    if error:
        d.rectangle((682, 70, 956, 89), fill=(58, 10, 12, 218))
        d.text((688, 73), error[:40], fill=(255, 154, 154, 255))
    return frame


def write_frame(fb_map, logical):
    fb_w, fb_h, stride, mm = fb_map
    mm[:] = logical_to_native_bytes(logical, fb_w, fb_h, stride)
    mm.flush()


def find_touch_event():
    for event in sorted(EVENT_ROOT.glob("event*")):
        name_file = event / "device/name"
        if not name_file.exists():
            continue
        name = name_file.read_text(errors="ignore").strip().lower()
        if "goodix" in name or "touchscreen" in name:
            return Path("/dev/input") / event.name
    raise SystemExit("could not find a Goodix/touchscreen event device")


def clamp(value, low, high):
    return max(low, min(high, value))


def transform_touch(x, y, args):
    if args.swap_x_y:
        x, y = y, x
    if args.invert_x:
        x = LOGICAL_W - 1 - x
    if args.invert_y:
        y = LOGICAL_H - 1 - y
    return clamp(x, 0, LOGICAL_W - 1), clamp(y, 0, LOGICAL_H - 1)


def is_waterfall_touch(y):
    return WATERFALL_Y0 <= y <= WATERFALL_Y1


def is_waterfall_tune_touch(x, y):
    return WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1


def retune_from_drag(start_freq, start_x, x, span_khz, args):
    hz_per_px = span_khz * 1000 / LOGICAL_W
    direction = 1 if args.invert_tune else -1
    return start_freq + direction * (x - start_x) * hz_per_px / 1000


def retune_from_tap(x, freq_khz, span_khz, args):
    hz_per_px = span_khz * 1000 / LOGICAL_W
    return freq_khz + (x - LOGICAL_W / 2) * hz_per_px / 1000


def bounded_freq(freq_khz, args):
    return clamp(freq_khz, args.min_khz, args.max_khz)


def touch_points(mt_slots, raw_x, raw_y, active, args):
    if not active:
        return []

    points = []
    for slot in sorted(mt_slots):
        info = mt_slots[slot]
        if info.get("active") and info.get("x") is not None and info.get("y") is not None:
            points.append(transform_touch(info["x"], info["y"], args))
    if mt_slots:
        return points
    if not points and active and raw_x is not None and raw_y is not None:
        points.append(transform_touch(raw_x, raw_y, args))
    return points


def midpoint(points):
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pinch_zoom(start_zoom, start_distance, current_distance, step_ratio, max_zoom):
    if start_distance < 18 or current_distance < 1:
        return start_zoom
    ratio = current_distance / start_distance
    if ratio <= 0:
        return start_zoom
    delta = int(round(math.log(ratio, step_ratio)))
    return clamp(start_zoom + delta, 0, max_zoom)


def display_loop(args, state, stop_event):
    fb_w, fb_h, stride = fb_info()
    event_path = args.event or find_touch_event()
    stations = STATIONS
    with FB.open("r+b") as fb, event_path.open("rb", buffering=0) as ev:
        os.set_blocking(ev.fileno(), False)
        mm = mmap.mmap(fb.fileno(), stride * fb_h)
        fb_map = (fb_w, fb_h, stride, mm)
        picker_open = False
        station_scroll = 0
        ui_dirty = True
        zoom_osd_until = 0.0
        zoom_osd_was_visible = False
        write_frame(fb_map, render_live_frame(state, picker_open=picker_open, station_scroll=station_scroll, stations=stations))
        print(f"live KiwiSDR display on /dev/fb0; touch input {event_path}; server {state.current_server()}", flush=True)

        active = False
        raw_x = raw_y = None
        current_slot = 0
        mt_slots = {}
        touch_started = False
        touch_in_waterfall = False
        gesture = None
        saw_multitouch = False
        swipe_started = False
        start_x = start_freq = None
        start_y = 0
        start_scroll = 0
        start_span = state.get_span()
        start_zoom = state.get_zoom()
        start_pinch_distance = 0
        start_mid_x = start_mid_y = 0
        start_zoom_y = 0
        pinch_freq = state.get_freq()
        pinch_zoom_level = start_zoom
        last_x = None
        candidate_freq = state.get_freq()
        min_frame_interval = 1.0 / args.fps if args.fps > 0 else 0
        waterfall_scroll_interval = 1.0 / args.wf_scroll_fps
        next_waterfall_scroll = time.monotonic()
        next_frame = time.monotonic()

        def advance_smooth_waterfall():
            nonlocal next_waterfall_scroll
            now = time.monotonic()
            if now < next_waterfall_scroll:
                return
            if state.advance_waterfall():
                pending = state.pending_waterfall_count()
                catchup = pending > max(8, int(args.wf_scroll_fps * 0.5))
                interval = waterfall_scroll_interval * (0.5 if catchup else 1.0)
                next_waterfall_scroll = now + interval

        while not stop_event.is_set():
            advance_smooth_waterfall()
            now = time.monotonic()
            zoom_osd_visible = now < zoom_osd_until
            waterfall_pending = state.has_pending_waterfall()
            dirty = state.needs_render() or ui_dirty or zoom_osd_visible or zoom_osd_was_visible
            if dirty:
                timeout = max(0, min(next_frame, next_waterfall_scroll if waterfall_pending else next_frame) - now)
            elif waterfall_pending:
                timeout = max(0, next_waterfall_scroll - now)
            else:
                timeout = 0.1
            readable, _, _ = select.select([ev], [], [], timeout)
            if readable:
                while True:
                    try:
                        data = os.read(ev.fileno(), EVENT_STRUCT.size)
                    except BlockingIOError:
                        break
                    except OSError as exc:
                        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                            break
                        raise
                    if not data or len(data) != EVENT_STRUCT.size:
                        break

                    _, _, event_type, code, value = EVENT_STRUCT.unpack(data)
                    if event_type == EV_ABS:
                        if code == ABS_MT_SLOT:
                            current_slot = value
                            mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                        elif code == ABS_X:
                            raw_x = clamp(value, 0, LOGICAL_W - 1)
                        elif code == ABS_Y:
                            raw_y = clamp(value, 0, LOGICAL_H - 1)
                        elif code == ABS_MT_POSITION_X:
                            slot = mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                            slot["x"] = clamp(value, 0, LOGICAL_W - 1)
                        elif code == ABS_MT_POSITION_Y:
                            slot = mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                            slot["y"] = clamp(value, 0, LOGICAL_H - 1)
                        elif code == ABS_MT_TRACKING_ID:
                            slot = mt_slots.setdefault(current_slot, {"active": value >= 0, "x": None, "y": None})
                            slot["active"] = value >= 0
                    elif event_type == EV_KEY and code == BTN_TOUCH:
                        active = value == 1
                        if not active:
                            mt_slots.clear()
                    elif event_type == EV_SYN and code == SYN_REPORT:
                        points = touch_points(mt_slots, raw_x, raw_y, active, args)
                        is_active = bool(points)
                        if not is_active:
                            if raw_x is None or raw_y is None:
                                x = start_x if start_x is not None else 0
                                y = start_y
                            else:
                                x, y = transform_touch(raw_x, raw_y, args)
                        elif len(points) >= 2:
                            x, y = midpoint(points[:2])
                        else:
                            x, y = points[0]

                        if is_active and gesture == "pinch" and len(points) < 2:
                            state.set_freq_zoom(pinch_freq, pinch_zoom_level)
                            print(
                                f"pinch zoom {pinch_zoom_level} "
                                f"span {zoom_to_span_khz(pinch_zoom_level):.1f} kHz",
                                flush=True,
                            )
                            touch_started = False
                            touch_in_waterfall = False
                            gesture = None
                            saw_multitouch = False
                            swipe_started = False
                            start_x = start_freq = last_x = None
                            state.mark_dirty()
                            continue

                        if is_active and len(points) >= 2:
                            saw_multitouch = True

                        if is_active and saw_multitouch and len(points) < 2 and gesture not in ("pinch", "picker"):
                            gesture = "ignore"

                        if is_active and len(points) >= 2 and not picker_open and all(is_waterfall_tune_touch(point[0], point[1]) for point in points[:2]):
                            if not touch_started or gesture != "pinch":
                                base_freq = start_freq if gesture == "waterfall" and start_freq is not None else state.get_freq()
                                touch_started = True
                                gesture = "pinch"
                                touch_in_waterfall = True
                                start_freq = base_freq
                                start_zoom = state.get_zoom()
                                start_span = zoom_to_span_khz(start_zoom)
                                start_mid_x, start_mid_y = midpoint(points[:2])
                                start_zoom_y = start_mid_y
                                start_pinch_distance = distance(points[0], points[1])
                                pinch_freq = start_freq
                                pinch_zoom_level = start_zoom
                                state.preview_freq(pinch_freq)
                            if gesture == "pinch":
                                _mid_x, mid_y = midpoint(points[:2])
                                current_distance = distance(points[0], points[1])
                                vertical_steps = int((start_zoom_y - mid_y) / args.two_finger_zoom_step_px)
                                pinch_level = pinch_zoom(
                                    start_zoom,
                                    start_pinch_distance,
                                    current_distance,
                                    args.pinch_step_ratio,
                                    args.max_pinch_zoom,
                                )
                                vertical_level = clamp(start_zoom + vertical_steps, 0, args.max_pinch_zoom)
                                if abs(vertical_steps) > 0:
                                    new_zoom = vertical_level
                                else:
                                    new_zoom = pinch_level
                                if new_zoom != pinch_zoom_level:
                                    pinch_zoom_level = new_zoom
                                    state.set_freq_zoom(pinch_freq, pinch_zoom_level)
                                    zoom_osd_until = time.monotonic() + args.zoom_osd_seconds
                                    ui_dirty = True
                                    start_zoom = pinch_zoom_level
                                    start_span = zoom_to_span_khz(start_zoom)
                                    start_freq = pinch_freq
                                    start_zoom_y = mid_y
                                    start_pinch_distance = current_distance
                                    print(f"zoom {pinch_zoom_level} span {zoom_to_span_khz(pinch_zoom_level):.1f} kHz", flush=True)
                                else:
                                    state.preview_freq(pinch_freq)
                            continue

                        if is_active:
                            if not touch_started:
                                touch_started = True
                                saw_multitouch = len(points) >= 2
                                start_y = y
                                start_x = x
                                start_scroll = station_scroll
                                if contains(GEAR_BOX, x, y):
                                    gesture = "gear"
                                elif not picker_open and contains(ZOOM_PLUS_BOX, x, y):
                                    gesture = "zoom_plus"
                                elif not picker_open and contains(ZOOM_MINUS_BOX, x, y):
                                    gesture = "zoom_minus"
                                elif picker_open and contains(PICKER_BOX, x, y):
                                    gesture = "picker"
                                elif not picker_open and is_waterfall_tune_touch(x, y):
                                    gesture = "waterfall"
                                    touch_in_waterfall = True
                                    start_freq = state.get_freq()
                                    start_span = state.get_span()
                                    candidate_freq = start_freq
                                    swipe_started = False
                                else:
                                    gesture = "none"
                            if gesture == "picker":
                                row_h = max(1, (PICKER_BOX[3] - PICKER_BOX[1] - 42) // PICKER_ROWS)
                                row_delta = int(round((start_y - y) / row_h))
                                new_scroll = clamp(start_scroll + row_delta * PICKER_COLS, 0, station_page_max(stations))
                                if new_scroll != station_scroll:
                                    station_scroll = new_scroll
                                    ui_dirty = True
                            elif gesture == "waterfall":
                                last_x = x
                                if not swipe_started and abs(x - start_x) >= args.swipe_start_px:
                                    swipe_started = True
                                if swipe_started:
                                    candidate_freq = bounded_freq(retune_from_drag(start_freq, start_x, x, start_span, args), args)
                                    state.preview_freq(candidate_freq)
                        else:
                            if touch_started and gesture == "gear":
                                moved = max(abs(x - start_x), abs(y - start_y))
                                if moved <= args.tap_px:
                                    picker_open = not picker_open
                                    station_scroll = 0
                                    ui_dirty = True
                            elif touch_started and gesture in ("zoom_plus", "zoom_minus"):
                                moved = max(abs(x - start_x), abs(y - start_y))
                                if moved <= args.tap_px:
                                    zoom = state.get_zoom()
                                    delta = 1 if gesture == "zoom_plus" else -1
                                    new_zoom = clamp(zoom + delta, 0, args.max_pinch_zoom)
                                    if new_zoom != zoom:
                                        state.set_freq_zoom(state.get_freq(), new_zoom)
                                        print(f"zoom {new_zoom} span {zoom_to_span_khz(new_zoom):.1f} kHz", flush=True)
                                    zoom_osd_until = time.monotonic() + args.zoom_osd_seconds
                                    ui_dirty = True
                            elif touch_started and gesture == "picker":
                                moved = max(abs(x - start_x), abs(y - start_y))
                                if moved <= args.tap_px:
                                    idx = station_at(x, y, stations, station_scroll)
                                    if idx is not None:
                                        name, _location, server = stations[idx]
                                        state.set_server(server, zoom=args.station_zoom)
                                        picker_open = False
                                        station_scroll = 0
                                        print(f"station {name}: {server}", flush=True)
                                        ui_dirty = True
                            elif touch_started and gesture == "waterfall":
                                moved = abs((last_x if last_x is not None else x) - start_x)
                                if moved <= args.tap_px:
                                    candidate_freq = bounded_freq(retune_from_tap(x, state.get_freq(), start_span, args), args)
                                    state.set_freq(candidate_freq)
                                    print(f"tuned {candidate_freq:.3f} kHz", flush=True)
                                elif swipe_started:
                                    state.set_freq(candidate_freq)
                                    print(f"tuned {candidate_freq:.3f} kHz", flush=True)
                                else:
                                    state.preview_freq(start_freq)
                            elif touch_started and gesture == "pinch":
                                state.set_freq_zoom(pinch_freq, pinch_zoom_level)
                                print(
                                    f"pinch zoom {pinch_zoom_level} "
                                    f"span {zoom_to_span_khz(pinch_zoom_level):.1f} kHz",
                                    flush=True,
                                )
                            touch_started = False
                            touch_in_waterfall = False
                            gesture = None
                            saw_multitouch = False
                            swipe_started = False
                            start_x = start_freq = last_x = None
                            state.mark_dirty()

            now = time.monotonic()
            advance_smooth_waterfall()
            now = time.monotonic()
            zoom_osd_visible = now < zoom_osd_until
            if (state.needs_render() or ui_dirty or zoom_osd_visible or zoom_osd_was_visible) and now >= next_frame:
                osd_alpha = 0
                if zoom_osd_visible:
                    remaining = zoom_osd_until - now
                    fade_window = min(0.45, max(0.0, args.zoom_osd_seconds * 0.33))
                    if fade_window > 0 and remaining < fade_window:
                        osd_alpha = int(220 * remaining / fade_window)
                    else:
                        osd_alpha = 220
                write_frame(
                    fb_map,
                    render_live_frame(
                        state,
                        last_x if active and touch_in_waterfall else None,
                        picker_open=picker_open,
                        station_scroll=station_scroll,
                        stations=stations,
                        zoom_osd_alpha=osd_alpha,
                    ),
                )
                ui_dirty = False
                zoom_osd_was_visible = zoom_osd_visible
                next_frame = time.monotonic() + min_frame_interval


def main():
    parser = argparse.ArgumentParser(description="Live KiwiSDR waterfall/S-meter display for the 960x320 Pi frontend.")
    parser.add_argument("--server", default="http://kx4az2.proxy.kiwisdr.com:8073")
    parser.add_argument("--event", type=Path, help="input event device, defaults to auto-detected Goodix")
    parser.add_argument("--freq-khz", type=float, default=sdr_ui.DEFAULT_FREQ_KHZ)
    parser.add_argument("--span-khz", type=float, default=sdr_ui.DEFAULT_SPAN_KHZ)
    parser.add_argument("--zoom", type=int, default=13)
    parser.add_argument("--max-pinch-zoom", type=int, default=14)
    parser.add_argument("--station-zoom", type=int, default=13)
    parser.add_argument("--mode", default="usb")
    parser.add_argument("--low-cut", type=int, default=300)
    parser.add_argument("--high-cut", type=int, default=2700)
    parser.add_argument("--wf-speed", type=int, default=4)
    parser.add_argument("--wf-row-pixels", type=int, default=2)
    parser.add_argument("--wf-scroll-fps", type=float, default=24.0)
    parser.add_argument("--wf-floor", type=int, default=142)
    parser.add_argument("--wf-ceil", type=int, default=245)
    parser.add_argument("--wf-auto-levels", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--wf-smeter-fallback", action="store_true")
    parser.add_argument("--smeter-dbm", type=float, default=-95.0)
    parser.add_argument("--min-khz", type=float, default=0.0)
    parser.add_argument("--max-khz", type=float, default=30000.0)
    parser.add_argument("--tap-px", type=int, default=12)
    parser.add_argument("--swipe-start-px", type=int, default=22)
    parser.add_argument("--pinch-step-ratio", type=float, default=1.22)
    parser.add_argument("--two-finger-zoom-step-px", type=int, default=26)
    parser.add_argument("--zoom-osd-seconds", type=float, default=ZOOM_OSD_SECONDS)
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--audio-rate", type=int, default=12000)
    parser.add_argument("--user", default="Codex SDR display")
    parser.add_argument("--invert-x", action="store_true")
    parser.add_argument("--invert-y", action="store_true")
    parser.add_argument("--swap-x-y", action="store_true")
    parser.add_argument("--invert-tune", action="store_true")
    args = parser.parse_args()

    if args.pinch_step_ratio <= 1.02:
        raise SystemExit("--pinch-step-ratio must be greater than 1.02")
    if args.two_finger_zoom_step_px < 8:
        raise SystemExit("--two-finger-zoom-step-px must be at least 8")
    if args.zoom_osd_seconds < 0.2:
        raise SystemExit("--zoom-osd-seconds must be at least 0.2")
    if args.wf_scroll_fps <= 0:
        raise SystemExit("--wf-scroll-fps must be greater than 0")
    args.max_pinch_zoom = clamp(args.max_pinch_zoom, 0, 14)
    args.station_zoom = clamp(args.station_zoom, 0, 14)
    args.freq_khz = bounded_freq(args.freq_khz, args)
    stop_event = threading.Event()
    state = LiveState(args.server, args.freq_khz, args.zoom, args.smeter_dbm)

    threads = [
        threading.Thread(target=waterfall_worker, args=(args, state, stop_event), daemon=True),
        threading.Thread(target=snd_worker, args=(args, state, stop_event), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        display_loop(args, state, stop_event)
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=1.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
