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

try:
    # `audioop` was removed in Python 3.13. It is only needed for the local
    # CoreAudio convenience player; the Pi's PipeWire path does not use it.
    import audioop
except ImportError:
    audioop = None

# The deployed radio is a KMSDRM fullscreen application. On macOS, leave SDL
# on its native Cocoa backend so --desktop can open a normal dev window.
if sys.platform.startswith("linux"):
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
DESKTOP_MODE = False
DESKTOP_AUDIO_VOLUME = 1.0
WATERFALL_Y0 = sdr_ui.TOP_H + sdr_ui.RULER_H - 12
WATERFALL_Y1 = 292
WATERFALL_FOCUS_Y0 = sdr_ui.TOP_H
WATERFALL_FOCUS_Y1 = LOGICAL_H
SPECTRUM_H = 70
SPECTRUM_RAISE_Y = 12
SPECTRUM_BINS = 240
SPECTRUM_PEAK_HOLD_SECONDS = 10.0
SCOUT_HEAT_REMANENCE_SECONDS = 1800.0
SCOUT_RF_SAMPLE_SECONDS = 1.5
SCOUT_RF_CONNECT_TIMEOUT_SECONDS = 7.0
SCOUT_SNR_NOISE_SECONDS = 0.5
SCOUT_SNR_OFFSET_KHZ = 5.0
SCOUT_PROMOTION_MARGIN_DB = 8.0
SCOUT_PROMOTION_COOLDOWN_SECONDS = 45.0
SCOUT_PROMOTION_REVIEW_SECONDS = 8.0
CONSTELLATION_MIN_SEPARATION_KM = 180.0
CONSTELLATION_WARM_RADIUS_KM = 3218.7  # 2,000 statute miles
SCOUT_INITIAL_HEAT_RADIUS_KM = 1609.3  # 1,000 statute miles
SCOUT_SEARCH_START_KM = 805.0  # 500 statute miles
SCOUT_SEARCH_STEP_KM = 805.0
SCOUT_SEARCH_MAX_KM = 16000.0
SCOUT_LOCAL_ROUNDS = 3
SCOUT_GLOBAL_CELL_BONUS_KM = 3500.0
# Each rendered SNR tile is four times the former area. This deliberately
# favors a legible, receiver-backed field over a sparse cloud of tiny points.
SCOUT_HEAT_GRID_PIXELS = 40.0
SCOUT_HEAT_AREA_MULTIPLIER = 4.0
SCOUT_ROTATION_SECONDS = 15.0
SCOUT_MAX_TOTAL = 100
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
FREQUENCY_RIGHT_X = 570
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
GLOBE_PANEL_BOX = (0, 0, LOGICAL_W, LOGICAL_H)
GLOBE_MAP_BOX = (12, 40, 580, 258)
GLOBE_BACK_BOX = (466, 6, 578, 34)
GLOBE_INFO_BOX = (594, 0, 948, LOGICAL_H)
GLOBE_SCOUT_BAR_BOX = (12, 268, 580, 316)
# Constellation keeps three listenable streams warm. The four scouts are
# represented by the heat field, rather than a geometric receiver polygon.
GLOBE_STATION_BOXES = (
    (604, 46, 938, 126),
    (604, 134, 938, 214),
    (604, 222, 938, 302),
)
def load_globe_coastlines():
    """Load genuine Natural Earth land outlines, decimated for the small panel."""
    try:
        payload = json.loads((Path(__file__).parent / "assets" / "ne_110m_land.geojson").read_text())
    except (OSError, ValueError, TypeError):
        return ()
    outlines = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 3:
                    continue
                stride = max(1, len(ring) // 72)
                simplified = ring[::stride]
                if simplified[-1] != ring[-1]:
                    simplified.append(ring[-1])
                outlines.append(tuple((float(lat), float(lon)) for lon, lat, *_rest in simplified))
    return tuple(outlines)


GLOBE_COASTLINES = load_globe_coastlines()
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


def choose_constellation(center, receivers, health):
    """Pick three warmed listeners and four nearby rotating scout targets.

    Listener selection uses the persisted stream-readiness observation when it
    exists, while keeping stations geographically distinct. Scouts deliberately
    stay nearby so their heat field describes local reception alternatives, not
    an arbitrary pentagon or other artificial shape.
    """
    if not center:
        return [], []

    def readiness(receiver):
        return health.get(receiver["server"], {}).get("audio") is True

    listeners = [center]
    remaining = [receiver for receiver in receivers if receiver["server"] != center["server"]]
    while remaining and len(listeners) < 3:
        def stream_score(receiver):
            anchor_distance = globe_haversine_km(center, receiver)
            nearest_listener = min(globe_haversine_km(receiver, listener) for listener in listeners)
            readiness_penalty = 0.0 if readiness(receiver) else 0.35
            radius_penalty = abs(anchor_distance - CONSTELLATION_WARM_RADIUS_KM) / CONSTELLATION_WARM_RADIUS_KM
            separation_penalty = max(0.0, CONSTELLATION_MIN_SEPARATION_KM - nearest_listener) / CONSTELLATION_MIN_SEPARATION_KM
            return readiness_penalty + radius_penalty + separation_penalty

        selected = min(remaining, key=stream_score)
        listeners.append(selected)
        remaining.remove(selected)

    listener_servers = {receiver["server"] for receiver in listeners}
    scouts = [
        receiver for receiver in sorted(receivers, key=lambda receiver: globe_haversine_km(center, receiver))
        if receiver["server"] not in listener_servers
    ][:4]
    return listeners, scouts


def choose_scout_promotion(listeners, active_server, scouts, scout_measurements, listener_measurements, now):
    """Return a materially stronger scout that can safely replace a standby."""
    best = None
    for scout in scouts:
        scout_sample = scout_measurements.get(scout["server"], {})
        scout_dbm = scout_sample.get("smeter")
        if scout_dbm is None or now - scout_sample.get("sampled_at", 0.0) > 12.0:
            continue
        for index, listener in enumerate(listeners):
            if listener["server"] == active_server:
                continue
            listener_sample = listener_measurements.get(listener["server"], {})
            listener_dbm = listener_sample.get("smeter")
            if listener_dbm is None or now - listener_sample.get("sampled_at", 0.0) > 12.0:
                continue
            remaining = listeners[:index] + listeners[index + 1:]
            if not all(globe_haversine_km(scout, other) >= CONSTELLATION_MIN_SEPARATION_KM for other in remaining):
                continue
            improvement = scout_dbm - listener_dbm
            if improvement < SCOUT_PROMOTION_MARGIN_DB:
                continue
            candidate = (improvement, index, scout, scout_dbm, listener_dbm)
            if best is None or candidate[0] > best[0]:
                best = candidate
    return best


def choose_expanding_scouts(anchor, receivers, listeners, scanned_servers, inner_radius_km):
    """Select the next unscanned four receivers from the outward search front."""
    listener_servers = {receiver["server"] for receiver in listeners}
    available = [
        receiver for receiver in receivers
        if receiver["server"] not in listener_servers and receiver["server"] not in scanned_servers
    ]
    outer_radius_km = min(SCOUT_SEARCH_MAX_KM, inner_radius_km + SCOUT_SEARCH_STEP_KM)
    in_front = [
        receiver for receiver in available
        if inner_radius_km < globe_haversine_km(anchor, receiver) <= outer_radius_km
    ]
    # Sparse receiver regions should continue outward, rather than revisit the
    # same local stations simply because one annulus did not contain four sites.
    farther = [receiver for receiver in available if globe_haversine_km(anchor, receiver) > outer_radius_km]
    candidates = sorted(in_front, key=lambda receiver: globe_haversine_km(anchor, receiver))
    candidates.extend(sorted(farther, key=lambda receiver: globe_haversine_km(anchor, receiver)))
    references = [receiver for receiver in receivers if receiver["server"] in scanned_servers] + list(listeners)
    return choose_tetris_coverage_scouts(candidates, references), outer_radius_km


def scout_coverage_cell(receiver):
    """Coarse geographic tile used only to avoid dense-city oversampling."""
    return (int((receiver["lat"] + 90.0) // 20.0), int((receiver["lon"] + 180.0) // 30.0))


def scout_heat_coverage_cells(receiver):
    """Cells visually covered by one enlarged SNR square footprint."""
    lat_cell = int((receiver["lat"] + 90.0) // 15.0)
    lon_cell = int((receiver["lon"] + 180.0) // 15.0) % 24
    # Four times the original area means twice its linear span.  The resulting
    # 5 x 5 cell footprint lets the scout planner place tiles like a loose
    # tessellation, rather than re-measuring the same city cluster.
    return {
        (max(0, min(11, lat_cell + d_lat)), (lon_cell + d_lon) % 24)
        for d_lat in range(-2, 3)
        for d_lon in range(-2, 3)
    }


def choose_tetris_coverage_scouts(candidates, references):
    """Pick four sites that add the most previously uncovered heatmap area."""
    available = list(candidates)
    selected = []
    covered = set().union(*(scout_heat_coverage_cells(receiver) for receiver in references)) if references else set()
    while available and len(selected) < 4:
        def coverage_score(receiver):
            footprint = scout_heat_coverage_cells(receiver)
            novel_cells = len(footprint - covered)
            nearest_km = min((globe_haversine_km(receiver, point) for point in references + selected), default=0.0)
            # New footprint is dominant; distance breaks ties so that equally
            # useful tiles do not bunch around one another.
            return novel_cells * 10000.0 + nearest_km

        choice = max(available, key=coverage_score)
        selected.append(choice)
        covered.update(scout_heat_coverage_cells(choice))
        available.remove(choice)
    return selected


def choose_global_coverage_scouts(receivers, listeners, scan_history, scanned_servers):
    """Farthest-first sampling for a broad, receiver-backed global heatmap."""
    listener_servers = {receiver["server"] for receiver in listeners}
    available = [
        receiver for receiver in receivers
        if receiver["server"] not in listener_servers and receiver["server"] not in scanned_servers
    ]
    references = [receiver for receiver, _scanned_at, _smeter_dbm, _snr_db in scan_history] + list(listeners)
    return choose_tetris_coverage_scouts(available, references)


def format_scout_measurement(sample):
    smeter_dbm = sample.get("smeter") if sample else None
    snr_db = sample.get("snr") if sample else None
    smeter_label = f"{smeter_dbm:.1f}dBm" if isinstance(smeter_dbm, (int, float)) else "pending"
    snr_label = f"SNR{snr_db:+.1f}" if isinstance(snr_db, (int, float)) else "SNR?"
    return f"{smeter_label}/{snr_label}"


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
    if DESKTOP_MODE:
        return x, y
    if DISPLAY_ORIENTATION == "normal":
        return ACTIVE_H - y, x
    return y + VISIBLE_Y_OFFSET, NATIVE_H - x


def set_display_orientation(orientation):
    global DISPLAY_ORIENTATION
    DISPLAY_ORIENTATION = orientation


def configure_output(desktop=False):
    """Select the Pi framebuffer geometry or a native landscape desktop window."""
    global NATIVE_W, NATIVE_H, ACTIVE_H, VISIBLE_Y_OFFSET, DESKTOP_MODE
    DESKTOP_MODE = bool(desktop)
    if DESKTOP_MODE:
        # Desktop development uses the logical SDR orientation directly.
        NATIVE_W, NATIVE_H = LOGICAL_W, LOGICAL_H
        ACTIVE_H = LOGICAL_H
        VISIBLE_Y_OFFSET = 0
    else:
        NATIVE_W, NATIVE_H = 400, 960
        ACTIVE_H = 400
        VISIBLE_Y_OFFSET = ACTIVE_H - LOGICAL_H


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
        self.external_audio = False
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

    def set_external_audio(self, enabled):
        with self.lock:
            self.external_audio = bool(enabled)

    def external_audio_snapshot(self):
        with self.lock:
            return self.external_audio

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


def setup_gl(desktop=False):
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    flags = pygame.OPENGL if desktop else pygame.OPENGL | pygame.FULLSCREEN
    screen = pygame.display.set_mode((NATIVE_W, NATIVE_H), flags)
    if desktop:
        pygame.display.set_caption("Kiwi SDR Desktop")
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


def top_instrument_layout(text_cache, freq_khz):
    """Return a right-aligned mode/frequency cluster next to the S-meter."""
    frequency_text = sdr_ui.format_freq(freq_khz)
    frequency_width = text_cache.font(50, bold=True, family="Liberation Sans").size(frequency_text)[0]
    frequency_left = FREQUENCY_RIGHT_X - frequency_width
    radio_x1 = frequency_left - RADIO_SETUP_GAP
    radio_box = (radio_x1 - RADIO_SETUP_WIDTH, 10, radio_x1, 54)
    return frequency_text, radio_box


def draw_radio_setup_pill(text_cache, mode, digital, step_hz, box=RADIO_SETUP_BOX):
    x0, y0, x1, y1 = box
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


def tests_option_at(x, y):
    if contains(TEST_GLOBE_BOX, x, y):
        return "globe"
    if contains(TEST_DJ_BOX, x, y):
        return "dj"
    if contains(TEST_PATTERN_BOX, x, y):
        return "pattern"
    if contains(TEST_RUN_BOX, x, y):
        return "run"
    return None


def draw_tests_button(text_cache, box, title, detail, active=False):
    x0, y0, x1, y1 = box
    fill = (104, 53, 20, 204) if active else (18, 29, 38, 210)
    line = (255, 184, 83, 220) if active else (115, 140, 151, 78)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, line, 1)
    draw_logical_line(x0, y1, x1, y1, line, 1)
    draw_logical_line(x0, y0, x0, y1, line, 1)
    draw_logical_line(x1, y0, x1, y1, line, 1)
    draw_text(text_cache, x0 + 22, (y0 + y1) / 2 - 10, title, (237, 248, 248), 20, True, True, "lm")
    draw_text(text_cache, x0 + 22, (y0 + y1) / 2 + 16, detail, (255, 211, 151) if active else (154, 186, 192), 14, False, True, "lm")


def draw_tests_panel(text_cache, pattern_index, sweep):
    """Dedicated, extensible diagnostics workspace; Audio remains listening-only."""
    x0, y0, x1, y1 = TEST_PANEL_BOX
    pattern_name, _shape, _steps, _step_hz, _cadence, _hold = RETUNE_TEST_PATTERNS[pattern_index]
    _name, offsets_khz, _delays = retune_test_schedule(pattern_index)
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 234))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    draw_text(text_cache, 36, 94, "TESTS", (229, 243, 246), 18, True, True, "lm")
    draw_tests_button(text_cache, TEST_GLOBE_BOX, "CONSTELLATION", "3 WARM STREAMS  /  4 ROTATING SCOUTS", True)
    draw_tests_button(text_cache, TEST_DJ_BOX, "DJ TUNE", "LIVE FINGER DIAL  /  100 Hz DETENTS")
    draw_tests_button(text_cache, TEST_PATTERN_BOX, pattern_name, f"{len(offsets_khz)} TUNES  /  RETURNS TO START")
    if sweep is None:
        draw_tests_button(text_cache, TEST_RUN_BOX, "RUN TEST", "LIVE KIWI WATERFALL + USB AUDIO")
    else:
        draw_tests_button(
            text_cache,
            TEST_RUN_BOX,
            "STOP",
            f"{sweep.name}  {sweep.index}/{sweep.command_count}",
            active=True,
        )


def flat_map_project(receiver, center_lon, center_lat, box, scale, longitude_offset=None):
    """Equirectangular map projection for an unfolded, direct-manipulation world."""
    x0, y0, x1, y1 = box
    view_lon = 360.0 / scale
    # Keep longitude and latitude at the same geographic scale even though
    # this unusually wide display crops polar space at the base view.
    view_lat = min(180.0, view_lon * (y1 - y0) / (x1 - x0))
    raw_delta_lon = receiver["lon"] - center_lon
    delta_lon = (
        (raw_delta_lon + 540.0) % 360.0 - 180.0
        if longitude_offset is None
        else raw_delta_lon + longitude_offset
    )
    delta_lat = receiver["lat"] - center_lat
    if abs(delta_lon) > view_lon / 2 or abs(delta_lat) > view_lat / 2:
        return None
    return (
        (x0 + x1) / 2 + delta_lon / view_lon * (x1 - x0),
        (y0 + y1) / 2 - delta_lat / view_lat * (y1 - y0),
    )


def draw_flat_coastlines(center_lon, center_lat, box, scale):
    """Real coastlines, split at projection seams and map edges."""
    width = box[2] - box[0]
    # At the lower zooms the edges repeat the world, just like an unfolded
    # cylindrical map: America can sit between Europe and Asia without voids.
    for longitude_offset in (-360.0, 0.0, 360.0):
        for coastline in GLOBE_COASTLINES:
            segment = []
            for lat, lon in coastline:
                point = flat_map_project({"lat": lat, "lon": lon}, center_lon, center_lat, box, scale, longitude_offset)
                if point is None or (segment and abs(point[0] - segment[-1][0]) > width * 0.32):
                    draw_logical_polyline(segment, (96, 187, 181, 166), 1)
                    segment = []
                if point is not None:
                    segment.append(point)
            draw_logical_polyline(segment, (96, 187, 181, 166), 1)


def scout_rf_strength(smeter_dbm):
    """Map Kiwi's useful S-meter range onto an opacity weight."""
    if smeter_dbm is None:
        return 0.16
    return clamp((smeter_dbm - SMETER_FLOOR_DBM) / (SMETER_S9_DBM - SMETER_FLOOR_DBM), 0.10, 1.0)


def scout_heat_strength(smeter_dbm, snr_db):
    """Only measured SNR contributes to the SNR heatmap."""
    if snr_db is None:
        return 0.0
    return clamp((snr_db + 5.0) / 25.0, 0.08, 1.0)


def scout_snr_color(snr_db):
    """Contrast bands calibrated to the observed adjacent-channel SNR proxy."""
    if snr_db < -4.0:
        return (111, 74, 175)
    if snr_db < -1.0:
        return (76, 125, 220)
    if snr_db < 2.0:
        return (61, 201, 194)
    if snr_db < 5.0:
        return (255, 186, 63)
    return (239, 88, 75)


def scout_heat_radius_pixels(box, scale):
    """Approximate the enlarged readable SNR tile footprint in this view."""
    view_lon = 360.0 / scale
    view_lat = min(180.0, view_lon * (box[3] - box[1]) / (box[2] - box[0]))
    pixels_per_latitude_degree = (box[3] - box[1]) / view_lat
    return clamp(
        (SCOUT_INITIAL_HEAT_RADIUS_KM * math.sqrt(SCOUT_HEAT_AREA_MULTIPLIER)) / 111.32 * pixels_per_latitude_degree,
        8.0,
        min(box[2] - box[0], box[3] - box[1]) / 2,
    )


def draw_constellation_heatmap(scouts, scan_history, measurements, center_lon, center_lat, box, scale, now):
    """Render a normalized SNR surface: one value per map cell, never density."""
    outer_radius = scout_heat_radius_pixels(box, scale)

    def add_sample(receiver, smeter_dbm, snr_db, recency, samples):
        if snr_db is None:
            return
        point = flat_map_project(receiver, center_lon, center_lat, box, scale)
        if not point:
            return
        samples.append((point, snr_db, scout_heat_strength(smeter_dbm, snr_db), recency))

    samples = []
    for receiver, scanned_at, smeter_dbm, snr_db in scan_history:
        age = max(0.0, now - scanned_at)
        if age < SCOUT_HEAT_REMANENCE_SECONDS:
            add_sample(receiver, smeter_dbm, snr_db, 0.18 + 0.52 * (1.0 - age / SCOUT_HEAT_REMANENCE_SECONDS), samples)
    for receiver in scouts:
        sample = measurements.get(receiver["server"], {})
        add_sample(receiver, sample.get("smeter"), sample.get("snr"), 1.0, samples)

    if not samples:
        return
    # Collapse nearby samples before interpolation. This keeps the Pi workload
    # bounded and retains the best SNR in a geographic neighborhood instead of
    # rewarding its receiver count.
    reduced = {}
    sample_cell_size = outer_radius * 1.5
    for sample in samples:
        (sample_x, sample_y), snr_db, _strength, recency = sample
        cell = (int((sample_x - box[0]) // sample_cell_size), int((sample_y - box[1]) // sample_cell_size))
        previous = reduced.get(cell)
        if previous is None or (snr_db, recency) > (previous[1], previous[3]):
            reduced[cell] = sample
    samples = list(reduced.values())
    # The numerator and denominator use the same distance kernel. This is a
    # weighted average, not an additive blend: testing ten stations in one
    # place cannot create a hotter patch than one equally good station.
    grid = SCOUT_HEAT_GRID_PIXELS
    for y in range(int(box[1]), int(box[3]), int(grid)):
        for x in range(int(box[0]), int(box[2]), int(grid)):
            center_x, center_y = x + grid / 2, y + grid / 2
            numerator = denominator = coverage = 0.0
            for (sample_x, sample_y), snr_db, strength, recency in samples:
                distance = math.hypot(center_x - sample_x, center_y - sample_y)
                if distance >= outer_radius:
                    continue
                weight = (1.0 - distance / outer_radius) ** 2 * recency
                numerator += snr_db * weight
                denominator += weight
                coverage = max(coverage, weight)
            if denominator <= 0.0:
                continue
            snr_db = numerator / denominator
            heat_color = scout_snr_color(snr_db)
            # Keep weak but valid SNR samples visible. Alpha is based on the
            # nearest kernel only, so this boosts readability without making
            # dense receiver regions look stronger.
            quality = scout_heat_strength(None, snr_db)
            alpha = int(72 + 178 * coverage * (0.35 + 0.65 * quality))
            draw_logical_rect(x, y, min(x + grid, box[2]), min(y + grid, box[3]), (*heat_color, alpha))


def nearby_scout_snr(receiver, scouts, scout_history, scout_measurements):
    """Estimate the local SNR field at a warm receiver without retuning audio."""
    samples = [
        (other, snr_db)
        for other, _at, _rf, snr_db in scout_history
        if snr_db is not None
    ]
    samples.extend(
        (other, sample.get("snr"))
        for other in scouts
        if (sample := scout_measurements.get(other["server"], {})).get("snr") is not None
    )
    radius_km = SCOUT_INITIAL_HEAT_RADIUS_KM * math.sqrt(SCOUT_HEAT_AREA_MULTIPLIER)
    numerator = denominator = 0.0
    for other, snr_db in samples:
        weight = max(0.0, 1.0 - globe_haversine_km(receiver, other) / radius_km) ** 2
        numerator += snr_db * weight
        denominator += weight
    return numerator / denominator if denominator else None


def scouted_receiver_at_tap(x, y, scouts, scout_history, scout_measurements, center_lon, center_lat, box, scale):
    """Return the measured scout represented by a heat tile under a map tap."""
    samples = [(receiver, sampled_at) for receiver, sampled_at, _rf, snr_db in scout_history if snr_db is not None]
    samples.extend(
        (receiver, time.monotonic())
        for receiver in scouts
        if scout_measurements.get(receiver["server"], {}).get("snr") is not None
    )
    candidates = []
    for receiver, sampled_at in samples:
        for longitude_offset in (-360.0, 0.0, 360.0):
            point = flat_map_project(receiver, center_lon, center_lat, box, scale, longitude_offset)
            if point:
                candidates.append((math.hypot(point[0] - x, point[1] - y), -sampled_at, receiver))
    if not candidates:
        return None
    distance, _age, receiver = min(candidates)
    # A tile is 40 logical pixels wide; accepting one tile radius makes a tap
    # anywhere on its visible SNR square select the actual measured receiver.
    return receiver if distance <= SCOUT_HEAT_GRID_PIXELS * 1.15 else None


def draw_globe_panel(text_cache, receivers, yaw, pitch, scale, listeners, listener_measurements, scouts, scout_history, scout_measurements, replacement_slots, scout_total, active_server, anchor, status):
    """Constellation receiver model with listener streams and scout heatmaps."""
    x0, y0, x1, y1 = GLOBE_PANEL_BOX
    draw_logical_rect(0, 0, LOGICAL_W, LOGICAL_H, (0, 0, 0, 174))
    draw_logical_rect(x0, y0, x1, y1, (6, 13, 20, 220))
    draw_logical_line(x0, y0, x1, y0, (116, 170, 183, 100), 1)
    draw_text(text_cache, 36, 24, "CONSTELLATION", (230, 243, 246), 20, True, True, "lm")
    draw_text(text_cache, 214, 20, "MAP SNR COVERAGE", (119, 182, 195), 14, True, True, "lm")
    draw_tests_button(text_cache, GLOBE_BACK_BOX, "BACK", "TESTS")
    map_box = GLOBE_MAP_BOX
    draw_logical_rect(*map_box, (10, 35, 55, 245))
    draw_logical_line(map_box[0], map_box[1], map_box[2], map_box[1], (86, 173, 195, 150), 1)
    draw_logical_line(map_box[0], map_box[3], map_box[2], map_box[3], (86, 173, 195, 150), 1)
    center_lon, center_lat = math.degrees(yaw), math.degrees(pitch)
    for latitude in (-60, -30, 0, 30, 60):
        a = flat_map_project({"lat": latitude, "lon": center_lon - 180 / scale}, center_lon, center_lat, map_box, scale)
        b = flat_map_project({"lat": latitude, "lon": center_lon + 180 / scale}, center_lon, center_lat, map_box, scale)
        if a and b:
            draw_logical_line(a[0], a[1], b[0], b[1], (80, 148, 170, 42), 1)
    draw_flat_coastlines(center_lon, center_lat, map_box, scale)
    draw_constellation_heatmap(scouts, scout_history, scout_measurements, center_lon, center_lat, map_box, scale, time.monotonic())
    legend_x = 42
    draw_text(text_cache, legend_x, 54, "SNR", (180, 204, 208), 13, True, True, "lm")
    for color, label, offset in (
        ((111, 74, 175), "<-4", 34),
        ((76, 125, 220), "-4–-1", 78),
        ((61, 201, 194), "-1–2", 134),
        ((255, 186, 63), "2–5", 186),
        ((239, 88, 75), ">5 dB", 232),
    ):
        draw_logical_circle(legend_x + offset, 54, 3.5, (*color, 235), 12)
        draw_text(text_cache, legend_x + offset + 8, 54, label, (180, 204, 208), 13, False, True, "lm")
    listener_servers = {receiver["server"] for receiver in listeners}
    for receiver in receivers:
        for longitude_offset in (-360.0, 0.0, 360.0):
            p = flat_map_project(receiver, center_lon, center_lat, map_box, scale, longitude_offset)
            if not p:
                continue
            dot_color = (116, 228, 201, 240) if receiver["server"] in listener_servers else (90, 219, 228, 48)
            dot_radius = 3.2 if receiver["server"] in listener_servers else 0.9
            if receiver["server"] == active_server:
                draw_logical_circle(p[0], p[1], 10, (91, 242, 180, 180), 18, True)
                dot_color = (104, 239, 171, 255)
                dot_radius = 4.2
            draw_logical_circle(p[0], p[1], dot_radius, dot_color, 10)
    draw_text(text_cache, (map_box[0] + map_box[2]) / 2, map_box[3] - 10, "DRAG / PINCH   •   TAP TO START", (154, 201, 210), 13, True, True, "cm")
    right_x = 610
    draw_logical_rect(*GLOBE_INFO_BOX, (5, 13, 19, 232))
    draw_logical_line(GLOBE_INFO_BOX[0], GLOBE_INFO_BOX[1], GLOBE_INFO_BOX[2], GLOBE_INFO_BOX[1], (104, 180, 188, 104), 1)
    draw_text(text_cache, right_x, 22, "HOT RECEIVERS", (239, 248, 248), 19, True, True, "lm")
    draw_text(text_cache, 932, 22, "TAP TO LISTEN", (119, 182, 195), 12, True, True, "rm")
    if not receivers:
        draw_text(text_cache, right_x, 96, "Loading public GPS map...", (255, 196, 108), 17, False, True, "lm")
    elif not listeners:
        draw_text(text_cache, right_x, 96, "Tap a receiver region", (171, 204, 211), 18, False, True, "lm")
        draw_text(text_cache, right_x, 126, f"{len(receivers)} mapped receivers", (116, 162, 174), 16, False, True, "lm")
    else:
        for index, receiver in enumerate(listeners):
            bx0, by0, bx1, by1 = GLOBE_STATION_BOXES[index]
            active = receiver["server"] == active_server
            draw_logical_rect(bx0, by0, bx1, by1, (26, 79, 68, 205) if active else (18, 34, 43, 204))
            draw_logical_line(bx0, by0, bx1, by0, (98, 226, 172, 210) if active else (120, 169, 181, 108), 1)
            title = bottom_station_title(receiver["name"], receiver["location"])[:21]
            draw_text(text_cache, bx0 + 12, by0 + 16, f"{index + 1}. {title}", (239, 248, 248), 21, True, True, "lm")
            smeter_dbm = listener_measurements.get(receiver["server"], {}).get("smeter")
            slot = replacement_slots[index] if index < len(replacement_slots) else {}
            snr_db = slot.get("snr") if slot.get("current_server") == receiver["server"] else None
            snr_is_direct = snr_db is not None
            if snr_db is None:
                snr_db = nearby_scout_snr(receiver, scouts, scout_history, scout_measurements)
            # A warmed audio stream supplies a direct RF S-meter, but it must
            # not be retuned for an SNR baseline. Show an SNR only when this
            # receiver was first measured by a silent scout.
            rf_label = f"RF {smeter_dbm:.0f} dBm" if smeter_dbm is not None else "RF WARMING"
            snr_label = (
                f"SNR {snr_db:+.1f} dB" if snr_is_direct
                else (f"MAP SNR~ {snr_db:+.1f}" if snr_db is not None else "MAP SNR —")
            )
            draw_text(text_cache, bx0 + 12, by0 + 43, f"{rf_label}   {snr_label}", (107, 229, 168) if active else (185, 212, 217), 16, True, True, "lm")
            if slot.get("reason") == "scout":
                previous = slot.get("previous_name", "original")[:19]
                detail = f"SCOUT REPLACED {previous}  +{slot.get('gain_db', 0):.0f} dB"
                detail_color = (255, 202, 107)
            elif slot.get("reason") == "failed":
                detail = "REPLACED AFTER RECEIVER FAILURE"
                detail_color = (255, 169, 114)
            else:
                detail = "ORIGINAL HOT RECEIVER" if not active else "ORIGINAL HOT • LIVE AUDIO"
                detail_color = (141, 184, 193)
            draw_text(text_cache, bx0 + 12, by0 + 65, detail, detail_color, 13, True, True, "lm")

    # Keep the active scouts and accumulated coverage in one large bottom bar,
    # leaving the three warm receiver cards readable at a glance.
    bar = GLOBE_SCOUT_BAR_BOX
    draw_logical_rect(*bar, (5, 13, 19, 236))
    draw_logical_line(bar[0], bar[1], bar[2], bar[1], (255, 190, 93, 160), 1)
    draw_text(text_cache, 24, 282, f"SCOUTING  {len(scouts)}/4", (255, 204, 113), 16, True, True, "lm")
    draw_text(text_cache, 250, 282, f"TOTAL  {scout_total}", (255, 204, 113), 16, True, True, "lm")
    scan_mode = "LOCAL EXPANSION" if "expanding locally" in status else "MAXIMIZING MAP COVERAGE"
    draw_text(text_cache, 26, 304, scan_mode, (176, 208, 213), 14, True, True, "lm")


def draw_dj_control(text_cache, box, title, detail, active=False):
    x0, y0, x1, y1 = box
    fill = (27, 76, 70, 210) if active else (18, 29, 38, 210)
    line = (94, 230, 178, 210) if active else (115, 140, 151, 78)
    draw_logical_rect(x0, y0, x1, y1, fill)
    draw_logical_line(x0, y0, x1, y0, line, 1)
    draw_logical_line(x0, y1, x1, y1, line, 1)
    draw_logical_line(x0, y0, x0, y1, line, 1)
    draw_logical_line(x1, y0, x1, y1, line, 1)
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2 - 9, title, (232, 247, 247), 16, True, True, "cm")
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2 + 14, detail, (126, 225, 183), 13, False, True, "cm")


def draw_dj_tune_panel(text_cache, origin_khz, current_khz, step_hz, range_khz, link_rate_hz):
    """Finger-driven, detented tune laboratory that always has an origin."""
    x0, y0, x1, y1 = DJ_PANEL_BOX
    tx0, ty0, tx1, ty1 = DJ_TRACK_BOX
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 234))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    draw_text(text_cache, 36, 94, "DJ TUNE", (229, 243, 246), 18, True, True, "lm")
    delta_hz = round((current_khz - origin_khz) * 1000)
    delta_label = f"{delta_hz:+d} Hz" if delta_hz else "CENTRE"
    draw_text(text_cache, 918, 94, delta_label, (110, 230, 180), 16, True, True, "rm")
    draw_text(text_cache, LOGICAL_W / 2, 114, sdr_ui.format_freq(current_khz), (232, 246, 247), 28, True, False, "cm")
    draw_logical_rect(tx0, ty0, tx1, ty1, (10, 23, 29, 232))
    mid_x = (tx0 + tx1) / 2
    draw_logical_line(mid_x, ty0 + 7, mid_x, ty1 - 7, (113, 239, 187, 235), 2)
    for tick in range(-10, 11):
        x = mid_x + tick * (tx1 - tx0) / 20
        height = 22 if tick % 5 == 0 else 12
        draw_logical_line(x, (ty0 + ty1) / 2 - height / 2, x, (ty0 + ty1) / 2 + height / 2, (132, 167, 174, 130), 1)
    marker_x = clamp(mid_x + (current_khz - origin_khz) / range_khz * (tx1 - tx0) / 2, tx0, tx1)
    draw_logical_line(marker_x, ty0 + 5, marker_x, ty1 - 5, (244, 224, 151, 255), 3)
    draw_dj_control(text_cache, DJ_STEP_BOX, "STEP", f"{step_hz} Hz", step_hz == 100)
    draw_dj_control(text_cache, DJ_RANGE_BOX, "RANGE", f"+/-{range_khz:.1f} kHz")
    draw_dj_control(text_cache, DJ_RATE_BOX, "LINK RATE", f"{link_rate_hz} Hz", link_rate_hz != 50)
    draw_dj_control(text_cache, DJ_RETURN_BOX, "RETURN", sdr_ui.format_freq(origin_khz))


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
    # Amber is deliberately reserved for the tuned RF center: it remains
    # legible over blue/cyan waterfall energy without resembling a signal.
    center_shadow = (2, 7, 11, int(128 * alpha))
    center = (255, 192, 68, int(222 * alpha))
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
        # A continuous marker masks a weak, perfectly tuned carrier. Use a
        # fine dashed guide instead, with a clear top reference tick.
        draw_logical_line(center_x - 6, y0 + 2, center_x + 6, y0 + 2, center, 1)
        dash_h = 5
        dash_period = 12
        for dash_y in range(int(y0 + 8), int(y1), dash_period):
            dash_end = min(dash_y + dash_h, y1)
            draw_logical_line(center_x, dash_y, center_x, dash_end, center_shadow, 3)
            draw_logical_line(center_x, dash_y, center_x, dash_end, center, 1)


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
    pad = 12
    gap = 10
    item_w = (x1 - x0 - 2 * pad - (MENU_COLS - 1) * gap) / MENU_COLS
    item_h = (y1 - y0 - 2 * pad - (MENU_ROWS - 1) * gap) / MENU_ROWS
    return x0, y0, x1, y1, pad, gap, item_w, item_h


