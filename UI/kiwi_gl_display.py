Warning: truncated output (original token count: 53937)
Total output lines: 4504

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
SMETER_PEAK_HOLD_SECONDS = 2.0
SMETER_PEAK_DECAY_DB_PER_SECOND = 9.0
SMETER_READOUT_INTERVAL_SECONDS = 0.30
# Kiwi delivers 512-frame raw packets at 12 kHz. Six packets make a 3072-frame
# (256 ms) PipeWire quantum: enough to cover the observed 107 ms network gap
# while keeping buffer boundaries aligned with the incoming PCM cadence.
PIPEWIRE_AUDIO_LATENCY = "3072"
# Touch may generate far more events than a public Kiwi receiver can use.
# The stream workers coalesce those events and transmit only the current
# position at this cadence, keeping a fast drag responsive without a backlog.
LIVE_TUNE_MIN_INTERVAL_SECONDS = 0.020
KIWI_IO_POLL_SECONDS = 0.010
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
HOME_BOX = (30, 13, 102, 71)
# The top instruments share one right alignment. Home is intentionally the
# single left-anchored control.
# The S legend sits left of the LED bars. Align to that true visual edge,
# leaving a 28 px quiet gap before the meter typography rather than its bars.
FREQUENCY_RIGHT_X = 590
RADIO_SETUP_WIDTH = 74
RADIO_SETUP_GAP = 10
RADIO_SETUP_BOX = (260, 10, 334, 54)
RADIO_PANEL_BOX = (12, 72, 948, 282)
KIWI_MODE_PAGES = (
    ("STANDARD", ("AM", "AMN", "AMW", "USB", "LSB", "USN", "LSN", "CW", "CWN", "NBFM")),
    ("SPECIAL", ("NNFM", "DRM", "IQ", "SAM", "SAU", "SAL", "SAS", "QAM")),
)
KIWI_RADIO_MODES = frozenset(mode for _page, modes in KIWI_MODE_PAGES for mode in modes)
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
# Thumb-safe exclusion around floating controls: nearby touches must never
# become a waterfall retune.
CONTROL_TOUCH_GUARD_PX = 32
WATERFALL_DRAG_START_PX = 14
WATERFALL_HORIZONTAL_DRAG_RATIO = 1.5
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
TEST_PANEL_BOX = (12, 72, 948, 288)
TEST_GLOBE_BOX = (42, 112, 468, 166)
TEST_DJ_BOX = (492, 112, 918, 166)
TEST_PATTERN_BOX = (42, 178, 918, 224)
TEST_RUN_BOX = (42, 236, 918, 280)
GLOBE_PANEL_BOX = (12, 72, 948, 312)
GLOBE_MAP_BOX = (30, 94, 560, 300)
GLOBE_BACK_BOX = (770, 88, 930, 120)
DJ_PANEL_BOX = (12, 72, 948, 288)
DJ_TRACK_BOX = (42, 130, 918, 205)
DJ_STEP_BOX = (42, 224, 240, 276)
DJ_RANGE_BOX = (258, 224, 456, 276)
DJ_RATE_BOX = (474, 224, 672, 276)
DJ_RETURN_BOX = (690, 224, 918, 276)
GEAR_BOX = (892, 228, 958, 294)
# Home is a temporary waterfall-scale workspace, leaving the top instrument
# strip and its Home affordance visible.
MENU_BOX = (12, 72, 948, LOGICAL_H)
# Home remains visible above the overlay and is the single, unambiguous way
# to close this temporary workspace.
MENU_CLOSE_BOX = (0, 0, 0, 0)
MENU_COLS = 5
MENU_ROWS = 2
MENU_ITEMS = (
    ("rx", "RX"),
    ("audio", "AUDIO"),
    ("tests", "TESTS"),
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
GLOBE_DIRECTORY_URL = "http://rx.linkfanel.net/kiwisdr_com.js"
GLOBE_DIRECTORY_CACHE = Path.home() / ".local/state/kiwi-gl-globe-receivers.json"
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


def parse_globe_directory(script):
    """Read the public map feed without turning its JavaScript into trusted code."""
    receivers = []
    seen = set()
    # Map records are flat JSON-like objects. The feed occasionally contains
    # malformed control text, so extract only the fields Globe needs.
    for record in re.findall(r"\{(.*?)\n\s*\},?", script, re.S):
        gps = re.search(r'"gps"\s*:\s*"[^0-9-]*([-0-9.]+)\s*[, ]\s*([-0-9.]+)', record)
        url = re.search(r'"url"\s*:\s*"([^"]+)', record)
        if not gps or not url:
            continue
        try:
            lat, lon = float(gps.group(1)), float(gps.group(2))
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        server = html.unescape(url.group(1)).strip()
        if not server or server in seen:
            continue
        seen.add(server)
        def field(key, fallback=""):
            match = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"])*)"', record)
            return html.unescape(match.group(1).replace(r'\\"', '"')) if match else fallback
        name = field("name", "Public KiwiSDR")
        location = field("loc", "")
        try:
            used = int(field("users", "0"))
            total = int(field("users_max", "0"))
        except ValueError:
            used = total = 0
        receivers.append({"name": name, "location": location, "server": server, "lat": lat, "lon": lon, "used": used, "total": total})
    return receivers


def load_globe_receivers():
    """Fetch GPS receiver points in a worker; a saved map keeps Globe usable offline."""
    try:
        cached = json.loads(GLOBE_DIRECTORY_CACHE.read_text())
        if isinstance(cached, list):
            return cached
    except (OSError, ValueError, TypeError):
        return []
    return []


def refresh_globe_receivers(result):
    try:
        request = Request(GLOBE_DIRECTORY_URL, headers={"User-Agent": "KiwiTouch/1.0"})
        with urlopen(request, timeout=15) as response:
            receivers = parse_globe_directory(response.read().decode("utf-8", "replace"))
        if len(receivers) >= 100:
            GLOBE_DIRECTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            temporary = GLOBE_DIRECTORY_CACHE.with_suffix(".tmp")
            temporary.write_text(json.dumps(receivers, separators=(",", ":")))
            os.replace(temporary, GLOBE_DIRECTORY_CACHE)
            result.put(("ready", receivers))
            return
    except OSError as exc:
        result.put(("error", str(exc)))
        return
    result.put(("error", "public map returned no usable GPS receivers"))


def globe_haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(h)))


