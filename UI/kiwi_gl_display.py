#!/usr/bin/env python3
import argparse
from collections import deque
import errno
import json
import math
import os
import queue
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import re
import html
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from OpenGL import GL

import kiwi_live_display_fb as kiwi
import render_sdr_frontend_mockup as sdr_ui


NATIVE_W = 400
NATIVE_H = 960
LOGICAL_W = 960
LOGICAL_H = 320
ACTIVE_H = 400
VISIBLE_Y_OFFSET = ACTIVE_H - LOGICAL_H
WATERFALL_Y0 = sdr_ui.TOP_H + sdr_ui.RULER_H - 12
WATERFALL_Y1 = 292
WATERFALL_FOCUS_Y0 = sdr_ui.TOP_H
WATERFALL_FOCUS_Y1 = LOGICAL_H
SPECTRUM_H = 70
SPECTRUM_RAISE_Y = 12
SPECTRUM_BINS = 240
SPECTRUM_PEAK_HOLD_SECONDS = 10.0
# A responsive radio meter should rise nearly immediately, settle back more
# gently, and retain a brief, decaying indication of recent peaks.
SMETER_ATTACK_SECONDS = 0.085
SMETER_RELEASE_SECONDS = 0.70
SMETER_PEAK_HOLD_SECONDS = 0.75
SMETER_PEAK_DECAY_DB_PER_SECOND = 16.0
SMETER_READOUT_INTERVAL_SECONDS = 0.30
# Kiwi delivers 512-frame raw packets at 12 kHz. Six packets make a 3072-frame
# (256 ms) PipeWire quantum: enough to cover the observed 107 ms network gap
# while keeping buffer boundaries aligned with the incoming PCM cadence.
PIPEWIRE_AUDIO_LATENCY = "3072"
SMETER_FLOOR_DBM = -121
SMETER_S9_DBM = -73
SMETER_PLUS20_DBM = -53
SMETER_CEILING_DBM = -33
# S1–S9 remains the main range, while the progressively compressed upper
# range gives +20/+40 enough visual and label space at 400×960.
SMETER_S1_TO_S9_SEGMENTS = 22
SMETER_S9_TO_PLUS20_SEGMENTS = 6
SMETER_PLUS20_TO_PLUS40_SEGMENTS = 8
# A real waterfall line normally arrives in roughly one second. Four seconds
# leaves room for a slow receiver without treating an open idle socket as live.
WATERFALL_STARTUP_TIMEOUT_SECONDS = 4.0
BOTTOM_RULER_H = 30
BOTTOM_STATUS_H = 28
WF_TEX_W = 960
WF_TEX_H = 256
DISPLAY_ORIENTATION = "flipped"
ZOOM_MINUS_BOX = (24, 197, 96, 257)
ZOOM_PLUS_BOX = (168, 197, 240, 257)
ZOOM_GROUP_BOX = (16, 194, 248, 260)
FILTER_TOGGLE_BOX = (740, 190, 828, 262)
SPECTRUM_TOGGLE_BOX = (850, 190, 938, 262)
VIEW_GROUP_BOX = (742, 188, 946, 264)
HOME_BOX = (15, 8, 87, 66)
RADIO_SETUP_BOX = (530, 12, 590, 52)
RADIO_PANEL_BOX = (12, 72, 948, 282)
KIWI_MODE_PAGES = (
    ("STANDARD", ("AM", "AMN", "AMW", "USB", "LSB", "USN", "LSN", "CW", "CWN", "NBFM")),
    ("SPECIAL", ("NNFM", "DRM", "IQ", "SAM", "SAU", "SAL", "SAS", "QAM")),
)
RADIO_MODE_BOXES = (
    (32, 118, 205, 158),
    (217, 118, 390, 158),
    (402, 118, 575, 158),
    (587, 118, 760, 158),
    (772, 118, 945, 158),
    (32, 166, 205, 206),
    (217, 166, 390, 206),
    (402, 166, 575, 206),
    (587, 166, 760, 206),
    (772, 166, 945, 206),
)
RADIO_MODE_PREV_BOX = (760, 78, 812, 108)
RADIO_MODE_NEXT_BOX = (880, 78, 932, 108)
RADIO_DIGITAL_OPTIONS = (
    ("DIG", (32, 232, 172, 274)),
    ("IQ", (184, 232, 324, 274)),
)
RADIO_STEP_OPTIONS = (
    (10, (474, 232, 576, 274)),
    (100, (588, 232, 690, 274)),
    (1000, (702, 232, 804, 274)),
    (5000, (816, 232, 918, 274)),
)
DISPLAY_PANEL_BOX = (12, 72, 948, 282)
DISPLAY_SPECTRUM_BOX = (510, 82, 736, 120)
DISPLAY_AUTO_BOX = (754, 82, 924, 120)
DISPLAY_FLOOR_MINUS_BOX = (150, 130, 222, 180)
DISPLAY_FLOOR_PLUS_BOX = (330, 130, 402, 180)
DISPLAY_CEIL_MINUS_BOX = (578, 130, 650, 180)
DISPLAY_CEIL_PLUS_BOX = (758, 130, 830, 180)
DISPLAY_RATE_BOXES = (
    (1, (126, 220, 238, 270), "SLOW"),
    (4, (250, 220, 362, 270), "MED"),
    (8, (374, 220, 486, 270), "FAST"),
)
DISPLAY_PALETTE_BOXES = (
    ("kiwi", (650, 220, 772, 270), "KIWI"),
    ("ice", (784, 220, 906, 270), "ICE"),
)
# Filter editing is intentionally a large, temporary workspace. Its slider
# and bottom controls have independent touch zones to avoid accidental edits.
FILTER_PANEL_BOX = (12, 72, 948, 288)
FILTER_EDIT_BOX = (42, 116, 918, 214)
FILTER_WIDTH_MINUS_BOX = (42, 230, 190, 280)
FILTER_WIDTH_LABEL_BOX = (208, 230, 752, 280)
FILTER_WIDTH_PLUS_BOX = (770, 230, 918, 280)
FILTER_HANDLE_TOUCH_PX = 34
FILTER_LIMIT_HZ = 12000
FILTER_SNAP_HZ = 50
FILTER_FINE_WIDTH_STEP_HZ = 100
FILTER_WIDTH_PRESETS = (
    ("CW", 500),
    ("VOICE NARROW", 1200),
    ("VOICE", 2400),
    ("VOICE WIDE", 3000),
    ("WIDE 6k", 6000),
    ("WIDE 9k", 9000),
    ("KIWI MAX", 12000),
)
AUDIO_PANEL_BOX = (12, 72, 948, 288)
AUDIO_VOLUME_BOX = (42, 108, 918, 166)
AUDIO_SQUELCH_BOX = (42, 190, 380, 266)
AUDIO_FILTER_BOX = (400, 190, 918, 266)
GEAR_BOX = (892, 228, 958, 294)
MENU_BOX = (12, 202, 948, 282)
MENU_CLOSE_BOX = (0, 0, 0, 0)
MENU_VISIBLE_ITEMS = 5
MENU_ITEMS = (
    ("rx", "RX"),
    ("audio", "AUDIO"),
    ("radio", "RADIO"),
    ("display", "DISP"),
    ("decode", "DEC"),
    ("network", "NET"),
    ("about", "INFO"),
)
WATERFALL_TUNE_X0 = 88
WATERFALL_TUNE_X1 = kiwi.WATERFALL_TUNE_X1
PICKER_BOX = (0, 0, 790, LOGICAL_H)
PICKER_COLS = 1
PICKER_ROWS = 5
PICKER_SEARCH_BOX = (806, 20, 948, 86)
PICKER_SORT_LOCATION_BOX = (806, 98, 948, 164)
PICKER_SORT_NAME_BOX = (806, 176, 948, 242)
PICKER_EXIT_BOX = (806, 254, 948, 320)
SEARCH_CASE_BOX = (608, 8, 662, 64)
SEARCH_MODE_BOX = (674, 8, 736, 64)
SEARCH_EXIT_BOX = (748, 8, 946, 64)
SEARCH_LEFT_EXIT_BOX = (18, 306, 111, 376)
SEARCH_KEY_ROWS = (
    ("QWERTYUIOP", 18, 78, 93),
    ("ASDFGHJKL<", 18, 154, 93),
    ("ZXCVBNM~~>", 18, 230, 93),
)
SEARCH_NUMERIC_KEY_ROWS = (
    ("1234567890", 18, 78, 93),
    ("@#$_&-+<?.", 18, 154, 93),
    ("!%*=/()~~>", 18, 230, 93),
)
PUBLIC_DIRECTORY_URL = "http://kiwisdr.com/public/"
PUBLIC_DIRECTORY_CACHE = Path.home() / ".local/state/kiwi-gl-public-directory.json"
STATION_HEALTH_CACHE = Path.home() / ".local/state/kiwi-gl-station-health.json"
station_health_write_lock = threading.Lock()


def persist_live_station_health(server, stream, available):
    """Reflect a confirmed live stream transition in the station-list cache.

    The background scanner is deliberately slow and a station can change between
    scans.  A real frame or a live stream failure is stronger, immediate evidence
    for the station the user just selected.  Keep audio and waterfall independent.
    """
    try:
        with station_health_write_lock:
            try:
                health = json.loads(STATION_HEALTH_CACHE.read_text())
            except (OSError, ValueError, TypeError):
                health = {"cursor": 0, "stations": {}}
            stations = health.setdefault("stations", {})
            entry = stations.setdefault(server, {})
            if entry.get(stream) is available:
                return
            entry[stream] = available
            entry["status"] = "ok" if entry.get("audio") or entry.get("waterfall") else "failed"
            entry["checked"] = int(time.time())
            STATION_HEALTH_CACHE.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATION_HEALTH_CACHE.with_suffix(".live.tmp")
            temporary.write_text(json.dumps(health, separators=(",", ":")))
            os.replace(temporary, STATION_HEALTH_CACHE)
    except OSError as exc:
        print(f"gl health cache update failed: {exc}", flush=True)


def parse_public_directory(page):
    """Extract active receiver entries from the official public directory HTML."""
    stations = []
    seen = set()
    entry_re = re.compile(r"<div class='cl-entry.*?(?=<div class='cl-entry|</body>)", re.S)
    for entry in entry_re.findall(page):
        if not re.search(r"<!--\s*status=active\s*-->", entry) or re.search(r"<!--\s*offline=yes\s*-->", entry):
            continue
        link = re.search(r"<a href='(http://[^']+)'", entry)
        label = re.search(r"<div class='cl-name'>(.*?)</div>", entry, re.S)
        location = re.search(r"<!--\s*loc=(.*?)\s*-->", entry, re.S)
        if not link or not label:
            continue
        server = html.unescape(link.group(1)).strip()
        if server in seen:
            continue
        seen.add(server)
        name = re.sub(r"<[^>]+>", "", html.unescape(label.group(1))).strip()
        loc = html.unescape(location.group(1)).strip() if location else "Public KiwiSDR"
        if name:
            used, total = parse_listener_capacity(entry)
            stations.append((name, loc, server, used, total))
    return stations


def parse_listener_capacity(entry):
    """Return directory-reported listener use and capacity when available.

    The public directory has used several HTML/comment formats over time. Keep
    the parser deliberately permissive and leave either value unknown instead
    of guessing when a directory revision omits it.
    """
    text = html.unescape(re.sub(r"<[^>]+>", " ", entry))
    metadata = {
        key.casefold().replace("-", "_"): value.strip()
        for key, value in re.findall(r"<!--\s*([\w-]+)\s*=\s*([^>]*?)\s*-->", entry, re.S)
    }

    def value_for(*keys):
        for key in keys:
            value = metadata.get(key)
            if value is not None:
                match = re.search(r"\d+", value)
                if match:
                    return int(match.group())
        return None

    used = value_for("users", "listeners", "connections", "active_users", "active_listeners", "used")
    total = value_for(
        "users_max",
        "listeners_max",
        "connections_max",
        "max_users",
        "max_listeners",
        "max_connections",
        "capacity",
        "channels",
        "max_channels",
        "total",
    )
    if used is not None and total is not None:
        return used, total

    # Some directory revisions expose a compact visible value rather than
    # separate comment fields, e.g. "Listeners: 3/4".
    match = re.search(
        r"(?:listeners?|users?|connections?|channels?)\s*[:=]?\s*(\d+)\s*(?:/|of)\s*(\d+)",
        text,
        re.I,
    )
    return (int(match.group(1)), int(match.group(2))) if match else (used, total)


def normalize_station(item):
    """Make older three-field directory caches compatible with capacity rows."""
    if not isinstance(item, (list, tuple)) or len(item) < 3:
        return None
    name, location, server = item[:3]
    used = total = None
    if len(item) >= 5:
        try:
            used = int(item[3]) if item[3] is not None else None
            total = int(item[4]) if item[4] is not None else None
        except (TypeError, ValueError):
            pass
    return name, location, server, used, total


def load_public_stations():
    """Fetch the official live list over HTTP, falling back to its saved copy."""
    cached = []
    try:
        cached = [station for item in json.loads(PUBLIC_DIRECTORY_CACHE.read_text()) if (station := normalize_station(item))]
    except (OSError, ValueError, TypeError):
        pass
    try:
        # The directory returns the full listing to an ordinary HTTP client.
        # Its browser-only authentication marker instead yields an empty
        # response here, so retain the normal request and validate its output.
        request = Request(PUBLIC_DIRECTORY_URL, headers={"User-Agent": "KiwiTouch/1.0"})
        with urlopen(request, timeout=15) as response:
            stations = parse_public_directory(response.read().decode("utf-8", "replace"))
        if len(stations) >= 20:
            PUBLIC_DIRECTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            PUBLIC_DIRECTORY_CACHE.write_text(json.dumps(stations))
            return stations
    except OSError:
        pass
    return cached if cached else kiwi.STATIONS


STATIONS = load_public_stations()


def filtered_stations(stations, query, sort_mode):
    terms = query.casefold().split()
    def matches(station):
        name, location, server = station[:3]
        haystack = f"{name} {location} {urlparse(server).hostname or server}".casefold()
        return all(term in haystack for term in terms)
    filtered = [station for station in stations if matches(station)]
    key = (lambda station: (station[1].casefold(), station[0].casefold())) if sort_mode == "location" else (lambda station: (station[0].casefold(), station[1].casefold()))
    return sorted(filtered, key=key)


def bottom_station_title(name, location):
    """Format the selected-station label without directory service boilerplate."""
    stripped = re.sub(
        r"^\s*0\s*[-–—]\s*30\s*mhz\s*(?:kiwi\s*)?sdr\s*[,|]?\s*",
        "",
        name,
        flags=re.I,
    ).strip()
    identifier = stripped.split(",", 1)[0].strip() if stripped else ""
    if not identifier:
        identifier = stripped or name.strip()
    normalized_identifier = re.sub(r"[^\w]+", " ", identifier).casefold().strip()
    normalized_location = re.sub(r"[^\w]+", " ", location).casefold().strip()
    # Many directory entries repeat the owner-supplied address in both name
    # and location. Keep the meaningful identifier once in that case.
    if not normalized_location or normalized_location == normalized_identifier:
        return identifier
    if normalized_location in normalized_identifier or normalized_identifier in normalized_location:
        return identifier if len(identifier) <= len(location) else location
    return f"{identifier}  ·  {location}"


def health_prioritized_stations(stations, station_health, sort_mode):
    now = time.time()
    def health_group(station):
        _name, _location, server = station[:3]
        entry = station_health.get(server, {})
        fresh = now - entry.get("checked", 0) <= 86400
        if not fresh:
            return 2
        # Audio availability defines an active receiver. Within a matching
        # audio state, prefer an available waterfall for the browsing view.
        audio_active = entry.get("audio") is True
        waterfall_active = entry.get("waterfall") is True
        if audio_active and waterfall_active:
            return 0
        if audio_active:
            return 1
        if waterfall_active:
            return 2
        return 3

    # `stations` has already been ordered by the chosen Location/Name sort.
    # Keep that exact, predictable order inside each availability group.
    return [station for _index, station in sorted(enumerate(stations), key=lambda item: (health_group(item[1]), item[0]))]


def keyboard_rows(mode):
    if mode == "numeric":
        return SEARCH_NUMERIC_KEY_ROWS
    if mode == "lower":
        return tuple((keys.lower(), x0, y0, key_w) for keys, x0, y0, key_w in SEARCH_KEY_ROWS)
    return SEARCH_KEY_ROWS