def menu_max_scroll():
    # The Home grid is deliberately finite: no hidden horizontal pages.
    return 0.0


def menu_item_box(index, scroll):
    x0, y0, _x1, _y1, pad, gap, item_w, item_h = menu_metrics()
    col = index % MENU_COLS
    row = index // MENU_COLS
    if row >= MENU_ROWS:
        return None
    # The second row remains left-justified, like the first, so operators can
    # scan a stable grid without a competing close target.
    left = x0 + pad + col * (item_w + gap)
    top = y0 + pad + row * (item_h + gap)
    return left, top, left + item_w, top + item_h


def menu_at(x, y, scroll):
    if not contains(MENU_BOX, x, y):
        return None
    for idx in range(len(MENU_ITEMS)):
        box = menu_item_box(idx, scroll)
        if box and contains(box, x, y):
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
    elif kind == "tests":
        pygame.draw.rect(surface, color, (cx - 26, cy - 23, 52, 48), 3, border_radius=5)
        pygame.draw.line(surface, dim, (cx - 14, cy - 10), (cx + 14, cy - 10), 3)
        pygame.draw.line(surface, dim, (cx - 14, cy), (cx + 8, cy), 3)
        pygame.draw.line(surface, dim, (cx - 14, cy + 10), (cx + 2, cy + 10), 3)
        pygame.draw.circle(surface, color, (cx + 15, cy + 11), 10, 3)
        pygame.draw.line(surface, color, (cx + 15, cy + 4), (cx + 15, cy + 12), 2)
        pygame.draw.line(surface, color, (cx + 15, cy + 12), (cx + 21, cy + 16), 2)
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
    # Let the waterfall remain legible behind a single calm, temporary veil.
    draw_logical_rect(x0, y0, x1, y1, (5, 12, 18, 222))
    draw_logical_line(x0 + 12, y0, x1 - 12, y0, (174, 201, 205, 72), 1)
    for idx, (kind, label) in enumerate(MENU_ITEMS):
        box = menu_item_box(idx, scroll)
        if box is None:
            continue
        bx0, by0, bx1, by1 = box
        if bx1 < x0 or bx0 > x1:
            continue
        tex, tex_w, tex_h = menu_icon_texture(text_cache, kind, label)
        target_w = min(132, bx1 - bx0 - 12)
        target_h = min(92, by1 - by0 - 4)
        target_x = bx0 + ((bx1 - bx0) - target_w) / 2
        target_y = by0 + ((by1 - by0) - target_h) / 2
        draw_textured_quad(tex, target_x, target_y, target_x + target_w, target_y + target_h, 0, 0, 1, 1)


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