def choose_globe_triangle(anchor, receivers, health):
    """Choose a nearby, non-collinear receiver triangle with healthy audio first."""
    pool = sorted((r for r in receivers if r["server"] != anchor["server"]), key=lambda r: globe_haversine_km(anchor, r))[:18]
    if len(pool) < 2:
        return [anchor] + pool
    best = None
    for left_index, left in enumerate(pool[:-1]):
        for right in pool[left_index + 1:]:
            # Equirectangular local area is adequate for ranking nearby candidates.
            x1 = (left["lon"] - anchor["lon"]) * math.cos(math.radians(anchor["lat"]))
            y1 = left["lat"] - anchor["lat"]
            x2 = (right["lon"] - anchor["lon"]) * math.cos(math.radians(anchor["lat"]))
            y2 = right["lat"] - anchor["lat"]
            area = abs(x1 * y2 - y1 * x2)
            distance = globe_haversine_km(anchor, left) + globe_haversine_km(anchor, right)
            score = area / max(400.0, distance)
            if best is None or score > best[0]:
                best = (score, left, right)
    triangle = [anchor, best[1], best[2]] if best else [anchor] + pool[:2]
    # First healthy known audio endpoint becomes the audition receiver. The
    # remaining vertices stay in distance order as automatic fallbacks.
    healthy = [r for r in triangle if health.get(r["server"], {}).get("audio") is True]
    return healthy + [r for r in triangle if r not in healthy]


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


def contains_with_guard(box, x, y, guard=CONTROL_TOUCH_GUARD_PX):
    """Reserve a small touch-safe moat around overlay controls."""
    return (
        box[0] - guard <= x <= box[2] + guard
        and box[1] - guard <= y <= box[3] + guard
    )