def search_key_at(x, y, mode):
    for keys, x0, y0, key_w in keyboard_rows(mode):
        if y0 <= y < y0 + 70 and x0 <= x < x0 + len(keys) * key_w:
            key = keys[min(len(keys) - 1, int((x - x0) // key_w))]
            if key == "<":
                return "BACK"
            if key == ">":
                return "ENTER"
            return " " if key == "~" else key
    return None


ZOOM_OSD_SECONDS = 1.4
CONTROL_QUIET_SECONDS = 5.0
CONTROL_FADE_SECONDS = 0.65


def logical_to_native(x, y):
    if DISPLAY_ORIENTATION == "normal":
        return ACTIVE_H - y, x
    return y + VISIBLE_Y_OFFSET, NATIVE_H - x


def set_display_orientation(orientation):
    global DISPLAY_ORIENTATION
    DISPLAY_ORIENTATION = orientation


def rgba(color):
    return tuple(channel / 255.0 for channel in color)


def clamp(value, low, high):
    return max(low, min(high, value))


def ease_out_cubic(t):
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


def contains(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def is_waterfall_tune_touch(x, y):
    if not (WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1):
        return False
    return not contains(ZOOM_GROUP_BOX, x, y) and not contains(VIEW_GROUP_BOX, x, y)


def is_waterfall_band_touch(x, y):
    return WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1


def swipe_effective_sensitivity(speed_px_s, args):
    speed = abs(speed_px_s)
    # Normal tuning is positional: the visible frequency and ruler track the
    # finger at a constant rate. Acceleration belongs only to an actual sweep,
    # not to the start of a careful drag.
    if speed <= args.swipe_fast_px_s:
        return args.swipe_slow_sensitivity
    # Keep acceleration progressive after normal travel speed instead of
    # jumping from the direct mapping to a fast multiplier at one pixel.
    fast_ramp_end = args.swipe_fast_px_s * 1.8
    blend = (speed - args.swipe_fast_px_s) / (fast_ramp_end - args.swipe_fast_px_s)
    return args.swipe_slow_sensitivity + (args.swipe_fast_sensitivity - args.swipe_slow_sensitivity) * clamp(blend, 0.0, 1.0)


def retune_from_drag(start_freq, start_x, x, span_khz, invert_tune=False, sensitivity=1.0):
    hz_per_px = span_khz * 1000 / LOGICAL_W
    direction = 1 if invert_tune else -1
    return start_freq + direction * (x - start_x) * hz_per_px * sensitivity / 1000


def retune_delta_from_drag(delta_px, span_khz, invert_tune=False, sensitivity=1.0):
    hz_per_px = span_khz * 1000 / LOGICAL_W
    direction = 1 if invert_tune else -1
    return direction * delta_px * hz_per_px * sensitivity / 1000


def retune_from_tap(x, freq_khz, span_khz):
    hz_per_px = span_khz * 1000 / LOGICAL_W
    return freq_khz + (x - LOGICAL_W / 2) * hz_per_px / 1000


def snap_frequency_khz(freq_khz, step_hz):
    """Return a receiver frequency aligned to the visible tuning step."""
    step_hz = max(1, int(step_hz))
    return round(freq_khz * 1000 / step_hz) * step_hz / 1000


def waterfall_mapper(palette):
    if palette == "kiwi":
        return kiwi.make_waterfall_mapper()

    r_lut, g_lut, b_lut = [], [], []
    for value in range(256):
        t = value / 255.0
        r_lut.append(int(14 + 76 * t))
        g_lut.append(int(22 + 186 * t))
        b_lut.append(int(46 + 209 * t))
    return r_lut, g_lut, b_lut


def load_remembered_view(path):
    try:
        saved = json.loads(path.read_text())
        server = saved.get("server")
        parsed = urlparse(server)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            view = {"server": server}
            freq_khz = saved.get("freq_khz")
            if isinstance(freq_khz, (int, float)) and 0.0 <= freq_khz <= 30000.0:
                view["freq_khz"] = float(freq_khz)
            zoom = saved.get("zoom")
            if isinstance(zoom, int) and 0 <= zoom <= 14:
                view["zoom"] = zoom
            return view
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_remembered_view(path, server, freq_khz, zoom):
    parsed = urlparse(server)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        saved = {
            "freq_khz": round(float(freq_khz), 3),
            "server": server,
            "zoom": clamp(int(zoom), 0, 14),
        }
        temporary.write_text(json.dumps(saved, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except OSError as exc:
        print(f"gl receiver state save failed: {exc}", flush=True)


class SharedState:
    def __init__(
        self,
        server,
        freq_khz,
        zoom,
        smeter_dbm,
        wf_floor,
        wf_ceil,
        wf_speed,
        radio_mode,
        spectrum_enabled,
    ):
        self.lock = threading.Lock()
        self.server = server
        self.freq_khz = freq_khz
        self.zoom = clamp(int(zoom), 0, 14)
        self.smeter_dbm = smeter_dbm
        self.smeter_peak_dbm = smeter_dbm
        self.smeter_source = "wf"
        self.last_snd_smeter_t = 0.0
        self.last_smeter_update_t = 0.0
        self.smeter_peak_hold_until = 0.0
        self.smeter_peak_last_decay_t = 0.0
        self.view_generation = 0
        self.server_generation = 0
        self.wf_floor = float(wf_floor)
        self.wf_ceil = float(wf_ceil)
        self.wf_speed = int(wf_speed)
        self.wf_auto = True
        self.wf_palette = "kiwi"
        self.wf_generation = 0
        self.radio_mode = radio_mode
        self.low_cut, self.high_cut = kiwi_mode_filter(radio_mode)
        self.radio_generation = 0
        # These map directly to Kiwi's existing SND `SET squelch` command.
        self.squelch_enabled = False
        self.audio_generation = 0
        self.spectrum_enabled = bool(spectrum_enabled)
        self.spectrum_values = ()
        self.spectrum_peak_values = ()
        self.spectrum_peak_history = deque()
        # The remembered receiver also has a real connection delay at launch;
        # show the same concise feedback as a newly selected station.
        self.connection_announce = True
        self.connection_status = "connecting"
        self.connection_status_until = 0.0
        self.connection_failures = 0
        self.connection_streams = {"audio": False, "waterfall": False}
        self.connection_stream_failures = {"audio": 0, "waterfall": 0}

    def snapshot(self):
        with self.lock:
            return self.server, self.freq_khz, self.zoom, self.smeter_dbm, self.view_generation, self.server_generation

    def set_view(self, freq_khz=None, zoom=None):
        with self.lock:
            if freq_khz is not None:
                self.freq_khz = freq_khz
            if zoom is not None:
                self.zoom = clamp(int(zoom), 0, 14)
            self.spectrum_peak_values = ()
            self.spectrum_peak_history.clear()
            self.view_generation += 1
            return self.freq_khz, self.zoom, self.view_generation

    def set_server(self, server, zoom=None):
        with self.lock:
            self.server = server
            if zoom is not None:
                self.zoom = clamp(int(zoom), 0, 14)
            self.smeter_dbm = -110.0
            self.smeter_peak_dbm = -110.0
            self.smeter_source = "none"
            self.last_snd_smeter_t = 0.0
            self.last_smeter_update_t = 0.0
            self.smeter_peak_hold_until = 0.0
            self.smeter_peak_last_decay_t = 0.0
            self.spectrum_values = tuple(0.0 for _ in range(SPECTRUM_BINS))
            self.spectrum_peak_values = tuple(0.0 for _ in range(SPECTRUM_BINS))
            self.spectrum_peak_history.clear()
            self.view_generation += 1
            self.server_generation += 1
            self.connection_announce = True
            self.connection_status = "connecting"
            self.connection_status_until = 0.0
            self.connection_failures = 0
            self.connection_streams = {"audio": False, "waterfall": False}
            self.connection_stream_failures = {"audio": 0, "waterfall": 0}
            return self.server, self.freq_khz, self.zoom, self.view_generation, self.server_generation

    def connection_attempt(self, generation, stream):
        with self.lock:
            if not self.connection_announce or generation != self.server_generation:
                return
            if self.connection_streams.get("audio") or self.connection_streams.get("waterfall"):
                return
            if self.connection_failures >= 3:
                self.connection_status = "failed"
            elif self.connection_failures:
                self.connection_status = "retrying"
            else:
                self.connection_status = "connecting"

    def connection_ready(self, generation, stream):
        with self.lock:
            if not self.connection_announce or generation != self.server_generation:
                return False
            was_ready = self.connection_streams.get(stream, False)
            self.connection_streams[stream] = True
            self.connection_stream_failures[stream] = 0
            self.connection_failures = 0
            if not was_ready:
                self.connection_status = "connected"
                self.connection_status_until = time.monotonic() + 2.6
                return True
            return False

    def connection_failed(self, generation, stream):
        with self.lock:
            if not self.connection_announce or generation != self.server_generation:
                return False
            self.connection_streams[stream] = False
            self.connection_stream_failures[stream] = self.connection_stream_failures.get(stream, 0) + 1
            if self.connection_streams.get("audio"):
                self.connection_status = "no_waterfall" if stream == "waterfall" else "retrying"
                self.connection_status_until = 0.0
                return True
            if self.connection_streams.get("waterfall"):
                self.connection_status = "waterfall_audio_retry" if stream == "audio" else "retrying"
                self.connection_status_until = 0.0
                return True
            self.connection_failures += 1
            self.connection_status = "failed" if self.connection_failures >= 3 else "retrying"
            self.connection_status_until = 0.0
            return True

    def connection_snapshot(self):
        with self.lock:
            if not self.connection_announce or self.connection_status is None:
                return None
            if self.connection_status == "connected" and time.monotonic() >= self.connection_status_until:
                return None
            return self.connection_status

    def waterfall_snapshot(self):
        with self.lock:
            return self.wf_floor, self.wf_ceil, self.wf_speed, self.wf_auto, self.wf_palette, self.wf_generation

    def set_waterfall(self, floor=None, ceil=None, speed=None, auto=None, palette=None):
        with self.lock:
            next_floor = self.wf_floor if floor is None else clamp(float(floor), 40.0, 220.0)
            next_ceil = self.wf_ceil if ceil is None else clamp(float(ceil), next_floor + 30.0, 255.0)
            self.wf_floor = min(next_floor, next_ceil - 30.0)
            self.wf_ceil = next_ceil
            if speed is not None:
                self.wf_speed = clamp(int(speed), 1, 8)
            if auto is not None:
                self.wf_auto = bool(auto)
            if palette is not None:
                self.wf_palette = palette if palette in ("kiwi", "ice") else "kiwi"
            self.wf_generation += 1
            return self.wf_floor, self.wf_ceil, self.wf_speed, self.wf_auto, self.wf_palette, self.wf_generation

    def radio_snapshot(self):
        with self.lock:
            return self.radio_mode, self.low_cut, self.high_cut, self.radio_generation

    def set_radio_mode(self, radio_mode):
        with self.lock:
            self.radio_mode = radio_mode.lower()
            self.low_cut, self.high_cut = kiwi_mode_filter(self.radio_mode)
            self.radio_generation += 1
            return self.radio_mode, self.low_cut, self.high_cut, self.radio_generation

    def audio_snapshot(self):
        with self.lock:
            return self.squelch_enabled, self.audio_generation

    def set_squelch(self, enabled):
        with self.lock:
            enabled = bool(enabled)
            if enabled != self.squelch_enabled:
                self.squelch_enabled = enabled
                self.audio_generation += 1
            return self.squelch_enabled, self.audio_generation

    def set_filter(self, low_cut=None, high_cut=None):
        with self.lock:
            low = self.low_cut if low_cut is None else int(round(low_cut / FILTER_SNAP_HZ) * FILTER_SNAP_HZ)
            high = self.high_cut if high_cut is None else int(round(high_cut / FILTER_SNAP_HZ) * FILTER_SNAP_HZ)
            if low_cut is not None and high_cut is None:
                low = clamp(low, -FILTER_LIMIT_HZ, self.high_cut - FILTER_SNAP_HZ)
            elif high_cut is not None and low_cut is None:
                high = clamp(high, self.low_cut + FILTER_SNAP_HZ, FILTER_LIMIT_HZ)
            else:
                low = clamp(low, -FILTER_LIMIT_HZ, FILTER_LIMIT_HZ - FILTER_SNAP_HZ)
                high = clamp(high, low + FILTER_SNAP_HZ, FILTER_LIMIT_HZ)
            if (low, high) != (self.low_cut, self.high_cut):
                self.low_cut, self.high_cut = low, high
                self.radio_generation += 1
            return self.low_cut, self.high_cut, self.radio_generation

    def _decay_smeter_peak(self, now):
        if self.smeter_peak_dbm <= self.smeter_dbm:
            self.smeter_peak_dbm = self.smeter_dbm
            return
        if now <= self.smeter_peak_hold_until:
            return
        started = max(self.smeter_peak_hold_until, self.smeter_peak_last_decay_t)
        elapsed = max(0.0, now - started)
        if elapsed:
            self.smeter_peak_dbm = max(
                self.smeter_dbm,
                self.smeter_peak_dbm - SMETER_PEAK_DECAY_DB_PER_SECOND * elapsed,
            )
        self.smeter_peak_last_decay_t = now

    def set_smeter(self, smeter_dbm, source="wf"):
        with self.lock:
            now = time.monotonic()
            if source == "wf" and now - self.last_snd_smeter_t < 2.0:
                return
            if source == "snd":
                self.last_snd_smeter_t = now
            elapsed = min(0.25, max(0.0, now - self.last_smeter_update_t))
            time_constant = SMETER_ATTACK_SECONDS if smeter_dbm >= self.smeter_dbm else SMETER_RELEASE_SECONDS
            blend = 1.0 - math.exp(-elapsed / time_constant) if elapsed else 0.0
            self.smeter_dbm += (smeter_dbm - self.smeter_dbm) * blend
            self.last_smeter_update_t = now
            self.smeter_source = source
            if self.smeter_dbm >= self.smeter_peak_dbm:
                self.smeter_peak_dbm = self.smeter_dbm
                self.smeter_peak_hold_until = now + SMETER_PEAK_HOLD_SECONDS
                self.smeter_peak_last_decay_t = now
            else:
                self._decay_smeter_peak(now)

    def smeter_snapshot(self):
        with self.lock:
            self._decay_smeter_peak(time.monotonic())
            return self.smeter_dbm, self.smeter_peak_dbm

    def spectrum_snapshot(self):
        with self.lock:
            return self.spectrum_enabled, self.spectrum_values, self.spectrum_peak_values

    def set_spectrum_enabled(self, enabled):
        with self.lock:
            self.spectrum_enabled = bool(enabled)
            return self.spectrum_enabled

    def update_spectrum(self, samples, floor, ceiling):
        if not samples:
            return
        scale = 1.0 / max(1.0, ceiling - floor)
        values = []
        for index in range(SPECTRUM_BINS):
            start = index * len(samples) // SPECTRUM_BINS
            end = max(start + 1, (index + 1) * len(samples) // SPECTRUM_BINS)
            peak = max(samples[start:end])
            values.append(clamp((peak - floor) * scale, 0.0, 1.0))
        with self.lock:
            if len(self.spectrum_values) == len(values):
                self.spectrum_values = tuple(
                    old * 0.56 + new * 0.44 for old, new in zip(self.spectrum_values, values)
                )
            else:
                self.spectrum_values = tuple(values)
            # Icom's default Max Hold mode is a 10-second peak window, not a
            # gradual decay. Keep the recent sweep maxima, then draw their
            # per-bin envelope behind the live trace.
            now = time.monotonic()
            self.spectrum_peak_history.append((now, tuple(values)))
            cutoff = now - SPECTRUM_PEAK_HOLD_SECONDS
            while self.spectrum_peak_history and self.spectrum_peak_history[0][0] < cutoff:
                self.spectrum_peak_history.popleft()
            self.spectrum_peak_values = tuple(
                max(frame[index] for _timestamp, frame in self.spectrum_peak_history)
                for index in range(len(values))
            )


class TextCache:
    def __init__(self):
        pygame.font.init()
        self.cache = {}

    def font(self, size, bold=False, mono=False, family=None):
        key = ("font", size, bold, mono, family)
        font = self.cache.get(key)
        if font is None:
            names = [family] if family else (["DejaVu Sans Mono", "monospace"] if mono else ["DejaVu Sans", "sans"])
            font = pygame.font.SysFont(names, size, bold=bold)
            self.cache[key] = font
        return font

    def texture(self, text, size, color, bold=False, mono=False, family=None):
        key = ("text", text, size, color, bold, mono, family)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        surface = self.font(size, bold=bold, mono=mono, family=family).render(text, True, color)
        surface = surface.convert_alpha()
        width, height = surface.get_size()
        data = pygame.image.tostring(surface, "RGBA", False)
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        cached = tex, width, height
        self.cache[key] = cached
        return cached

    def surface_texture(self, key, surface):
        cache_key = ("surface", key)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        surface = surface.convert_alpha()
        width, height = surface.get_size()
        data = pygame.image.tostring(surface, "RGBA", False)
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        cached = tex, width, height
        self.cache[cache_key] = cached
        return cached


def setup_gl():
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    screen = pygame.display.set_mode((NATIVE_W, NATIVE_H), pygame.OPENGL | pygame.FULLSCREEN)
    GL.glViewport(0, 0, NATIVE_W, NATIVE_H)
    GL.glMatrixMode(GL.GL_PROJECTION)
    GL.glLoadIdentity()
    GL.glOrtho(0, NATIVE_W, NATIVE_H, 0, -1, 1)
    GL.glMatrixMode(GL.GL_MODELVIEW)
    GL.glLoadIdentity()
    GL.glDisable(GL.GL_DEPTH_TEST)
    GL.glEnable(GL.GL_BLEND)
    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    GL.glEnable(GL.GL_TEXTURE_2D)
    return screen


def draw_logical_rect(x0, y0, x1, y1, color):
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    points = (logical_to_native(x0, y0), logical_to_native(x1, y0), logical_to_native(x1, y1), logical_to_native(x0, y1))
    GL.glBegin(GL.GL_QUADS)
    for x, y in points:
        GL.glVertex2f(x, y)
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_logical_line(x0, y0, x1, y1, color, width=1):
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glLineWidth(width)
    GL.glBegin(GL.GL_LINES)
    GL.glVertex2f(*logical_to_native(x0, y0))
    GL.glVertex2f(*logical_to_native(x1, y1))
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_logical_polyline(points, color, width=1):
    if len(points) < 2:
        return
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glLineWidth(width)
    GL.glBegin(GL.GL_LINE_STRIP)
    for x, y in points:
        GL.glVertex2f(*logical_to_native(x, y))
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_logical_area(points, baseline_y, color):
    if len(points) < 2:
        return
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glBegin(GL.GL_TRIANGLE_STRIP)
    for x, y in points:
        GL.glVertex2f(*logical_to_native(x, baseline_y))
        GL.glVertex2f(*logical_to_native(x, y))
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_text(text_cache, x, y, text, color, size, bold=False, mono=False, anchor="lt", alpha=1.0, family=None):
    tex, width, height = text_cache.texture(text, size, color, bold=bold, mono=mono, family=family)
    if "m" in anchor:
        y -= height / 2
    elif "b" in anchor:
        y -= height
    if "c" in anchor:
        x -= width / 2
    elif "r" in anchor:
        x -= width
    draw_textured_quad(tex, x, y, x + width, y + height, 0, 0, 1, 1, alpha)


def draw_textured_quad(tex, x0, y0, x1, y1, u0, v0, u1, v1, alpha=1.0):
    GL.glEnable(GL.GL_TEXTURE_2D)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glColor4f(1, 1, 1, clamp(alpha, 0.0, 1.0))
    vertices = (
        (x0, y0, u0, v0),
        (x1, y0, u1, v0),
        (x1, y1, u1, v1),
        (x0, y1, u0, v1),
    )
    GL.glBegin(GL.GL_QUADS)
    for x, y, u, v in vertices:
        GL.glTexCoord2f(u, v)
        GL.glVertex2f(*logical_to_native(x, y))
    GL.glEnd()


class WaterfallTexture:
    def __init__(self):
        self.tex = GL.glGenTextures(1)
        self.row = 0
        self.row_center_khz = [None] * WF_TEX_H
        self.row_span_khz = [None] * WF_TEX_H
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            WF_TEX_W,
            WF_TEX_H,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            bytes(WF_TEX_W * WF_TEX_H * 4),
        )

    def clear(self):
        self.row = 0
        self.row_center_khz = [None] * WF_TEX_H
        self.row_span_khz = [None] * WF_TEX_H
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            WF_TEX_W,
            WF_TEX_H,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            bytes(WF_TEX_W * WF_TEX_H * 4),
        )

    def push_line(self, line, center_khz=None, span_khz=None):
        self.row = (self.row - 1) % WF_TEX_H
        self.row_center_khz[self.row] = center_khz
        self.row_span_khz[self.row] = span_khz
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        data = line.convert("RGBA").tobytes("raw", "RGBA")
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, self.row, WF_TEX_W, 1, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)

    def draw(self, x0, y0, x1, y1, center_khz=None, span_khz=None, row_offset=0):
        if center_khz is not None and span_khz is not None:
            self._draw_frequency_aligned(x0, y0, x1, y1, center_khz, span_khz)
            return
        height = int(y1 - y0)
        start_row = (self.row + max(0, int(row_offset))) % WF_TEX_H
        first = min(height, WF_TEX_H - start_row)
        if first > 0:
            self._draw_slice(x0, y0, x1, y0 + first, start_row, start_row + first)
        remaining = height - first
        if remaining > 0:
            self._draw_slice(x0, y0 + first, x1, y1, 0, remaining)

    def _draw_slice(self, x0, y0, x1, y1, tex_y0, tex_y1):
        v0 = tex_y0 / WF_TEX_H
        v1 = tex_y1 / WF_TEX_H
        draw_textured_quad(self.tex, x0, y0, x1, y1, 0, v0, 1, v1)

    def _draw_frequency_aligned(self, x0, y0, x1, y1, center_khz, span_khz):
        height = int(y1 - y0)
        hz_per_px = max(0.001, span_khz * 1000 / LOGICAL_W)
        GL.glEnable(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glColor4f(1, 1, 1, 1)
        GL.glBegin(GL.GL_QUADS)
        for logical_y in range(height):
            tex_row = (self.row + logical_y) % WF_TEX_H
            row_center = self.row_center_khz[tex_row]
            if row_center is None:
                row_center = center_khz
            dx = clamp((row_center - center_khz) * 1000 / hz_per_px, -LOGICAL_W, LOGICAL_W)
            ly0 = y0 + logical_y
            ly1 = ly0 + 1
            v0 = tex_row / WF_TEX_H
            v1 = (tex_row + 1) / WF_TEX_H
            vertices = (
                (x0 + dx, ly0, 0, v0),
                (x1 + dx, ly0, 1, v0),
                (x1 + dx, ly1, 1, v1),
                (x0 + dx, ly1, 0, v1),
            )
            for x, y, u, v in vertices:
                GL.glTexCoord2f(u, v)
                GL.glVertex2f(*logical_to_native(x, y))
        GL.glEnd()


def draw_button(text_cache, x, y, w, h, label, active=False):
    fill = (18, 72, 62, 245) if active else (18, 26, 35, 230)
    draw_logical_rect(x, y, x + w, y + h, fill)
    draw_text(text_cache, x + w / 2, y + h / 2, label, (226, 255, 246) if active else (157, 174, 188), 15, True, True, "cm")


def fade_color(color, alpha):
    if len(color) == 3:
        return color + (int(255 * alpha),)
    return color[:3] + (int(color[3] * alpha),)


def draw_control_group_background(text_cache, box, key, separators, alpha=1.0, separator_bottom=13):
    if alpha <= 0:
        return
    x0, y0, x1, y1 = box
    cached = text_cache.cache.get(("surface", key))
    if cached is None:
        w = int(x1 - x0)
        h = int(y1 - y0)
        scale = 3
        hi = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)

        def p(value):
            return int(round(value * scale))

        pill = pygame.Rect(p(1), p(2), p(w - 2), p(h - 4))
        pygame.draw.rect(hi, (112, 125, 132, 52), pill, border_radius=p(24))
        pygame.draw.rect(hi, (224, 234, 237, 45), pill, p(1), border_radius=p(24))
        pygame.draw.line(hi, (255, 255, 255, 24), (p(21), p(8)), (p(w - 21), p(8)), p(1))
        for separator_x in separators:
            pygame.draw.line(hi, (4, 11, 16, 58), (p(separator_x), p(13)), (p(separator_x), p(h - separator_bottom)), p(1))
            pygame.draw.line(hi, (235, 244, 247, 37), (p(separator_x + 1), p(13)), (p(separator_x + 1), p(h - separator_bottom)), p(1))
        surface = pygame.transform.smoothscale(hi, (w, h))
        cached = text_cache.surface_texture(key, surface)
    tex, tex_w, tex_h = cached
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def draw_zoom_button(text_cache, box, label, alpha=1.0):
    if alpha <= 0:
        return
    x0, y0, x1, y1 = box
    key = f"zoom_sign_group_v4_{label}"
    cached = text_cache.cache.get(("surface", key))
    if cached is None:
        w = int(x1 - x0)
        h = int(y1 - y0)
        scale = 3
        hi = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)

        def p(value):
            return int(round(value * scale))

        cx = w / 2
        cy = h / 2
        icon = (244, 250, 252, 222)
        sign_w = 14 if label == "-" else 15
        pygame.draw.line(hi, icon, (p(cx - sign_w), p(cy)), (p(cx + sign_w), p(cy)), p(2.4))
        if label == "+":
            pygame.draw.line(hi, icon, (p(cx), p(cy - sign_w)), (p(cx), p(cy + sign_w)), p(2.4))
        surface = pygame.transform.smoothscale(hi, (w, h))
        cached = text_cache.surface_texture(key, surface)
    tex, tex_w, tex_h = cached
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def draw_spectrum_toggle_button(text_cache, enabled, alpha=1.0):
    if alpha <= 0:
        return
    x0, y0, x1, y1 = SPECTRUM_TOGGLE_BOX
    key = f"spectrum_toggle_v3_{int(enabled)}"
    cached = text_cache.cache.get(("surface", key))
    if cached is None:
        w = int(x1 - x0)
        h = int(y1 - y0)
        scale = 3
        hi = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)

        def p(value):
            return int(round(value * scale))

        color = (218, 223, 225, 234) if enabled else (220, 224, 226, 170)
        fill = (184, 189, 193, 72) if enabled else (220, 224, 226, 36)
        baseline = h / 2 - 1
        points = ((10, baseline), (18, baseline - 5), (27, baseline - 2), (36, baseline - 18), (46, baseline - 7), (56, baseline - 12), (66, baseline))
        pygame.draw.polygon(hi, fill, [(p(x), p(baseline)) for x, _y in points] + [(p(x), p(y)) for x, y in reversed(points)])
        pygame.draw.line(hi, color, (p(9), p(baseline)), (p(67), p(baseline)), p(1.1))
        pygame.draw.lines(hi, color, False, [(p(x), p(y)) for x, y in points], p(1.8))
        label = text_cache.font(16 * scale, bold=True, mono=True).render("SCOPE", True, color[:3])
        hi.blit(label, ((hi.get_width() - label.get_width()) // 2, p(h - 27)))
        surface = pygame.transform.smoothscale(hi, (w, h))
        cached = text_cache.surface_texture(key, surface)
    tex, tex_w, tex_h = cached
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def draw_filter_toggle_button(text_cache, alpha=1.0):
    if alpha <= 0:
        return
    x0, y0, x1, y1 = FILTER_TOGGLE_BOX
    key = "filter_toggle_v3"
    cached = text_cache.cache.get(("surface", key))
    if cached is None:
        w = int(x1 - x0)
        h = int(y1 - y0)
        scale = 3
        hi = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)

        def p(value):
            return int(round(value * scale))

        color = (219, 223, 225, 178)
        dim = (174, 180, 184, 54)
        baseline = h / 2 - 1
        left = w / 2 - 14
        right = w / 2 + 14
        pygame.draw.line(hi, dim, (p(10), p(baseline)), (p(w - 10), p(baseline)), p(1.2))
        pygame.draw.rect(hi, dim, (p(left), p(baseline - 14), p(right - left), p(14)))
        pygame.draw.line(hi, color, (p(left), p(baseline - 18)), (p(left), p(baseline)), p(2.0))
        pygame.draw.line(hi, color, (p(right), p(baseline - 18)), (p(right), p(baseline)), p(2.0))
        pygame.draw.line(hi, (221, 245, 246, 122), (p(w / 2), p(baseline - 20)), (p(w / 2), p(baseline + 2)), p(1.1))
        label = text_cache.font(16 * scale, bold=True, mono=True).render("FILTER", True, color[:3])
        hi.blit(label, ((hi.get_width() - label.get_width()) // 2, p(h - 27)))
        surface = pygame.transform.smoothscale(hi, (w, h))
        cached = text_cache.surface_texture(key, surface)
    tex, tex_w, tex_h = cached
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def draw_gear_button(text_cache):
    x0, y0, x1, y1 = GEAR_BOX
    draw_logical_rect(x0, y0, x1, y1, (3, 9, 14, 58))
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    ring = (206, 238, 242, 128)
    color = (226, 246, 249, 210)
    for ox, oy in ((0, 0), (1, 0), (0, 1)):
        draw_logical_line(x0 + 8 + ox, y0 + 6 + oy, x1 - 8 + ox, y0 + 6 + oy, ring, 1)
        draw_logical_line(x0 + 8 + ox, y1 - 6 + oy, x1 - 8 + ox, y1 - 6 + oy, ring, 1)
        draw_logical_line(x0 + 6 + ox, y0 + 8 + oy, x0 + 6 + ox, y1 - 8 + oy, ring, 1)
        draw_logical_line(x1 - 6 + ox, y0 + 8 + oy, x1 - 6 + ox, y1 - 8 + oy, ring, 1)
    for angle in range(0, 360, 45):
        radians = math.radians(angle)
        r0 = 9 if angle % 90 == 0 else 8
        r1 = 15 if angle % 90 == 0 else 13
        draw_logical_line(
            cx + math.sin(radians) * r0,
            cy - math.cos(radians) * r0,
            cx + math.sin(radians) * r1,
            cy - math.cos(radians) * r1,
            color,
            3,
        )
    for angle0, angle1 in ((0, 50), (70, 140), (160, 230), (250, 340)):
        prev = None
        for angle in range(angle0, angle1 + 1, 10):
            radians = math.radians(angle)
            point = (cx + math.sin(radians) * 10, cy - math.cos(radians) * 10)
            if prev is not None:
                draw_logical_line(prev[0], prev[1], point[0], point[1], color, 2)
            prev = point
    draw_logical_rect(cx - 3, cy - 3, cx + 3, cy + 3, color)


def draw_home_button(text_cache, alpha=1.0):
    if alpha <= 0:
        return
    x0, y0, x1, y1 = HOME_BOX
    w, h, scale = int(x1 - x0), int(y1 - y0), 3
    hi = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)
    def p(value):
        return int(round(value * scale))
    # Material-style Home: large outline, calm boundary, no label or filled tile.
    cx, cy = w / 2, h / 2 + 2
    color = (231, 235, 237, 238)
    roof = [(p(cx - 25), p(cy - 3)), (p(cx), p(cy - 25)), (p(cx + 25), p(cy - 3))]
    pygame.draw.lines(hi, color, False, roof, p(3))
    pygame.draw.line(hi, color, (p(cx - 18), p(cy - 2)), (p(cx - 18), p(cy + 18)), p(3))
    pygame.draw.line(hi, color, (p(cx + 18), p(cy - 2)), (p(cx + 18), p(cy + 18)), p(3))
    pygame.draw.line(hi, color, (p(cx - 18), p(cy + 18)), (p(cx + 18), p(cy + 18)), p(3))
    pygame.draw.line(hi, color, (p(cx - 5), p(cy + 18)), (p(cx - 5), p(cy + 7)), p(3))
    pygame.draw.line(hi, color, (p(cx + 5), p(cy + 18)), (p(cx + 5), p(cy + 7)), p(3))
    surface = pygame.transform.smoothscale(hi, (w, h))
    tex, tex_w, tex_h = text_cache.surface_texture("home_button_v11", surface)
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def draw_radio_setup_pill(text_cache, mode, digital, step_hz):
    x0, y0, x1, y1 = RADIO_SETUP_BOX
    gap = 4
    mid = (y0 + y1) / 2
    pills = ((y0 + 2, mid - gap / 2, mode.upper(), True), (mid + gap / 2, y1 - 2, digital.upper(), digital.upper() not in ("", "OFF", "NONE")))
    for py0, py1, label, active in pills:
        fill = (48, 122, 72, 155) if active else (67, 72, 76, 100)
        edge = (95, 232, 132, 210) if active else (143, 149, 153, 125)
        draw_logical_rect(x0 + 2, py0, x1 - 2, py1, fill)
        draw_logical_line(x0 + 8, py0 + 1, x1 - 8, py0 + 1, edge, 1)
        text_color = (232, 255, 238) if active else (150, 155, 158)
        draw_text(text_cache, (x0 + x1) / 2, (py0 + py1) / 2, label, text_color, 13, True, True, "cm")


def radio_option_at(x, y, mode_page):
    if contains(RADIO_MODE_PREV_BOX, x, y):
        return "mode_page", -1
    if contains(RADIO_MODE_NEXT_BOX, x, y):
        return "mode_page", 1
    _page_label, modes = KIWI_MODE_PAGES[mode_page]
    for mode, box in zip(modes, RADIO_MODE_BOXES):
        if contains(box, x, y):
            return "mode", mode
    for digital, box in RADIO_DIGITAL_OPTIONS:
        if contains(box, x, y):
            return "digital", digital
    for step_hz, box in RADIO_STEP_OPTIONS:
        if contains(box, x, y):
            return "step", step_hz
    return None


def draw_radio_option(text_cache, box, label, active):
    x0, y0, x1, y1 = box
    fill = (32, 87, 89, 220) if active else (18, 29, 38, 184)
    line = (94, 235, 225, 220) if active else (115, 140, 151, 78)
    color = (238, 252, 250) if active else (173, 196, 201)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, line, 1)
    draw_logical_line(x0, y1, x1, y1, line, 1)
    draw_logical_line(x0, y0, x0, y1, line, 1)
    draw_logical_line(x1, y0, x1, y1, line, 1)
    if active:
        draw_logical_line(x0 + 12, y1 - 5, x1 - 12, y1 - 5, (91, 242, 227, 230), 2)
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2, label, color, 16, True, True, "cm")


def draw_radio_setup_panel(text_cache, mode, digital, step_hz, mode_page):
    x0, y0, x1, y1 = RADIO_PANEL_BOX
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 228))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    page_label, modes = KIWI_MODE_PAGES[mode_page]
    draw_text(text_cache, 32, 94, "RADIO", (229, 243, 246), 18, True, True, "lm")
    draw_text(text_cache, 32, 106, page_label, (139, 180, 187), 12, True, True, "lm")
    draw_display_control(text_cache, RADIO_MODE_PREV_BOX, "<", False)
    draw_text(text_cache, 846, 93, f"{mode_page + 1}/{len(KIWI_MODE_PAGES)}", (169, 194, 199), 13, True, True, "cm")
    draw_display_control(text_cache, RADIO_MODE_NEXT_BOX, ">", False)
    draw_text(text_cache, 32, 221, "DIGITAL", (139, 180, 187), 12, True, True, "lm")
    draw_text(text_cache, 354, 221, "STEP", (139, 180, 187), 12, True, True, "lm")
    for option, box in zip(modes, RADIO_MODE_BOXES):
        draw_radio_option(text_cache, box, option, option == mode)
    for option, box in RADIO_DIGITAL_OPTIONS:
        draw_radio_option(text_cache, box, option, option == digital)
    for option, box in RADIO_STEP_OPTIONS:
        label = f"{option // 1000}k" if option >= 1000 else str(option)
        draw_radio_option(text_cache, box, label, option == step_hz)