def station_fields(station):
    """Return a consistent station row for both directory and fallback data."""
    name, location, server = station[:3]
    listener_used = station[3] if len(station) > 3 else None
    listener_total = station[4] if len(station) > 4 else None
    return name, location, server, listener_used, listener_total


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

    for idx, station in enumerate(stations):
        name, location, server, listener_used, listener_total = station_fields(station)
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
    meter_x0 = 690
    # Leave the usual right quiet margin while fitting a full calibrated scale.
    meter_x1 = 915
    green = (222, 255, 228, 255)
    red = (230, 20, 42, 255)
    rail = (160, 178, 182, 155)
    tick = (192, 211, 214, 220)
    blue = (0, 76, 245, 255)
    dbm_color = (189, 198, 201, 225)
    # The trace is the optical center of one calibrated assembly: S-units
    # above, dBm below. Keep every tick balanced around this datum.
    trace_y = 39

    def dbx(dbm):
        return meter_x0 + round((meter_x1 - meter_x0) * (smeter_segment_position(dbm) / 36.0))

    # Put the passive channel behind the calibration. Its recess should not
    # erase the midpoint of the vertical scale marks.
    draw_logical_line(meter_x0, trace_y, meter_x1, trace_y, (5, 13, 21, 235), 8)
    draw_logical_line(meter_x0, trace_y - 3, meter_x1, trace_y - 3, (112, 143, 152, 112), 1)
    draw_logical_line(meter_x0, trace_y + 3, meter_x1, trace_y + 3, (1, 6, 11, 225), 1)
    live_x = clamp(dbx(smeter_dbm), meter_x0, meter_x1)
    live_color = red if smeter_dbm >= SMETER_S9_DBM else blue
    live_shadow = (94, 0, 16, 255) if smeter_dbm >= SMETER_S9_DBM else (0, 18, 116, 255)
    live_highlight = (255, 202, 208, 235) if smeter_dbm >= SMETER_S9_DBM else (150, 232, 255, 235)
    # The active trace belongs behind the scale too. The calibrated tick
    # geometry must remain uninterrupted at every level.
    draw_logical_line(meter_x0, trace_y, live_x, trace_y, live_shadow, 6)
    draw_logical_line(meter_x0, trace_y - 1, live_x, trace_y - 1, live_color, 4)
    draw_logical_line(meter_x0 + 1, trace_y - 2.5, max(meter_x0 + 1, live_x - 2), trace_y - 2.5, live_highlight, 1)

    labels = (
        ("S", dbx(-121) - 40, green[:3], 14),
        ("1", dbx(-121), green[:3], 14),
        ("3", dbx(-109), green[:3], 14),
        ("5", dbx(-97), green[:3], 14),
        ("7", dbx(-85), green[:3], 14),
        ("9", dbx(-73), green[:3], 14),
        ("+20", dbx(-53), red[:3], 14),
        ("+40", dbx(-33), red[:3], 14),
    )
    for text, x, color, size in labels:
        draw_text(text_cache, x, 10, text, color, size, False, True, "cm")

    # Major calibration lines reach equally above and below the trace. The
    # short midpoint ticks use the same symmetric treatment, so the dBm row
    # does not accidentally read as the only side with fine graduation.
    major_ticks = ((-121, tick), (-109, tick), (-97, tick), (-85, tick), (-73, tick), (-53, red), (-33, red))
    for dbm, color in major_ticks:
        x = dbx(dbm)
        draw_logical_line(x, trace_y - 14, x, trace_y + 14, color, 2)
    for dbm in (-115, -103, -91, -79, -63, -43):
        x = dbx(dbm)
        tick_color = red if dbm in (-63, -43) else rail
        draw_logical_line(x, trace_y - 6, x, trace_y + 6, tick_color, 1)

    # A single-line reading is quickest to parse. The scale begins farther
    # right so the large value and its unit do not touch the live trace.
    draw_text(text_cache, meter_x0 - 35, trace_y, f"{int(round(smeter_dbm))}", (194, 211, 214), 28, True, True, "rm")
    draw_text(text_cache, meter_x0 - 32, trace_y, "dBm", (164, 184, 188), 13, True, True, "lm")
    draw_logical_circle(
        live_x,
        trace_y - 1,
        5,
        (139, 234, 255, 255) if smeter_dbm < SMETER_S9_DBM else (255, 174, 178, 255),
    )
    draw_logical_circle(live_x - 1, trace_y - 2.5, 1.6, (237, 254, 255, 245))
    # The retained peak is a quiet vertical reference, independent from the
    # live marker, so a changing signal remains easy to read at a glance.
    if peak_dbm is not None and peak_dbm > smeter_dbm + 0.75:
        peak_x = clamp(dbx(peak_dbm), meter_x0, meter_x1)
        draw_logical_line(peak_x, trace_y - 11, peak_x, trace_y + 11, (182, 197, 200, 178), 1)

    # A simple 20 dB cadence follows the reference instrument style. The
    # labels are calibrated through the same nonlinear S-unit mapping above.
    for dbm in (-120, -100, -80, -60, -40):
        draw_text(text_cache, dbx(dbm), 65, f"{dbm}", dbm_color[:3], 13, True, True, "cm")
    draw_text(text_cache, meter_x1 + 16, 65, "dBm", dbm_color[:3], 13, True, True, "lm")


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
    draw_logical_area(points, bottom, (161, 184, 196, 154))
    draw_logical_polyline(points, (204, 219, 224, 208), 1.25)


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
    frequency_text, radio_box = top_instrument_layout(text_cache, freq_khz)
    draw_radio_setup_pill(text_cache, mode, digital, step_hz, radio_box)
    # Liberation Sans Bold stays clean and compact at the display's physical
    # pixel density, leaving headroom inside the short instrument strip.
    # Right alignment keeps this cluster locked to the S-meter while the
    # number of MHz digits changes between bands.
    draw_text(text_cache, FREQUENCY_RIGHT_X, 39, frequency_text, (169, 189, 193), 50, True, False, "rm", family="Liberation Sans")
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
            smeter_readout_dbm=None,
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
            smeter_readout_dbm=None,
            alpha=instrument_alpha,
        )
    draw_control_group_background(text_cache, ZOOM_GROUP_BOX, "zoom_group_pill_v7", (64, 156), controls_alpha)
    draw_zoom_button(text_cache, ZOOM_PLUS_BOX, "+", controls_alpha)
    draw_zoom_button(text_cache, ZOOM_MINUS_BOX, "-", controls_alpha)
    draw_text(text_cache, 132, 227, "ZOOM", (211, 227, 231), 16, True, True, "cm", controls_alpha)
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