def is_waterfall_tune_touch(x, y):
    if not (WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1):
        return False
    return not contains_with_guard(ZOOM_GROUP_BOX, x, y) and not contains_with_guard(VIEW_GROUP_BOX, x, y)


def is_waterfall_band_touch(x, y):
    return WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1


def is_deliberate_waterfall_drag(start_x, start_y, x, y, args):
    """Accept only an intentional horizontal waterfall-tuning gesture."""
    dx = abs(x - start_x)
    dy = abs(y - start_y)
    return (
        dx >= max(args.swipe_start_px, WATERFALL_DRAG_START_PX)
        and dx >= dy * WATERFALL_HORIZONTAL_DRAG_RATIO
    )


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


def finger_tune_step_hz(zoom, base_step_hz):
    """Use close zoom levels as a fine VFO without changing the base setting."""
    zoom = int(zoom)
    if zoom >= 14:
        return min(int(base_step_hz), 5)
    if zoom >= 13:
        return min(int(base_step_hz), 10)
    if zoom >= 12:
        return min(int(base_step_hz), 25)
    if zoom >= 11:
        return min(int(base_step_hz), 50)
    return int(base_step_hz)


RETUNE_TEST_PATTERNS = (
    ("GENTLE", "triangle", 8, 250, 0.10, 0.80),
    ("FAST", "triangle", 10, 250, 0.05, 0.35),
    ("JITTER", "jitter", 0, 0, 0.075, 0.0),
    # AM envelope audio does not pitch-shift on small retunes. These go just
    # beyond the normal +/-5 kHz AM receive passband, making a matched
    # +6.4 kHz excursion audible at slow, medium, and fast tune cadences.
    ("AM SLOW", "triangle", 16, 400, 0.16, 0.95),
    ("AM MED", "triangle", 16, 400, 0.09, 0.75),
    ("AM FAST", "triangle", 16, 400, 0.045, 0.35),
    # Four two-second scan legs: +50 kHz, centre, -50 kHz, centre. Twelve
    # moves per leg keeps the complete wide scan below the 50-command limit.
    ("SCAN +/-50k", "scan", 12, 50000, 2.0 / 12.0, 0.0),
    # FT8/SSB transition probe: one audible 50 Hz frequency increment every
    # 20 ms, 50 steps outward and 50 back. It completes in two seconds.
    ("SSB 50Hz 2s", "triangle", 50, 50, 0.020, 0.0),
    # Four seconds total: 0 -> +25 kHz -> -25 kHz -> 0. Its 200 small state
    # steps are intentionally never queued; a slower public Kiwi coalesces
    # only the stale intermediate receiver commands.
    ("SCAN +/-25k 4s", "cross_scan", 50, 25000, 0.020, 0.0),
)
RETUNE_TEST_MAX_COMMANDS = 200


def retune_test_schedule(pattern_index):
    """Return a short bounded sequence; no test can exceed 50 retunes."""
    name, shape, steps, step_hz, cadence, hold_s = RETUNE_TEST_PATTERNS[pattern_index]
    if shape == "triangle":
        offsets_hz = [step * step_hz for step in range(1, steps + 1)]
        offsets_hz.extend(step * step_hz for step in range(steps - 1, -1, -1))
        delays_s = [cadence] * len(offsets_hz)
        if hold_s > 0:
            delays_s[steps - 1] = hold_s
    elif shape == "jitter":
        offsets_hz = (250, -250, 500, -500, 750, -750, 500, -500, 250, -250, 0)
        delays_s = [cadence] * len(offsets_hz)
    elif shape == "scan":
        leg_step_hz = step_hz / steps
        positive = [step * leg_step_hz for step in range(1, steps + 1)]
        return_positive = [step * leg_step_hz for step in range(steps - 1, -1, -1)]
        negative = [-step * leg_step_hz for step in range(1, steps + 1)]
        return_negative = [-step * leg_step_hz for step in range(steps - 1, -1, -1)]
        offsets_hz = positive + return_positive + negative + return_negative
        delays_s = [cadence] * len(offsets_hz)
    else:
        increment_hz = step_hz / steps
        to_positive = [step * increment_hz for step in range(1, steps + 1)]
        through_negative = [step_hz - step * increment_hz for step in range(1, 2 * steps + 1)]
        return_to_center = [-step_hz + step * increment_hz for step in range(1, steps + 1)]
        offsets_hz = to_positive + through_negative + return_to_center
        delays_s = [cadence] * len(offsets_hz)
    if len(offsets_hz) > RETUNE_TEST_MAX_COMMANDS:
        raise ValueError("retune test command limit exceeded")
    return name, tuple(offset / 1000.0 for offset in offsets_hz), tuple(delays_s)