def display_option_at(x, y):
    if contains(DISPLAY_SPECTRUM_BOX, x, y):
        return "spectrum", None
    if contains(DISPLAY_AUTO_BOX, x, y):
        return "auto", None
    for name, box, delta in (
        ("floor", DISPLAY_FLOOR_MINUS_BOX, -4),
        ("floor", DISPLAY_FLOOR_PLUS_BOX, 4),
        ("ceil", DISPLAY_CEIL_MINUS_BOX, -4),
        ("ceil", DISPLAY_CEIL_PLUS_BOX, 4),
    ):
        if contains(box, x, y):
            return name, delta
    for rate, box, _label in DISPLAY_RATE_BOXES:
        if contains(box, x, y):
            return "rate", rate
    for palette, box, _label in DISPLAY_PALETTE_BOXES:
        if contains(box, x, y):
            return "palette", palette
    return None


def draw_display_control(text_cache, box, label, active=False):
    x0, y0, x1, y1 = box
    fill = (86, 91, 95, 214) if active else (18, 29, 38, 152)
    line = (213, 218, 221, 194) if active else (118, 143, 151, 78)
    color = (236, 239, 241) if active else (177, 199, 204)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, line, 1)
    draw_logical_line(x0, y1, x1, y1, line, 1)
    draw_logical_line(x0, y0, x0, y1, line, 1)
    draw_logical_line(x1, y0, x1, y1, line, 1)
    size = 42 if label in ("-", "+") else 15
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2, label, color, size, True, True, "cm")


def audio_volume_at_x(x):
    x0, _y0, x1, _y1 = AUDIO_VOLUME_BOX
    return clamp((x - x0) / max(1, x1 - x0), 0.0, 1.0)


def draw_audio_panel(text_cache, volume, squelch_enabled, low_cut, high_cut, output_available):
    """Touch-first controls backed by the live PipeWire and Kiwi SND state."""
    x0, y0, x1, y1 = AUDIO_PANEL_BOX
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 234))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    draw_text(text_cache, 36, 92, "AUDIO", (229, 243, 246), 18, True, True, "lm")
    output_label = "USB SPEAKER" if output_available else "OUTPUT UNAVAILABLE"
    output_color = (104, 230, 151) if output_available else (242, 163, 104)
    draw_text(text_cache, 148, 92, output_label, output_color, 13, True, True, "lm")
    # AGC is actively configured in the current Kiwi SND setup; present it as
    # status rather than offering unsupported manual gain semantics.
    draw_text(text_cache, 906, 92, "AGC AUTO", (151, 180, 187), 13, False, True, "rm")

    vx0, vy0, vx1, vy1 = AUDIO_VOLUME_BOX
    level = clamp(volume if volume is not None else 0.0, 0.0, 1.0)
    track_y = (vy0 + vy1) / 2 + 8
    draw_text(text_cache, vx0, vy0 + 4, "SPEAKER VOLUME", (164, 193, 198), 14, True, True, "lt")
    draw_text(text_cache, vx1, vy0 + 4, f"{round(level * 100):.0f}%", (232, 246, 248), 22, True, True, "rt")
    draw_logical_rect(vx0, track_y - 7, vx1, track_y + 7, (22, 35, 43, 230))
    draw_logical_rect(vx0, track_y - 7, vx0 + (vx1 - vx0) * level, track_y + 7, (68, 209, 151, 226))
    knob_x = vx0 + (vx1 - vx0) * level
    draw_logical_rect(knob_x - 8, track_y - 16, knob_x + 8, track_y + 16, (226, 246, 246, 255))

    def panel_button(box, title, detail, active=False):
        bx0, by0, bx1, by1 = box
        fill = (28, 78, 67, 230) if active else (18, 29, 38, 210)
        line = (92, 229, 174, 220) if active else (115, 140, 151, 78)
        draw_logical_rect(bx0, by0, bx1, by1, fill)
        draw_logical_line(bx0, by0, bx1, by0, line, 1)
        draw_logical_line(bx0, by1, bx1, by1, line, 1)
        draw_logical_line(bx0, by0, bx0, by1, line, 1)
        draw_logical_line(bx1, by0, bx1, by1, line, 1)
        draw_text(text_cache, bx0 + 20, by0 + 23, title, (230, 246, 247), 16, True, True, "lm")
        draw_text(text_cache, bx0 + 20, by0 + 51, detail, (112, 223, 169) if active else (153, 185, 191), 13, False, True, "lm")

    panel_button(AUDIO_SQUELCH_BOX, "SQUELCH", "ON" if squelch_enabled else "OFF", squelch_enabled)
    panel_button(AUDIO_FILTER_BOX, "AUDIO FILTER", format_filter_width(high_cut - low_cut), False)


def draw_filter_width_control(text_cache, box, label):
    """Large neutral controls that stay legible over the cool waterfall."""
    x0, y0, x1, y1 = box
    fill = (54, 57, 60, 96)
    line = (183, 188, 192, 156)
    color = (236, 239, 241)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, line, 1)
    draw_logical_line(x0, y1, x1, y1, line, 1)
    draw_logical_line(x0, y0, x0, y1, line, 1)
    draw_logical_line(x1, y0, x1, y1, line, 1)
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2, label, color, 42, True, True, "cm")


def draw_display_setup_panel(text_cache, floor, ceiling, speed, auto, palette, spectrum_enabled):
    x0, y0, x1, y1 = DISPLAY_PANEL_BOX
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 228))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    draw_text(text_cache, 36, 101, "WATERFALL", (229, 243, 246), 18, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_SPECTRUM_BOX, "SPECTRUM", spectrum_enabled)
    draw_display_control(text_cache, DISPLAY_AUTO_BOX, "AUTO SCALE", auto)
    draw_logical_line(32, 120, 928, 120, (149, 171, 177, 56), 1)
    draw_text(text_cache, 36, 155, "FLOOR", (139, 180, 187), 14, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_FLOOR_MINUS_BOX, "-", False)
    draw_text(text_cache, 276, 155, f"{floor:.0f}", (224, 241, 243), 22, True, True, "cm")
    draw_display_control(text_cache, DISPLAY_FLOOR_PLUS_BOX, "+", False)
    draw_text(text_cache, 460, 155, "CEILING", (139, 180, 187), 14, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_CEIL_MINUS_BOX, "-", False)
    draw_text(text_cache, 704, 155, f"{ceiling:.0f}", (224, 241, 243), 22, True, True, "cm")
    draw_display_control(text_cache, DISPLAY_CEIL_PLUS_BOX, "+", False)
    draw_text(text_cache, 36, 202, "RATE", (139, 180, 187), 13, True, True, "lm")
    for rate, box, label in DISPLAY_RATE_BOXES:
        draw_display_control(text_cache, box, label, rate == speed)
    draw_text(text_cache, 548, 202, "PALETTE", (139, 180, 187), 13, True, True, "lm")
    for option, box, label in DISPLAY_PALETTE_BOXES:
        draw_display_control(text_cache, box, label, option == palette)


def format_filter_width(width_hz):
    if width_hz < 1000:
        return f"{width_hz:.0f} Hz"
    return f"{width_hz / 1000:.1f} k"


def filter_preset_index(width_hz):
    for index, (_name, preset_width_hz) in enumerate(FILTER_WIDTH_PRESETS):
        if abs(preset_width_hz - width_hz) <= FILTER_SNAP_HZ / 2:
            return index
    return None


def next_filter_preset(width_hz):
    index = filter_preset_index(width_hz)
    return FILTER_WIDTH_PRESETS[0] if index is None else FILTER_WIDTH_PRESETS[(index + 1) % len(FILTER_WIDTH_PRESETS)]


def fine_filter_width(width_hz, delta):
    return clamp(width_hz + delta * FILTER_FINE_WIDTH_STEP_HZ, FILTER_SNAP_HZ, FILTER_LIMIT_HZ)


def symmetric_filter_bounds(low_cut, high_cut, width_hz):
    half_width = width_hz / 2.0
    center = clamp(
        (low_cut + high_cut) / 2.0,
        -FILTER_LIMIT_HZ + half_width,
        FILTER_LIMIT_HZ - half_width,
    )
    return center - half_width, center + half_width