class DesktopAudioPlayer:
    """Small CoreAudio-backed PCM sink with the same write interface as pw-cat."""

    def __init__(self, rate):
        import sounddevice

        self.stream = sounddevice.RawOutputStream(
            samplerate=rate,
            channels=1,
            dtype="int16",
            latency="low",
        )
        self.stream.start()
        # Existing stream workers write to player.stdin. Point it back at this
        # lightweight compatibility sink instead of forking their data path.
        self.stdin = self

    def write(self, data):
        if data:
            if audioop is not None and DESKTOP_AUDIO_VOLUME < 0.995:
                data = audioop.mul(data, 2, DESKTOP_AUDIO_VOLUME)
            self.stream.write(data)
        return len(data)

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass

    def poll(self):
        return None

    def terminate(self):
        self.close()

    def wait(self, timeout=None):
        return 0


def start_audio_player(args):
    """Open the SDR's mono PCM stream on PipeWire's current default sink.

    PipeWire/WirePlumber owns the output choice, so a USB sink selected as the
    system default continues to receive this stream without pinning a volatile
    numeric node id in the renderer configuration.
    """
    if not args.audio:
        return None
    if args.desktop:
        try:
            return DesktopAudioPlayer(args.audio_rate)
        except Exception as exc:
            print(f"gl desktop audio {exc}", flush=True)
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
    if isinstance(player, DesktopAudioPlayer):
        player.close()
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
    if DESKTOP_MODE:
        return DESKTOP_AUDIO_VOLUME
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
    global DESKTOP_AUDIO_VOLUME
    volume = clamp(float(volume), 0.0, 1.0)
    if DESKTOP_MODE:
        DESKTOP_AUDIO_VOLUME = volume
        return volume
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
            if state.external_audio_snapshot():
                stop_audio_player(player)
                player = None
                stop_event.wait(0.10)
                continue
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
            next_view_send_at = 0.0
            while not stop_event.is_set():
                if state.external_audio_snapshot():
                    break
                server, freq_khz, _zoom, _smeter, view_generation, server_generation = state.snapshot()
                radio_mode, low_cut, high_cut, radio_generation = state.radio_snapshot()
                squelch_enabled, audio_generation = state.audio_snapshot()
                live_tune_interval = 1.0 / state.tune_rate_snapshot()
                if server_generation != seen_server_generation:
                    seen_server_generation = server_generation
                    break
                now_monotonic = time.monotonic()
                if (
                    configured
                    and (view_generation != seen_view_generation or radio_generation != seen_radio_generation)
                    and now_monotonic >= next_view_send_at
                ):
                    snd_freq_khz = snd_carrier_khz(freq_khz, low_cut, high_cut)
                    kiwi.send_snd_setup(ws, snd_freq_khz, radio_mode, low_cut, high_cut)
                    ws.send_text(f"SET squelch={int(squelch_enabled)} max=0")
                    seen_view_generation = view_generation
                    seen_radio_generation = radio_generation
                    seen_audio_generation = audio_generation
                    next_view_send_at = now_monotonic + live_tune_interval
                    print(
                        f"gl snd mode={radio_mode} carrier={snd_freq_khz:.3f} view={freq_khz:.3f}",
                        flush=True,
                    )

                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now
                try:
                    readable, _writable, _errors = select.select([ws.sock], [], [], KIWI_IO_POLL_SECONDS)
                    if not readable:
                        continue
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
                        next_view_send_at = time.monotonic() + live_tune_interval
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