class RetuneSweep:
    """A clocked test with no command queue or delayed catch-up behavior."""

    def __init__(self, start_khz, pattern_index, now):
        self.start_khz = start_khz
        self.name, self.offsets_khz, self.delays_s = retune_test_schedule(pattern_index)
        self.index = 0
        self.next_due = now + self.delays_s[0]

    @property
    def command_count(self):
        return len(self.offsets_khz)

    def advance(self, now):
        if self.index >= self.command_count or now < self.next_due:
            return None
        frequency_khz = self.start_khz + self.offsets_khz[self.index]
        self.next_due = now + self.delays_s[self.index]
        self.index += 1
        return frequency_khz, self.index >= self.command_count


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
            radio_mode = saved.get("radio_mode")
            if isinstance(radio_mode, str) and radio_mode.upper() in KIWI_RADIO_MODES:
                view["radio_mode"] = radio_mode.upper()
            return view
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_remembered_view(path, server, freq_khz, zoom, radio_mode=None, manual_radio_mode=False):
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
        if manual_radio_mode and isinstance(radio_mode, str) and radio_mode.upper() in KIWI_RADIO_MODES:
            saved["radio_mode"] = radio_mode.upper()
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
        self.live_tune_rate_hz = round(1.0 / LIVE_TUNE_MIN_INTERVAL_SECONDS)
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

    def tune_rate_snapshot(self):
        with self.lock:
            return self.live_tune_rate_hz

    def set_tune_rate(self, rate_hz):
        with self.lock:
            self.live_tune_rate_hz = int(clamp(int(rate_hz), 1, 100))
            return self.live_tune_rate_hz

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