def format_filter_cut(cut_hz):
    sign = "+" if cut_hz >= 0 else "-"
    return f"{sign}{abs(cut_hz) / 1000:.2f}k"


def filter_x(cut_hz, x0, x1, limit_hz=FILTER_LIMIT_HZ, center_hz=0.0):
    return x0 + (cut_hz - center_hz + limit_hz) / (2 * limit_hz) * (x1 - x0)


def filter_cut_at_x(x, x0, x1, limit_hz=FILTER_LIMIT_HZ, center_hz=0.0):
    fraction = clamp((x - x0) / max(1.0, x1 - x0), 0.0, 1.0)
    return int(round((center_hz + (fraction * 2.0 - 1.0) * limit_hz) / FILTER_SNAP_HZ) * FILTER_SNAP_HZ)


def filter_edit_limit(low_cut, high_cut):
    # Scale the editor around the selected RF center (0 Hz).
    outer_cut = max(abs(low_cut), abs(high_cut), 500.0)
    return int(clamp(math.ceil(outer_cut * 1.25 / 500) * 500, 1500, FILTER_LIMIT_HZ))


def draw_filter_overlay(span_khz, low_cut, high_cut, y0, y1, alpha=1.0):
    if alpha <= 0.01:
        return
    hz_per_px = max(1.0, span_khz * 1000.0 / LOGICAL_W)
    center_x = LOGICAL_W / 2
    low_x = center_x + low_cut / hz_per_px
    high_x = center_x + high_cut / hz_per_px
    raw_left = min(low_x, high_x)
    raw_right = max(low_x, high_x)
    left = clamp(raw_left, 0.0, float(LOGICAL_W))
    right = clamp(raw_right, 0.0, float(LOGICAL_W))
    if right <= left:
        return
    # Cool cyan keeps the passband distinct without warming the waterfall.
    fill = (154, 159, 163, int(42 * alpha))
    edge = (221, 225, 227, int(184 * alpha))
    center = (240, 242, 243, int(108 * alpha))
    if raw_right - raw_left < 10:
        # At wide waterfall spans the real filter can be sub-pixel narrow.
        # Show a compact bracket instead of visually falsifying its width.
        bracket_x = clamp((low_x + high_x) / 2, 6.0, LOGICAL_W - 6.0)
        for edge_x in (bracket_x - 4, bracket_x + 4):
            draw_logical_line(edge_x, y0, edge_x, y1, edge, 1)
            draw_logical_line(edge_x, y0 + 5, bracket_x, y0 + 5, edge, 1)
    else:
        draw_logical_rect(left, y0, right, y1, fill)
        for edge_x, cap_direction in ((low_x, 1), (high_x, -1)):
            clipped_edge_x = clamp(edge_x, 0.0, float(LOGICAL_W))
            draw_logical_line(clipped_edge_x, y0, clipped_edge_x, y1, edge, 1)
            draw_logical_line(
                clipped_edge_x,
                y0 + 5,
                clipped_edge_x + cap_direction * 5,
                y0 + 5,
                edge,
                1,
            )
    if 0 <= center_x <= LOGICAL_W:
        draw_logical_line(center_x, y0, center_x, y1, center, 1)


def draw_filter_setup_panel(text_cache, mode, low_cut, high_cut, custom_width=False):
    x0, y0, x1, y1 = FILTER_PANEL_BOX
    draw_logical_rect(x0, y0, x1, y1, (5, 12, 18, 174))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 132), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 132), 1)
    draw_text(text_cache, 34, y0 + 22, f"FILTER  {mode}", (229, 243, 246), 24, True, True, "lm")
    width_hz = high_cut - low_cut
    draw_text(text_cache, 926, y0 + 22, f"BW {width_hz / 1000:.2f} kHz", (205, 210, 213), 24, True, True, "rm")

    sx0, sy0, sx1, sy1 = FILTER_EDIT_BOX
    view_low_cut, view_high_cut = filter_view_offsets(low_cut, high_cut)
    edit_limit = filter_edit_limit(view_low_cut, view_high_cut)
    carrier_hz = 0.0
    zero_x = filter_x(carrier_hz, sx0, sx1, edit_limit, carrier_hz)
    low_x = filter_x(view_low_cut, sx0, sx1, edit_limit, carrier_hz)
    high_x = filter_x(view_high_cut, sx0, sx1, edit_limit, carrier_hz)
    block_y0 = sy0 + 52
    block_y1 = sy1 - 17
    draw_logical_rect(sx0, sy0, sx1, sy1, (3, 17, 25, 174))
    draw_logical_line(sx0, block_y0, sx1, block_y0, (83, 128, 141, 96), 1)
    draw_logical_line(sx0, block_y1, sx1, block_y1, (83, 128, 141, 96), 1)
    draw_logical_line(zero_x, sy0 + 6, zero_x, sy1 - 6, (185, 220, 224, 150), 2)
    draw_logical_rect(low_x, block_y0, high_x, block_y1, (112, 118, 122, 104))
    draw_logical_line(low_x, block_y0, low_x, block_y1, (207, 213, 216, 255), 3)
    draw_logical_line(high_x, block_y0, high_x, block_y1, (207, 213, 216, 255), 3)
    for handle_x in (low_x, high_x):
        draw_logical_rect(handle_x - 12, block_y0 - 8, handle_x + 12, block_y1 + 8, (166, 172, 176, 188))
        draw_logical_line(handle_x - 4, block_y0 + 5, handle_x - 4, block_y1 - 5, (47, 51, 54, 220), 2)
        draw_logical_line(handle_x + 4, block_y0 + 5, handle_x + 4, block_y1 - 5, (47, 51, 54, 220), 2)
    draw_text(text_cache, (low_x + high_x) / 2, (block_y0 + block_y1) / 2, "PASSBAND", (236, 239, 241), 14, True, True, "cm")
    draw_text(text_cache, sx0 + 8, sy0 + 13, "LEFT EDGE", (202, 208, 211), 13, True, True, "lm")
    draw_text(text_cache, sx1 - 8, sy0 + 13, "RIGHT EDGE", (202, 208, 211), 13, True, True, "rm")
    draw_text(text_cache, sx0 + 8, sy0 + 29, format_filter_cut(view_low_cut), (225, 229, 231), 23, True, True, "lm")
    draw_text(text_cache, sx1 - 8, sy0 + 29, format_filter_cut(view_high_cut), (225, 229, 231), 23, True, True, "rm")
    draw_text(text_cache, zero_x, sy1 - 7, "CARRIER", (152, 181, 187), 12, True, True, "cm")
    preset_index = filter_preset_index(width_hz)
    is_preset = preset_index is not None and not custom_width
    draw_filter_width_control(text_cache, FILTER_WIDTH_MINUS_BOX, "-")
    draw_filter_width_control(text_cache, FILTER_WIDTH_PLUS_BOX, "+")
    label_color = (236, 239, 241) if is_preset else (199, 204, 207)
    label_fill = (86, 91, 95, 104) if is_preset else (54, 58, 62, 78)
    label_line = (190, 196, 199, 172) if is_preset else (143, 149, 153, 126)
    lx0, ly0, lx1, ly1 = FILTER_WIDTH_LABEL_BOX
    draw_logical_rect(lx0, ly0, lx1, ly1, label_fill)
    draw_logical_line(lx0, ly0, lx1, ly0, label_line, 1)
    draw_logical_line(lx0, ly1, lx1, ly1, label_line, 1)
    draw_logical_line(lx0, ly0, lx0, ly1, label_line, 1)
    draw_logical_line(lx1, ly0, lx1, ly1, label_line, 1)
    if is_preset:
        choice_name, choice_width = FILTER_WIDTH_PRESETS[preset_index]
        label = f"{choice_name}  {format_filter_width(choice_width)}"
    else:
        label = f"CUSTOM  {format_filter_width(width_hz)}"
    draw_text(text_cache, (lx0 + lx1) / 2, (ly0 + ly1) / 2, label, label_color, 24, True, True, "cm")


def format_zoom_span(span_khz):
    if span_khz >= 1000:
        return f"{span_khz / 1000:.1f} MHz"
    return f"{span_khz:.1f} kHz"


def draw_zoom_osd(text_cache, zoom, span_khz, alpha):
    alpha = clamp(int(alpha), 0, 255)
    if alpha <= 0:
        return
    x0, y0, x1, y1 = 240, 63, 720, 161
    green = (72, 255, 122, alpha)
    dim = (72, 255, 122, int(alpha * 0.18))
    soft = (72, 255, 122, int(alpha * 0.35))
    draw_logical_rect(x0, y0, x1, y1, (0, 8, 4, int(alpha * 0.42)))
    for offset, line_alpha in ((32, 0.20), (64, 0.12)):
        y = y0 + offset
        draw_logical_line(x0 + 4, y, x1 - 4, y, (72, 255, 122, int(alpha * line_alpha)), 1)
    draw_text(text_cache, x0 + 18, y0 + 22, "ZOOM", green[:3], 28, True, True, "lm")
    draw_text(text_cache, x1 - 18, y0 + 22, format_zoom_span(span_khz), green[:3], 28, True, True, "rm")

    track_x0 = x0 + 24
    track_x1 = x1 - 24
    base_y = y0 + 81
    draw_logical_line(track_x0, base_y, track_x1, base_y, soft, 3)
    bar_w = 17
    for level in range(15):
        x = int(round(track_x0 + (track_x1 - track_x0) * level / 14))
        fill = green if level <= zoom else dim
        h = 36 if level == zoom else 24
        draw_logical_rect(x - bar_w / 2, base_y - h, x + bar_w / 2, base_y - 1, fill)


def station_page_max(stations):
    visible = PICKER_COLS * PICKER_ROWS
    return max(0, len(stations) - visible)


def station_tile(index, scroll):
    visible_index = index - scroll
    if visible_index < 0 or visible_index >= PICKER_COLS * PICKER_ROWS:
        return None
    x0, y0, x1, y1 = PICKER_BOX
    pad = 4
    header_h = 0
    gap = 3
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


def menu_metrics():
    x0, y0, x1, y1 = MENU_BOX
    pad = 4
    gap = 8
    header_h = 0
    item_w = (x1 - x0 - 2 * pad - (MENU_VISIBLE_ITEMS - 1) * gap) / MENU_VISIBLE_ITEMS
    item_h = y1 - y0 - header_h - 2 * pad
    return x0, y0, x1, y1, pad, gap, item_w, item_h, header_h


def menu_max_scroll():
    _x0, _y0, _x1, _y1, _pad, gap, item_w, _item_h, _header_h = menu_metrics()
    overflow = max(0, len(MENU_ITEMS) - MENU_VISIBLE_ITEMS)
    return overflow * (item_w + gap)


def menu_item_box(index, scroll):
    x0, y0, _x1, _y1, pad, gap, item_w, item_h, header_h = menu_metrics()
    left = x0 + pad + index * (item_w + gap) - scroll
    top = y0 + header_h + pad
    return left, top, left + item_w, top + item_h


def menu_at(x, y, scroll):
    if not contains(MENU_BOX, x, y):
        return None
    for idx in range(len(MENU_ITEMS)):
        box = menu_item_box(idx, scroll)
        if contains(box, x, y):
            return idx
    return None


def draw_menu_icon(surface, kind, cx, cy, color, dim):
    if kind == "rx":
        pygame.draw.circle(surface, color, (cx, cy - 2), 13, 3)
        pygame.draw.line(surface, color, (cx, cy + 12), (cx, cy + 28), 3)
        pygame.draw.arc(surface, dim, (cx - 35, cy - 28, 70, 56), math.radians(130), math.radians(230), 3)
        pygame.draw.arc(surface, dim, (cx - 35, cy - 28, 70, 56), math.radians(-50), math.radians(50), 3)
    elif kind == "radio":
        pygame.draw.rect(surface, color, (cx - 27, cy - 17, 54, 36), 3, border_radius=5)
        pygame.draw.line(surface, color, (cx - 17, cy - 24), (cx + 18, cy - 36), 3)
        pygame.draw.circle(surface, dim, (cx + 14, cy + 1), 8, 3)
        pygame.draw.line(surface, dim, (cx - 18, cy - 3), (cx - 2, cy - 3), 3)
        pygame.draw.line(surface, dim, (cx - 18, cy + 8), (cx - 4, cy + 8), 3)
    elif kind == "display":
        for offset, knob_x in ((-16, -8), (0, 15), (16, -18)):
            pygame.draw.line(surface, color, (cx - 28, cy + offset), (cx + 28, cy + offset), 3)
            pygame.draw.circle(surface, dim, (cx + knob_x, cy + offset), 7, 3)
    elif kind == "filter":
        pygame.draw.line(surface, dim, (cx - 32, cy + 18), (cx + 32, cy + 18), 2)
        pygame.draw.rect(surface, (74, 222, 225, 76), (cx - 15, cy - 20, 30, 38))
        pygame.draw.line(surface, color, (cx - 15, cy - 24), (cx - 15, cy + 22), 3)
        pygame.draw.line(surface, color, (cx + 15, cy - 24), (cx + 15, cy + 22), 3)
        pygame.draw.line(surface, dim, (cx, cy - 30), (cx, cy + 25), 2)
    elif kind == "audio":
        pygame.draw.polygon(surface, color, ((cx - 28, cy + 4), (cx - 13, cy + 4), (cx + 6, cy - 15), (cx + 6, cy + 23), (cx - 13, cy + 4)))
        pygame.draw.arc(surface, dim, (cx, cy - 21, 36, 48), math.radians(-45), math.radians(45), 3)
        pygame.draw.arc(surface, dim, (cx + 9, cy - 30, 50, 66), math.radians(-45), math.radians(45), 3)
    elif kind == "decode":
        for offset in (-18, 0, 18):
            pygame.draw.line(surface, color, (cx + offset, cy - 24), (cx + offset, cy + 24), 3)
        pygame.draw.line(surface, dim, (cx - 30, cy - 12), (cx + 30, cy - 12), 2)
        pygame.draw.line(surface, dim, (cx - 30, cy + 12), (cx + 30, cy + 12), 2)
    elif kind == "network":
        points = ((cx, cy - 24), (cx - 25, cy + 18), (cx + 25, cy + 18))
        for a, b in ((0, 1), (0, 2), (1, 2)):
            pygame.draw.line(surface, dim, points[a], points[b], 3)
        for point in points:
            pygame.draw.circle(surface, color, point, 8, 3)
    else:
        pygame.draw.circle(surface, color, (cx, cy), 24, 3)
        pygame.draw.line(surface, color, (cx, cy - 4), (cx, cy + 20), 3)
        pygame.draw.circle(surface, color, (cx, cy - 20), 3)


def menu_icon_texture(text_cache, kind, label):
    key = f"menu_{kind}_{label}"
    cached = text_cache.cache.get(("surface", key))
    if cached is not None:
        return cached
    surface = pygame.Surface((132, 112), pygame.SRCALPHA)
    color = (232, 248, 250, 232)
    dim = (82, 235, 231, 150)
    draw_menu_icon(surface, kind, 66, 44, color, dim)
    label_surface = text_cache.font(16, bold=True, mono=True).render(label, True, (232, 246, 248))
    surface.blit(label_surface, ((132 - label_surface.get_width()) // 2, 86))
    return text_cache.surface_texture(key, surface)


def draw_main_menu(text_cache, scroll):
    x0, y0, x1, y1 = MENU_BOX
    draw_logical_rect(x0, y0, x1, y1, (6, 13, 18, 214))
    draw_logical_line(x0, y0, x1, y0, (151, 178, 184, 92), 1)
    for idx, (kind, label) in enumerate(MENU_ITEMS):
        bx0, by0, bx1, by1 = menu_item_box(idx, scroll)
        if bx1 < x0 or bx0 > x1:
            continue
        tex, tex_w, tex_h = menu_icon_texture(text_cache, kind, label)
        target_w = min(84, bx1 - bx0 - 8)
        target_h = min(72, by1 - by0 - 2)
        target_x = bx0 + ((bx1 - bx0) - target_w) / 2
        target_y = by0 + ((by1 - by0) - target_h) / 2
        draw_textured_quad(tex, target_x, target_y, target_x + target_w, target_y + target_h, 0, 0, 1, 1)
    if scroll > 2:
        draw_text(text_cache, x0 + 18, (y0 + y1) / 2, "<", (226, 246, 249), 20, True, True, "cm")
    if scroll < menu_max_scroll() - 2:
        draw_text(text_cache, x1 - 18, (y0 + y1) / 2, ">", (226, 246, 249), 20, True, True, "cm")


def draw_picker_button(text_cache, box, label, size=16, selected=False):
    x0, y0, x1, y1 = box
    fill = (72, 77, 81, 255) if selected else (38, 42, 46, 255)
    outline = (220, 223, 225, 235) if selected else (150, 155, 159, 220)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, outline, 1)
    draw_logical_line(x0, y1, x1, y1, outline, 1)
    draw_logical_line(x0, y0, x0, y1, outline, 1)
    draw_logical_line(x1, y0, x1, y1, outline, 1)
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2, label, (238, 240, 242), size, True, False, "cm")


def draw_station_search(text_cache, all_stations, query, sort_mode, keyboard_mode):
    draw_logical_rect(0, 0, LOGICAL_W, LOGICAL_H, (5, 6, 8, 255))
    draw_logical_rect(18, 8, 596, 64, (36, 40, 44, 255))
    draw_logical_line(18, 8, 596, 8, (166, 171, 175, 210), 1)
    draw_logical_line(18, 64, 596, 64, (166, 171, 175, 210), 1)
    draw_text(text_cache, 34, 36, query or "Country, city, call sign, or station name", (240, 242, 244) if query else (166, 171, 175), 23, False, False, "lm")
    draw_picker_button(text_cache, SEARCH_CASE_BOX, "aA", 16, keyboard_mode != "numeric")
    draw_picker_button(text_cache, SEARCH_MODE_BOX, "123" if keyboard_mode != "numeric" else "ABC", 14, keyboard_mode == "numeric")
    draw_picker_button(text_cache, SEARCH_EXIT_BOX, "EXIT", 19)
    draw_picker_button(text_cache, SEARCH_LEFT_EXIT_BOX, "EXIT", 19)
    for keys, x0, y0, key_w in keyboard_rows(keyboard_mode):
        for index, key in enumerate(keys):
            box = (x0 + index * key_w, y0, x0 + (index + 1) * key_w - 5, y0 + 70)
            label = "BACK" if key == "<" else ("ENTER" if key == ">" else ("SPACE" if key == "~" else key))
            draw_picker_button(text_cache, box, label, 19 if key in "<>~" else 26)