class GlobeAudioMixer:
    """Three prewarmed listener streams with one selected PipeWire output."""
    def __init__(self, args, state):
        self.args, self.state = args, state
        self.lock = threading.Lock()
        self.stop_event = None
        self.player = None
        self.active_server = None
        self.pending_server = None
        self.ready_servers = set()
        self.source_smeters = {}
        self.events = queue.Queue()
        self.servers = ()

    def start(self, receivers, active_server):
        self.stop()
        self.stop_event = threading.Event()
        self.servers = tuple(receiver["server"] for receiver in receivers[:3])
        self.active_server = active_server
        self.pending_server = active_server
        self.ready_servers = set()
        self.source_smeters = {}
        # Keep normal audio alive until a Globe source has proved it can
        # deliver PCM. This avoids turning a failed public endpoint into silence.
        self.state.set_external_audio(False)
        self.player = start_audio_player(self.args)
        for server in self.servers:
            threading.Thread(target=self._source_worker, args=(server, self.stop_event), daemon=True).start()

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.stop_event = None
        stop_audio_player(self.player)
        self.player = None
        self.servers = ()
        self.ready_servers = set()
        self.source_smeters = {}
        self.pending_server = None
        self.state.set_external_audio(False)

    def select(self, server):
        with self.lock:
            if server not in self.servers:
                return False
            self.pending_server = server
            if server in self.ready_servers:
                self.active_server = server
                self.state.set_external_audio(True)
                return True
            return False

    def _source_ready(self, server):
        with self.lock:
            newly_ready = server not in self.ready_servers
            self.ready_servers.add(server)
            if self.pending_server == server or self.active_server == server:
                self.active_server = server
                self.pending_server = None
                self.state.set_external_audio(True)
        if newly_ready:
            self.events.put(("ready", server))

    def smeter_snapshot(self):
        with self.lock:
            return {server: dict(sample) for server, sample in self.source_smeters.items()}

    def ready_snapshot(self):
        with self.lock:
            return set(self.ready_servers)

    def _write_active(self, server, audio):
        with self.lock:
            active = server == self.active_server
            player = self.player
        if active and player and player.stdin:
            try:
                player.stdin.write(audio)
            except (BrokenPipeError, OSError):
                pass

    def _source_worker(self, server, stop_event):
        ws = None
        try:
            ws = kiwi.KiwiWebSocket.connect(server, "SND")
            kiwi.send_kiwi_setup(ws, "kiwi", self.args.user)
            configured = False
            seen_view = seen_radio = -1
            last_keepalive = 0
            while not stop_event.is_set():
                _server, freq_khz, _zoom, _smeter, view_generation, _server_generation = self.state.snapshot()
                radio_mode, low_cut, high_cut, radio_generation = self.state.radio_snapshot()
                if configured and (view_generation != seen_view or radio_generation != seen_radio):
                    kiwi.send_snd_setup(ws, snd_carrier_khz(freq_khz, low_cut, high_cut), radio_mode, low_cut, high_cut)
                    seen_view, seen_radio = view_generation, radio_generation
                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now
                readable, _writable, _errors = select.select([ws.sock], [], [], KIWI_IO_POLL_SECONDS)
                if not readable:
                    continue
                message = ws.recv()
                if message[:3] == b"MSG":
                    params = kiwi.parse_msg_params(message)
                    if "audio_rate" in params:
                        ws.send_text(f"SET AR OK in={int(float(params['audio_rate']))} out=44100")
                    if "sample_rate" in params and not configured:
                        kiwi.send_snd_setup(ws, snd_carrier_khz(freq_khz, low_cut, high_cut), radio_mode, low_cut, high_cut)
                        configured = True
                        seen_view, seen_radio = view_generation, radio_generation
                    continue
                if not configured or message[:3] != b"SND" or len(message) < 10:
                    continue
                body = message[3:]
                flags, _sequence = struct.unpack("<BI", body[:5])
                smeter, = struct.unpack(">H", body[5:7])
                with self.lock:
                    self.source_smeters[server] = {
                        "smeter": 0.1 * smeter - 127.0,
                        "sampled_at": time.monotonic(),
                    }
                audio = body[7:]
                if flags & kiwi.SND_FLAG_COMPRESSED or flags & kiwi.SND_FLAG_STEREO:
                    continue
                if not flags & kiwi.SND_FLAG_LITTLE_ENDIAN:
                    audio = kiwi.swap_s16_bytes(audio)
                self._source_ready(server)
                self._write_active(server, audio)
        except Exception as exc:
            print(f"gl globe audio {server}: {exc}", flush=True)
            self.events.put(("failed", server))
        finally:
            if ws:
                ws.send_close()