def draw_logical_circle(cx, cy, radius, color, segments=72, outline=False):
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glBegin(GL.GL_LINE_LOOP if outline else GL.GL_TRIANGLE_FAN)
    if not outline:
        GL.glVertex2f(*logical_to_native(cx, cy))
    for index in range(segments + (1 if not outline else 0)):
        theta = (index % segments) * math.tau / segments
        GL.glVertex2f(*logical_to_native(cx + radius * math.cos(theta), cy + radius * math.sin(theta)))
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
        # A darkened glass substrate protects white icons from the active,
        # high-luminance waterfall while retaining a light translucent feel.
        pygame.draw.rect(hi, (13, 21, 28, 128), pill, border_radius=p(24))
        pygame.draw.rect(hi, (202, 216, 220, 52), pill, p(1), border_radius=p(24))
        pygame.draw.line(hi, (255, 255, 255, 38), (p(21), p(8)), (p(w - 21), p(8)), p(1))
        for separator_x in separators:
            pygame.draw.line(hi, (1, 5, 8, 118), (p(separator_x), p(13)), (p(separator_x), p(h - separator_bottom)), p(1))
            pygame.draw.line(hi, (235, 244, 247, 52), (p(separator_x + 1), p(13)), (p(separator_x + 1), p(h - separator_bottom)), p(1))
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
    …23937 tokens truncated…om=new_zoom)
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
        sensitivity = (
            args.swipe_slow_sensitivity
            if args.finger_tune_positional
            else swipe_effective_sensitivity(swipe_velocity_px_s, args) * live_swipe_boost
        )
        candidate_freq = clamp(
            candidate_freq + retune_delta_from_drag(dx, start_span, args.invert_tune, sensitivity),
            0.0,
            30000.0,
        )
        # A normal waterfall drag is a live, positional tuning control. The
        # active zoom supplies the travel range, while the radio step supplies
        # tactile detents. Publishing state here lets the two Kiwi streams
        # follow the finger; their workers coalesce to the newest request.
        _server, _live_freq, active_zoom, _smeter, _generation, _server_generation = state.snapshot()
        live_step_hz = finger_tune_step_hz(active_zoom, tune_step_hz)
        live_candidate_freq = snap_frequency_khz(candidate_freq, live_step_hz)
        last_move_x = x
        last_move_t = now_move
        display_freq = live_candidate_freq
        _server, live_freq, _zoom, _smeter, _generation, _server_generation = state.snapshot()
        if live_freq != live_candidate_freq:
            state.set_view(freq_khz=live_candidate_freq)

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
                            # Any new operator gesture takes ownership from a
                            # running test. The run button itself is exempt so
                            # it remains an immediate, obvious Stop control.
                            if retune_sweep is not None and not (
                                tests_panel_open and contains(TEST_RUN_BOX, x, y)
                            ):
                                stop_retune_sweep("interrupted")
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
                            start_freq = display_freq if not menu_open and not picker_open and not radio_setup_open and not display_setup_open and not audio_panel_open and not tests_panel_open and not globe_open and not dj_tune_open and not filter_panel_open else freq_khz
                            start_span = display_span
                            candidate_freq = start_freq
                            if waterfall_focus_progress() > 0.01:
                                wake_controls()
                                gesture = "wake"
                            elif contains(HOME_BOX, x, y):
                                gesture = "home"
                            elif contains(top_instrument_layout(text_cache, display_freq)[1], x, y):
                                gesture = "radio_toggle"
                            elif audio_panel_open and contains(AUDIO_VOLUME_BOX, x, y):
                                gesture = "audio_volume"
                            elif audio_panel_open and contains(AUDIO_SQUELCH_BOX, x, y):
                                gesture = "audio_squelch"
                            elif audio_panel_open and contains(AUDIO_FILTER_BOX, x, y):
                                gesture = "audio_filter"
                            elif audio_panel_open:
                                gesture = "audio_panel_outside"
                            elif dj_tune_open and contains(DJ_TRACK_BOX, x, y):
                                dj_drag_remainder_hz = 0.0
                                gesture = "dj_tune"
                            elif dj_tune_open and (
                                contains(DJ_STEP_BOX, x, y)
                                or contains(DJ_RANGE_BOX, x, y)
                                or contains(DJ_RATE_BOX, x, y)
                                or contains(DJ_RETURN_BOX, x, y)
                            ):
                                gesture = "dj_controls"
                            elif dj_tune_open:
                                gesture = "dj_tune_outside"
                            elif globe_open and contains(GLOBE_BACK_BOX, x, y):
                                gesture = "globe_back"
                            elif globe_open and contains(GLOBE_PANEL_BOX, x, y):
                                globe_start_yaw = globe_yaw
                                globe_start_pitch = globe_pitch
                                globe_pinch_distance = None
                                gesture = "globe"
                            elif globe_open:
                                gesture = "globe_outside"
                            elif tests_panel_open and contains(TEST_PANEL_BOX, x, y):
                                gesture = "tests_panel"
                            elif tests_panel_open:
                                gesture = "tests_panel_outside"
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
                            # The Home screen is a fixed two-row grid; keep a
                            # finger within its original tile until release.
                            pass
                        elif gesture == "audio_volume":
                            desired_volume = audio_volume_at_x(x)
                            if (audio_volume is None or abs(desired_volume - audio_volume) >= 0.01) and time.monotonic() - audio_volume_last_apply >= 0.10:
                                applied_volume = set_pipewire_default_volume(desired_volume)
                                if applied_volume is not None:
                                    audio_volume = applied_volume
                                    audio_volume_last_apply = time.monotonic()
                        elif gesture == "dj_tune":
                            advance_dj_tune(x - last_move_x)
                            last_move_x = x
                        elif gesture == "globe":
                            if len(points) >= 2:
                                px0, py0 = points[0]
                                px1, py1 = points[1]
                                distance = math.hypot(px1 - px0, py1 - py0)
                                if globe_pinch_distance is None:
                                    globe_pinch_distance = max(1.0, distance)
                                else:
                                    globe_scale = clamp(globe_scale * (distance / globe_pinch_distance), 0.72, 1.35)
                                    globe_pinch_distance = max(1.0, distance)
                            else:
                                globe_pinch_distance = None
                                globe_yaw = globe_start_yaw + (x - start_x) * 0.011
                                globe_pitch = clamp(globe_start_pitch - (y - start_y) * 0.008, math.radians(-48), math.radians(48))
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
                            # A control owns its entire touch from press to
                            # release. It must never leak into waterfall
                            # tuning, even if the finger slides away from it.
                            pass
                        elif gesture == "waterfall":
                            last_x = x
                            if not swipe_started and is_deliberate_waterfall_drag(start_x, start_y, x, y, args):
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
                                tests_panel_open = False
                                globe_open = False
                                if dj_tune_open:
                                    restore_dj_origin("closed")
                                    dj_tune_open = False
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
                                tests_panel_open = False
                                globe_open = False
                                if dj_tune_open:
                                    restore_dj_origin("closed")
                                    dj_tune_open = False
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
                        elif touch_started and gesture == "dj_tune":
                            wake_controls()
                        elif touch_started and gesture == "dj_controls":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                if contains(DJ_STEP_BOX, x, y):
                                    steps = (50, 100, 250)
                                    dj_step_hz = steps[(steps.index(dj_step_hz) + 1) % len(steps)]
                                elif contains(DJ_RANGE_BOX, x, y):
                                    ranges = (2.5, 5.0, 10.0)
                                    dj_range_khz = ranges[(ranges.index(dj_range_khz) + 1) % len(ranges)]
                                    dj_current_khz = clamp(
                                        dj_current_khz,
                                        dj_origin_khz - dj_range_khz,
                                        dj_origin_khz + dj_range_khz,
                                    )
                                    set_test_frequency(dj_current_khz)
                                elif contains(DJ_RATE_BOX, x, y):
                                    rate_options = tuple(range(10, 101, 10))
                                    current_rate = state.tune_rate_snapshot()
                                    state.set_tune_rate(rate_options[(rate_options.index(current_rate) + 1) % len(rate_options)])
                                elif contains(DJ_RETURN_BOX, x, y):
                                    restore_dj_origin("return")
                            wake_controls()
                        elif touch_started and gesture == "dj_tune_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                restore_dj_origin("closed")
                                dj_tune_open = False
                            wake_controls()
                        elif touch_started and gesture == "globe_back":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                globe_open = False
                                tests_panel_open = True
                            wake_controls()
                        elif touch_started and gesture == "globe":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px and globe_receivers:
                                # Resolve against visible dots. This naturally selects the
                                # receiver cluster under the operator's finger.
                                candidates = []
                                for receiver in globe_receivers:
                                    point = globe_project(receiver, globe_yaw, globe_pitch, 294, 199, 101 * globe_scale)
                                    if point:
                                        candidates.append((math.hypot(point[0] - x, point[1] - y), receiver))
                                if candidates:
                                    _distance, anchor = min(candidates, key=lambda item: item[0])
                                    globe_triangle = choose_globe_triangle(anchor, globe_receivers, station_health)
                                    globe_failover = list(globe_triangle)
                                    selected = globe_failover.pop(0)
                                    globe_status = "Connecting live audio; triangle has two ready fallbacks"
                                    _server, freq_khz, zoom, _gen, _server_gen = state.set_server(selected["server"])
                                    remember_current_view()
                                    drain_queue(line_queue)
                                    wf_texture.clear()
                                    animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                                    globe_failover_deadline = time.monotonic() + 5.0
                                    globe_open = False
                                    print(f"gl globe audition {selected['name']}: {selected['server']}", flush=True)
                            wake_controls()
                        elif touch_started and gesture == "globe_outside":
                            wake_controls()
                        elif touch_started and gesture == "tests_panel":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                choice = tests_option_at(x, y)
                                if choice == "globe":
                                    tests_panel_open = False
                                    globe_open = True
                                    if not globe_fetch_started:
                                        globe_fetch_started = True
                                        threading.Thread(target=refresh_globe_receivers, args=(globe_result_queue,), daemon=True).start()
                                elif choice == "dj":
                                    tests_panel_open = False
                                    open_dj_tune()
                                elif choice == "pattern" and retune_sweep is None:
                                    retune_pattern_index = (retune_pattern_index + 1) % len(RETUNE_TEST_PATTERNS)
                                elif choice == "run":
                                    if retune_sweep is None:
                                        start_retune_sweep()
                                    else:
                                        stop_retune_sweep("stopped")
                            wake_controls()
                        elif touch_started and gesture == "tests_panel_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                tests_panel_open = False
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
                                        remember_current_view()
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
                                        tests_panel_open = False
                                        dj_tune_open = False
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
                                        tests_panel_open = False
                                        dj_tune_open = False
                                        filter_panel_open = False
                                    elif kind == "radio":
                                        radio_setup_open = True
                                        menu_open = False
                                        display_setup_open = False
                                        audio_panel_open = False
                                        tests_panel_open = False
                                        dj_tune_open = False
                                        filter_panel_open = False
                                    elif kind == "audio":
                                        audio_volume = pipewire_default_volume()
                                        audio_panel_open = True
                                        menu_open = False
                                        radio_setup_open = False
                                        display_setup_open = False
                                        tests_panel_open = False
                                        dj_tune_open = False
                                        filter_panel_open = False
                                    elif kind == "tests":
                                        tests_panel_open = True
                                        menu_open = False
                                        picker_open = False
                                        radio_setup_open = False
                                        display_setup_open = False
                                        audio_panel_open = False
                                        dj_tune_open = False
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
                                tests_panel_open = False
                                dj_tune_open = False
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
                            if not swipe_started:
                                # Tuning is drag-only. A tap now just wakes
                                # the controls, preventing a thumb near an
                                # overlay from jumping the receiver.
                                candidate_freq = start_freq
                            live_step_hz = finger_tune_step_hz(zoom, tune_step_hz)
                            candidate_freq = clamp(
                                snap_frequency_khz(candidate_freq, live_step_hz),
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
            advance_retune_sweep(now)
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
            while True:
                try:
                    globe_result, globe_payload = globe_result_queue.get_nowait()
                except queue.Empty:
                    break
                if globe_result == "ready":
                    globe_receivers = globe_payload
                    globe_status = f"{len(globe_receivers)} GPS receivers ready"
                else:
                    globe_status = "Map feed unavailable; using saved GPS map"
            if globe_failover and now >= globe_failover_deadline and state.connection_snapshot() in ("failed", "retrying"):
                fallback = globe_failover.pop(0)
                _server, freq_khz, zoom, _gen, _server_gen = state.set_server(fallback["server"])
                remember_current_view()
                drain_queue(line_queue)
                wf_texture.clear()
                animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                globe_status = "Previous receiver unavailable; auditioning triangle fallback"
                globe_failover_deadline = now + 5.0
                print(f"gl globe fallback {fallback['name']}: {fallback['server']}", flush=True)
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
            # The bottom ruler lives over live waterfall energy. Give its
            # labels a steadier dark substrate without flattening the view.
            ruler_background_alpha = 150 if bottom_ruler else 185
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
            control_alpha = 0.0 if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or tests_panel_open or globe_open or dj_tune_open or filter_panel_open else controls_alpha(now)
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
                finger_tune_step_hz(zoom, tune_step_hz),
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
            if tests_panel_open:
                draw_tests_panel(text_cache, retune_pattern_index, retune_sweep)
            if globe_open:
                draw_globe_panel(text_cache, globe_receivers, globe_yaw, globe_pitch, globe_scale, globe_triangle, globe_status)
            if dj_tune_open:
                draw_dj_tune_panel(
                    text_cache,
                    dj_origin_khz,
                    dj_current_khz,
                    dj_step_hz,
                    dj_range_khz,
                    state.tune_rate_snapshot(),
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