def fit_station_text(text_cache, text, max_width, size, bold=False, mono=False, family=None):
    """Ellipsize a row label to its measured slot, not an arbitrary count."""
    if text_cache.texture(text, size, (255, 255, 255), bold=bold, mono=mono, family=family)[1] <= max_width:
        return text
    ellipsis = "…"
    while text and text_cache.texture(text + ellipsis, size, (255, 255, 255), bold=bold, mono=mono, family=family)[1] > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def draw_station_picker(text_cache, stations, scroll, selected_server, query, sort_mode, station_health):
    x0, y0, x1, y1 = PICKER_BOX
    draw_logical_rect(0, 0, LOGICAL_W, LOGICAL_H, (5, 6, 8, 255))
    draw_logical_rect(794, 0, LOGICAL_W, LOGICAL_H, (18, 21, 24, 255))
    draw_logical_line(794, 0, 794, LOGICAL_H, (138, 143, 147, 185), 1)
    draw_picker_button(text_cache, PICKER_SEARCH_BOX, "SEARCH", 23)
    draw_text(text_cache, (PICKER_SEARCH_BOX[0] + PICKER_SEARCH_BOX[2]) / 2, PICKER_SEARCH_BOX[3] - 14,
              f"{scroll + 1}–{min(len(stations), scroll + PICKER_ROWS)} / {len(stations)}", (198, 202, 205), 12, False, False, "cm")
    draw_picker_button(text_cache, PICKER_SORT_LOCATION_BOX, "LOCATION", 20, sort_mode == "location")
    draw_picker_button(text_cache, PICKER_SORT_NAME_BOX, "NAME", 20, sort_mode == "name")
    draw_picker_button(text_cache, PICKER_EXIT_BOX, "EXIT", 20)

    for idx, (name, location, server, listener_used, listener_total) in enumerate(stations):
        box = station_tile(idx, scroll)
        if not box:
            continue
        selected = server == selected_server
        entry_health = station_health.get(server, {})
        checked = entry_health.get("checked", 0)
        health_fresh = time.time() - checked <= 86400
        active = health_fresh and entry_health.get("audio") is True
        if selected:
            fill = (72, 77, 81, 235)
            outline = (212, 216, 219, 230)
        elif active:
            fill = (30, 34, 38, 220)
            outline = (136, 142, 146, 170)
        else:
            fill = (20, 23, 26, 205)
            outline = (83, 88, 92, 135)
        draw_logical_rect(*box, fill)
        draw_logical_line(box[0], box[1], box[2], box[1], outline, 1)
        draw_logical_line(box[0], box[3], box[2], box[3], outline, 1)
        draw_logical_line(box[0], box[1], box[0], box[3], outline, 1)
        draw_logical_line(box[2], box[1], box[2], box[3], outline, 1)
        marker_y = (box[1] + box[3]) / 2
        draw_station_health_icons(text_cache, box[0] + 17, marker_y, entry_health, health_fresh)
        generic_name = "0-30" in name.lower() and "sdr" in name.lower()
        if generic_name:
            # Keep the useful suffix for otherwise generic directory labels;
            # e.g. the two Julussdalen receivers must not both appear only as
            # "Elverum, Norway" when their #1/#2 endpoints differ.
            identifier = re.sub(r"^0-30\s*mhz\s*kiwisdr\s*,?\s*", "", name, flags=re.I)
            identifier = re.split(r"\s+-\s+", identifier, maxsplit=1)[0].strip()
            identifier = identifier.split(",", 1)[0].strip()
            station_label = f"{location}  ·  {identifier}" if identifier else location
        else:
            station_label = f"{name}  ·  {location}"
        title_color = (238, 240, 242) if active or selected else (137, 142, 146)
        host_color = (129, 134, 138) if active or selected else (82, 87, 91)
        capacity_color = (198, 202, 205) if active or selected else (110, 115, 119)
        # Reserve a fixed, generously padded glyph lane. This prevents long
        # station titles from ever colliding with the audio/waterfall symbols.
        title_x = box[0] + 90
        station_label = fit_station_text(text_cache, station_label, box[2] - title_x - 76, 20, True)
        draw_text(text_cache, title_x, marker_y - 10, station_label, title_color, 20, True, False, "lm")
        parsed = urlparse(server if "://" in server else "http://" + server)
        host = (parsed.hostname or server)[:24]
        draw_text(text_cache, title_x, marker_y + 11, host, host_color, 11, False, False, "lm")
        capacity = f"{listener_used}/{listener_total}" if listener_used is not None and listener_total is not None else "–/–"
        draw_text(text_cache, box[2] - 16, marker_y - 10, capacity, capacity_color, 17, True, True, "rm")


def station_health_color(entry, key, fresh):
    if not fresh or entry.get(key) is not True:
        return (112, 117, 121, 255)
    return (72, 194, 104, 255)


def draw_station_health_icons(text_cache, x, y, entry, fresh):
    """Draw separate shape-first audio and waterfall availability indicators."""
    audio = station_health_color(entry, "audio", fresh)
    waterfall = station_health_color(entry, "waterfall", fresh)
    # Speaker: cone plus two compact sound-wave arcs.
    draw_logical_line(x - 8, y, x - 3, y, audio, 3)
    draw_logical_line(x - 3, y, x + 3, y - 6, audio, 3)
    draw_logical_line(x - 3, y, x + 3, y + 6, audio, 3)
    draw_logical_line(x + 3, y - 6, x + 3, y + 6, audio, 3)
    draw_logical_line(x + 8, y - 5, x + 12, y, audio, 2)
    draw_logical_line(x + 12, y, x + 8, y + 5, audio, 2)
    # Waterfall: descending intensity bars, visually distinct from the speaker.
    wx = x + 39
    for offset, height in ((0, 4), (5, 7), (10, 10)):
        draw_logical_line(wx + offset, y - height / 2, wx + offset, y + height / 2, waterfall, 3)


def smeter_segment_position(dbm):
    """Map true dBm to the deliberately non-linear 36-segment display."""
    if dbm <= SMETER_FLOOR_DBM:
        return 0.0
    if dbm <= SMETER_S9_DBM:
        return (dbm - SMETER_FLOOR_DBM) / (SMETER_S9_DBM - SMETER_FLOOR_DBM) * SMETER_S1_TO_S9_SEGMENTS
    if dbm <= SMETER_PLUS20_DBM:
        return SMETER_S1_TO_S9_SEGMENTS + (dbm - SMETER_S9_DBM) / (SMETER_PLUS20_DBM - SMETER_S9_DBM) * SMETER_S9_TO_PLUS20_SEGMENTS
    if dbm <= SMETER_CEILING_DBM:
        return (
            SMETER_S1_TO_S9_SEGMENTS
            + SMETER_S9_TO_PLUS20_SEGMENTS
            + (dbm - SMETER_PLUS20_DBM) / (SMETER_CEILING_DBM - SMETER_PLUS20_DBM) * SMETER_PLUS20_TO_PLUS40_SEGMENTS
        )
    return float(SMETER_S1_TO_S9_SEGMENTS + SMETER_S9_TO_PLUS20_SEGMENTS + SMETER_PLUS20_TO_PLUS40_SEGMENTS)


def smeter_dbm_at_segment(position):
    """Inverse display map used only to color the correct segment range."""
    total_segments = SMETER_S1_TO_S9_SEGMENTS + SMETER_S9_TO_PLUS20_SEGMENTS + SMETER_PLUS20_TO_PLUS40_SEGMENTS
    position = clamp(position, 0.0, float(total_segments))
    if position <= SMETER_S1_TO_S9_SEGMENTS:
        return SMETER_FLOOR_DBM + position / SMETER_S1_TO_S9_SEGMENTS * (SMETER_S9_DBM - SMETER_FLOOR_DBM)
    if position <= SMETER_S1_TO_S9_SEGMENTS + SMETER_S9_TO_PLUS20_SEGMENTS:
        return SMETER_S9_DBM + (position - SMETER_S1_TO_S9_SEGMENTS) / SMETER_S9_TO_PLUS20_SEGMENTS * (SMETER_PLUS20_DBM - SMETER_S9_DBM)
    return SMETER_PLUS20_DBM + (position - SMETER_S1_TO_S9_SEGMENTS - SMETER_S9_TO_PLUS20_SEGMENTS) / SMETER_PLUS20_TO_PLUS40_SEGMENTS * (SMETER_CEILING_DBM - SMETER_PLUS20_DBM)


def draw_smeter(text_cache, smeter_dbm, scope_enabled, peak_dbm=None):
    meter_x0 = 654
    # Extend 15 px into otherwise unused instrument space, retaining a 30 px
    # right margin. The fixed 2 px gutter keeps segments cleanly separated.
    meter_x1 = 930
    segment_count = 36
    bar_gap = 2
    bar_w = (meter_x1 - meter_x0 - (segment_count - 1) * bar_gap) / segment_count
    green = (222, 255, 228, 255)
    # Saturated, lower-luminance segment colors retain contrast on the dark
    # panel without the previous electric/white-hot appearance.
    red = (218, 38, 52, 255)
    rail = (220, 238, 232, 255)
    blue = (0, 72, 204, 255)
    # Keep the bar tops fixed, while leaving four more pixels of clearance below.
    bar_bottom = (69 if scope_enabled else sdr_ui.TOP_H - 2) - 4

    def dbx(dbm):
        return meter_x0 + round((meter_x1 - meter_x0) * (smeter_segment_position(dbm) / segment_count))

    labels = (
        ("S", dbx(-121) - 30, green[:3], 14),
        ("1", dbx(-121), green[:3], 14),
        ("3", dbx(-109), green[:3], 14),
        ("5", dbx(-97), green[:3], 14),
        ("7", dbx(-85), green[:3], 14),
        ("9", dbx(-73), green[:3], 14),
        ("+20", dbx(-53), red[:3], 14),
        ("+40", dbx(-33), red[:3], 14),
    )
    for text, x, color, size in labels:
        draw_text(text_cache, x, 17, text, color, size, False, True, "cm")

    for dbm, color in ((-121, rail), (-109, rail), (-97, rail), (-85, rail), (-73, rail), (-53, red), (-33, red)):
        x = dbx(dbm)
        draw_logical_line(x, 30, x, 36, color, 1)

    active_bars = max(
        0,
        min(segment_count, int(round(smeter_segment_position(smeter_dbm)))),
    )
    for i in range(active_bars):
        x = meter_x0 + i * (bar_w + bar_gap)
        bar_mid_dbm = smeter_dbm_at_segment(i + 0.5)
        fill = red if bar_mid_dbm >= SMETER_S9_DBM else blue
        draw_logical_rect(x, 38, x + bar_w, bar_bottom, fill)
    # A single muted line is enough to retain a recent peak without adding a
    # flashy second bar. It disappears once the decaying peak reaches live level.
    if peak_dbm is not None and peak_dbm > smeter_dbm + 0.75:
        peak_x = clamp(dbx(peak_dbm), meter_x0, meter_x1)
        draw_logical_line(peak_x, 36, peak_x, bar_bottom, (170, 190, 193, 210), 1)


def read_cpu_temp_c():
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return float(raw) / 1000.0
    except Exception:
        return None


def read_total_cpu_percent(previous_sample=None):
    """Return whole-system CPU use across all cores from /proc/stat."""
    try:
        fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        total = sum(fields)
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        current_sample = (total, idle)
        if previous_sample is None:
            return None, current_sample
        total_delta = total - previous_sample[0]
        idle_delta = idle - previous_sample[1]
        if total_delta <= 0:
            return None, current_sample
        return 100.0 * (1.0 - idle_delta / total_delta), current_sample
    except Exception:
        return None, previous_sample


def draw_system_annunciator(text_cache, cpu_percent, temp_c, y, size, alpha=1.0):
    parts = []
    if cpu_percent is not None:
        parts.append(f"CPU {cpu_percent:.0f}%")
    if temp_c is not None:
        parts.append(f"{temp_c:.0f}C")
    if not parts:
        return
    # Keep this in the reserved gap between IQ and DECODER; right-aligning it
    # at the decoder area made the two annunciators draw over one another.
    draw_text(text_cache, 575, y, " ".join(parts), (118, 218, 229), size, False, False, "lm", alpha, family="Cantarell")


def format_smeter_readout(smeter_dbm):
    value = int(round(smeter_dbm))
    return f"−{abs(value)} dBm" if value < 0 else f"+{value} dBm"


def draw_lower_status(text_cache, cpu_percent, temp_c, y0, y1, station_name="", smeter_readout_dbm=None, alpha=1.0):
    if alpha <= 0.01:
        return
    compact = y1 - y0 < 28
    # One typography family, weight and vertical center makes this read as a
    # deliberate single status bar instead of independent overlay labels.
    size = 14 if compact else 16
    status_mid_y = (y0 + y1) / 2
    draw_logical_rect(0, y0, LOGICAL_W, y1, (4, 8, 12, int((164 if compact else 208) * alpha)))
    if station_name:
        # The station is deliberately limited to 40% of the logical display,
        # leaving a permanent clear lane before the right-side status readouts.
        title = fit_station_text(text_cache, station_name, LOGICAL_W * 0.40, size, False, False, family="Cantarell")
        draw_text(text_cache, 18, status_mid_y, title, (151, 160, 165), size, False, False, "lm", alpha, family="Cantarell")
    if smeter_readout_dbm is not None:
        # Center this calm numeric readout in the permanent lane between the
        # 40%-wide station title and the CPU/decoder status on the right.
        draw_text(text_cache, 486, status_mid_y, format_smeter_readout(smeter_readout_dbm), (163, 181, 185), size, False, False, "cm", alpha, family="Cantarell")
    draw_system_annunciator(text_cache, cpu_percent, temp_c, status_mid_y, size, alpha)
    draw_text(text_cache, 730, status_mid_y, "DECODER", (229, 236, 239), size, False, False, "lm", alpha, family="Cantarell")
    draw_text(text_cache, 838, status_mid_y, "NO SYNC", (255, 178, 105), size, False, False, "lm", alpha, family="Cantarell")