class ConstellationScoutProbe:
    """Silent SND probes returning tuned RF level and an offset-noise SNR proxy."""
    def __init__(self, args, state):
        self.args, self.state = args, state
        self.stop_event = None
        self.events = queue.Queue()

    def scan(self, receivers):
        self.stop()
        self.stop_event = threading.Event()
        for receiver in receivers[:4]:
            print(f"gl scout start {receiver['server']}", flush=True)
            threading.Thread(
                target=self._scan_worker,
                args=(receiver["server"], self.stop_event),
                daemon=True,
            ).start()

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.stop_event = None

    def _scan_worker(self, server, stop_event):
        ws = None
        signal_readings = []
        noise_readings = []
        try:
            _active_server, freq_khz, _zoom, _smeter, _view_generation, _server_generation = self.state.snapshot()
            radio_mode, low_cut, high_cut, _radio_generation = self.state.radio_snapshot()
            ws = kiwi.KiwiWebSocket.connect(server, "SND")
            kiwi.send_kiwi_setup(ws, "kiwi", self.args.user)
            configured = False
            last_keepalive = 0
            connect_deadline = time.monotonic() + SCOUT_RF_CONNECT_TIMEOUT_SECONDS
            sample_deadline = None
            phase = "signal"
            while not stop_event.is_set() and time.monotonic() < connect_deadline:
                now = int(time.time())
                if now != last_keepalive:
                    ws.send_text("SET keepalive")
                    last_keepalive = now
                readable, _writable, _errors = select.select([ws.sock], [], [], 0.20)
                if not readable:
                    continue
                message = ws.recv()
                if message[:3] == b"MSG":
                    params = kiwi.parse_msg_params(message)
                    if "audio_rate" in params:
                        ws.send_text(f"SET AR OK in={int(float(params['audio_rate']))} out=44100")
                    if "sample_rate" in params and not configured:
                        kiwi.send_snd_setup(ws, snd_carrier_khz(freq_khz, low_cut, high_cut), radio_mode, low_cut, high_cut)
                        configured = True
                        sample_deadline = time.monotonic() + SCOUT_RF_SAMPLE_SECONDS
                    continue
                if not configured or message[:3] != b"SND" or len(message) < 10:
                    continue
                body = message[3:]
                smeter, = struct.unpack(">H", body[5:7])
                readings = signal_readings if phase == "signal" else noise_readings
                readings.append(0.1 * smeter - 127.0)
                if sample_deadline and time.monotonic() >= sample_deadline and len(readings) >= 3:
                    if phase == "signal":
                        # A short adjacent-channel sample estimates the local
                        # noise floor. It is a practical SNR proxy, not a
                        # calibrated lab measurement.
                        noise_freq_khz = clamp(freq_khz + SCOUT_SNR_OFFSET_KHZ, 0.0, 30000.0)
                        kiwi.send_snd_setup(ws, snd_carrier_khz(noise_freq_khz, low_cut, high_cut), radio_mode, low_cut, high_cut)
                        phase = "noise"
                        sample_deadline = time.monotonic() + SCOUT_SNR_NOISE_SECONDS
                    else:
                        break
            if signal_readings:
                signal_ordered = sorted(signal_readings)
                signal_dbm = signal_ordered[len(signal_ordered) // 2]
                if noise_readings:
                    noise_ordered = sorted(noise_readings)
                    noise_dbm = noise_ordered[len(noise_ordered) // 2]
                    snr_db = signal_dbm - noise_dbm
                else:
                    snr_db = None
                snr_label = f" snr={snr_db:+.1f}dB" if snr_db is not None else " snr=unavailable"
                print(f"gl scout sample {server} signal={signal_dbm:.1f}dBm{snr_label}", flush=True)
                self.events.put(("sample", server, signal_dbm, snr_db))
            else:
                self.events.put(("failed", server, None, None))
        except Exception as exc:
            print(f"gl scout RF {server}: {exc}", flush=True)
            self.events.put(("failed", server, None, None))
        finally:
            if ws:
                ws.send_close()


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
            next_view_send_at = 0.0
            print(f"gl wf setup: {server} {freq_khz:.3f} kHz zoom {zoom}", flush=True)
            while not stop_event.is_set():
                server, freq_khz, zoom, _smeter_dbm, generation, server_generation = state.snapshot()
                next_floor, next_ceil, next_speed, next_auto, next_palette, wf_generation = state.waterfall_snapshot()
                live_tune_interval = 1.0 / state.tune_rate_snapshot()
                if server_generation != seen_server_generation:
                    seen_server_generation = server_generation
                    drain_queue(line_queue)
                    break
                now_monotonic = time.monotonic()
                if generation != seen_generation and now_monotonic >= next_view_send_at:
                    seen_generation = generation
                    drain_queue(line_queue)
                    kiwi.send_wf_setup(ws, freq_khz, zoom, wf_speed)
                    next_view_send_at = now_monotonic + live_tune_interval
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
                    readable, _writable, _errors = select.select([ws.sock], [], [], KIWI_IO_POLL_SECONDS)
                    if not readable:
                        continue
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
    parser.add_argument("--desktop", action="store_true", help="run locally in a mouse-driven 960x320 landscape development window")
    parser.add_argument("--orientation", choices=("flipped", "normal"), default="flipped")
    parser.add_argument("--event", type=Path, help="input event device, defaults to auto-detected Goodix")
    parser.add_argument("--invert-x", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--invert-y", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--swap-x-y", action="store_true")
    parser.add_argument("--invert-tune", action="store_true")
    parser.add_argument(
        "--finger-tune-positional",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="map finger distance to the active zoom span independently of drag velocity",
    )
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
    remembered_radio_mode = None
    if args.remember_receiver:
        remembered_view = load_remembered_view(args.receiver_state_file)
        if remembered_view:
            args.server = remembered_view["server"]
            args.freq_khz = remembered_view.get("freq_khz", args.freq_khz)
            args.zoom = remembered_view.get("zoom", args.zoom)
            remembered_radio_mode = remembered_view.get("radio_mode")
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

    if args.desktop:
        # Synthetic mouse events are already logical coordinates; do not apply
        # the touchscreen's hardware-specific axis corrections a second time.
        args.invert_x = False
        args.invert_y = False
        args.swap_x_y = False
    configure_output(args.desktop)
    set_display_orientation(args.orientation)
    setup_gl(args.desktop)
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
    radio_mode = remembered_radio_mode or default_sideband_mode(args.freq_khz)
    auto_sideband_mode = radio_mode
    manual_radio_mode = remembered_radio_mode is not None
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
    globe_mixer = GlobeAudioMixer(args, state)
    scout_probe = ConstellationScoutProbe(args, state)
    if args.remember_receiver:
        save_remembered_view(args.receiver_state_file, args.server, args.freq_khz, args.zoom, radio_mode, manual_radio_mode)
    wf_thread = threading.Thread(target=waterfall_worker, args=(args, line_queue, stop_event, state), daemon=True)
    snd_thread = threading.Thread(target=snd_meter_worker, args=(args, stop_event, state), daemon=True)
    wf_thread.start()
    snd_thread.start()

    desktop_event_writer = None
    if args.desktop:
        event_read_fd, desktop_event_writer = os.pipe()
        # The Pygame loop creates the synthetic touch events for this pipe.
        # It must therefore never wait here for an event that it has not yet
        # had a chance to poll from the desktop window.
        os.set_blocking(event_read_fd, False)
        ev = os.fdopen(event_read_fd, "rb", buffering=0)
        print(f"gl desktop window {NATIVE_W}x{NATIVE_H}; mouse drag tunes, wheel zooms", flush=True)
    else:
        event_path = args.event or kiwi.find_touch_event()
        ev = event_path.open("rb", buffering=0)
        print(f"gl touch input {event_path}", flush=True)
    os.set_blocking(ev.fileno(), False)

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
    tests_panel_open = False
    globe_open = False
    globe_receivers = load_globe_receivers()
    globe_result_queue = queue.Queue(maxsize=1)
    globe_fetch_started = False
    globe_yaw = math.radians(-20)
    globe_pitch = math.radians(18)
    globe_scale = 0.72
    globe_listeners = []
    globe_replacement_slots = []
    globe_scouts = []
    globe_scout_history = []
    globe_scout_measurements = {}
    globe_next_scout_rotation = 0.0
    globe_next_scout_promotion = 0.0
    globe_next_scout_review = 0.0
    globe_scout_search_radius_km = SCOUT_SEARCH_START_KM
    globe_scout_scanned_servers = set()
    globe_scout_local_rounds = 0
    globe_heat_frequency_khz = None
    globe_heat_radio_mode = None
    globe_anchor = None
    globe_active_server = None
    globe_status = "Tap a region to warm 3 listeners and launch 4 scouts"
    globe_start_yaw = globe_yaw
    globe_start_pitch = globe_pitch
    globe_pinch_distance = None
    globe_failed_servers = set()
    retune_pattern_index = 0
    retune_sweep = None
    dj_tune_open = False
    dj_origin_khz = args.freq_khz
    dj_current_khz = args.freq_khz
    dj_step_hz = 100
    dj_range_khz = 5.0
    dj_drag_remainder_hz = 0.0
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
        save_remembered_view(args.receiver_state_file, server, freq_khz, zoom, radio_mode, manual_radio_mode)

    def apply_band_default(freq_khz):
        """Follow the conventional 10 MHz split until the operator takes over."""
        nonlocal radio_mode, auto_sideband_mode
        # The retune test is observational. It must not unexpectedly change
        # the current demodulator while it crosses a nearby band threshold.
        if retune_sweep is not None:
            return
        desired_mode = default_sideband_mode(freq_khz)
        if manual_radio_mode or desired_mode == auto_sideband_mode:
            return
        radio_mode = desired_mode
        auto_sideband_mode = desired_mode
        state.set_radio_mode(radio_mode)
        print(f"gl auto sideband {radio_mode.lower()} freq={freq_khz:.3f}", flush=True)

    def controls_alpha(now=None):
        now = now or time.monotonic()
        if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or tests_panel_open or globe_open or dj_tune_open or filter_panel_open or now <= controls_active_until:
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

    def set_test_frequency(freq_khz):
        """Publish a fresh desired tune; workers consume state, not a queue."""
        nonlocal display_freq, candidate_freq, anim_start, inertia_velocity_khz_s
        frequency = clamp(freq_khz, 0.0, 30000.0)
        state.set_view(freq_khz=frequency)
        display_freq = frequency
        candidate_freq = frequency
        anim_start = 0.0
        inertia_velocity_khz_s = 0.0

    def start_retune_sweep():
        nonlocal retune_sweep, display_freq, candidate_freq, anim_start, inertia_velocity_khz_s
        _server, freq_khz, _zoom, _smeter, _generation, _server_generation = state.snapshot()
        retune_sweep = RetuneSweep(freq_khz, retune_pattern_index, time.monotonic())
        display_freq = freq_khz
        candidate_freq = freq_khz
        anim_start = 0.0
        inertia_velocity_khz_s = 0.0
        wake_controls()
        print(f"gl test start {retune_sweep.name} {retune_sweep.command_count} at {freq_khz:.3f} kHz", flush=True)

    def stop_retune_sweep(reason):
        nonlocal retune_sweep
        if retune_sweep is None:
            return
        start_khz = retune_sweep.start_khz
        retune_sweep = None
        set_test_frequency(start_khz)
        remember_current_view()
        print(f"gl test {reason}; restored {start_khz:.3f} kHz", flush=True)

    def advance_retune_sweep(now):
        nonlocal retune_sweep
        if retune_sweep is None:
            return
        step = retune_sweep.advance(now)
        if step is None:
            return
        frequency, done = step
        set_test_frequency(frequency)
        if done:
            finished = retune_sweep
            retune_sweep = None
            remember_current_view()
            print(f"gl test complete {finished.name}; restored {frequency:.3f} kHz", flush=True)

    def open_dj_tune():
        nonlocal dj_tune_open, dj_origin_khz, dj_current_khz, dj_drag_remainder_hz
        _server, frequency, _zoom, _smeter, _generation, _server_generation = state.snapshot()
        dj_tune_open = True
        dj_origin_khz = frequency
        dj_current_khz = frequency
        dj_drag_remainder_hz = 0.0
        wake_controls()

    def restore_dj_origin(reason):
        nonlocal dj_current_khz, dj_drag_remainder_hz
        set_test_frequency(dj_origin_khz)
        dj_current_khz = dj_origin_khz
        dj_drag_remainder_hz = 0.0
        remember_current_view()
        print(f"gl dj {reason}; restored {dj_origin_khz:.3f} kHz", flush=True)

    def advance_dj_tune(delta_px):
        nonlocal dj_current_khz, dj_drag_remainder_hz, display_freq, candidate_freq
        hz_per_px = 2.0 * dj_range_khz * 1000.0 / (DJ_TRACK_BOX[2] - DJ_TRACK_BOX[0])
        dj_drag_remainder_hz += delta_px * hz_per_px
        steps = math.trunc(dj_drag_remainder_hz / dj_step_hz)
        if not steps:
            return
        target = clamp(
            dj_current_khz + steps * dj_step_hz / 1000.0,
            dj_origin_khz - dj_range_khz,
            dj_origin_khz + dj_range_khz,
        )
        if target == dj_current_khz:
            dj_drag_remainder_hz = 0.0
            return
        dj_drag_remainder_hz -= steps * dj_step_hz
        dj_current_khz = target
        state.set_view(freq_khz=target)
        display_freq = target
        candidate_freq = target

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
            not args.finger_tune_positional
            and not repeat_zoom_applied
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
            not args.finger_tune_positional
            and not fast_sweep_zoom_applied
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

    desktop_pointer_down = False

    def desktop_logical_point(position):
        """Map a desktop mouse position directly into logical UI space."""
        window_w, window_h = pygame.display.get_window_size()
        nx = clamp(round(position[0] * NATIVE_W / max(1, window_w)), 0, NATIVE_W - 1)
        ny = clamp(round(position[1] * NATIVE_H / max(1, window_h)), 0, NATIVE_H - 1)
        if DESKTOP_MODE:
            return nx, ny
        if args.orientation == "normal":
            return clamp(ny, 0, LOGICAL_W - 1), clamp(ACTIVE_H - 1 - nx, 0, LOGICAL_H - 1)
        return clamp(NATIVE_H - 1 - ny, 0, LOGICAL_W - 1), clamp(nx - VISIBLE_Y_OFFSET, 0, LOGICAL_H - 1)

    def emit_desktop_touch(position, phase):
        """Feed mouse input to the established EV_ABS touch gesture pipeline."""
        if desktop_event_writer is None:
            return
        x, y = desktop_logical_point(position)

        def write(kind, code, value):
            os.write(desktop_event_writer, kiwi.EVENT_STRUCT.pack(0, 0, kind, code, int(value)))

        write(kiwi.EV_ABS, kiwi.ABS_X, x)
        write(kiwi.EV_ABS, kiwi.ABS_Y, y)
        if phase == "down":
            write(kiwi.EV_ABS, kiwi.ABS_MT_SLOT, 0)
            write(kiwi.EV_ABS, kiwi.ABS_MT_TRACKING_ID, 1)
            write(kiwi.EV_ABS, kiwi.ABS_MT_POSITION_X, x)
            write(kiwi.EV_ABS, kiwi.ABS_MT_POSITION_Y, y)
            write(kiwi.EV_KEY, kiwi.BTN_TOUCH, 1)
        elif phase == "move":
            write(kiwi.EV_ABS, kiwi.ABS_MT_POSITION_X, x)
            write(kiwi.EV_ABS, kiwi.ABS_MT_POSITION_Y, y)
        else:
            write(kiwi.EV_ABS, kiwi.ABS_MT_TRACKING_ID, -1)
            write(kiwi.EV_KEY, kiwi.BTN_TOUCH, 0)
        write(kiwi.EV_SYN, kiwi.SYN_REPORT, 0)


    try:
        while not stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    stop_event.set()
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                    stop_event.set()
                elif args.desktop and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    desktop_pointer_down = True
                    emit_desktop_touch(event.pos, "down")
                elif args.desktop and event.type == pygame.MOUSEMOTION and desktop_pointer_down:
                    emit_desktop_touch(event.pos, "move")
                elif args.desktop and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    emit_desktop_touch(event.pos, "up")
                    desktop_pointer_down = False
                elif args.desktop and event.type == pygame.MOUSEWHEEL and event.y:
                    change_zoom(1 if event.y > 0 else -1)

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
                            elif globe_open and any(contains(box, x, y) for box in GLOBE_STATION_BOXES):
                                gesture = "globe_station"
                            elif globe_open and contains(GLOBE_MAP_BOX, x, y) and not contains(GLOBE_INFO_BOX, x, y):
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
                                    # Regional receiver selection needs far more than a
                                    # whole-hemisphere view. Allow a continent-scale closeup.
                                    globe_scale = clamp(globe_scale * (distance / globe_pinch_distance), 0.55, 10.0)
                                    globe_pinch_distance = max(1.0, distance)
                            else:
                                globe_pinch_distance = None
                                # Treat the sphere as a direct-manipulation object:
                                # dragging right/down carries its visible surface right/down.
                                globe_yaw = (globe_start_yaw - (x - start_x) * 0.011 + math.pi) % math.tau - math.pi
                                globe_pitch = clamp(globe_start_pitch + (y - start_y) * 0.008, math.radians(-80), math.radians(80))
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
                                globe_mixer.stop()
                                scout_probe.stop()
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
                                globe_mixer.stop()
                                scout_probe.stop()
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
                                globe_mixer.stop()
                                scout_probe.stop()
                            wake_controls()
                        elif touch_started and gesture == "globe_station":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                selected_index = next((index for index, box in enumerate(GLOBE_STATION_BOXES) if contains(box, x, y)), None)
                                if selected_index is not None and selected_index < len(globe_listeners):
                                    selected = globe_listeners[selected_index]
                                    globe_active_server = selected["server"]
                                    globe_mixer.select(selected["server"])
                                    globe_status = "Switching live waterfall and audio"
                                    _server, freq_khz, zoom, _gen, _server_gen = state.set_server(selected["server"])
                                    remember_current_view()
                                    drain_queue(line_queue)
                                    wf_texture.clear()
                                    animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                                    print(f"gl globe select {selected['name']}: {selected['server']}", flush=True)
                            wake_controls()
                        elif touch_started and gesture == "globe":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px and globe_receivers:
                                # A measured SNR tile takes precedence over a nearby
                                # directory dot. That makes a tap on past coverage turn
                                # the actual scouted receiver into warm listener #1.
                                anchor = scouted_receiver_at_tap(
                                    x, y, globe_scouts, globe_scout_history, globe_scout_measurements,
                                    math.degrees(globe_yaw), math.degrees(globe_pitch),
                                    GLOBE_MAP_BOX, globe_scale,
                                )
                                # Otherwise resolve against visible directory dots. This
                                # naturally selects the receiver cluster under the finger.
                                candidates = []
                                if anchor is None:
                                    for receiver in globe_receivers:
                                        point = flat_map_project(
                                            receiver,
                                            math.degrees(globe_yaw),
                                            math.degrees(globe_pitch),
                                            GLOBE_MAP_BOX,
                                            globe_scale,
                                        )
                                        if point:
                                            candidates.append((math.hypot(point[0] - x, point[1] - y), receiver))
                                    if candidates:
                                        _distance, anchor = min(candidates, key=lambda item: item[0])
                                if anchor is not None:
                                    _map_server, map_freq_khz, _map_zoom, _map_smeter, _map_view_gen, _map_server_gen = state.snapshot()
                                    map_radio_mode, _map_low_cut, _map_high_cut, _map_radio_gen = state.radio_snapshot()
                                    retain_heat = (
                                        globe_heat_frequency_khz is not None
                                        and abs(map_freq_khz - globe_heat_frequency_khz) < 0.001
                                        and map_radio_mode == globe_heat_radio_mode
                                    )
                                    if not retain_heat:
                                        globe_scout_history = []
                                        globe_scout_scanned_servers = set()
                                    globe_heat_frequency_khz = map_freq_khz
                                    globe_heat_radio_mode = map_radio_mode
                                    globe_anchor = anchor
                                    globe_listeners, globe_scouts = choose_constellation(anchor, globe_receivers, station_health)
                                    remaining_scout_budget = max(0, SCOUT_MAX_TOTAL - len(globe_scout_scanned_servers))
                                    globe_scouts = [
                                        scout for scout in globe_scouts
                                        if scout["server"] not in globe_scout_scanned_servers
                                    ][:remaining_scout_budget]
                                    globe_replacement_slots = [
                                        {
                                            "current_server": receiver["server"],
                                            "original_server": receiver["server"],
                                            "previous_name": bottom_station_title(receiver["name"], receiver["location"]),
                                            "reason": None,
                                            "gain_db": 0.0,
                                            "snr": None,
                                        }
                                        for receiver in globe_listeners
                                    ]
                                    globe_scout_measurements = {}
                                    globe_scout_search_radius_km = max(
                                        SCOUT_SEARCH_START_KM,
                                        max((globe_haversine_km(anchor, scout) for scout in globe_scouts), default=0.0),
                                    )
                                    globe_scout_scanned_servers.update(scout["server"] for scout in globe_scouts)
                                    globe_scout_local_rounds = 0
                                    globe_next_scout_rotation = time.monotonic() + SCOUT_ROTATION_SECONDS
                                    globe_next_scout_promotion = time.monotonic() + 10.0
                                    globe_next_scout_review = time.monotonic() + 10.0
                                    globe_failed_servers.clear()
                                    globe_active_server = globe_listeners[0]["server"] if globe_listeners else None
                                    if globe_active_server:
                                        _server, freq_khz, zoom, _gen, _server_gen = state.set_server(globe_active_server)
                                        remember_current_view()
                                        drain_queue(line_queue)
                                        wf_texture.clear()
                                        animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                                        globe_mixer.start(globe_listeners, globe_active_server)
                                        heat_label = "retaining prior heat cloud; " if retain_heat else "new heat cloud; "
                                        if globe_scouts:
                                            scout_probe.scan(globe_scouts)
                                            globe_status = f"{heat_label}{len(globe_listeners)}/3 listeners warming"
                                        else:
                                            scout_probe.stop()
                                            globe_status = f"Scout cap ({SCOUT_MAX_TOTAL}) reached; heat cloud retained"
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
            while True:
                try:
                    globe_event, globe_server = globe_mixer.events.get_nowait()
                except queue.Empty:
                    break
                if globe_event == "ready":
                    ready_count = len(globe_mixer.ready_servers)
                    globe_status = f"{ready_count}/{len(globe_listeners)} listener streams warmed; 4 scouts sampling"
                elif globe_event == "failed" and globe_server in {r["server"] for r in globe_listeners}:
                    globe_failed_servers.add(globe_server)
                    if globe_server == globe_active_server:
                        ready_servers = globe_mixer.ready_snapshot()
                        standbys = [
                            receiver for receiver in globe_listeners
                            if receiver["server"] != globe_server and receiver["server"] not in globe_failed_servers
                        ]
                        # Prefer a stream already producing PCM; if neither is
                        # ready, select the first survivor so it becomes active
                        # as soon as its warm connection finishes.
                        fallback = next((receiver for receiver in standbys if receiver["server"] in ready_servers), None)
                        fallback = fallback or (standbys[0] if standbys else None)
                        if fallback:
                            globe_active_server = fallback["server"]
                            globe_mixer.select(fallback["server"])
                            _server, freq_khz, zoom, _gen, _server_gen = state.set_server(fallback["server"])
                            remember_current_view()
                            drain_queue(line_queue)
                            wf_texture.clear()
                            animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                            print(
                                f"gl globe failover {globe_server} -> {fallback['server']} "
                                f"ready={fallback['server'] in ready_servers}",
                                flush=True,
                            )
                        else:
                            globe_status = "Active receiver failed; no warm standby available"
                            continue
                    replace_index = next(i for i, receiver in enumerate(globe_listeners) if receiver["server"] == globe_server)
                    occupied = {receiver["server"] for receiver in globe_listeners} | globe_failed_servers
                    candidates = sorted(
                        (receiver for receiver in globe_receivers if receiver["server"] not in occupied),
                        key=lambda receiver: globe_haversine_km(globe_anchor, receiver),
                    ) if globe_anchor else []
                    if candidates:
                        replacement = candidates[0]
                        globe_listeners[replace_index] = replacement
                        if replace_index < len(globe_replacement_slots):
                            globe_replacement_slots[replace_index].update({
                                "current_server": replacement["server"],
                                "reason": "failed",
                                "snr": None,
                            })
                        if globe_active_server == globe_server:
                            globe_active_server = replacement["server"]
                            _server, freq_khz, zoom, _gen, _server_gen = state.set_server(replacement["server"])
                            animate_to(freq_khz, kiwi.zoom_to_span_khz(zoom), 0.20)
                        globe_status = "Active failed — switched to warm standby; replenishing listener"
                        globe_mixer.start(globe_listeners, globe_active_server)
                        globe_next_scout_promotion = now + 10.0
                        globe_next_scout_review = now + 10.0
            while True:
                try:
                    scout_event, scout_server, scout_smeter_dbm, scout_snr_db = scout_probe.events.get_nowait()
                except queue.Empty:
                    break
                if scout_server in {receiver["server"] for receiver in globe_scouts}:
                    globe_scout_measurements[scout_server] = {
                        "smeter": scout_smeter_dbm if scout_event == "sample" else None,
                        "snr": scout_snr_db if scout_event == "sample" else None,
                        "sampled_at": now,
                    }
                    if scout_event == "sample":
                        # Persist each completed probe immediately. A listener
                        # promotion can start a fresh scout batch before the
                        # next scheduled rotation; committing only at rotation
                        # used to throw those valid SNR readings away.
                        globe_scout_history.append((
                            next(receiver for receiver in globe_scouts if receiver["server"] == scout_server),
                            now,
                            scout_smeter_dbm,
                            scout_snr_db,
                        ))
                        globe_scout_scanned_servers.add(scout_server)
                        snr_label = f", SNR~{scout_snr_db:+.0f} dB" if scout_snr_db is not None else ""
                        globe_status = f"Scout RF measured at {scout_smeter_dbm:.0f} dBm{snr_label}"
            if globe_anchor and now >= globe_next_scout_promotion and now >= globe_next_scout_review:
                listener_measurements = globe_mixer.smeter_snapshot()
                promotion = choose_scout_promotion(
                    globe_listeners,
                    globe_active_server,
                    globe_scouts,
                    globe_scout_measurements,
                    listener_measurements,
                    now,
                )
                standby_report = ", ".join(
                    f"{receiver['server']}={format_scout_measurement(listener_measurements.get(receiver['server']))}"
                    for receiver in globe_listeners if receiver["server"] != globe_active_server
                ) or "none"
                scout_report = ", ".join(
                    f"{receiver['server']}={format_scout_measurement(globe_scout_measurements.get(receiver['server']))}"
                    for receiver in globe_scouts
                ) or "none"
                if promotion:
                    improvement, listener_index, scout, scout_dbm, listener_dbm = promotion
                    displaced = globe_listeners[listener_index]
                    scout_index = next(index for index, receiver in enumerate(globe_scouts) if receiver["server"] == scout["server"])
                    globe_listeners[listener_index] = scout
                    if listener_index < len(globe_replacement_slots):
                        globe_replacement_slots[listener_index].update({
                            "current_server": scout["server"],
                            "previous_name": bottom_station_title(displaced["name"], displaced["location"]),
                            "reason": "scout",
                            "gain_db": improvement,
                            "snr": globe_scout_measurements.get(scout["server"], {}).get("snr"),
                        })
                    globe_scouts[scout_index] = displaced
                    globe_scout_scanned_servers.add(displaced["server"])
                    globe_scout_measurements = {}
                    globe_mixer.start(globe_listeners, globe_active_server)
                    scout_probe.scan(globe_scouts)
                    globe_next_scout_promotion = now + SCOUT_PROMOTION_COOLDOWN_SECONDS
                    globe_status = f"Scout promoted: {scout_dbm:.0f} dBm replaces {listener_dbm:.0f} dBm standby"
                    print(
                        f"gl scout promote {scout['server']} {scout_dbm:.1f}dBm -> "
                        f"{displaced['server']} {listener_dbm:.1f}dBm gain={improvement:.1f}dB",
                        flush=True,
                    )
                else:
                    print(
                        f"gl scout review no-promotion active={globe_active_server} "
                        f"standbys=[{standby_report}] scouts=[{scout_report}] "
                        f"margin={SCOUT_PROMOTION_MARGIN_DB:.1f}dB cooldown_until={globe_next_scout_promotion:.1f}",
                        flush=True,
                    )
                globe_next_scout_review = now + SCOUT_PROMOTION_REVIEW_SECONDS
            if globe_anchor and now >= globe_next_scout_rotation and globe_receivers:
                # Preserve previous scout samples in the same heat cloud, then
                # move the four live scouts through the next nearby candidates.
                globe_scout_history = [
                    (receiver, scanned_at, smeter_dbm, snr_db)
                    for receiver, scanned_at, smeter_dbm, snr_db in globe_scout_history
                    if now - scanned_at < SCOUT_HEAT_REMANENCE_SECONDS
                ]
                globe_scout_scanned_servers.update(
                    receiver["server"] for receiver, _scanned_at, _smeter_dbm, _snr_db in globe_scout_history
                )
                if len(globe_scout_scanned_servers) >= SCOUT_MAX_TOTAL:
                    globe_scouts = []
                    globe_scout_measurements = {}
                    scout_probe.stop()
                    globe_next_scout_rotation = now + 3600.0
                    globe_status = f"Scout cap reached: {SCOUT_MAX_TOTAL} locations mapped"
                    print(f"gl scout cap reached total={SCOUT_MAX_TOTAL}", flush=True)
                else:
                    if globe_scout_local_rounds < SCOUT_LOCAL_ROUNDS:
                        next_scouts, globe_scout_search_radius_km = choose_expanding_scouts(
                            globe_anchor,
                            globe_receivers,
                            globe_listeners,
                            globe_scout_scanned_servers,
                            globe_scout_search_radius_km,
                        )
                        globe_scout_local_rounds += 1
                        scout_status = f"4 scouts expanding locally to {globe_scout_search_radius_km / 1.609344:.0f} MI"
                    else:
                        next_scouts = choose_global_coverage_scouts(
                            globe_receivers,
                            globe_listeners,
                            globe_scout_history,
                            globe_scout_scanned_servers,
                        )
                        scout_status = "4 scouts maximizing global heatmap coverage"
                    remaining_scout_budget = SCOUT_MAX_TOTAL - len(globe_scout_scanned_servers)
                    globe_scouts = next_scouts[:remaining_scout_budget]
                    globe_scout_scanned_servers.update(scout["server"] for scout in globe_scouts)
                    globe_scout_measurements = {}
                    if globe_scouts:
                        scout_probe.scan(globe_scouts)
                        globe_next_scout_rotation = now + SCOUT_ROTATION_SECONDS
                        globe_status = scout_status
                    else:
                        scout_probe.stop()
                        globe_next_scout_rotation = now + 3600.0
                        globe_status = f"Scout cap reached: {SCOUT_MAX_TOTAL} locations mapped"
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
                draw_globe_panel(
                    text_cache, globe_receivers, globe_yaw, globe_pitch, globe_scale,
                    globe_listeners, globe_mixer.smeter_snapshot(), globe_scouts,
                    globe_scout_history, globe_scout_measurements,
                    globe_replacement_slots, len(globe_scout_scanned_servers),
                    globe_active_server, globe_anchor, globe_status,
                )
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
            # macOS's SDL OpenGL path can leave the composited window black
            # even though glReadPixels sees a complete backbuffer. Explicitly
            # flush before the swap so the drawable is presented to Cocoa.
            if DESKTOP_MODE:
                GL.glFlush()
            pygame.display.flip()
            frames += 1
            if args.duration and time.monotonic() - start >= args.duration:
                break
            clock.tick(args.fps)
    finally:
        globe_mixer.stop()
        scout_probe.stop()
        stop_event.set()
        ev.close()
        if desktop_event_writer is not None:
            os.close(desktop_event_writer)
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