def draw_ruler(
    text_cache,
    center_khz,
    span_khz,
    alpha=1.0,
    y0=sdr_ui.TOP_H,
    height=sdr_ui.RULER_H,
    background_alpha=185,
    subdued=False,
):
    if alpha <= 0.01:
        return
    draw_logical_rect(
        0,
        y0,
        LOGICAL_W,
        y0 + height,
        (10, 15, 21, int(background_alpha * alpha)),
    )
    span_hz = max(1, int(round(span_khz * 1000)))
    center_hz = int(round(center_khz * 1000))
    start_hz = center_hz - span_hz // 2
    end_hz = center_hz + span_hz // 2
    hz_per_px = span_hz / LOGICAL_W
    major_step_hz = sdr_ui.ruler_major_step_hz(span_khz)
    minor_step_hz = max(50, major_step_hz // 5)
    minor_start_hz = int(math.ceil(start_hz / minor_step_hz) * minor_step_hz)
    major_start_hz = int(math.ceil(start_hz / major_step_hz) * major_step_hz)
    # The bottom ruler sits over live spectrum/waterfall content. Keep it
    # visibly separate from the brighter cyan/white telemetry status layer.
    minor_color = (103, 128, 142, 150) if subdued else (142, 158, 166, 215)
    major_color = (133, 161, 174, 178) if subdued else (196, 210, 216, 255)
    label_color = (145, 178, 191) if subdued else (231, 240, 244)
    label_alpha = 0.84 if subdued else 1.0

    hz = minor_start_hz
    while hz <= end_hz:
        if hz % major_step_hz:
            x = int(round((hz - start_hz) / hz_per_px))
            if 0 <= x < LOGICAL_W:
                draw_logical_line(x, y0 + 2, x, y0 + 5, (minor_color[0], minor_color[1], minor_color[2], int(minor_color[3] * alpha)), 1)
        hz += minor_step_hz

    hz = major_start_hz
    last_label_x = -999
    while hz <= end_hz:
        x = int(round((hz - start_hz) / hz_per_px))
        if 0 <= x < LOGICAL_W:
            draw_logical_line(x, y0 + 2, x, y0 + 8, (major_color[0], major_color[1], major_color[2], int(major_color[3] * alpha)), 2)
            if x - last_label_x > 140:
                draw_text(
                    text_cache,
                    x,
                    y0 + 18,
                    sdr_ui.format_ruler_label(hz, major_step_hz),
                    label_color,
                    15,
                    True,
                    True,
                    "cm",
                    alpha * label_alpha,
                )
                last_label_x = x
        hz += major_step_hz


def draw_spectrum(y0, y1, values, peak_values=()):
    """Draw a compact amplitude-versus-frequency trace from the Kiwi W/F bins."""
    draw_logical_rect(0, y0, LOGICAL_W, y1, (2, 7, 12, 236))
    for fraction in (0.25, 0.50, 0.75):
        y = y0 + (y1 - y0) * fraction
        draw_logical_line(0, y, LOGICAL_W, y, (89, 139, 155, 34), 1)
    if not values:
        return
    top = y0 + 3
    bottom = y1 - 3
    if len(peak_values) == len(values):
        peak_points = [
            (index * (LOGICAL_W - 1) / max(1, len(peak_values) - 1), bottom - value * (bottom - top))
            for index, value in enumerate(peak_values)
        ]
        draw_logical_area(peak_points, bottom, (145, 159, 168, 76))
        draw_logical_polyline(peak_points, (174, 187, 194, 142), 1.0)
    points = [
        (index * (LOGICAL_W - 1) / max(1, len(values) - 1), bottom - value * (bottom - top))
        for index, value in enumerate(values)
    ]
    draw_logical_area(points, bottom, (226, 240, 255, 218))
    draw_logical_polyline(points, (255, 255, 255, 255), 1.4)


def draw_connection_annunciator(text_cache, status):
    if not status:
        return
    labels = {
        "connecting": "CONNECTING",
        "retrying": "RETRYING",
        "connected": "CONNECTED",
        "audio_wf_retry": "AUDIO OK · WF RETRY",
        "waterfall_audio_retry": "WF OK · AUDIO RETRY",
        "no_waterfall": "NO WATERFALL AVAILABLE",
        "failed": "CONNECTION FAILED",
    }
    colors = {
        "connecting": (94, 216, 152, 255),
        "retrying": (112, 222, 160, 255),
        "connected": (72, 236, 126, 255),
        "audio_wf_retry": (112, 222, 160, 255),
        "waterfall_audio_retry": (112, 222, 160, 255),
        "no_waterfall": (255, 184, 105, 255),
        "failed": (246, 144, 100, 255),
    }
    label = labels.get(status)
    if not label:
        return
    color = colors[status]
    x0, y0, x1, y1 = 520, 72, 942, 114
    alert = status in ("failed", "no_waterfall")
    draw_logical_rect(x0, y0, x1, y1, (4, 17, 13, 228) if not alert else (32, 12, 9, 230))
    draw_logical_line(x0, y0, x1, y0, color, 2)
    draw_logical_line(x0, y1, x1, y1, color, 2)
    if status == "connected":
        draw_logical_line(x0 + 15, y0 + 22, x0 + 23, y0 + 30, color, 4)
        draw_logical_line(x0 + 23, y0 + 30, x0 + 38, y0 + 12, color, 4)
    elif alert:
        draw_logical_line(x0 + 16, y0 + 11, x0 + 34, y0 + 31, color, 3)
        draw_logical_line(x0 + 34, y0 + 11, x0 + 16, y0 + 31, color, 3)
    else:
        draw_logical_rect(x0 + 16, y0 + 15, x0 + 30, y0 + 29, color)
    draw_text(text_cache, x0 + 54, (y0 + y1) / 2, label, color[:3], 20, True, True, "lm")


def draw_ui(
    text_cache,
    freq_khz,
    span_khz,
    smeter_dbm,
    smeter_peak_dbm,
    smeter_readout_dbm,
    mode,
    digital,
    step_hz,
    controls_alpha=1.0,
    focus_progress=0.0,
    ruler_y0=sdr_ui.TOP_H,
    ruler_height=sdr_ui.RULER_H,
    ruler_background_alpha=185,
    bottom_ruler=False,
    spectrum_enabled=False,
    cpu_percent=None,
    temp_c=None,
    station_name="",
    connection_status=None,
):
    # Previous comparison color: (5, 9, 14, 252). Keep the instrument strip
    # deliberately pure black until a requested visual comparison restores it.
    draw_logical_rect(0, 0, LOGICAL_W, sdr_ui.TOP_H, (0, 0, 0, 255))
    draw_home_button(text_cache, 1.0)
    draw_radio_setup_pill(text_cache, mode, digital, step_hz)
    # Cantarell Bold is an upright humanist alternative with clean, plain
    # zeros and visibly more open numeral forms than the prior DejaVu face.
    # It remains left-anchored so its proportional figures do not move the
    # readout's starting position during a tune.
    draw_text(text_cache, 218, 39, sdr_ui.format_freq(freq_khz), (184, 202, 205), 48, True, False, "lm", family="Cantarell")
    draw_smeter(text_cache, smeter_dbm, spectrum_enabled, smeter_peak_dbm)
    instrument_alpha = 1.0 - clamp(focus_progress, 0.0, 1.0)
    draw_ruler(
        text_cache,
        freq_khz,
        span_khz,
        instrument_alpha,
        y0=ruler_y0,
        height=ruler_height,
        background_alpha=ruler_background_alpha,
        subdued=bottom_ruler,
    )
    if bottom_ruler:
        draw_lower_status(
            text_cache,
            cpu_percent,
            temp_c,
            ruler_y0 + ruler_height,
            LOGICAL_H,
            station_name=station_name,
            smeter_readout_dbm=smeter_readout_dbm,
            alpha=instrument_alpha,
        )
    else:
        draw_lower_status(
            text_cache,
            cpu_percent,
            temp_c,
            WATERFALL_Y1,
            LOGICAL_H,
            station_name=station_name,
            smeter_readout_dbm=smeter_readout_dbm,
            alpha=instrument_alpha,
        )
    draw_control_group_background(text_cache, ZOOM_GROUP_BOX, "zoom_group_pill_v7", (64, 156), controls_alpha)
    draw_zoom_button(text_cache, ZOOM_PLUS_BOX, "+", controls_alpha)
    draw_zoom_button(text_cache, ZOOM_MINUS_BOX, "-", controls_alpha)
    draw_text(text_cache, 118, 227, "ZOOM", (211, 227, 231), 16, True, True, "cm", controls_alpha)
    draw_control_group_background(text_cache, VIEW_GROUP_BOX, "view_group_pill_v3", (100,), controls_alpha)
    draw_filter_toggle_button(text_cache, controls_alpha)
    draw_spectrum_toggle_button(text_cache, spectrum_enabled, controls_alpha)
    draw_connection_annunciator(text_cache, connection_status)


def drain_queue(line_queue):
    while True:
        try:
            line_queue.get_nowait()
        except queue.Empty:
            return


def kiwi_mode_filter(mode):
    mode = mode.lower()
    if mode in ("usb", "usn"):
        return 300, 2700
    if mode in ("lsb", "lsn"):
        return -2700, -300
    if mode in ("cw", "cwn"):
        return -500, 500
    if mode in ("nbfm", "nnfm"):
        return -6000, 6000
    if mode == "iq":
        return -12000, 12000
    return -5000, 5000


def default_sideband_mode(freq_khz):
    """Use conventional HF sideband defaults until an operator chooses a mode."""
    return "USB" if freq_khz >= 10000.0 else "LSB"


def filter_center_hz(low_cut, high_cut):
    return (low_cut + high_cut) / 2.0


def snd_carrier_khz(view_center_khz, low_cut, high_cut):
    """Place the actual SND passband around the waterfall's selected RF center."""
    return view_center_khz - filter_center_hz(low_cut, high_cut) / 1000.0


def filter_view_offsets(low_cut, high_cut):
    """Return passband edges relative to the selected waterfall center."""
    center_hz = filter_center_hz(low_cut, high_cut)
    return low_cut - center_hz, high_cut - center_hz


def start_audio_player(args):
    """Open the SDR's mono PCM stream on PipeWire's current default sink.

    PipeWire/WirePlumber owns the output choice, so a USB sink selected as the
    system default continues to receive this stream without pinning a volatile
    numeric node id in the renderer configuration.
    """
    if not args.audio:
        return None
    try:
        return subprocess.Popen(
            [
                "pw-cat",
                "--playback",
                "--raw",
                "--rate", str(args.audio_rate),
                "--channels", "1",
                "--format", "s16",
                "--latency", PIPEWIRE_AUDIO_LATENCY,
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except OSError as exc:
        print(f"gl audio player {exc}", flush=True)
        return None


def stop_audio_player(player):
    if not player:
        return
    try:
        if player.stdin:
            player.stdin.close()
    except OSError:
        pass
    try:
        player.terminate()
        player.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            player.kill()
        except OSError:
            pass


def pipewire_default_volume():
    """Read the real default-sink level used by the USB speaker path."""
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
        match = re.search(r"Volume:\s+([0-9.]+)", result.stdout)
        return clamp(float(match.group(1)), 0.0, 1.0) if match else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def set_pipewire_default_volume(volume):
    """Set the actual current default sink, not a UI-only volume value."""
    volume = clamp(float(volume), 0.0, 1.0)
    try:
        result = subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume:.2f}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=0.5,
            check=False,
        )
        return volume if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def snd_meter_worker(args, stop_event, state):
    seen_view_generation = -1
    seen_radio_generation = -1
    seen_server_generation = -1
    seen_audio_generation = -1
    player = None
    while not stop_event.is_set():
        ws = None
        try:
            if args.audio and (player is None or player.poll() is not None):
                stop_audio_player(player)
                player = start_audio_player(args)
            server, freq_khz, _zoom, _smeter, view_generation, server_generation = state.snapshot()
            state.connection_attempt(server_generation, "audio")
            radio_mode, low_cut, high_cut, radio_generation = state.radio_snapshot()
            squelch_enabled, audio_generation = state.audio_snapshot()
            ws = kiwi.KiwiWebSocket.connect(server, "SND")
            kiwi.send_kiwi_setup(ws, "kiwi", args.user)
            configured = False
            last_keepalive = 0
            while not stop_event.is_set():
                server, freq_khz, _zoom, _smeter, view_generation, server_generation = state.snapshot()
                radio_mode, low_cut, high_cut, radio_generation = state.radio_snapshot()
                squelch_enabled, audio_generation = state.audio_snapshot()
                if server_generation != seen_server_generation:
                    seen_server_generation = server_generation
                    break
                if configured and (view_generation != seen_view_generation or radio_generation != seen_radio_generation):
                    snd_freq_khz = snd_carrier_khz(freq_khz, low_cut, high_cut)
                    kiwi.send_snd_setup(ws, snd_freq_khz, radio_mode, low_cut, high_cut)
                    ws.send_text(f"SET squelch={int(squelch_enabled)} max=0")
                    seen_view_generation = view_generation
                    seen_radio_generation = radio_generation
                    seen_audio_generation = audio_generation
                    print(
                        f"gl snd mode={radio_mode} carrier={snd_freq_khz:.3f} view={freq_khz:.3f}",
                        flush=True,
                    )

                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now
                try:
                    message = ws.recv()
                except socket.timeout:
                    continue
                if message[:3] == b"MSG":
                    params = kiwi.parse_msg_params(message)
                    if "audio_rate" in params:
                        # Kiwi's raw, uncompressed SND packets remain at the
                        # receiver's 12 kHz PCM cadence. Retain the normal
                        # browser-output acknowledgement, while feeding the
                        # locally measured raw rate to PipeWire below.
                        ws.send_text(f"SET AR OK in={int(float(params['audio_rate']))} out=44100")
                    if "sample_rate" in params and not configured:
                        snd_freq_khz = snd_carrier_khz(freq_khz, low_cut, high_cut)
                        kiwi.send_snd_setup(ws, snd_freq_khz, radio_mode, low_cut, high_cut)
                        ws.send_text(f"SET squelch={int(squelch_enabled)} max=0")
                        configured = True
                        seen_view_generation = view_generation
                        seen_radio_generation = radio_generation
                        seen_audio_generation = audio_generation
                        print(
                            f"gl snd setup mode={radio_mode} carrier={snd_freq_khz:.3f} view={freq_khz:.3f}",
                            flush=True,
                        )
                        if state.connection_ready(server_generation, "audio"):
                            persist_live_station_health(server, "audio", True)
                    continue
                if configured and audio_generation != seen_audio_generation:
                    ws.send_text(f"SET squelch={int(squelch_enabled)} max=0")
                    seen_audio_generation = audio_generation
                if message[:3] != b"SND" or len(message) < 10:
                    continue
                body = message[3:]
                flags, _sequence = struct.unpack("<BI", body[:5])
                smeter, = struct.unpack(">H", body[5:7])
                state.set_smeter(0.1 * smeter - 127.0, source="snd")
                # Kiwi sends signed PCM after the seven-byte SND header. The
                # legacy aplay path expected big-endian samples; pw-cat uses
                # native S16, so convert only the normal big-endian packets.
                audio = body[7:]
                if player and player.stdin and not (flags & kiwi.SND_FLAG_COMPRESSED) and not (flags & kiwi.SND_FLAG_STEREO):
                    if not (flags & kiwi.SND_FLAG_LITTLE_ENDIAN):
                        audio = kiwi.swap_s16_bytes(audio)
                    try:
                        player.stdin.write(audio)
                    except (BrokenPipeError, OSError):
                        stop_audio_player(player)
                        player = None
        except Exception as exc:
            print(f"gl SND {exc}", flush=True)
            if state.connection_failed(server_generation, "audio"):
                persist_live_station_health(server, "audio", False)
            if stop_event.wait(2.0):
                break
        finally:
            if ws:
                ws.send_close()
    stop_audio_player(player)


def waterfall_worker(args, line_queue, stop_event, state):
    while not stop_event.is_set():
        ws = None
        try:
            server, freq_khz, zoom, _smeter_dbm, seen_generation, seen_server_generation = state.snapshot()
            state.connection_attempt(seen_server_generation, "waterfall")
            wf_floor, wf_ceil, wf_speed, wf_auto, wf_palette, seen_wf_generation = state.waterfall_snapshot()
            mapper = waterfall_mapper(wf_palette)
            leveler = kiwi.WaterfallLeveler(wf_floor, wf_ceil, auto=wf_auto)
            ws = kiwi.KiwiWebSocket.connect(server, "W/F")
            kiwi.send_kiwi_setup(ws, "kiwi", args.user)
            kiwi.send_wf_setup(ws, freq_khz, zoom, wf_speed)
            last_keepalive = 0
            last_frame_at = time.monotonic()
            print(f"gl wf setup: {server} {freq_khz:.3f} kHz zoom {zoom}", flush=True)
            while not stop_event.is_set():
                server, freq_khz, zoom, _smeter_dbm, generation, server_generation = state.snapshot()
                next_floor, next_ceil, next_speed, next_auto, next_palette, wf_generation = state.waterfall_snapshot()
                if server_generation != seen_server_generation:
                    seen_server_generation = server_generation
                    drain_queue(line_queue)
                    break
                if generation != seen_generation:
                    seen_generation = generation
                    drain_queue(line_queue)
                    kiwi.send_wf_setup(ws, freq_khz, zoom, wf_speed)
                    print(f"gl wf retune: {freq_khz:.3f} kHz zoom {zoom}", flush=True)
                if wf_generation != seen_wf_generation:
                    seen_wf_generation = wf_generation
                    wf_floor, wf_ceil, wf_speed, wf_auto, wf_palette = next_floor, next_ceil, next_speed, next_auto, next_palette
                    leveler.floor = wf_floor
                    leveler.ceiling = wf_ceil
                    leveler.auto = wf_auto
                    mapper = waterfall_mapper(wf_palette)
                    ws.send_text(f"SET wf_speed={wf_speed}")
                    print(f"gl waterfall floor={wf_floor:.0f} ceil={wf_ceil:.0f} auto={int(wf_auto)} rate={wf_speed} palette={wf_palette}", flush=True)

                if time.monotonic() - last_frame_at > WATERFALL_STARTUP_TIMEOUT_SECONDS:
                    raise RuntimeError("waterfall startup timeout")
                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now
                try:
                    message = ws.recv()
                except socket.timeout:
                    continue
                if message[:3] == b"W/F" and len(message) > 16:
                    last_frame_at = time.monotonic()
                    if state.connection_ready(seen_server_generation, "waterfall"):
                        persist_live_station_health(server, "waterfall", True)
                    samples = message[16:]
                    floor, ceiling = leveler.levels_for(samples)
                    line = kiwi.waterfall_line(samples, mapper, floor, ceiling)
                    state.update_spectrum(samples, floor, ceiling)
                    row_span = kiwi.zoom_to_span_khz(zoom)
                    row_item = (line, freq_khz, row_span)
                    for _ in range(args.wf_row_pixels):
                        try:
                            line_queue.put_nowait(row_item)
                        except queue.Full:
                            try:
                                line_queue.get_nowait()
                            except queue.Empty:
                                pass
                            line_queue.put_nowait(row_item)
                    if samples:
                        sorted_samples = sorted(samples)
                        p95 = sorted_samples[min(len(sorted_samples) - 1, int(len(sorted_samples) * 0.95))]
                        state.set_smeter(p95 - 268)
        except Exception as exc:
            print(f"gl WF {exc}", flush=True)
            if state.connection_failed(seen_server_generation, "waterfall"):
                persist_live_station_health(server, "waterfall", False)
            if stop_event.wait(2.0):
                break
        finally:
            if ws:
                ws.send_close()


def main():
    parser = argparse.ArgumentParser(description="OpenGL KiwiSDR display prototype.")
    parser.add_argument("--server", default="http://21662.proxy2.kiwisdr.com:8073")
    parser.add_argument("--receiver-state-file", type=Path, default=Path.home() / ".local/state/kiwi-gl-display-receiver.json")
    parser.add_argument("--remember-receiver", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--screenshot-path", type=Path, default=Path("/tmp/kiwi-gl-display.png"), help=argparse.SUPPRESS)
    parser.add_argument("--freq-khz", type=float, default=7075.794)
    parser.add_argument("--zoom", type=int, default=13)
    parser.add_argument("--wf-speed", type=int, default=4)
    parser.add_argument("--wf-row-pixels", type=int, default=1)
    parser.add_argument("--wf-floor", type=int, default=142)
    parser.add_argument("--wf-ceil", type=int, default=245)
    parser.add_argument("--spectrum", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--duration", type=float, default=0.0, help="optional run limit in seconds")
    parser.add_argument("--orientation", choices=("flipped", "normal"), default="flipped")
    parser.add_argument("--event", type=Path, help="input event device, defaults to auto-detected Goodix")
    parser.add_argument("--invert-x", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--invert-y", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--swap-x-y", action="store_true")
    parser.add_argument("--invert-tune", action="store_true")
    parser.add_argument("--tap-px", type=int, default=12)
    parser.add_argument("--swipe-start-px", type=int, default=4)
    parser.add_argument("--swipe-sensitivity", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--swipe-velocity-gain", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--swipe-velocity-low-px-s", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--swipe-velocity-high-px-s", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--swipe-fine-sensitivity", type=float, default=0.12)
    parser.add_argument("--swipe-fine-px-s", type=float, default=130.0)
    parser.add_argument("--swipe-slow-sensitivity", type=float, default=1.15)
    parser.add_argument("--swipe-fast-sensitivity", type=float, default=2.4)
    parser.add_argument("--swipe-fast-px-s", type=float, default=420.0)
    parser.add_argument("--swipe-fast-zoom-px-s", type=float, default=1400.0)
    parser.add_argument("--swipe-fast-zoom-distance-px", type=int, default=180)
    parser.add_argument("--swipe-fast-zoom-out", type=int, default=5)
    parser.add_argument("--swipe-fast-zoom-min", type=int, default=4)
    parser.add_argument("--swipe-auto-zoom-budget", type=int, default=5)
    parser.add_argument("--swipe-repeat-window-s", type=float, default=1.4)
    parser.add_argument("--swipe-repeat-boost", type=float, default=0.65)
    parser.add_argument("--swipe-repeat-max", type=int, default=3)
    parser.add_argument("--swipe-repeat-zoom-out", type=int, default=1)
    parser.add_argument("--swipe-repeat-zoom-threshold", type=int, default=2)
    parser.add_argument("--swipe-repeat-zoom-min", type=int, default=11)
    parser.add_argument("--swipe-inertia-min-px-s", type=float, default=520.0)
    parser.add_argument("--swipe-inertia-strength", type=float, default=0.0)
    parser.add_argument("--swipe-inertia-tau", type=float, default=0.30)
    parser.add_argument("--max-zoom", type=int, default=14)
    parser.add_argument("--station-zoom", type=int, default=13)
    parser.add_argument("--tune-step-hz", type=int, default=100)
    parser.add_argument("--zoom-osd-seconds", type=float, default=ZOOM_OSD_SECONDS)
    parser.add_argument("--user", default="Codex OpenGL SDR display")
    parser.add_argument("--audio", action=argparse.BooleanOptionalAction, default=True, help="play Kiwi PCM through the PipeWire default sink")
    parser.add_argument("--audio-rate", type=int, default=12000, help="Kiwi raw PCM rate for the local PipeWire stream")
    args = parser.parse_args()
    if args.remember_receiver:
        remembered_view = load_remembered_view(args.receiver_state_file)
        if remembered_view:
            args.server = remembered_view["server"]
            args.freq_khz = remembered_view.get("freq_khz", args.freq_khz)
            args.zoom = remembered_view.get("zoom", args.zoom)
            print(
                f"gl remembered receiver: {args.server} "
                f"{args.freq_khz:.3f} kHz zoom {args.zoom}",
                flush=True,
            )
    args.max_zoom = clamp(args.max_zoom, 0, 14)
    args.station_zoom = clamp(args.station_zoom, 0, 14)
    if args.swipe_sensitivity is not None:
        args.swipe_slow_sensitivity = args.swipe_sensitivity
    args.swipe_slow_sensitivity = max(0.1, args.swipe_slow_sensitivity)
    args.swipe_fine_sensitivity = clamp(args.swipe_fine_sensitivity, 0.02, args.swipe_slow_sensitivity)
    args.swipe_fine_px_s = clamp(args.swipe_fine_px_s, 10.0, max(11.0, args.swipe_fast_px_s - 1.0))
    args.swipe_fast_sensitivity = max(args.swipe_slow_sensitivity, args.swipe_fast_sensitivity)
    args.swipe_fast_px_s = max(50.0, args.swipe_fast_px_s)
    args.swipe_fast_zoom_px_s = max(args.swipe_fast_px_s, args.swipe_fast_zoom_px_s)
    args.swipe_fast_zoom_distance_px = max(args.swipe_start_px, args.swipe_fast_zoom_distance_px)
    args.swipe_fast_zoom_out = max(0, args.swipe_fast_zoom_out)
    args.swipe_fast_zoom_min = clamp(args.swipe_fast_zoom_min, 0, args.max_zoom)
    args.swipe_auto_zoom_budget = max(0, args.swipe_auto_zoom_budget)
    args.swipe_repeat_window_s = max(0.2, args.swipe_repeat_window_s)
    args.swipe_repeat_boost = max(0.0, args.swipe_repeat_boost)
    args.swipe_repeat_max = max(0, args.swipe_repeat_max)
    args.swipe_repeat_zoom_out = max(0, args.swipe_repeat_zoom_out)
    args.swipe_repeat_zoom_threshold = max(1, args.swipe_repeat_zoom_threshold)
    args.swipe_repeat_zoom_min = clamp(args.swipe_repeat_zoom_min, 0, args.max_zoom)
    args.tune_step_hz = max(1, args.tune_step_hz)
    args.swipe_inertia_min_px_s = max(0.0, args.swipe_inertia_min_px_s)
    args.swipe_inertia_strength = max(0.0, args.swipe_inertia_strength)
    args.swipe_inertia_tau = max(0.05, args.swipe_inertia_tau)

    set_display_orientation(args.orientation)
    setup_gl()
    print(
        "OpenGL:",
        GL.glGetString(GL.GL_VENDOR).decode(),
        GL.glGetString(GL.GL_RENDERER).decode(),
        GL.glGetString(GL.GL_VERSION).decode(),
        f"orientation={args.orientation}",
        flush=True,
    )
    text_cache = TextCache()
    wf_texture = WaterfallTexture()
    line_queue = queue.Queue(maxsize=96)
    stop_event = threading.Event()
    screenshot_requested = threading.Event()
    zoom_osd_requested = threading.Event()

    def request_screenshot(_signum, _frame):
        screenshot_requested.set()

    def request_zoom_osd(_signum, _frame):
        zoom_osd_requested.set()

    signal.signal(signal.SIGUSR1, request_screenshot)
    signal.signal(signal.SIGUSR2, request_zoom_osd)
    radio_mode = default_sideband_mode(args.freq_khz)
    auto_sideband_mode = radio_mode
    manual_radio_mode = False
    state = SharedState(
        args.server,
        args.freq_khz,
        args.zoom,
        -95.0,
        args.wf_floor,
        args.wf_ceil,
        args.wf_speed,
        radio_mode.lower(),
        args.spectrum,
    )
    if args.remember_receiver:
        save_remembered_view(args.receiver_state_file, args.server, args.freq_khz, args.zoom)
    wf_thread = threading.Thread(target=waterfall_worker, args=(args, line_queue, stop_event, state), daemon=True)
    snd_thread = threading.Thread(target=snd_meter_worker, args=(args, stop_event, state), daemon=True)
    wf_thread.start()
    snd_thread.start()

    event_path = args.event or kiwi.find_touch_event()
    ev = event_path.open("rb", buffering=0)
    os.set_blocking(ev.fileno(), False)
    print(f"gl touch input {event_path}", flush=True)

    clock = pygame.time.Clock()
    start = time.monotonic()
    frames = 0
    display_freq = args.freq_khz
    display_span = kiwi.zoom_to_span_khz(args.zoom)
    anim_from_freq = display_freq
    anim_from_span = display_span
    anim_to_freq = display_freq
    anim_to_span = display_span
    anim_start = 0.0
    anim_duration = 0.20
    zoom_osd_until = 0.0
    next_system_sample = 0.0
    next_smeter_readout_update = 0.0
    smeter_readout_dbm = -121.0
    cpu_percent = None
    cpu_sample = None
    temp_c = None
    controls_active_until = time.monotonic() + CONTROL_QUIET_SECONDS
    all_stations = STATIONS
    station_query = ""
    station_sort = "location"
    stations = filtered_stations(all_stations, station_query, station_sort)
    station_health = {}
    next_health_reload = 0.0
    menu_open = False
    menu_opened_at = 0.0
    menu_scroll = 0.0
    picker_open = False
    search_open = False
    keyboard_mode = "lower"
    radio_setup_open = False
    display_setup_open = False
    audio_panel_open = False
    audio_volume = pipewire_default_volume()
    audio_volume_last_apply = 0.0
    filter_panel_open = False
    filter_drag_edge = None
    filter_drag_center = 0.0
    filter_drag_audio_center = 0.0
    filter_drag_limit = FILTER_LIMIT_HZ
    filter_custom_width = False
    station_scroll = 0
    digital_mode = "DIG"
    tune_step_hz = args.tune_step_hz
    radio_mode_page = 0

    active = False
    raw_x = raw_y = None
    current_slot = 0
    mt_slots = {}
    touch_started = False
    gesture = None
    swipe_started = False
    start_x = start_freq = None
    start_y = 0
    start_scroll = 0
    start_menu_scroll = 0.0
    start_time = 0.0
    last_move_x = 0.0
    last_move_t = 0.0
    swipe_velocity_px_s = 0.0
    last_swipe_direction = 0
    last_swipe_time = 0.0
    repeat_swipe_count = 0
    active_swipe_boost = 1.0
    repeat_zoom_applied = False
    repeat_zoom_changed = False
    fast_sweep_zoom_applied = False
    auto_zoom_levels_used = 0
    inertia_velocity_khz_s = 0.0
    inertia_last_t = time.monotonic()
    start_span = display_span
    candidate_freq = display_freq
    last_x = None

    def remember_current_view():
        if not args.remember_receiver:
            return
        server, freq_khz, zoom, _smeter, _generation, _server_generation = state.snapshot()
        save_remembered_view(args.receiver_state_file, server, freq_khz, zoom)

    def apply_band_default(freq_khz):
        """Follow the conventional 10 MHz split until the operator takes over."""
        nonlocal radio_mode, auto_sideband_mode
        desired_mode = default_sideband_mode(freq_khz)
        if manual_radio_mode or desired_mode == auto_sideband_mode:
            return
        radio_mode = desired_mode
        auto_sideband_mode = desired_mode
        state.set_radio_mode(radio_mode)
        print(f"gl auto sideband {radio_mode.lower()} freq={freq_khz:.3f}", flush=True)

    def controls_alpha(now=None):
        now = now or time.monotonic()
        if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or filter_panel_open or now <= controls_active_until:
            return 1.0
        fade_t = (now - controls_active_until) / CONTROL_FADE_SECONDS
        return clamp(1.0 - fade_t, 0.0, 1.0)

    def controls_quiet(now=None):
        return controls_alpha(now) <= 0.05

    def waterfall_focus_progress(now=None):
        """Keep the waterfall stable; touch only reveals controls."""
        return 0.0

    def wake_controls():
        nonlocal controls_active_until
        controls_active_until = time.monotonic() + CONTROL_QUIET_SECONDS

    def animate_to(freq_khz, span_khz, duration=0.20):
        nonlocal anim_from_freq, anim_from_span, anim_to_freq, anim_to_span, anim_start, anim_duration
        nonlocal display_freq, display_span
        anim_from_freq = display_freq
        anim_from_span = display_span
        anim_to_freq = freq_khz
        anim_to_span = span_khz
        anim_start = time.monotonic()
        anim_duration = max(0.001, duration)

    def update_animation():
        nonlocal display_freq, display_span, anim_start
        if anim_start <= 0:
            return
        t = (time.monotonic() - anim_start) / anim_duration
        if t >= 1.0:
            display_freq = anim_to_freq
            display_span = anim_to_span
            anim_start = 0.0
            return
        e = ease_out_cubic(t)
        display_freq = anim_from_freq + (anim_to_freq - anim_from_freq) * e
        display_span = anim_from_span + (anim_to_span - anim_from_span) * e

    def change_zoom(delta):
        nonlocal zoom_osd_until, auto_zoom_levels_used
        wake_controls()
        _server, freq_khz, zoom, _smeter, _gen, _server_gen = state.snapshot()
        new_zoom = clamp(zoom + delta, 0, args.max_zoom)
        if new_zoom == zoom:
            zoom_osd_until = time.monotonic() + args.zoom_osd_seconds
            return
        freq_khz, new_zoom, _gen = state.set_view(zoom=new_zoom)
        remember_current_view()
        auto_zoom_levels_used = 0
        animate_to(freq_khz, kiwi.zoom_to_span_khz(new_zoom), 0.22)
        zoom_osd_until = time.monotonic() + args.zoom_osd_seconds
        print(f"gl zoom {new_zoom} span {kiwi.zoom_to_span_khz(new_zoom):.1f} kHz", flush=True)

    def advance_waterfall_drag(x):
        nonlocal candidate_freq, display_freq, last_move_x, last_move_t, swipe_velocity_px_s
        nonlocal start_span, zoom_osd_until, fast_sweep_zoom_applied, auto_zoom_levels_used
        nonlocal repeat_zoom_applied, repeat_zoom_changed
        now_move = time.monotonic()
        dt = max(0.006, now_move - last_move_t)
        dx = x - last_move_x
        instant_velocity = dx / dt
        # Decelerating must feel immediate: a slow finger movement takes
        # precedence over the preceding quick swipe within the next samples.
        velocity_blend = 0.72 if abs(instant_velocity) < abs(swipe_velocity_px_s) else 0.46
        swipe_velocity_px_s = (1.0 - velocity_blend) * swipe_velocity_px_s + velocity_blend * instant_velocity

        # Consecutive gestures only widen the view once this gesture itself is
        # moving decisively. That leaves a deliberate slow follow-up drag as
        # fine tuning, even directly after travelling quickly.
        if (
            not repeat_zoom_applied
            and repeat_swipe_count >= args.swipe_repeat_zoom_threshold
            and abs(swipe_velocity_px_s) >= args.swipe_fast_px_s
            and abs(x - start_x) >= args.swipe_fast_zoom_distance_px
            and args.swipe_repeat_zoom_out
        ):
            _server, _freq, zoom, _smeter, _gen, _server_gen = state.snapshot()
            new_zoom = (
                max(
                    args.swipe_repeat_zoom_min,
                    zoom - min(args.swipe_repeat_zoom_out, max(0, args.swipe_auto_zoom_budget - auto_zoom_levels_used)),
                )
                if zoom > args.swipe_repeat_zoom_min
                else zoom
            )
            applied_levels = zoom - new_zoom
            if applied_levels:
                state.set_view(zoom=new_zoom)
                remember_current_view()
                start_span = kiwi.zoom_to_span_khz(new_zoom)
                animate_to(candidate_freq, start_span, 0.18)
                zoom_osd_until = now_move + args.zoom_osd_seconds
                auto_zoom_levels_used += applied_levels
                repeat_zoom_changed = True
                print(f"gl repeat swipe: zoom {new_zoom} span {start_span:.1f} kHz", flush=True)
            repeat_zoom_applied = True

        if (
            not fast_sweep_zoom_applied
            and repeat_zoom_applied
            and abs(swipe_velocity_px_s) >= args.swipe_fast_zoom_px_s
            and abs(x - start_x) >= args.swipe_fast_zoom_distance_px
            and args.swipe_fast_zoom_out
        ):
            _server, _freq, zoom, _smeter, _gen, _server_gen = state.snapshot()
            if zoom > args.swipe_fast_zoom_min:
                remaining_levels = max(0, args.swipe_fast_zoom_out - (1 if repeat_zoom_changed else 0))
                allowed_levels = min(remaining_levels, max(0, args.swipe_auto_zoom_budget - auto_zoom_levels_used))
                new_zoom = max(args.swipe_fast_zoom_min, zoom - allowed_levels)
                applied_levels = zoom - new_zoom
                if applied_levels:
                    state.set_view(zoom=new_zoom)
                    remember_current_view()
                    start_span = kiwi.zoom_to_span_khz(new_zoom)
                    animate_to(candidate_freq, start_span, 0.18)
                    zoom_osd_until = now_move + args.zoom_osd_seconds
                    auto_zoom_levels_used += applied_levels
                    print(f"gl fast swipe: zoom {new_zoom} span {start_span:.1f} kHz", flush=True)
            fast_sweep_zoom_applied = True
        # Travel boost is tied to live velocity, not merely to the fact that
        # recent swipes were fast. It fades to exactly 1x during fine motion.
        travel_t = clamp(
            (abs(swipe_velocity_px_s) - args.swipe_fast_px_s) / args.swipe_fast_px_s,
            0.0,
            1.0,
        )
        travel_t = travel_t * travel_t * (3.0 - 2.0 * travel_t)
        live_swipe_boost = 1.0 + (active_swipe_boost - 1.0) * travel_t
        sensitivity = swipe_effective_sensitivity(swipe_velocity_px_s, args) * live_swipe_boost
        candidate_freq = clamp(
            candidate_freq + retune_delta_from_drag(dx, start_span, args.invert_tune, sensitivity),
            0.0,
            30000.0,
        )
        last_move_x = x
        last_move_t = now_move
        display_freq = candidate_freq

    def begin_swipe(x):
        nonlocal swipe_started, last_swipe_direction, last_swipe_time, repeat_swipe_count, active_swipe_boost, repeat_zoom_applied, repeat_zoom_changed
        nonlocal auto_zoom_levels_used
        nonlocal start_span, zoom_osd_until
        swipe_started = True
        direction = 1 if x > start_x else -1
        now_swipe = time.monotonic()
        if direction == last_swipe_direction and now_swipe - last_swipe_time <= args.swipe_repeat_window_s:
            repeat_swipe_count = min(args.swipe_repeat_max, repeat_swipe_count + 1)
        else:
            repeat_swipe_count = 0
            repeat_zoom_applied = False
            repeat_zoom_changed = False
        last_swipe_direction = direction
        last_swipe_time = now_swipe
        active_swipe_boost = 1.0 + repeat_swipe_count * args.swipe_repeat_boost


    try:
        while not stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    stop_event.set()
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                    stop_event.set()

            while True:
                try:
                    data = os.read(ev.fileno(), kiwi.EVENT_STRUCT.size)
                except BlockingIOError:
                    break
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    raise
                if not data or len(data) != kiwi.EVENT_STRUCT.size:
                    break
                _, _, event_type, code, value = kiwi.EVENT_STRUCT.unpack(data)
                if event_type == kiwi.EV_ABS:
                    if code == kiwi.ABS_MT_SLOT:
                        current_slot = value
                        mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                    elif code == kiwi.ABS_X:
                        raw_x = clamp(value, 0, LOGICAL_W - 1)
                    elif code == kiwi.ABS_Y:
                        raw_y = clamp(value, 0, LOGICAL_H - 1)
                    elif code == kiwi.ABS_MT_POSITION_X:
                        slot = mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                        slot["x"] = clamp(value, 0, LOGICAL_W - 1)
                    elif code == kiwi.ABS_MT_POSITION_Y:
                        slot = mt_slots.setdefault(current_slot, {"active": True, "x": None, "y": None})
                        slot["y"] = clamp(value, 0, LOGICAL_H - 1)
                    elif code == kiwi.ABS_MT_TRACKING_ID:
                        slot = mt_slots.setdefault(current_slot, {"active": value >= 0, "x": None, "y": None})
                        slot["active"] = value >= 0
                elif event_type == kiwi.EV_KEY and code == kiwi.BTN_TOUCH:
                    active = value == 1
                    if not active:
                        mt_slots.clear()
                elif event_type == kiwi.EV_SYN and code == kiwi.SYN_REPORT:
                    points = kiwi.touch_points(mt_slots, raw_x, raw_y, active, args)
                    is_active = bool(points)
                    if not is_active:
                        if raw_x is None or raw_y is None:
                            x = start_x if start_x is not None else 0
                            y = start_y
                        else:
                            x, y = kiwi.transform_touch(raw_x, raw_y, args)
                    else:
                        x, y = points[0] if len(points) == 1 else kiwi.midpoint(points[:2])

                    if is_active:
                        if not touch_started:
                            if abs(inertia_velocity_khz_s) > 0.001:
                                state.set_view(freq_khz=display_freq)
                                remember_current_view()
                                inertia_velocity_khz_s = 0.0
                            touch_started = True
                            # A stale completed zoom/tune animation used to
                            # overwrite live drag feedback every frame.
                            anim_start = 0.0
                            start_x = x
                            start_y = y
                            start_scroll = station_scroll
                            start_menu_scroll = menu_scroll
                            start_time = time.monotonic()
                            last_move_x = x
                            last_move_t = start_time
                            swipe_velocity_px_s = 0.0
                            swipe_started = False
                            fast_sweep_zoom_applied = False
                            _server, freq_khz, _zoom, _smeter, _gen, _server_gen = state.snapshot()
                            start_freq = display_freq if not menu_open and not picker_open and not radio_setup_open and not display_setup_open and not audio_panel_open and not filter_panel_open else freq_khz
                            start_span = display_span
                            candidate_freq = start_freq
                            if waterfall_focus_progress() > 0.01:
                                wake_controls()
                                gesture = "wake"
                            elif contains(HOME_BOX, x, y):
                                gesture = "home"
                            elif contains(RADIO_SETUP_BOX, x, y):
                                gesture = "radio_toggle"
                            elif audio_panel_open and contains(AUDIO_VOLUME_BOX, x, y):
                                gesture = "audio_volume"
                            elif audio_panel_open and contains(AUDIO_SQUELCH_BOX, x, y):
                                gesture = "audio_squelch"
                            elif audio_panel_open and contains(AUDIO_FILTER_BOX, x, y):
                                gesture = "audio_filter"
                            elif audio_panel_open:
                                gesture = "audio_panel_outside"
                            elif filter_panel_open and contains(FILTER_EDIT_BOX, x, y):
                                _mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
                                filter_drag_audio_center = filter_center_hz(low_cut, high_cut)
                                filter_drag_center = 0.0
                                view_low_cut, view_high_cut = filter_view_offsets(low_cut, high_cut)
                                filter_drag_limit = filter_edit_limit(view_low_cut, view_high_cut)
                                low_x = filter_x(
                                    view_low_cut,
                                    FILTER_EDIT_BOX[0],
                                    FILTER_EDIT_BOX[2],
                                    filter_drag_limit,
                                    filter_drag_center,
                                )
                                high_x = filter_x(
                                    view_high_cut,
                                    FILTER_EDIT_BOX[0],
                                    FILTER_EDIT_BOX[2],
                                    filter_drag_limit,
                                    filter_drag_center,
                                )
                                nearest_edge = "low" if abs(x - low_x) <= abs(x - high_x) else "high"
                                nearest_x = low_x if nearest_edge == "low" else high_x
                                if abs(x - nearest_x) <= FILTER_HANDLE_TOUCH_PX:
                                    gesture = "filter_drag"
                                    filter_drag_edge = nearest_edge
                                else:
                                    gesture = "filter_workspace"
                            elif filter_panel_open and (
                                contains(FILTER_WIDTH_MINUS_BOX, x, y)
                                or contains(FILTER_WIDTH_LABEL_BOX, x, y)
                                or contains(FILTER_WIDTH_PLUS_BOX, x, y)
                            ):
                                gesture = "filter_controls"
                            elif filter_panel_open and contains(FILTER_PANEL_BOX, x, y):
                                gesture = "filter_idle"
                            elif filter_panel_open:
                                gesture = "filter_edit_outside"
                            elif radio_setup_open and contains(RADIO_PANEL_BOX, x, y):
                                gesture = "radio_setup"
                            elif radio_setup_open:
                                gesture = "radio_setup_outside"
                            elif display_setup_open and contains(DISPLAY_PANEL_BOX, x, y):
                                gesture = "display_setup"
                            elif display_setup_open:
                                gesture = "display_setup_outside"
                            elif menu_open and contains(MENU_CLOSE_BOX, x, y):
                                gesture = "menu_close"
                            elif menu_open and contains(MENU_BOX, x, y):
                                gesture = "menu"
                            elif menu_open:
                                gesture = "menu_outside"
                            elif not picker_open and contains(ZOOM_PLUS_BOX, x, y):
                                gesture = "zoom_plus"
                            elif not picker_open and contains(ZOOM_MINUS_BOX, x, y):
                                gesture = "zoom_minus"
                            elif not picker_open and contains(SPECTRUM_TOGGLE_BOX, x, y):
                                gesture = "spectrum_toggle"
                            elif not picker_open and contains(FILTER_TOGGLE_BOX, x, y):
                                gesture = "filter_toggle"
                            elif picker_open and search_open:
                                gesture = "search"
                            elif picker_open and contains(PICKER_SEARCH_BOX, x, y):
                                gesture = "picker_search"
                            elif picker_open and contains(PICKER_SORT_LOCATION_BOX, x, y):
                                gesture = "picker_sort_location"
                            elif picker_open and contains(PICKER_SORT_NAME_BOX, x, y):
                                gesture = "picker_sort_name"
                            elif picker_open and contains(PICKER_EXIT_BOX, x, y):
                                gesture = "picker_exit"
                            elif picker_open and contains(PICKER_BOX, x, y):
                                gesture = "picker"
                            elif not picker_open and is_waterfall_tune_touch(x, y):
                                gesture = "waterfall"
                            else:
                                gesture = "none"
                        elif gesture == "picker":
                            row_h = max(1, (PICKER_BOX[3] - PICKER_BOX[1] - 42) // PICKER_ROWS)
                            row_delta = int(round((start_y - y) / row_h))
                            station_scroll = clamp(start_scroll + row_delta * PICKER_COLS, 0, station_page_max(stations))
                        elif gesture == "menu":
                            menu_scroll = clamp(start_menu_scroll + (start_x - x), 0.0, menu_max_scroll())
                        elif gesture == "audio_volume":
                            desired_volume = audio_volume_at_x(x)
                            if (audio_volume is None or abs(desired_volume - audio_volume) >= 0.01) and time.monotonic() - audio_volume_last_apply >= 0.10:
                                applied_volume = set_pipewire_default_volume(desired_volume)
                                if applied_volume is not None:
                                    audio_volume = applied_volume
                                    audio_volume_last_apply = time.monotonic()
                        elif gesture == "filter_drag" and contains(FILTER_EDIT_BOX, x, y):
                            _mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
                            cut_hz = filter_cut_at_x(
                                x,
                                FILTER_EDIT_BOX[0],
                                FILTER_EDIT_BOX[2],
                                filter_drag_limit,
                                filter_drag_center,
                            )
                            audio_cut_hz = cut_hz + filter_drag_audio_center
                            if filter_drag_edge == "low":
                                next_low, next_high, _radio_generation = state.set_filter(low_cut=audio_cut_hz, high_cut=high_cut)
                            else:
                                next_low, next_high, _radio_generation = state.set_filter(low_cut=low_cut, high_cut=audio_cut_hz)
                            if (next_low, next_high) != (low_cut, high_cut):
                                filter_custom_width = True
                        elif gesture in ("zoom_plus", "zoom_minus"):
                            if is_waterfall_band_touch(start_x, start_y) and abs(x - start_x) >= args.swipe_start_px:
                                gesture = "waterfall"
                                start_freq = display_freq
                                start_span = display_span
                                candidate_freq = start_freq
                                last_move_x = start_x
                                last_move_t = start_time
                                swipe_velocity_px_s = 0.0
                                begin_swipe(x)
                                advance_waterfall_drag(x)
                        elif gesture == "waterfall":
                            last_x = x
                            if not swipe_started and abs(x - start_x) >= args.swipe_start_px:
                                begin_swipe(x)
                            if swipe_started:
                                advance_waterfall_drag(x)
                    else:
                        if touch_started and gesture == "home":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                wake_controls()
                                menu_open = not menu_open
                                menu_opened_at = time.monotonic() if menu_open else 0.0
                                picker_open = False
                                radio_setup_open = False
                                display_setup_open = False
                                audio_panel_open = False
                                filter_panel_open = False
                                menu_scroll = 0.0
                                station_scroll = 0
                        elif touch_started and gesture == "radio_toggle":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                wake_controls()
                                radio_setup_open = not radio_setup_open
                                menu_open = False
                                picker_open = False
                                display_setup_open = False
                                audio_panel_open = False
                                filter_panel_open = False
                        elif touch_started and gesture == "audio_volume":
                            applied_volume = set_pipewire_default_volume(audio_volume_at_x(x))
                            if applied_volume is not None:
                                audio_volume = applied_volume
                                audio_volume_last_apply = time.monotonic()
                            wake_controls()
                        elif touch_started and gesture == "audio_squelch":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                squelch_enabled, _audio_generation = state.audio_snapshot()
                                state.set_squelch(not squelch_enabled)
                            wake_controls()
                        elif touch_started and gesture == "audio_filter":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                audio_panel_open = False
                                filter_panel_open = True
                            wake_controls()
                        elif touch_started and gesture == "audio_panel_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                audio_panel_open = False
                            wake_controls()
                        elif touch_started and gesture == "radio_setup":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                choice = radio_option_at(x, y, radio_mode_page)
                                if choice is not None:
                                    kind, value = choice
                                    if kind == "mode":
                                        radio_mode = value
                                        manual_radio_mode = True
                                        filter_custom_width = False
                                        digital_mode = "IQ" if value == "IQ" else "DIG"
                                        state.set_radio_mode(radio_mode)
                                    elif kind == "mode_page":
                                        radio_mode_page = clamp(
                                            radio_mode_page + value,
                                            0,
                                            len(KIWI_MODE_PAGES) - 1,
                                        )
                                    elif kind == "digital":
                                        digital_mode = value
                                    else:
                                        tune_step_hz = value
                                    wake_controls()
                                    print(f"gl radio {radio_mode} {digital_mode} step {tune_step_hz} Hz", flush=True)
                        elif touch_started and gesture == "radio_setup_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                radio_setup_open = False
                                wake_controls()
                        elif touch_started and gesture == "filter_controls":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                _mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
                                if contains(FILTER_WIDTH_MINUS_BOX, x, y):
                                    width_hz = fine_filter_width(high_cut - low_cut, -1)
                                    state.set_filter(*symmetric_filter_bounds(low_cut, high_cut, width_hz))
                                    filter_custom_width = True
                                elif contains(FILTER_WIDTH_PLUS_BOX, x, y):
                                    width_hz = fine_filter_width(high_cut - low_cut, 1)
                                    state.set_filter(*symmetric_filter_bounds(low_cut, high_cut, width_hz))
                                    filter_custom_width = True
                                elif contains(FILTER_WIDTH_LABEL_BOX, x, y):
                                    width_name, width_hz = next_filter_preset(high_cut - low_cut)
                                    state.set_filter(*symmetric_filter_bounds(low_cut, high_cut, width_hz))
                                    filter_custom_width = False
                                    print(
                                        f"gl filter preset {width_name.lower()} {format_filter_width(width_hz)} {radio_mode}",
                                        flush=True,
                                    )
                                else:
                                    width_hz = None
                                if width_hz is not None and not contains(FILTER_WIDTH_LABEL_BOX, x, y):
                                    print(
                                        f"gl filter fine {format_filter_width(width_hz)} {radio_mode}",
                                        flush=True,
                                    )
                            wake_controls()
                        elif touch_started and gesture in ("filter_drag", "filter_idle", "filter_workspace"):
                            wake_controls()
                        elif touch_started and gesture == "filter_edit_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                filter_panel_open = False
                                wake_controls()
                        elif touch_started and gesture == "display_setup":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                choice = display_option_at(x, y)
                                if choice is not None:
                                    kind, value = choice
                                    floor, ceiling, speed, auto, palette, _generation = state.waterfall_snapshot()
                                    if kind == "spectrum":
                                        state.set_spectrum_enabled(not state.spectrum_snapshot()[0])
                                    elif kind == "auto":
                                        auto = not auto
                                    elif kind == "floor":
                                        floor += value
                                        auto = False
                                    elif kind == "ceil":
                                        ceiling += value
                                        auto = False
                                    elif kind == "rate":
                                        speed = value
                                    else:
                                        palette = value
                                    floor, ceiling, speed, auto, palette, _generation = state.set_waterfall(
                                        floor=floor,
                                        ceil=ceiling,
                                        speed=speed,
                                        auto=auto,
                                        palette=palette,
                                    )
                                    wake_controls()
                                    print(f"gl display floor={floor:.0f} ceil={ceiling:.0f} auto={int(auto)} rate={speed} palette={palette}", flush=True)
                        elif touch_started and gesture == "display_setup_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                display_setup_open = False
                                wake_controls()
                        elif touch_started and gesture == "menu":
                            menu_opened_at = time.monotonic()
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                idx = menu_at(x, y, menu_scroll)
                                if idx is not None:
                                    kind, label = MENU_ITEMS[idx]
                                    wake_controls()
                                    if kind == "rx":
                                        picker_open = True
                                        menu_open = False
                                        radio_setup_open = False
                                        display_setup_open = False
                                        audio_panel_open = False
                                        filter_panel_open = False
                                        station_scroll = 0
                                        station_query = ""
                                        station_sort = "location"
                                        stations = filtered_stations(all_stations, station_query, station_sort)
                                        search_open = False
                                    elif kind == "display":
                                        display_setup_open = True
                                        menu_open = False
                                        radio_setup_open = False
                                        audio_panel_open = False
                                        filter_panel_open = False
                                    elif kind == "radio":
                                        radio_setup_open = True
                                        menu_open = False
                                        display_setup_open = False
                                        audio_panel_open = False
                                        filter_panel_open = False
                                    elif kind == "audio":
                                        audio_volume = pipewire_default_volume()
                                        audio_panel_open = True
                                        menu_open = False
                                        radio_setup_open = False
                                        display_setup_open = False
                                        filter_panel_open = False
                                    else:
                                        print(f"gl menu {label} pending", flush=True)
                        elif touch_started and gesture in ("menu_close", "menu_outside"):
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                wake_controls()
                                menu_open = False
                                menu_scroll = 0.0
                        elif touch_started and gesture in ("zoom_plus", "zoom_minus"):
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                change_zoom(1 if gesture == "zoom_plus" else -1)
                        elif touch_started and gesture == "spectrum_toggle":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                state.set_spectrum_enabled(not state.spectrum_snapshot()[0])
                                wake_controls()
                        elif touch_started and gesture == "filter_toggle":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                filter_panel_open = True
                                menu_open = False
                                radio_setup_open = False
                                display_setup_open = False
                                audio_panel_open = False
                                wake_controls()
                        elif touch_started and gesture == "search":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                if contains(SEARCH_EXIT_BOX, x, y) or contains(SEARCH_LEFT_EXIT_BOX, x, y):
                                    search_open = False
                                    station_scroll = 0
                                elif contains(SEARCH_CASE_BOX, x, y):
                                    if keyboard_mode != "numeric":
                                        keyboard_mode = "lower" if keyboard_mode == "upper" else "upper"
                                elif contains(SEARCH_MODE_BOX, x, y):
                                    keyboard_mode = "upper" if keyboard_mode == "numeric" else "numeric"
                                else:
                                    key = search_key_at(x, y, keyboard_mode)
                                    if key == "BACK":
                                        station_query = station_query[:-1]
                                    elif key == "ENTER":
                                        search_open = False
                                    elif key and len(station_query) < 48:
                                        station_query += key
                                    stations = filtered_stations(all_stations, station_query, station_sort)
                                    station_scroll = 0
                        elif touch_started and gesture == "picker_exit":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                picker_open = False
                                search_open = False
                                station_scroll = 0
                                wake_controls()
                        elif touch_started and gesture == "picker_search":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                search_open = True
                                keyboard_mode = "lower"
                        elif touch_started and gesture in ("picker_sort_location", "picker_sort_name"):
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                station_sort = "location" if gesture == "picker_sort_location" else "name"
                                stations = filtered_stations(all_stations, station_query, station_sort)
                                station_scroll = 0
                        elif touch_started and gesture == "picker":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                # Resolve the tap against the same health-prioritized
                                # sequence currently rendered. Using `stations` here
                                # selected a different endpoint whenever active rows
                                # had been promoted ahead of their base sort position.
                                visible_stations = health_prioritized_stations(stations, station_health, station_sort)
                                idx = station_at(x, y, visible_stations, station_scroll)
                                if idx is not None:
                                    wake_controls()
                                    name, _location, server, *_capacity = visible_stations[idx]
                                    _server, freq_khz, zoom, _gen, _server_gen = state.set_server(server)
                                    remember_current_view()
                                    drain_queue(line_queue)
                                    wf_texture.clear()
                                    animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                                    picker_open = False
                                    station_scroll = 0
                                    zoom_osd_until = time.monotonic() + args.zoom_osd_seconds
                                    print(f"gl station {name}: {server}", flush=True)
                        elif touch_started and gesture == "waterfall":
                            wake_controls()
                            moved = abs((last_x if last_x is not None else x) - start_x)
                            _server, _freq, zoom, _smeter, _gen, _server_gen = state.snapshot()
                            if not swipe_started and moved <= args.tap_px:
                                candidate_freq = clamp(retune_from_tap(x, start_freq, start_span), 0.0, 30000.0)
                            elif not swipe_started:
                                candidate_freq = start_freq
                            candidate_freq = clamp(
                                snap_frequency_khz(candidate_freq, tune_step_hz),
                                0.0,
                                30000.0,
                            )
                            if args.swipe_inertia_strength > 0 and swipe_started and abs(swipe_velocity_px_s) >= args.swipe_inertia_min_px_s:
                                sensitivity = swipe_effective_sensitivity(swipe_velocity_px_s, args)
                                inertia_velocity_khz_s = (
                                    retune_delta_from_drag(swipe_velocity_px_s, start_span, args.invert_tune, sensitivity)
                                    * args.swipe_inertia_strength
                                )
                                inertia_last_t = time.monotonic()
                                display_freq = candidate_freq
                                print(f"gl inertial tune {candidate_freq:.3f} kHz velocity {inertia_velocity_khz_s:.2f} kHz/s", flush=True)
                            else:
                                inertia_velocity_khz_s = 0.0
                                display_freq = candidate_freq
                                state.set_view(freq_khz=candidate_freq)
                                remember_current_view()
                                animate_to(candidate_freq, kiwi.zoom_to_span_khz(zoom), 0.001)
                                print(f"gl tuned {candidate_freq:.3f} kHz", flush=True)
                        touch_started = False
                        gesture = None
                        swipe_started = False
                        filter_drag_edge = None
                        filter_drag_center = 0.0
                        filter_drag_audio_center = 0.0
                        filter_drag_limit = FILTER_LIMIT_HZ
                        start_x = start_freq = last_x = None

            now = time.monotonic()
            if zoom_osd_requested.is_set():
                zoom_osd_until = now + args.zoom_osd_seconds
                zoom_osd_requested.clear()
            update_animation()
            inertia_active = False
            if not touch_started and abs(inertia_velocity_khz_s) > 0.01:
                dt = min(0.05, max(0.0, now - inertia_last_t))
                inertia_last_t = now
                display_freq = clamp(display_freq + inertia_velocity_khz_s * dt, 0.0, 30000.0)
                candidate_freq = display_freq
                inertia_velocity_khz_s *= math.exp(-dt / args.swipe_inertia_tau)
                inertia_active = True
                if abs(inertia_velocity_khz_s) <= 0.04:
                    inertia_velocity_khz_s = 0.0
                    state.set_view(freq_khz=display_freq)
                    remember_current_view()
                    print(f"gl tuned {display_freq:.3f} kHz", flush=True)
                    inertia_active = False
            server, freq_khz, zoom, _smeter_dbm, _generation, _server_generation = state.snapshot()
            smeter_dbm, smeter_peak_dbm = state.smeter_snapshot()
            # The bar itself remains frame-smooth. The numerical readout is
            # intentionally sampled at a calmer, radio-like 3.3 Hz cadence.
            if now >= next_smeter_readout_update:
                smeter_readout_dbm = smeter_dbm
                next_smeter_readout_update = now + SMETER_READOUT_INTERVAL_SECONDS
            if now >= next_health_reload:
                try:
                    station_health = json.loads(STATION_HEALTH_CACHE.read_text()).get("stations", {})
                except (OSError, ValueError, TypeError):
                    station_health = {}
                next_health_reload = now + 3.0
            if menu_open and time.monotonic() - menu_opened_at >= 5.0:
                menu_open = False
                menu_scroll = 0.0
            apply_band_default(freq_khz)
            if not touch_started and not inertia_active and time.monotonic() - anim_start > anim_duration:
                display_freq = freq_khz
                display_span = kiwi.zoom_to_span_khz(zoom)

            if now >= next_system_sample:
                next_system_sample = now + 2.0
                cpu_percent, cpu_sample = read_total_cpu_percent(cpu_sample)
                temp_c = read_cpu_temp_c()

            consumed = 0
            max_consume = 2 if line_queue.qsize() > 30 else 1
            while consumed < max_consume:
                try:
                    item = line_queue.get_nowait()
                    if isinstance(item, tuple):
                        line = item[0]
                    else:
                        line = item
                    wf_texture.push_line(line, display_freq, display_span)
                    consumed += 1
                except queue.Empty:
                    break

            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            draw_logical_rect(0, 0, LOGICAL_W, LOGICAL_H, (4, 7, 11, 255))
            focus_progress = waterfall_focus_progress(now)
            spectrum_enabled, spectrum_values, spectrum_peak_values = state.spectrum_snapshot()
            _state_mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
            spectrum_h = SPECTRUM_H if spectrum_enabled else 0
            # Keep scope compact and behind the top instrumentation. Its lower
            # edge now sits beside the S-meter, freeing the waterfall below.
            spectrum_y0 = sdr_ui.TOP_H - 8 if spectrum_enabled else sdr_ui.TOP_H + sdr_ui.RULER_H * (1.0 - focus_progress) - SPECTRUM_RAISE_Y * (1.0 - focus_progress)
            spectrum_y1 = spectrum_y0 + spectrum_h
            bottom_ruler = True
            ruler_height = BOTTOM_RULER_H if bottom_ruler else sdr_ui.RULER_H
            ruler_y0 = LOGICAL_H - BOTTOM_STATUS_H - ruler_height if bottom_ruler else sdr_ui.TOP_H
            ruler_background_alpha = 100 if bottom_ruler else 185
            normal_waterfall_y0 = spectrum_y0 + spectrum_h
            focus_waterfall_y0 = WATERFALL_FOCUS_Y0 + spectrum_h
            waterfall_y0 = normal_waterfall_y0 + (focus_waterfall_y0 - normal_waterfall_y0) * focus_progress
            normal_waterfall_y1 = LOGICAL_H if bottom_ruler else WATERFALL_Y1
            waterfall_y1 = normal_waterfall_y1 + (WATERFALL_FOCUS_Y1 - normal_waterfall_y1) * focus_progress
            # Anchor waterfall rows to the focus layout. Collapsing the
            # waterfall then covers rows under the ruler/status strip instead
            # of remapping the visible texture and making it appear to scroll up.
            row_offset = round(waterfall_y0 - focus_waterfall_y0)
            wf_texture.draw(0, waterfall_y0, LOGICAL_W, waterfall_y1, row_offset=row_offset)
            if spectrum_enabled:
                draw_spectrum(spectrum_y0, spectrum_y1, spectrum_values, spectrum_peak_values)
            overlay_low_cut, overlay_high_cut = filter_view_offsets(low_cut, high_cut)
            draw_filter_overlay(
                display_span,
                overlay_low_cut,
                overlay_high_cut,
                waterfall_y0,
                waterfall_y1,
                0.82,
            )
            control_alpha = 0.0 if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or filter_panel_open else controls_alpha(now)
            selected_station_name = next(
                (
                    bottom_station_title(name, location)
                    for name, location, candidate_server, *_capacity in all_stations
                    if candidate_server == server
                ),
                "",
            )
            connection_status = state.connection_snapshot()
            draw_ui(
                text_cache,
                display_freq,
                display_span,
                smeter_dbm,
                smeter_peak_dbm,
                smeter_readout_dbm,
                radio_mode,
                digital_mode,
                tune_step_hz,
                controls_alpha=control_alpha,
                focus_progress=focus_progress,
                ruler_y0=ruler_y0,
                ruler_height=ruler_height,
                ruler_background_alpha=ruler_background_alpha,
                bottom_ruler=bottom_ruler,
                spectrum_enabled=spectrum_enabled,
                cpu_percent=cpu_percent,
                temp_c=temp_c,
                station_name=selected_station_name,
                connection_status=connection_status,
            )
            if menu_open:
                draw_main_menu(text_cache, menu_scroll)
            if picker_open:
                if search_open:
                    draw_station_search(text_cache, all_stations, station_query, station_sort, keyboard_mode)
                else:
                    visible_stations = health_prioritized_stations(stations, station_health, station_sort)
                    draw_station_picker(text_cache, visible_stations, station_scroll, server, station_query, station_sort, station_health)
            if radio_setup_open:
                draw_radio_setup_panel(text_cache, radio_mode, digital_mode, tune_step_hz, radio_mode_page)
            if display_setup_open:
                wf_floor, wf_ceil, wf_speed, wf_auto, wf_palette, _wf_generation = state.waterfall_snapshot()
                spectrum_enabled, _spectrum_values, _spectrum_peak_values = state.spectrum_snapshot()
                draw_display_setup_panel(
                    text_cache,
                    wf_floor,
                    wf_ceil,
                    wf_speed,
                    wf_auto,
                    wf_palette,
                    spectrum_enabled,
                )
            if audio_panel_open:
                squelch_enabled, _audio_generation = state.audio_snapshot()
                _audio_mode, audio_low_cut, audio_high_cut, _audio_radio_generation = state.radio_snapshot()
                draw_audio_panel(
                    text_cache,
                    audio_volume,
                    squelch_enabled,
                    audio_low_cut,
                    audio_high_cut,
                    audio_volume is not None,
                )
            if filter_panel_open:
                draw_filter_setup_panel(text_cache, radio_mode, low_cut, high_cut, filter_custom_width)
            osd_remaining = zoom_osd_until - now
            if osd_remaining > 0:
                alpha = 220
                fade = min(0.45, args.zoom_osd_seconds * 0.33)
                if osd_remaining < fade:
                    alpha = int(220 * osd_remaining / fade)
                draw_zoom_osd(text_cache, zoom, kiwi.zoom_to_span_khz(zoom), alpha)
            if screenshot_requested.is_set():
                pixels = GL.glReadPixels(0, 0, NATIVE_W, NATIVE_H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
                screenshot = pygame.image.fromstring(pixels, (NATIVE_W, NATIVE_H), "RGBA", True)
                pygame.image.save(screenshot, str(args.screenshot_path))
                screenshot_requested.clear()
                print(f"gl screenshot: {args.screenshot_path}", flush=True)
            if Path("/tmp/kiwi-gl-screenshot").exists():
                pixels = GL.glReadPixels(0, 0, NATIVE_W, NATIVE_H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
                frame = pygame.image.frombuffer(pixels, (NATIVE_W, NATIVE_H), "RGBA")
                pygame.image.save(pygame.transform.flip(frame, False, True), "/tmp/kiwi-gl-screenshot.png")
                Path("/tmp/kiwi-gl-screenshot").unlink(missing_ok=True)
            pygame.display.flip()
            frames += 1
            if args.duration and time.monotonic() - start >= args.duration:
                break
            clock.tick(args.fps)
    finally:
        stop_event.set()
        ev.close()
        wf_thread.join(timeout=1.5)
        snd_thread.join(timeout=1.5)
        elapsed = max(0.001, time.monotonic() - start)
        print(f"gl frames={frames} fps={frames / elapsed:.1f}", flush=True)
        pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
