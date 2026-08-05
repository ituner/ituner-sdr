#!/usr/bin/env python3
import argparse
from collections import deque
import ctypes
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
import tempfile
import threading
import time
import re
import html
import wave
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    # `audioop` was removed in Python 3.13. It is only needed for the local
    # CoreAudio convenience player; the Pi's PipeWire path does not use it.
    import audioop
except ImportError:
    audioop = None

try:
    import vosk
except ImportError:
    vosk = None

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

try:
    import moonshine_voice
except ImportError:
    moonshine_voice = None

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
BASE_LOGICAL_W = LOGICAL_W
BASE_LOGICAL_H = LOGICAL_H
ACTIVE_H = 400
VISIBLE_Y_OFFSET = ACTIVE_H - LOGICAL_H
DESKTOP_MODE = False
DESKTOP_1280_MODE = False
DESKTOP_AUDIO_VOLUME = 1.0
WATERFALL_Y0 = sdr_ui.TOP_H + sdr_ui.RULER_H - 12
WATERFALL_Y1 = 292
WATERFALL_FOCUS_Y0 = sdr_ui.TOP_H
WATERFALL_FOCUS_Y1 = LOGICAL_H
DESKTOP_1280_MAIN_W = 1024
DESKTOP_1280_NAV_W = 256
DESKTOP_1280_STATUS_Y = 452
DESKTOP_1280_TOP_H = 96
# The wide layout's radio-status control deliberately shares the exact outer
# bounds of the two-column navigation rail beneath it. It is one touch target.
DESKTOP_1280_ANNUNCIATOR_BOX = (1031, 0, 1273, 96)
DESKTOP_1280_MODE_ANNUNCIATORS = ("AM", "SAM", "DRM", "LSB", "USB", "CW", "NBFM", "IQ")
_RENDERER_DIR = Path(__file__).resolve().parent
_MENU_ICON_DIRS = (_RENDERER_DIR.parent / "assets" / "menu-icons", _RENDERER_DIR / "assets" / "menu-icons")
MENU_ICON_ASSET_DIR = next((directory for directory in _MENU_ICON_DIRS if directory.exists()), _MENU_ICON_DIRS[0])
MENU_ICON_FILENAMES = {
    "rx": "receivers.png",
    "digital": "digi.png",
}
SPECTRUM_H = 70
# 109 px is a 22.1% reduction from the original 140 px wide scope, returning
# the recovered vertical space directly to the live waterfall.
SPECTRUM_WIDE_H = 109
SPECTRUM_WIDE_RAISE_Y = 10
SPECTRUM_RAISE_Y = 12
# In the wide display's Waterfall-only view, let live RF content occupy the
# unused scope space behind the fixed top instrumentation.
WATERFALL_ONLY_WIDE_RAISE_Y = 52
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
ASR_TOGGLE_BOX = (826, LOGICAL_H - BOTTOM_STATUS_H, LOGICAL_W, LOGICAL_H)
# This replaces the old one-bit Vosk switch with deliberate, readable
# choices. It is transient and leaves the radio view visible beneath it.
ASR_PANEL_BOX = (244, 186, 716, 244)
ASR_ENGINES = ("off", "vosk", "moonshine", "parakeet", "whisper")
ASR_ENGINE_LABELS = {
    "off": "OFF", "vosk": "VOSK", "moonshine": "MOON",
    "parakeet": "PARA", "whisper": "WHISPER",
}
VOSK_CAPTION_BOX = (16, LOGICAL_H - BOTTOM_STATUS_H - BOTTOM_RULER_H - 108, 944, LOGICAL_H - BOTTOM_STATUS_H - BOTTOM_RULER_H - 4)
VOSK_MODEL_OVERRIDE = os.environ.get("ITUNER_VOSK_MODEL")
VOSK_MODEL_PATHS = (
    Path("/home/ituner/codex-sdr-display/vendor/vosk-model-small-en-us-0.15"),
    # The larger lgraph model is installed for controlled tests, but it runs
    # over 3x behind real time on this 2 GB Pi and must not be the live default.
    Path("/home/ituner/codex-sdr-display/vendor/vosk-model-en-us-0.22-lgraph"),
)
# Moonshine Base has materially better English recognition than Tiny. The
# smaller model remains a no-touch fallback for installs with tighter storage.
MOONSHINE_MODEL_DIRS = (
    Path("/home/ituner/codex-sdr-display/vendor/sherpa-onnx-moonshine-base-en-int8"),
    Path("/home/ituner/codex-sdr-display/vendor/sherpa-onnx-moonshine-tiny-en-int8"),
)
MOONSHINE_STREAMING_MODEL_DIR = Path(
    "/home/ituner/codex-sdr-display/vendor/moonshine-voice/"
    "download.moonshine.ai/model/small-streaming-en/quantized"
)
# The official Small Streaming model is installed for controlled benchmarks,
# but on this Pi it measured 1.53x real time and starved live captions. Keep
# it opt-in only; the Base engine is the production Moonshine setting.
MOONSHINE_SMALL_STREAMING_TRIAL = os.environ.get("ITUNER_MOONSHINE_SMALL_STREAMING") == "1"
WHISPER_CLI = Path("/home/ituner/codex-sdr-display/vendor/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = Path("/home/ituner/codex-sdr-display/vendor/whisper.cpp/models/ggml-tiny.en.bin")
PARAKEET_MODEL_DIR = Path("/home/ituner/codex-sdr-display/vendor/sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8")
WF_TEX_W = 960
WF_TEX_H = 256
DISPLAY_ORIENTATION = "flipped"
ZOOM_MINUS_BOX = (24, 197, 96, 257)
ZOOM_PLUS_BOX = (168, 197, 240, 257)
ZOOM_GROUP_BOX = (16, 194, 248, 260)
FILTER_TOGGLE_BOX = (740, 190, 828, 262)
SPECTRUM_TOGGLE_BOX = (850, 190, 938, 262)
VIEW_GROUP_BOX = (742, 188, 946, 264)
BASE_ZOOM_MINUS_BOX = ZOOM_MINUS_BOX
BASE_ZOOM_PLUS_BOX = ZOOM_PLUS_BOX
BASE_ZOOM_GROUP_BOX = ZOOM_GROUP_BOX
BASE_FILTER_TOGGLE_BOX = FILTER_TOGGLE_BOX
BASE_SPECTRUM_TOGGLE_BOX = SPECTRUM_TOGGLE_BOX
BASE_VIEW_GROUP_BOX = VIEW_GROUP_BOX
# The 480 px desktop test keeps its persistent ruler/status band at the
# bottom. Place its transient view controls immediately above that band.
WIDE_ZOOM_MINUS_BOX = (24, 345, 96, 405)
WIDE_ZOOM_PLUS_BOX = (168, 345, 240, 405)
WIDE_ZOOM_GROUP_BOX = (16, 342, 248, 408)
WIDE_FILTER_TOGGLE_BOX = (780, 340, 868, 410)
WIDE_SPECTRUM_TOGGLE_BOX = (890, 340, 978, 410)
WIDE_VIEW_GROUP_BOX = (782, 338, 986, 412)
HOME_BOX = (30, 13, 102, 71)
# The top instruments share one right alignment. Home is intentionally the
# single left-anchored control.
# The S legend sits left of the LED bars. Align to that true visual edge,
# leaving a 28 px quiet gap before the meter typography rather than its bars.
FREQUENCY_RIGHT_X = 570
RADIO_SETUP_WIDTH = 74
RADIO_SETUP_GAP = 10
RADIO_SETUP_BOX = (260, 10, 334, 54)
RADIO_PANEL_BOX = (12, 66, 948, 316)
# All Kiwi demodulators are reached through eight large touch families. A
# family opens a second, full-width choice tray when it has variants.
KIWI_MODE_FAMILIES = (
    ("AM", ("AM", "AMN", "AMW")),
    ("SYNC AM", ("SAM", "SAU", "SAL", "SAS", "QAM")),
    ("USB", ("USB", "USN")),
    ("LSB", ("LSB", "LSN")),
    ("CW", ("CW", "CWN")),
    ("FM", ("NBFM", "NNFM")),
    ("I/Q", ("IQ",)),
    ("DRM", ("DRM",)),
)
KIWI_RADIO_MODES = frozenset(mode for _family, modes in KIWI_MODE_FAMILIES for mode in modes)
KIWI_MODE_LABELS = {
    "AM": "AM",
    "AMN": "AM NARROW",
    "AMW": "AM WIDE",
    "SAM": "SYNC AM",
    "SAU": "SYNC USB",
    "SAL": "SYNC LSB",
    "SAS": "PSEUDO ST",
    "QAM": "C-QUAM",
    "USB": "USB",
    "USN": "USB NARROW",
    "LSB": "LSB",
    "LSN": "LSB NARROW",
    "CW": "CW",
    "CWN": "CW NARROW",
    "NBFM": "NBFM",
    "NNFM": "NFM NARROW",
    "IQ": "I/Q",
    "DRM": "DRM",
}
KIWI_MODE_CONTEXT = {
    "AM": "AM",
    "AMN": "AMN · AM NARROW",
    "AMW": "AMW · AM WIDE",
    "SAM": "SAM · SYNCHRONOUS AM",
    "SAU": "SAU · SYNC UPPER",
    "SAL": "SAL · SYNC LOWER",
    "SAS": "SAS · PSEUDO STEREO",
    "QAM": "C-QUAM · AM STEREO",
    "USB": "USB",
    "USN": "USN · USB NARROW",
    "LSB": "LSB",
    "LSN": "LSN · LSB NARROW",
    "CW": "CW",
    "CWN": "CWN · CW NARROW",
    "NBFM": "NBFM",
    "NNFM": "NNFM · FM NARROW",
    "IQ": "I/Q · COMPLEX",
    "DRM": "DRM · EXTENSION",
}
KIWI_MODE_FAMILY = {
    "AM": "AM", "AMN": "AM", "AMW": "AM",
    "SAM": "SAM", "SAU": "SAM", "SAL": "SAM", "SAS": "SAM", "QAM": "SAM",
    "USB": "USB", "USN": "USB",
    "LSB": "LSB", "LSN": "LSB",
    "CW": "CW", "CWN": "CW",
    "NBFM": "NBFM", "NNFM": "NBFM",
    "IQ": "IQ", "DRM": "DRM",
}
# Defaults match Kiwi's mode_hbw/mode_offset table. Values are the actual
# low_cut/high_cut sent to the SND stream and remain user-adjustable afterward.
KIWI_MODE_FILTERS = {
    "am": (-4900, 4900),
    "amn": (-2500, 2500),
    "amw": (-6000, 6000),
    "sam": (-4900, 4900),
    "sau": (-4900, 4900),
    "sal": (-4900, 4900),
    "sas": (-4900, 4900),
    "qam": (-4900, 4900),
    "usb": (300, 2700),
    "usn": (300, 2400),
    "lsb": (-2700, -300),
    "lsn": (-2400, -300),
    "cw": (-200, 200),
    "cwn": (-30, 30),
    "nbfm": (-6000, 6000),
    "nnfm": (-3000, 3000),
    "iq": (-5000, 5000),
    "drm": (-5000, 5000),
}
KIWI_STEREO_AUDIO_MODES = frozenset(("sas", "qam"))
KIWI_NON_AUDIO_MODES = frozenset(("iq", "drm"))
RADIO_FAMILY_GRID_X0 = 30
RADIO_FAMILY_GRID_X1 = 934
RADIO_FAMILY_GRID_Y0 = 112
RADIO_FAMILY_COLS = 4
RADIO_FAMILY_BUTTON_H = 78
RADIO_FAMILY_BUTTON_GAP = 10
RADIO_VARIANT_MENU_W = 420
RADIO_VARIANT_BUTTON_H = 52
RADIO_VARIANT_BUTTON_GAP = 8
RADIO_VARIANT_COLS = 2
RADIO_STEP_OPTIONS = (
    (10, (590, 74, 670, 100)),
    (100, (678, 74, 758, 100)),
    (1000, (766, 74, 846, 100)),
    (5000, (854, 74, 934, 100)),
)


def radio_popup_offset_x():
    """Center the 960 px radio modal over the 1024 px wide waterfall."""
    return (DESKTOP_1280_MAIN_W - BASE_LOGICAL_W) // 2 if DESKTOP_1280_MODE else 0


def radio_popup_offset_y():
    """Keep the radio panel on the lower edge in both display geometries."""
    return max(0, LOGICAL_H - BASE_LOGICAL_H)


def radio_popup_x(x):
    return x + radio_popup_offset_x()


def radio_popup_y(y):
    return y + radio_popup_offset_y()


def radio_popup_box(box):
    x0, y0, x1, y1 = box
    return radio_popup_x(x0), radio_popup_y(y0), radio_popup_x(x1), radio_popup_y(y1)


def radio_step_options():
    for step_hz, box in RADIO_STEP_OPTIONS:
        yield step_hz, radio_popup_box(box)


def radio_panel_box():
    return radio_popup_box(RADIO_PANEL_BOX)


def radio_family_button_width():
    available = RADIO_FAMILY_GRID_X1 - RADIO_FAMILY_GRID_X0
    return (available - RADIO_FAMILY_BUTTON_GAP * (RADIO_FAMILY_COLS - 1)) / RADIO_FAMILY_COLS


def radio_variant_popup_box(modes):
    """Return a compact two-column context menu near the selected family."""
    family = next((family for family, options in KIWI_MODE_FAMILIES if options == modes), "")
    family_box = next((box for label, _options, box in radio_mode_layout() if label == family), radio_panel_box())
    cols = min(RADIO_VARIANT_COLS, len(modes))
    rows = math.ceil(len(modes) / cols)
    width = RADIO_VARIANT_MENU_W
    height = 42 + rows * RADIO_VARIANT_BUTTON_H + (rows - 1) * RADIO_VARIANT_BUTTON_GAP + 16
    panel_x0, _panel_y0, panel_x1, panel_y1 = radio_panel_box()
    x0 = min(max((family_box[0] + family_box[2] - width) / 2, panel_x0 + 8), panel_x1 - width - 8)
    y0 = panel_y1 - height - 8
    return x0, y0, x0 + width, y0 + height


def radio_variant_back_box(modes):
    x0, y0, _x1, _y1 = radio_variant_popup_box(modes)
    return x0 + 12, y0 + 7, x0 + 112, y0 + 35

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
AUDIO_PANEL_BOX = (12, 34, 948, 316)
AUDIO_VOLUME_BOX = (42, 76, 692, 128)
AUDIO_MUTE_BOX = (716, 76, 814, 128)
AUDIO_VOICE_CLEAN_BOX = (826, 76, 918, 128)
AUDIO_SQUELCH_BOX = (42, 154, 256, 210)
AUDIO_AGC_BOX = (268, 154, 482, 210)
AUDIO_BLANKER_BOX = (494, 154, 706, 210)
AUDIO_DENOISE_BOX = (718, 154, 918, 210)
AUDIO_NOTCH_BOX = (42, 224, 256, 280)
AUDIO_DEEMP_BOX = (268, 224, 482, 280)
AUDIO_FILTER_BOX = (494, 224, 706, 280)
AUDIO_RESET_BOX = (718, 224, 918, 280)
# Six evenly spaced, discrete Denoise settings. The DSP presets themselves
# remain intentionally useful at the strong end; only the touch scale is linear.
DENOISE_SLIDER_POSITIONS = (0.00, 0.20, 0.40, 0.60, 0.80, 1.00)
# A clear, no-extra-controls loudness recovery curve. It reaches the requested
# 0..12 dB range only at maximum cleanup and is applied after Kiwi's DSP.
DENOISE_MAKEUP_GAIN_DB = (0, 2, 4, 6, 9, 12)
# Speech cleanup has deliberately few operator-facing choices. Each level is
# a fixed RNNoise wet/dry blend: lower settings retain more radio brightness.
VOICE_CLEAN_PRESETS = ("OFF", "MEDIUM", "STRONG")
VOICE_CLEAN_MIX = (0.0, 0.75, 1.0)
# RNNoise is intentionally kept local to the Pi. The public Kiwi receiver
# remains responsible for demodulation while this optional stage cleans the
# received mono PCM before it reaches PipeWire/USB audio.
RNNOISE_LIBRARY = Path(os.environ.get(
    "ITUNER_RNNOISE_LIBRARY",
    "/home/ituner/codex-sdr-display/vendor/rnnoise-install/lib/librnnoise.so",
))
SPEEXDSP_LIBRARY = os.environ.get("ITUNER_SPEEXDSP_LIBRARY", "libspeexdsp.so.1")
PREFERENCES_WRITE_IDLE_SECONDS = 1.5
FREQUENCY_WRITE_IDLE_SECONDS = 60.0
PREFERENCES_POLL_SECONDS = 0.25
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
POPUP_BOTTOM_INSET = 4
# These temporary workspaces have intentionally different heights, but they
# should all end on the same lower visual edge. Keep immutable source geometry
# here so desktop/Pi mode changes never accumulate offsets.
POPUP_LAYOUT_BASE = {
    "display": (DISPLAY_PANEL_BOX, DISPLAY_SPECTRUM_BOX, DISPLAY_AUTO_BOX,
                DISPLAY_FLOOR_MINUS_BOX, DISPLAY_FLOOR_PLUS_BOX,
                DISPLAY_CEIL_MINUS_BOX, DISPLAY_CEIL_PLUS_BOX,
                DISPLAY_RATE_BOXES, DISPLAY_PALETTE_BOXES),
    "filter": (FILTER_PANEL_BOX, FILTER_EDIT_BOX, FILTER_WIDTH_MINUS_BOX,
               FILTER_WIDTH_LABEL_BOX, FILTER_WIDTH_PLUS_BOX),
    "audio": (AUDIO_PANEL_BOX, AUDIO_VOLUME_BOX, AUDIO_MUTE_BOX, AUDIO_VOICE_CLEAN_BOX,
              AUDIO_SQUELCH_BOX, AUDIO_AGC_BOX, AUDIO_BLANKER_BOX,
              AUDIO_DENOISE_BOX, AUDIO_NOTCH_BOX, AUDIO_DEEMP_BOX,
              AUDIO_FILTER_BOX, AUDIO_RESET_BOX),
    "tests": (TEST_PANEL_BOX, TEST_GLOBE_BOX, TEST_DJ_BOX, TEST_PATTERN_BOX,
              TEST_RUN_BOX),
    "dj": (DJ_PANEL_BOX, DJ_TRACK_BOX, DJ_STEP_BOX, DJ_RANGE_BOX,
           DJ_RATE_BOX, DJ_RETURN_BOX),
}


def popup_shift_box(box, offset_y):
    x0, y0, x1, y1 = box
    return x0, y0 + offset_y, x1, y1 + offset_y


def configure_popup_layout():
    """Bottom-align every temporary workspace and its touch geometry."""
    global DISPLAY_PANEL_BOX, DISPLAY_SPECTRUM_BOX, DISPLAY_AUTO_BOX
    global DISPLAY_FLOOR_MINUS_BOX, DISPLAY_FLOOR_PLUS_BOX
    global DISPLAY_CEIL_MINUS_BOX, DISPLAY_CEIL_PLUS_BOX
    global DISPLAY_RATE_BOXES, DISPLAY_PALETTE_BOXES
    global FILTER_PANEL_BOX, FILTER_EDIT_BOX, FILTER_WIDTH_MINUS_BOX
    global FILTER_WIDTH_LABEL_BOX, FILTER_WIDTH_PLUS_BOX
    global AUDIO_PANEL_BOX, AUDIO_VOLUME_BOX, AUDIO_MUTE_BOX, AUDIO_VOICE_CLEAN_BOX
    global AUDIO_SQUELCH_BOX, AUDIO_AGC_BOX, AUDIO_BLANKER_BOX
    global AUDIO_DENOISE_BOX, AUDIO_NOTCH_BOX, AUDIO_DEEMP_BOX
    global AUDIO_FILTER_BOX, AUDIO_RESET_BOX
    global TEST_PANEL_BOX, TEST_GLOBE_BOX, TEST_DJ_BOX, TEST_PATTERN_BOX, TEST_RUN_BOX
    global DJ_PANEL_BOX, DJ_TRACK_BOX, DJ_STEP_BOX, DJ_RANGE_BOX, DJ_RATE_BOX, DJ_RETURN_BOX

    def offset(kind):
        panel = POPUP_LAYOUT_BASE[kind][0]
        return LOGICAL_H - POPUP_BOTTOM_INSET - panel[3]

    dy = offset("display")
    (DISPLAY_PANEL_BOX, DISPLAY_SPECTRUM_BOX, DISPLAY_AUTO_BOX,
     DISPLAY_FLOOR_MINUS_BOX, DISPLAY_FLOOR_PLUS_BOX,
     DISPLAY_CEIL_MINUS_BOX, DISPLAY_CEIL_PLUS_BOX,
     base_rates, base_palettes) = POPUP_LAYOUT_BASE["display"]
    DISPLAY_PANEL_BOX = popup_shift_box(DISPLAY_PANEL_BOX, dy)
    DISPLAY_SPECTRUM_BOX = popup_shift_box(DISPLAY_SPECTRUM_BOX, dy)
    DISPLAY_AUTO_BOX = popup_shift_box(DISPLAY_AUTO_BOX, dy)
    DISPLAY_FLOOR_MINUS_BOX = popup_shift_box(DISPLAY_FLOOR_MINUS_BOX, dy)
    DISPLAY_FLOOR_PLUS_BOX = popup_shift_box(DISPLAY_FLOOR_PLUS_BOX, dy)
    DISPLAY_CEIL_MINUS_BOX = popup_shift_box(DISPLAY_CEIL_MINUS_BOX, dy)
    DISPLAY_CEIL_PLUS_BOX = popup_shift_box(DISPLAY_CEIL_PLUS_BOX, dy)
    DISPLAY_RATE_BOXES = tuple((rate, popup_shift_box(box, dy), label) for rate, box, label in base_rates)
    DISPLAY_PALETTE_BOXES = tuple((name, popup_shift_box(box, dy), label) for name, box, label in base_palettes)

    dy = offset("filter")
    (FILTER_PANEL_BOX, FILTER_EDIT_BOX, FILTER_WIDTH_MINUS_BOX,
     FILTER_WIDTH_LABEL_BOX, FILTER_WIDTH_PLUS_BOX) = (
        popup_shift_box(box, dy) for box in POPUP_LAYOUT_BASE["filter"]
    )

    dy = offset("audio")
    (AUDIO_PANEL_BOX, AUDIO_VOLUME_BOX, AUDIO_MUTE_BOX, AUDIO_VOICE_CLEAN_BOX,
     AUDIO_SQUELCH_BOX, AUDIO_AGC_BOX, AUDIO_BLANKER_BOX,
     AUDIO_DENOISE_BOX, AUDIO_NOTCH_BOX, AUDIO_DEEMP_BOX,
     AUDIO_FILTER_BOX, AUDIO_RESET_BOX) = (
        popup_shift_box(box, dy) for box in POPUP_LAYOUT_BASE["audio"]
    )

    dy = offset("tests")
    (TEST_PANEL_BOX, TEST_GLOBE_BOX, TEST_DJ_BOX, TEST_PATTERN_BOX,
     TEST_RUN_BOX) = (popup_shift_box(box, dy) for box in POPUP_LAYOUT_BASE["tests"])

    dy = offset("dj")
    (DJ_PANEL_BOX, DJ_TRACK_BOX, DJ_STEP_BOX, DJ_RANGE_BOX,
     DJ_RATE_BOX, DJ_RETURN_BOX) = (popup_shift_box(box, dy) for box in POPUP_LAYOUT_BASE["dj"])
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
    ("rx", "RECEIVERS"),
    ("rf", "RF"),
    ("audio", "AUDIO"),
    ("display", "DISPLAY"),
    ("tests", "TESTS"),
    ("digital", "DIGI"),
    ("stats", "STATS"),
    ("settings", "SETTINGS"),
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


def frequency_entry_layout():
    """Large temporary MHz keypad for the 1024x480 radio canvas."""
    if not DESKTOP_1280_MODE:
        return None
    panel = (724, 0, 1024, 480)
    entry = (757, 18, 991, 76)
    commands = (
        ("BACK", (757, 400, 827, 470)),
        ("CLEAR", (839, 400, 909, 470)),
        ("CANCEL", (921, 400, 991, 470)),
    )
    keys = []
    labels = (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), (".", "0", "ENTER"))
    for row, row_labels in enumerate(labels):
        y0 = 88 + row * 78
        for column, label in enumerate(row_labels):
            x0 = 757 + column * 82
            keys.append((label, (x0, y0, x0 + 70, y0 + 70)))
    return panel, entry, commands, tuple(keys)


def frequency_entry_action_at(x, y):
    layout = frequency_entry_layout()
    if layout is None:
        return None
    _panel, _entry, commands, keys = layout
    for label, box in commands:
        if contains(box, x, y):
            return label
    for label, box in keys:
        if contains(box, x, y):
            return label
    return None


def parse_frequency_entry_mhz(value):
    """Accept MHz primarily, while tolerating a pasted kHz value."""
    try:
        numeric = float(value.strip())
    except (TypeError, ValueError):
        return None
    frequency_khz = numeric * 1000.0 if numeric <= 30.0 else numeric
    return frequency_khz if 0.0 <= frequency_khz <= 30000.0 else None


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


def configure_output(desktop=False, desktop_1280=False):
    """Select the Pi framebuffer geometry or a native landscape desktop window."""
    global NATIVE_W, NATIVE_H, ACTIVE_H, VISIBLE_Y_OFFSET, DESKTOP_MODE, DESKTOP_1280_MODE
    global LOGICAL_W, LOGICAL_H, WF_TEX_W, WF_TEX_H
    global ZOOM_MINUS_BOX, ZOOM_PLUS_BOX, ZOOM_GROUP_BOX
    global FILTER_TOGGLE_BOX, SPECTRUM_TOGGLE_BOX, VIEW_GROUP_BOX
    DESKTOP_MODE = bool(desktop)
    DESKTOP_1280_MODE = bool(desktop_1280)
    if DESKTOP_1280_MODE:
        ZOOM_MINUS_BOX, ZOOM_PLUS_BOX, ZOOM_GROUP_BOX = WIDE_ZOOM_MINUS_BOX, WIDE_ZOOM_PLUS_BOX, WIDE_ZOOM_GROUP_BOX
        FILTER_TOGGLE_BOX, SPECTRUM_TOGGLE_BOX, VIEW_GROUP_BOX = WIDE_FILTER_TOGGLE_BOX, WIDE_SPECTRUM_TOGGLE_BOX, WIDE_VIEW_GROUP_BOX
    else:
        ZOOM_MINUS_BOX, ZOOM_PLUS_BOX, ZOOM_GROUP_BOX = BASE_ZOOM_MINUS_BOX, BASE_ZOOM_PLUS_BOX, BASE_ZOOM_GROUP_BOX
        FILTER_TOGGLE_BOX, SPECTRUM_TOGGLE_BOX, VIEW_GROUP_BOX = BASE_FILTER_TOGGLE_BOX, BASE_SPECTRUM_TOGGLE_BOX, BASE_VIEW_GROUP_BOX
    if DESKTOP_1280_MODE:
        # This is a real wider UI canvas, not a scaled 960x320 image. The
        # waterfall path receives 1024 samples and all controls stay 1:1.
        LOGICAL_W, LOGICAL_H = DESKTOP_1280_MAIN_W, 480
        WF_TEX_W, WF_TEX_H = LOGICAL_W, 480
        kiwi.LOGICAL_W = LOGICAL_W
        kiwi.LOGICAL_H = LOGICAL_H
        NATIVE_W, NATIVE_H = DESKTOP_1280_MAIN_W + DESKTOP_1280_NAV_W, 480
        ACTIVE_H = LOGICAL_H
        VISIBLE_Y_OFFSET = 0
    elif DESKTOP_MODE:
        LOGICAL_W, LOGICAL_H = BASE_LOGICAL_W, BASE_LOGICAL_H
        WF_TEX_W, WF_TEX_H = LOGICAL_W, 256
        kiwi.LOGICAL_W = LOGICAL_W
        kiwi.LOGICAL_H = LOGICAL_H
        # Desktop development uses the logical SDR orientation directly.
        NATIVE_W, NATIVE_H = LOGICAL_W, LOGICAL_H
        ACTIVE_H = LOGICAL_H
        VISIBLE_Y_OFFSET = 0
    else:
        LOGICAL_W, LOGICAL_H = BASE_LOGICAL_W, BASE_LOGICAL_H
        WF_TEX_W, WF_TEX_H = LOGICAL_W, 256
        kiwi.LOGICAL_W = LOGICAL_W
        kiwi.LOGICAL_H = LOGICAL_H
        NATIVE_W, NATIVE_H = 400, 960
        ACTIVE_H = 400
        VISIBLE_Y_OFFSET = ACTIVE_H - LOGICAL_H
    configure_popup_layout()


def rgba(color):
    return tuple(channel / 255.0 for channel in color)


def clamp(value, low, high):
    return max(low, min(high, value))


def active_vosk_model_path():
    """Prefer the model that can remain live on this receiver, with fallback."""
    if VOSK_MODEL_OVERRIDE:
        path = Path(VOSK_MODEL_OVERRIDE)
        return path if path.is_dir() else None
    return next((path for path in VOSK_MODEL_PATHS if path.is_dir()), None)


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
    if DESKTOP_1280_MODE:
        # The wider development display has enough room for its controls to
        # coexist with direct tuning. Any pixel of the radio canvas may begin
        # a swipe; exact control taps are handled earlier in the event chain.
        return 0 <= x < DESKTOP_1280_MAIN_W and 0 <= y < LOGICAL_H
    if not (WATERFALL_TUNE_X0 <= x <= WATERFALL_TUNE_X1 and WATERFALL_Y0 <= y <= WATERFALL_Y1):
        return False
    return (
        not contains_with_guard(ZOOM_GROUP_BOX, x, y)
        and not contains_with_guard(VIEW_GROUP_BOX, x, y)
        and not contains_with_guard(ASR_TOGGLE_BOX, x, y)
    )


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
    if zoom >= kiwi.DIGITAL_ZOOM_LEVEL:
        return min(int(base_step_hz), 1)
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
            if isinstance(zoom, int) and 0 <= zoom <= kiwi.DISPLAY_MAX_ZOOM:
                view["zoom"] = zoom
            radio_mode = saved.get("radio_mode")
            if isinstance(radio_mode, str) and radio_mode.upper() in KIWI_RADIO_MODES:
                view["radio_mode"] = radio_mode.upper()
            preferences = saved.get("preferences")
            if isinstance(preferences, dict):
                view["preferences"] = preferences
            return view
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_remembered_view(path, server, freq_khz, zoom, radio_mode=None, manual_radio_mode=False, preferences=None):
    parsed = urlparse(server)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        saved = {
            "version": 2,
            "freq_khz": round(float(freq_khz), 3),
            "server": server,
            "zoom": clamp(int(zoom), 0, kiwi.DISPLAY_MAX_ZOOM),
        }
        if manual_radio_mode and isinstance(radio_mode, str) and radio_mode.upper() in KIWI_RADIO_MODES:
            saved["radio_mode"] = radio_mode.upper()
        if preferences:
            saved["preferences"] = preferences
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
        self.zoom = clamp(int(zoom), 0, kiwi.DISPLAY_MAX_ZOOM)
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
        # Listening controls map directly to Kiwi's live SND command set.
        self.squelch_enabled = False
        self.squelch_level = 0
        self.squelch_tail = 0.25
        self.audio_mute = False
        self.agc_enabled = True
        self.agc_hang = False
        self.agc_threshold = -100
        self.agc_slope = 6
        self.agc_decay = 1000
        self.agc_manual_gain = 50
        self.deemphasis = 0
        self.nb_algo = 0
        self.nr_algo = 1
        self.denoise_level = 0
        self.voice_clean_enabled = False
        self.voice_clean_level = 0
        self.autonotch_enabled = False
        self.audio_generation = 0
        self.external_audio = False
        self.asr_engine = "off"
        self.transcription_enabled = False
        self.transcription_generation = 0
        self.transcript_lines = deque(maxlen=2)
        self.transcript_partial = ""
        self.transcript_status = "OFF"
        self.transcript_hold_until = 0.0
        self.transcript_partial_updated_at = 0.0
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
                self.zoom = clamp(int(zoom), 0, kiwi.DISPLAY_MAX_ZOOM)
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
                self.zoom = clamp(int(zoom), 0, kiwi.DISPLAY_MAX_ZOOM)
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
        radio_mode = radio_mode.upper()
        if radio_mode not in KIWI_RADIO_MODES:
            raise ValueError(f"unsupported Kiwi mode: {radio_mode}")
        with self.lock:
            self.radio_mode = radio_mode.lower()
            self.low_cut, self.high_cut = kiwi_mode_filter(self.radio_mode)
            self.radio_generation += 1
            return self.radio_mode, self.low_cut, self.high_cut, self.radio_generation

    def audio_snapshot(self):
        with self.lock:
            return self.squelch_enabled, self.audio_generation

    def audio_controls_snapshot(self):
        with self.lock:
            return {
                "squelch_enabled": self.squelch_enabled,
                "squelch_level": self.squelch_level,
                "squelch_tail": self.squelch_tail,
                "mute": self.audio_mute,
                "agc": self.agc_enabled,
                "agc_hang": self.agc_hang,
                "agc_threshold": self.agc_threshold,
                "agc_slope": self.agc_slope,
                "agc_decay": self.agc_decay,
                "agc_manual_gain": self.agc_manual_gain,
                "deemphasis": self.deemphasis,
                "nb_algo": self.nb_algo,
                "nr_algo": self.nr_algo,
                "denoise_level": self.denoise_level,
                "denoise": self.denoise_level > 0,
                "voice_clean": self.voice_clean_enabled,
                "voice_clean_level": self.voice_clean_level,
                "autonotch": self.autonotch_enabled,
            }, self.audio_generation

    def set_external_audio(self, enabled):
        with self.lock:
            self.external_audio = bool(enabled)

    def external_audio_snapshot(self):
        with self.lock:
            return self.external_audio

    def transcription_snapshot(self):
        with self.lock:
            return (
                self.transcription_enabled,
                self.asr_engine,
                tuple(self.transcript_lines),
                self.transcript_partial,
                self.transcript_status,
                self.transcription_generation,
            )

    def set_asr_engine(self, engine):
        engine = str(engine).lower()
        if engine not in ASR_ENGINES:
            raise ValueError(f"unsupported ASR engine: {engine}")
        with self.lock:
            enabled = engine != "off"
            if engine != self.asr_engine:
                self.asr_engine = engine
                self.transcription_enabled = enabled
                self.transcription_generation += 1
                self.transcript_lines.clear()
                self.transcript_partial = ""
                self.transcript_hold_until = 0.0
                self.transcript_partial_updated_at = 0.0
            self.transcript_status = "STARTING" if enabled else "OFF"
            return self.asr_engine, self.transcription_generation

    def set_transcription_enabled(self, enabled):
        # Compatibility with saved preferences from the Vosk-only release.
        return self.set_asr_engine("vosk" if enabled else "off")

    def set_transcript(self, text=None, partial=None, status=None):
        with self.lock:
            now = time.monotonic()
            if text:
                normalized = " ".join(str(text).split())
                if normalized and (not self.transcript_lines or self.transcript_lines[-1] != normalized):
                    self.transcript_lines.append(normalized)
                    # A completed phrase is useful only if the operator can
                    # read it. Hold it briefly before live hypotheses resume.
                    self.transcript_hold_until = now + 2.0
                self.transcript_partial = ""
                self.transcript_partial_updated_at = now
            if partial is not None:
                normalized_partial = " ".join(str(partial).split())
                if not normalized_partial:
                    self.transcript_partial = ""
                    self.transcript_partial_updated_at = now
                elif (
                    now >= self.transcript_hold_until
                    and (
                        normalized_partial == self.transcript_partial
                        or now - self.transcript_partial_updated_at >= 0.50
                    )
                ):
                    # Vosk revises its partial hypothesis at packet rate.
                    # Half-second pacing feels like captions, not a debugger.
                    self.transcript_partial = normalized_partial
                    self.transcript_partial_updated_at = now
            if status is not None:
                self.transcript_status = status

    def set_squelch(self, enabled):
        with self.lock:
            enabled = bool(enabled)
            self.squelch_level = 20 if enabled else 0
            if enabled != self.squelch_enabled:
                self.squelch_enabled = enabled
                self.audio_generation += 1
            return self.squelch_enabled, self.audio_generation

    def set_audio_controls(self, **changes):
        """Apply a small audio control change and notify the active SND worker."""
        allowed = {
            "squelch_level", "squelch_tail", "audio_mute", "agc_enabled", "agc_hang",
            "agc_threshold", "agc_slope", "agc_decay", "agc_manual_gain", "deemphasis",
            "nb_algo", "nr_algo", "denoise_level", "voice_clean_enabled", "voice_clean_level",
            "autonotch_enabled",
        }
        with self.lock:
            changed = False
            for name, value in changes.items():
                if name not in allowed:
                    continue
                if getattr(self, name) != value:
                    setattr(self, name, value)
                    changed = True
            self.squelch_level = int(clamp(int(self.squelch_level), 0, 99))
            self.squelch_enabled = self.squelch_level > 0
            self.squelch_tail = clamp(float(self.squelch_tail), 0.0, 5.0)
            self.deemphasis = int(clamp(int(self.deemphasis), 0, 2))
            self.nb_algo = int(clamp(int(self.nb_algo), 0, 2))
            self.nr_algo = int(clamp(int(self.nr_algo), 0, 3))
            self.denoise_level = int(clamp(int(self.denoise_level), 0, len(kiwi.DENOISE_PRESETS) - 1))
            if "voice_clean_level" in changes:
                self.voice_clean_level = int(clamp(int(self.voice_clean_level), 0, len(VOICE_CLEAN_PRESETS) - 1))
            elif "voice_clean_enabled" in changes:
                self.voice_clean_level = 2 if bool(self.voice_clean_enabled) else 0
            self.voice_clean_enabled = self.voice_clean_level > 0
            if changed:
                self.audio_generation += 1
            return {
                "squelch_enabled": self.squelch_enabled,
                "squelch_level": self.squelch_level,
                "squelch_tail": self.squelch_tail,
                "mute": self.audio_mute,
                "agc": self.agc_enabled,
                "agc_hang": self.agc_hang,
                "agc_threshold": self.agc_threshold,
                "agc_slope": self.agc_slope,
                "agc_decay": self.agc_decay,
                "agc_manual_gain": self.agc_manual_gain,
                "deemphasis": self.deemphasis,
                "nb_algo": self.nb_algo,
                "nr_algo": self.nr_algo,
                "denoise_level": self.denoise_level,
                "denoise": self.denoise_level > 0,
                "voice_clean": self.voice_clean_enabled,
                "voice_clean_level": self.voice_clean_level,
                "autonotch": self.autonotch_enabled,
            }, self.audio_generation

    def reset_audio_controls(self):
        return self.set_audio_controls(
            squelch_level=0, squelch_tail=0.25, audio_mute=False,
            agc_enabled=True, agc_hang=False, agc_threshold=-100, agc_slope=6,
            agc_decay=1000, agc_manual_gain=50, deemphasis=0, nb_algo=0,
            nr_algo=1, denoise_level=0, voice_clean_enabled=False, voice_clean_level=0,
            autonotch_enabled=False,
        )

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
    flags = pygame.OPENGL | pygame.NOFRAME if desktop else pygame.OPENGL | pygame.FULLSCREEN
    screen = pygame.display.set_mode((NATIVE_W, NATIVE_H), flags)
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


def draw_native_rect(x0, y0, x1, y1, color):
    """Draw directly in the desktop-wide framebuffer coordinate system."""
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glBegin(GL.GL_QUADS)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        GL.glVertex2f(x, y)
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_native_line(x0, y0, x1, y1, color, width=1):
    GL.glDisable(GL.GL_TEXTURE_2D)
    GL.glColor4f(*rgba(color))
    GL.glLineWidth(width)
    GL.glBegin(GL.GL_LINES)
    GL.glVertex2f(x0, y0)
    GL.glVertex2f(x1, y1)
    GL.glEnd()
    GL.glEnable(GL.GL_TEXTURE_2D)


def draw_native_textured_quad(tex, x0, y0, x1, y1, u0=0, v0=0, u1=1, v1=1, alpha=1.0):
    GL.glEnable(GL.GL_TEXTURE_2D)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glColor4f(1, 1, 1, clamp(alpha, 0.0, 1.0))
    GL.glBegin(GL.GL_QUADS)
    for x, y, u, v in ((x0, y0, u0, v0), (x1, y0, u1, v0), (x1, y1, u1, v1), (x0, y1, u0, v1)):
        GL.glTexCoord2f(u, v)
        GL.glVertex2f(x, y)
    GL.glEnd()


def draw_native_text(text_cache, x, y, text, color, size, bold=False, mono=False, anchor="lt", alpha=1.0, family=None):
    tex, width, height = text_cache.texture(text, size, color, bold=bold, mono=mono, family=family)
    if "m" in anchor:
        y -= height / 2
    elif "b" in anchor:
        y -= height
    if "c" in anchor:
        x -= width / 2
    elif "r" in anchor:
        x -= width
    draw_native_textured_quad(tex, x, y, x + width, y + height, alpha=alpha)


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
            self._draw_frequency_aligned(x0, y0, x1, y1, center_khz, span_khz, row_offset)
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

    def _draw_frequency_aligned(self, x0, y0, x1, y1, center_khz, span_khz, row_offset=0):
        """Map each stored Kiwi row into the current RF view.

        At display zoom 15/16, the current view is the central quarter/eighth
        of a native Kiwi zoom-14 row. Mapping source and display spans
        separately makes that a true digital magnifier instead of stretching
        the entire waterfall texture.
        """
        height = int(y1 - y0)
        view_low_khz = center_khz - span_khz / 2.0
        view_high_khz = center_khz + span_khz / 2.0
        GL.glEnable(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glColor4f(1, 1, 1, 1)
        GL.glBegin(GL.GL_QUADS)
        for logical_y in range(height):
            tex_row = (self.row + max(0, int(row_offset)) + logical_y) % WF_TEX_H
            row_center = self.row_center_khz[tex_row]
            if row_center is None:
                row_center = center_khz
            row_span = self.row_span_khz[tex_row]
            if not row_span or row_span <= 0:
                row_span = span_khz
            row_low_khz = row_center - row_span / 2.0
            u0 = (view_low_khz - row_low_khz) / row_span
            u1 = (view_high_khz - row_low_khz) / row_span
            if u1 <= 0.0 or u0 >= 1.0 or u1 <= u0:
                continue
            clipped_u0 = clamp(u0, 0.0, 1.0)
            clipped_u1 = clamp(u1, 0.0, 1.0)
            t0 = (clipped_u0 - u0) / (u1 - u0)
            t1 = (clipped_u1 - u0) / (u1 - u0)
            draw_x0 = x0 + (x1 - x0) * t0
            draw_x1 = x0 + (x1 - x0) * t1
            ly0 = y0 + logical_y
            ly1 = ly0 + 1
            v0 = tex_row / WF_TEX_H
            v1 = (tex_row + 1) / WF_TEX_H
            vertices = (
                (draw_x0, ly0, clipped_u0, v0),
                (draw_x1, ly0, clipped_u1, v0),
                (draw_x1, ly1, clipped_u1, v1),
                (draw_x0, ly1, clipped_u0, v1),
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
    w, h = int(x1 - x0), int(y1 - y0)
    surface = pygame.Surface((w, h), pygame.SRCALPHA)
    try:
        icon = pygame.image.load(str(MENU_ICON_ASSET_DIR / "home.png")).convert_alpha()
        icon_size = min(48, w - 14, h - 8)
        icon = pygame.transform.smoothscale(icon, (icon_size, icon_size))
        surface.blit(icon, ((w - icon_size) // 2, (h - icon_size) // 2))
    except (pygame.error, OSError):
        draw_menu_icon(surface, "home", w // 2, h // 2, (231, 235, 237, 238), (82, 235, 231, 150))
    tex, tex_w, tex_h = text_cache.surface_texture("home_button_v12", surface)
    draw_textured_quad(tex, x0, y0, x0 + tex_w, y0 + tex_h, 0, 0, 1, 1, alpha)


def frequency_right_x():
    """Keep the wide-layout frequency/meter cluster aligned as one unit."""
    return FREQUENCY_RIGHT_X + (50 if DESKTOP_1280_MODE else 0)


def frequency_display_box(text_cache, freq_khz):
    frequency_text = sdr_ui.format_freq(freq_khz)
    width = text_cache.font(50, bold=True, family="Liberation Sans").size(frequency_text)[0]
    return frequency_right_x() - width - 8, 4, frequency_right_x() + 8, 70


def top_instrument_layout(text_cache, freq_khz):
    """Return a right-aligned mode/frequency cluster next to the S-meter."""
    frequency_text = sdr_ui.format_freq(freq_khz)
    frequency_width = text_cache.font(50, bold=True, family="Liberation Sans").size(frequency_text)[0]
    frequency_left = frequency_right_x() - frequency_width
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


def draw_desktop_1280_annunciator_button(text_cache, mode, digital, step_hz, bandwidth_hz):
    """One unified radio-status button above the persistent navigation rail."""
    if not DESKTOP_1280_MODE:
        return
    x0, y0, x1, y1 = DESKTOP_1280_ANNUNCIATOR_BOX
    draw_native_rect(x0, y0, x1, y1, (15, 31, 39, 244))
    draw_native_line(x0, y0, x1, y0, (125, 147, 158, 168), 1)
    draw_native_line(x0, y0, x0, y1, (93, 120, 132, 155), 1)
    draw_native_line(x1, y0, x1, y1, (32, 50, 61, 215), 1)
    draw_native_line(x0, y1, x1, y1, (53, 88, 98, 210), 1)
    exact_mode = mode.upper()
    active_mode = KIWI_MODE_FAMILY.get(exact_mode, exact_mode)
    context_label = KIWI_MODE_CONTEXT.get(exact_mode, exact_mode)
    draw_native_text(
        text_cache,
        (x0 + x1) / 2,
        y0 + 13,
        context_label,
        (214, 238, 233),
        11 if len(context_label) > 20 else 12,
        True,
        False,
        "cm",
        family="Liberation Sans",
    )
    grid_x = x0 + 7
    grid_w = x1 - x0 - 14
    cell_w = grid_w / 4
    for index, label in enumerate(DESKTOP_1280_MODE_ANNUNCIATORS):
        col = index % 4
        row = index // 4
        bx0 = grid_x + col * cell_w
        bx1 = grid_x + (col + 1) * cell_w
        # Keep the mode matrix clear of the top edge of the wide status button.
        by0 = y0 + 26 + row * 23
        by1 = by0 + 20
        active = label == active_mode or (label == "IQ" and digital.upper() == "IQ")
        if active:
            draw_native_rect(bx0 + 3, by0 + 1, bx1 - 3, by1 - 1, (43, 121, 81, 205))
            # Layered underlines give the selected mode a readable neon halo
            # without introducing a blur texture in this compact strip.
            draw_native_line(bx0 + 5, by1 - 1, bx1 - 5, by1 - 1, (47, 255, 123, 105), 7)
            draw_native_line(bx0 + 5, by1 - 1, bx1 - 5, by1 - 1, (82, 255, 147, 190), 3)
            draw_native_line(bx0 + 5, by1 - 1, bx1 - 5, by1 - 1, (119, 255, 162, 245), 1)
        draw_native_text(
            text_cache,
            bx0 + 7,
            (by0 + by1) / 2 + 1,
            label,
            (235, 255, 239) if active else (130, 151, 157),
            12,
            True,
            False,
            "lm",
            family="Liberation Sans",
        )
    footer_y = y0 + 75
    draw_native_line(x0 + 9, footer_y, x1 - 9, footer_y, (64, 103, 112, 150), 1)
    draw_native_text(text_cache, grid_x + 7, y1 - 9, f"BW  {format_filter_width(bandwidth_hz)}", (192, 218, 222), 12, True, False, "lm", family="Liberation Sans")
    draw_native_text(text_cache, x1 - 12, y1 - 9, f"STEP  {step_hz} Hz", (192, 218, 222), 12, True, False, "rm", family="Liberation Sans")


def radio_mode_layout():
    """Yield eight simple, readable entry points for all Kiwi modes."""
    grid_x0 = radio_popup_x(RADIO_FAMILY_GRID_X0)
    grid_x1 = radio_popup_x(RADIO_FAMILY_GRID_X1)
    available = grid_x1 - grid_x0
    button_w = (available - RADIO_FAMILY_BUTTON_GAP * (RADIO_FAMILY_COLS - 1)) / RADIO_FAMILY_COLS
    for index, (family, modes) in enumerate(KIWI_MODE_FAMILIES):
        col = index % RADIO_FAMILY_COLS
        row = index // RADIO_FAMILY_COLS
        x0 = grid_x0 + col * (button_w + RADIO_FAMILY_BUTTON_GAP)
        y0 = radio_popup_y(RADIO_FAMILY_GRID_Y0 + row * (RADIO_FAMILY_BUTTON_H + RADIO_FAMILY_BUTTON_GAP))
        yield family, modes, (x0, y0, x0 + button_w, y0 + RADIO_FAMILY_BUTTON_H)


def radio_variant_layout(modes):
    """Lay variants out in a compact two-column context menu."""
    popup_x0, popup_y0, popup_x1, _popup_y1 = radio_variant_popup_box(modes)
    cols = min(RADIO_VARIANT_COLS, len(modes))
    button_w = (popup_x1 - popup_x0 - 24 - (cols - 1) * RADIO_VARIANT_BUTTON_GAP) / cols
    grid_w = cols * button_w + (cols - 1) * RADIO_VARIANT_BUTTON_GAP
    grid_x0 = (popup_x0 + popup_x1 - grid_w) / 2
    grid_y0 = popup_y0 + 42
    for index, mode in enumerate(modes):
        col = index % cols
        row = index // cols
        x0 = grid_x0 + col * (button_w + RADIO_VARIANT_BUTTON_GAP)
        y0 = grid_y0 + row * (RADIO_VARIANT_BUTTON_H + RADIO_VARIANT_BUTTON_GAP)
        yield mode, (x0, y0, x0 + button_w, y0 + RADIO_VARIANT_BUTTON_H)


def radio_option_at(x, y, family_open=None):
    if family_open is not None:
        modes = next((modes for family, modes in KIWI_MODE_FAMILIES if family == family_open), ())
        if contains(radio_variant_back_box(modes), x, y):
            return "back", None
        for mode, box in radio_variant_layout(modes):
            if contains(box, x, y):
                return "mode", mode
        if contains(radio_variant_popup_box(modes), x, y):
            return None
    for _family, modes, box in radio_mode_layout():
        if contains(box, x, y):
            return "mode_family", (_family, modes)
    for step_hz, box in radio_step_options():
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
    font_size = 12 if len(label) > 10 else (13 if len(label) > 8 else 15)
    draw_text(text_cache, (x0 + x1) / 2, (y0 + y1) / 2, label, color, font_size, True, True, "cm")


def draw_radio_family_option(text_cache, box, family, modes, active_mode):
    """Draw a large mode-family button without cramming its variants inside."""
    x0, y0, x1, y1 = box
    active = active_mode in modes
    fill = (32, 87, 89, 220) if active else (18, 29, 38, 184)
    line = (94, 235, 225, 220) if active else (115, 140, 151, 78)
    draw_logical_rect(x0, y0, x1, y1, fill)
    for ax0, ay0, ax1, ay1 in (
        (x0, y0, x1, y0),
        (x0, y1, x1, y1),
        (x0, y0, x0, y1),
        (x1, y0, x1, y1),
    ):
        draw_logical_line(ax0, ay0, ax1, ay1, line, 1)
    if active:
        draw_logical_line(x0 + 12, y1 - 5, x1 - 12, y1 - 5, (91, 242, 227, 230), 2)
    draw_text(
        text_cache,
        (x0 + x1) / 2,
        (y0 + y1) / 2 - 4,
        family,
        (238, 252, 250) if active else (190, 211, 215),
        21 if len(family) <= 6 else 19,
        True,
        False,
        "cm",
        family="Liberation Sans",
    )
    if active:
        draw_text(text_cache, (x0 + x1) / 2, y1 - 16, active_mode, (174, 244, 228), 14, True, False, "cm", family="Liberation Sans")
    elif len(modes) > 1:
        # A generously sized, two-stroke chevron reads as a touch disclosure,
        # rather than as a tiny text character.
        chevron_x = x1 - 24
        chevron_y = y1 - 21
        chevron_color = (116, 202, 201, 210)
        draw_logical_line(chevron_x - 10, chevron_y - 6, chevron_x, chevron_y + 4, chevron_color, 2)
        draw_logical_line(chevron_x, chevron_y + 4, chevron_x + 10, chevron_y - 6, chevron_color, 2)


def draw_radio_variant_option(text_cache, box, mode, active):
    """Render one readable option in the compact second-level popover."""
    x0, y0, x1, y1 = box
    fill = (32, 87, 89, 226) if active else (20, 34, 43, 226)
    line = (94, 235, 225, 230) if active else (129, 157, 168, 150)
    draw_logical_rect(x0, y0, x1, y1, fill)
    for ax0, ay0, ax1, ay1 in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)):
        draw_logical_line(ax0, ay0, ax1, ay1, line, 1)
    if active:
        draw_logical_line(x0 + 14, y1 - 6, x1 - 14, y1 - 6, (91, 242, 227, 235), 3)
    label = KIWI_MODE_LABELS.get(mode, mode)
    draw_text(
        text_cache,
        (x0 + x1) / 2,
        (y0 + y1) / 2,
        label,
        (240, 254, 251) if active else (213, 231, 233),
        17 if len(label) <= 11 else 15,
        True,
        False,
        "cm",
        family="Liberation Sans",
    )


def draw_radio_setup_panel(text_cache, mode, digital, step_hz, family_open=None):
    x0, y0, x1, y1 = radio_panel_box()
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 112))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 242))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 112), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 112), 1)
    draw_text(text_cache, radio_popup_x(30), radio_popup_y(84), "MODE", (229, 243, 246), 20, True, False, "lm", family="Liberation Sans")
    draw_text(text_cache, radio_popup_x(30), radio_popup_y(101), "Choose a mode family", (145, 183, 190), 13, False, False, "lm", family="Liberation Sans")
    draw_text(text_cache, radio_popup_x(532), radio_popup_y(87), "STEP", (145, 183, 190), 13, True, False, "lm", family="Liberation Sans")
    active_mode = mode.upper()
    for family, modes, box in radio_mode_layout():
        draw_radio_family_option(text_cache, box, family, modes, active_mode)
    draw_text(text_cache, radio_popup_x(30), radio_popup_y(300), f"ACTIVE  {KIWI_MODE_CONTEXT.get(active_mode, active_mode)}", (176, 221, 214), 14, True, False, "lm", family="Liberation Sans")
    for option, box in radio_step_options():
        label = f"{option // 1000}k" if option >= 1000 else str(option)
        draw_radio_option(text_cache, box, label, option == step_hz)
    if family_open is not None:
        modes = next((options for family, options in KIWI_MODE_FAMILIES if family == family_open), ())
        vx0, vy0, vx1, vy1 = radio_variant_popup_box(modes)
        draw_logical_rect(vx0, vy0, vx1, vy1, (6, 18, 25, 248))
        draw_logical_line(vx0, vy0, vx1, vy0, (122, 196, 200, 204), 1)
        draw_logical_line(vx0, vy1, vx1, vy1, (122, 196, 200, 204), 1)
        draw_logical_line(vx0, vy0, vx0, vy1, (122, 196, 200, 204), 1)
        draw_logical_line(vx1, vy0, vx1, vy1, (122, 196, 200, 204), 1)
        draw_radio_option(text_cache, radio_variant_back_box(modes), "BACK", False)
        draw_text(text_cache, (vx0 + vx1) / 2, vy0 + 20, family_open, (231, 246, 247), 18, True, False, "cm", family="Liberation Sans")
        for option, box in radio_variant_layout(modes):
            draw_radio_variant_option(text_cache, box, option, option == active_mode)


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


def audio_squelch_at_x(x):
    x0, _y0, x1, _y1 = AUDIO_SQUELCH_BOX
    return int(round(clamp((x - x0) / max(1, x1 - x0), 0.0, 1.0) * 99))


def audio_denoise_level_at_x(x):
    """Snap a finger position to the evenly spaced Denoise detents."""
    x0, _y0, x1, _y1 = AUDIO_DENOISE_BOX
    fraction = clamp((x - (x0 + 14)) / max(1, (x1 - 14) - (x0 + 14)), 0.0, 1.0)
    return min(
        range(len(DENOISE_SLIDER_POSITIONS)),
        key=lambda index: abs(DENOISE_SLIDER_POSITIONS[index] - fraction),
    )


def denoise_makeup_gain_db(level):
    return DENOISE_MAKEUP_GAIN_DB[int(clamp(level, 0, len(DENOISE_MAKEUP_GAIN_DB) - 1))]


def apply_denoise_makeup_gain(audio, gain_db):
    """Apply SDR-stream-only make-up gain to native S16 PCM, with saturation."""
    gain_db = clamp(float(gain_db), 0.0, 12.0)
    if gain_db <= 0.0 or not audio:
        return audio
    multiplier = 10.0 ** (gain_db / 20.0)
    if audioop is not None:
        return audioop.mul(audio, 2, multiplier)
    sample_count = len(audio) // 2
    samples = struct.unpack(f"<{sample_count}h", audio[:sample_count * 2])
    boosted = (int(clamp(round(sample * multiplier), -32768, 32767)) for sample in samples)
    return struct.pack(f"<{sample_count}h", *boosted)


class RNNoiseVoiceCleaner:
    """RNNoise with high-quality SpeexDSP conversion only on the Voice path."""

    INPUT_FRAME_SAMPLES = 120
    RNNOISE_FRAME_SAMPLES = 480
    SPEEX_QUALITY = 8

    def __init__(self, library_path=RNNOISE_LIBRARY, speex_library=SPEEXDSP_LIBRARY):
        self.library = ctypes.CDLL(str(library_path))
        self.library.rnnoise_create.argtypes = [ctypes.c_void_p]
        self.library.rnnoise_create.restype = ctypes.c_void_p
        self.library.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        self.library.rnnoise_destroy.restype = None
        self.library.rnnoise_process_frame.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
        self.library.rnnoise_process_frame.restype = ctypes.c_float
        self.state = self.library.rnnoise_create(None)
        if not self.state:
            raise RuntimeError("rnnoise_create failed")

        self.speex = ctypes.CDLL(str(speex_library))
        self.speex.speex_resampler_init.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.speex.speex_resampler_init.restype = ctypes.c_void_p
        self.speex.speex_resampler_destroy.argtypes = [ctypes.c_void_p]
        self.speex.speex_resampler_destroy.restype = None
        self.speex.speex_resampler_process_int.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_uint),
        ]
        self.speex.speex_resampler_process_int.restype = ctypes.c_int
        self.up_state = self._make_resampler(12000, 48000)
        self.wet_down_state = self._make_resampler(48000, 12000)
        self.dry_down_state = self._make_resampler(48000, 12000)
        self.pending = bytearray()
        self.rn_pending = []
        self.dry_pending = []
        self.wet_12k = []
        self.dry_12k = []
        # A modest 3 dB shelf restores consonant detail after voice cleanup
        # without inventing treble that is absent from Kiwi's 12 kHz stream.
        self._presence_biquad = self._make_high_shelf(12000.0, 2600.0, 3.0)
        self._presence_z1 = 0.0
        self._presence_z2 = 0.0
        self._level_rms = 0.0
        self._level_gain = 1.0

    def _make_resampler(self, source_rate, target_rate):
        error = ctypes.c_int()
        state = self.speex.speex_resampler_init(1, source_rate, target_rate, self.SPEEX_QUALITY, ctypes.byref(error))
        if not state or error.value:
            raise RuntimeError(f"SpeexDSP resampler init failed ({error.value})")
        return state

    def _resample(self, state, samples, output_capacity):
        if not samples:
            return []
        source = (ctypes.c_short * len(samples))(*samples)
        destination = (ctypes.c_short * output_capacity)()
        input_count = ctypes.c_uint(len(samples))
        output_count = ctypes.c_uint(output_capacity)
        error = self.speex.speex_resampler_process_int(
            state, 0, source, ctypes.byref(input_count), destination, ctypes.byref(output_count)
        )
        if error:
            raise RuntimeError(f"SpeexDSP resample failed ({error})")
        return list(destination[:output_count.value])

    @staticmethod
    def _make_high_shelf(sample_rate, frequency, gain_db):
        """RBJ high-shelf coefficients, normalized for transposed DF-II."""
        amplitude = 10.0 ** (gain_db / 40.0)
        omega = math.tau * frequency / sample_rate
        cosine = math.cos(omega)
        sine = math.sin(omega)
        alpha = sine / 2.0 * math.sqrt((amplitude + 1.0 / amplitude) * 2.0)
        beta = 2.0 * math.sqrt(amplitude) * alpha
        b0 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cosine + beta)
        b1 = -2.0 * amplitude * ((amplitude - 1.0) + (amplitude + 1.0) * cosine)
        b2 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cosine - beta)
        a0 = (amplitude + 1.0) - (amplitude - 1.0) * cosine + beta
        a1 = 2.0 * ((amplitude - 1.0) - (amplitude + 1.0) * cosine)
        a2 = (amplitude + 1.0) - (amplitude - 1.0) * cosine - beta
        return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0

    def _apply_voice_tone(self, samples):
        """Add light speech presence and a slow, conservative comfort leveler."""
        if not samples:
            return samples
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        self._level_rms = self._level_rms * 0.94 + rms * 0.06
        if self._level_rms >= 500.0:
            desired_gain = clamp(5000.0 / self._level_rms, 0.78, 1.38)
        else:
            desired_gain = 1.0
        # Pull loud speech down promptly, but return level gradually between words.
        follow = 0.18 if desired_gain < self._level_gain else 0.035
        self._level_gain += (desired_gain - self._level_gain) * follow
        b0, b1, b2, a1, a2 = self._presence_biquad
        output = []
        for sample in samples:
            shaped = b0 * sample + self._presence_z1
            self._presence_z1 = b1 * sample - a1 * shaped + self._presence_z2
            self._presence_z2 = b2 * sample - a2 * shaped
            # Gentle soft limiting prevents the presence shelf from clipping.
            leveled = shaped * self._level_gain
            limited = leveled / (1.0 + abs(leveled) / 36000.0)
            output.append(int(clamp(round(limited), -32768, 32767)))
        return output

    def close(self):
        for name in ("up_state", "wet_down_state", "dry_down_state"):
            state = getattr(self, name, None)
            if state:
                self.speex.speex_resampler_destroy(state)
                setattr(self, name, None)
        if self.state:
            self.library.rnnoise_destroy(self.state)
            self.state = None

    def process_pcm(self, audio, mix=1.0):
        """Clean mono S16 PCM, returning a matched high-quality-resampled stream."""
        if not audio:
            return audio
        mix = clamp(float(mix), 0.0, 1.0)
        self.pending.extend(audio)
        frame_bytes = self.INPUT_FRAME_SAMPLES * 2
        while len(self.pending) >= frame_bytes:
            frame = bytes(self.pending[:frame_bytes])
            del self.pending[:frame_bytes]
            samples = struct.unpack(f"<{self.INPUT_FRAME_SAMPLES}h", frame)
            upsampled = self._resample(self.up_state, samples, self.RNNOISE_FRAME_SAMPLES + 128)
            self.rn_pending.extend(upsampled)
            self.dry_pending.extend(upsampled)
            while len(self.rn_pending) >= self.RNNOISE_FRAME_SAMPLES:
                rn_frame = self.rn_pending[:self.RNNOISE_FRAME_SAMPLES]
                dry_frame = self.dry_pending[:self.RNNOISE_FRAME_SAMPLES]
                del self.rn_pending[:self.RNNOISE_FRAME_SAMPLES]
                del self.dry_pending[:self.RNNOISE_FRAME_SAMPLES]
                rn_input = (ctypes.c_float * self.RNNOISE_FRAME_SAMPLES)(*map(float, rn_frame))
                rn_output = (ctypes.c_float * self.RNNOISE_FRAME_SAMPLES)()
                self.library.rnnoise_process_frame(self.state, rn_output, rn_input)
                wet_frame = [int(clamp(round(value), -32768, 32767)) for value in rn_output]
                self.wet_12k.extend(self._resample(self.wet_down_state, wet_frame, self.INPUT_FRAME_SAMPLES + 128))
                self.dry_12k.extend(self._resample(self.dry_down_state, dry_frame, self.INPUT_FRAME_SAMPLES + 128))

        output_count = min(len(self.wet_12k), len(self.dry_12k))
        if not output_count:
            return b""
        wet = self.wet_12k[:output_count]
        dry = self.dry_12k[:output_count]
        del self.wet_12k[:output_count]
        del self.dry_12k[:output_count]
        blended = [int(clamp(round(w * mix + d * (1.0 - mix)), -32768, 32767)) for w, d in zip(wet, dry)]
        voiced = self._apply_voice_tone(blended)
        return struct.pack(f"<{output_count}h", *voiced)


class VoskResampler:
    """Streaming SpeexDSP converter for Vosk's required 16 kHz mono PCM."""

    def __init__(self):
        self.library = ctypes.CDLL(SPEEXDSP_LIBRARY)
        self.library.speex_resampler_init.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.library.speex_resampler_init.restype = ctypes.c_void_p
        self.library.speex_resampler_destroy.argtypes = [ctypes.c_void_p]
        self.library.speex_resampler_process_int.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_uint)]
        self.library.speex_resampler_process_int.restype = ctypes.c_int
        error = ctypes.c_int()
        self.state = self.library.speex_resampler_init(1, 12000, 16000, 6, ctypes.byref(error))
        if not self.state or error.value:
            raise RuntimeError(f"Vosk resampler init failed ({error.value})")

    def close(self):
        if self.state:
            self.library.speex_resampler_destroy(self.state)
            self.state = None

    def process(self, audio):
        sample_count = len(audio) // 2
        if not sample_count:
            return b""
        source = (ctypes.c_short * sample_count).from_buffer_copy(audio[:sample_count * 2])
        capacity = int(math.ceil(sample_count * 4.0 / 3.0)) + 128
        destination = (ctypes.c_short * capacity)()
        input_count, output_count = ctypes.c_uint(sample_count), ctypes.c_uint(capacity)
        error = self.library.speex_resampler_process_int(self.state, 0, source, ctypes.byref(input_count), destination, ctypes.byref(output_count))
        if error:
            raise RuntimeError(f"Vosk resample failed ({error})")
        # ``destination`` is signed 16-bit PCM. ``bytes(sequence)`` rejects
        # negative samples, so copy the raw sample memory exactly as Vosk
        # expects instead of treating it as an unsigned byte sequence.
        return ctypes.string_at(destination, output_count.value * ctypes.sizeof(ctypes.c_short))


def drain_caption_audio(audio_queue):
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            return


def active_moonshine_model_dir():
    return next((path for path in MOONSHINE_MODEL_DIRS if path.is_dir()), None)


def moonshine_recognizer():
    model_dir = active_moonshine_model_dir()
    if sherpa_onnx is None or model_dir is None:
        raise RuntimeError("Moonshine model unavailable")
    return (
        sherpa_onnx.OfflineRecognizer.from_moonshine(
            preprocessor=str(model_dir / "preprocess.onnx"),
            encoder=str(model_dir / "encode.int8.onnx"),
            uncached_decoder=str(model_dir / "uncached_decode.int8.onnx"),
            cached_decoder=str(model_dir / "cached_decode.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=2,
        ),
        model_dir,
    )


def parakeet_recognizer():
    """Load NVIDIA Parakeet TDT-CTC 110M through Sherpa-ONNX.

    It is a larger offline CTC model than Moonshine Base, but its INT8 build
    is still fast enough on the Pi for short, deliberately bounded windows.
    """
    model_path = PARAKEET_MODEL_DIR / "model.int8.onnx"
    tokens_path = PARAKEET_MODEL_DIR / "tokens.txt"
    if sherpa_onnx is None or not model_path.is_file() or not tokens_path.is_file():
        raise RuntimeError("Parakeet 110M model unavailable")
    return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
        model=str(model_path),
        tokens=str(tokens_path),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
    )


class MoonshineStreamingListener(
    moonshine_voice.TranscriptEventListener if moonshine_voice is not None else object
):
    """Bridge Moonshine Voice events into the SDR's calm subtitle pacing."""
    def __init__(self, state, generation):
        self.state = state
        self.generation = generation

    def _current(self):
        _enabled, engine, _lines, _partial, _status, generation = self.state.transcription_snapshot()
        return engine == "moonshine" and generation == self.generation

    def on_line_text_changed(self, event):
        if self._current():
            self.state.set_transcript(partial=event.line.text, status="LISTENING")

    def on_line_completed(self, event):
        if self._current():
            self.state.set_transcript(text=event.line.text, partial="", status="LISTENING")

    def on_error(self, event):
        if self._current():
            self.state.set_transcript(status="MOON ERROR")


def moonshine_streaming_transcriber(state, generation):
    """Optional benchmark backend; Base remains the live Pi default."""
    if (
        not MOONSHINE_SMALL_STREAMING_TRIAL
        or moonshine_voice is None
        or not MOONSHINE_STREAMING_MODEL_DIR.is_dir()
    ):
        return None
    listener = MoonshineStreamingListener(state, generation)
    transcriber = moonshine_voice.Transcriber(
        str(MOONSHINE_STREAMING_MODEL_DIR),
        moonshine_voice.ModelArch.SMALL_STREAMING,
        update_interval=0.55,
    )
    transcriber.add_listener(listener)
    transcriber.start()
    return transcriber


def close_moonshine_streaming(transcriber):
    if transcriber is None:
        return
    try:
        transcriber.stop()
    except Exception:
        pass
    try:
        transcriber.close()
    except Exception:
        pass


def whisper_transcribe(pcm16):
    """Run a bounded Whisper.cpp decode; stale source audio is dropped upstream."""
    if not WHISPER_CLI.is_file() or not WHISPER_MODEL.is_file():
        raise RuntimeError("Whisper.cpp model unavailable")
    with tempfile.TemporaryDirectory(prefix="kiwi-whisper-") as tmp:
        wav_path = Path(tmp) / "radio.wav"
        result_base = Path(tmp) / "result"
        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm16)
        result = subprocess.run(
            [
                str(WHISPER_CLI), "-m", str(WHISPER_MODEL), "-f", str(wav_path),
                "-l", "en", "-t", "4", "-nt", "-np", "-otxt", "-of", str(result_base),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=18.0,
            check=False,
        )
        text_path = result_base.with_suffix(".txt")
        if result.returncode != 0 or not text_path.is_file():
            raise RuntimeError(f"Whisper exit {result.returncode}")
        return " ".join(text_path.read_text(errors="replace").split())


def asr_caption_worker(stop_event, state, audio_queue):
    """One bounded ASR lane. Only the selected engine receives PCM or CPU."""
    vosk_model = vosk_recognizer = moonshine = moonshine_streaming = parakeet = resampler = None
    loaded_vosk_path = None
    active_engine = None
    seen_generation = -1
    offline_pcm = bytearray()
    offline_since_decode = 0.0
    measured_audio_seconds = 0.0
    measured_processing_seconds = 0.0
    next_performance_report = time.monotonic() + 10.0
    while not stop_event.is_set():
        enabled, engine, _lines, _partial, _status, generation = state.transcription_snapshot()
        if not enabled:
            active_engine = None
            vosk_recognizer = None
            moonshine = None
            parakeet = None
            close_moonshine_streaming(moonshine_streaming)
            moonshine_streaming = None
            offline_pcm.clear()
            offline_since_decode = 0.0
            if resampler:
                resampler.close()
                resampler = None
            drain_caption_audio(audio_queue)
            stop_event.wait(0.15)
            continue
        try:
            if engine != active_engine or generation != seen_generation:
                active_engine = engine
                seen_generation = generation
                vosk_recognizer = None
                moonshine = None
                parakeet = None
                close_moonshine_streaming(moonshine_streaming)
                moonshine_streaming = None
                offline_pcm.clear()
                offline_since_decode = 0.0
                if resampler:
                    resampler.close()
                resampler = VoskResampler()
                drain_caption_audio(audio_queue)
                state.set_transcript(status=f"LOADING {ASR_ENGINE_LABELS[engine]}")
            if engine == "vosk":
                model_path = active_vosk_model_path()
                if vosk is None or model_path is None:
                    raise RuntimeError("Vosk model unavailable")
                if vosk_model is None or loaded_vosk_path != model_path:
                    vosk.SetLogLevel(-1)
                    vosk_model = vosk.Model(str(model_path))
                    loaded_vosk_path = model_path
                    print(f"gl Vosk model {model_path.name}", flush=True)
                if vosk_recognizer is None:
                    vosk_recognizer = vosk.KaldiRecognizer(vosk_model, 16000)
                    vosk_recognizer.SetWords(False)
            elif engine == "moonshine" and moonshine_streaming is None and moonshine is None:
                moonshine_streaming = moonshine_streaming_transcriber(state, generation)
                if moonshine_streaming is not None:
                    print("gl Moonshine Small Streaming model ready", flush=True)
                else:
                    moonshine, moonshine_dir = moonshine_recognizer()
                    print(f"gl Moonshine fallback model {moonshine_dir.name} ready", flush=True)
            elif engine == "parakeet" and parakeet is None:
                parakeet = parakeet_recognizer()
                print("gl Parakeet TDT-CTC 110M INT8 model ready", flush=True)
            elif engine == "whisper" and (not WHISPER_CLI.is_file() or not WHISPER_MODEL.is_file()):
                raise RuntimeError("Whisper.cpp model unavailable")
            state.set_transcript(status="LISTENING")
            try:
                audio = audio_queue.get(timeout=0.20)
            except queue.Empty:
                continue
            process_started = time.monotonic()
            pcm16 = resampler.process(audio)
            if not pcm16:
                continue
            if engine == "vosk":
                if vosk_recognizer.AcceptWaveform(pcm16):
                    state.set_transcript(text=json.loads(vosk_recognizer.Result()).get("text", ""), partial="", status="LISTENING")
                else:
                    state.set_transcript(partial=json.loads(vosk_recognizer.PartialResult()).get("partial", ""), status="LISTENING")
            elif engine == "moonshine" and moonshine_streaming is not None:
                # Moonshine Voice handles incremental encoding, VAD-like
                # phrase boundaries, and revisions internally. Feeding each
                # radio packet straight through removes our old batch jitter.
                samples = [sample / 32768.0 for sample in struct.unpack(f"<{len(pcm16) // 2}h", pcm16)]
                moonshine_streaming.add_audio(samples, 16000)
            else:
                offline_pcm.extend(pcm16)
                offline_since_decode += len(pcm16) / 32000.0
                # The offline engines decode overlapping short windows. That
                # keeps latency bounded while avoiding a queue of old radio.
                if engine == "moonshine":
                    target_seconds = 3.5
                    max_window_seconds = 5.0
                elif engine == "parakeet":
                    # Parakeet is very quick here; three seconds gives it
                    # useful word context without making captions feel late.
                    target_seconds = 3.0
                    max_window_seconds = 4.0
                else:
                    target_seconds = 3.6
                    max_window_seconds = 4.0
                if offline_since_decode >= target_seconds:
                    # A five-second Moonshine window carries enough sentence
                    # context to reduce radio-noise substitutions, while its
                    # measured Pi RTF leaves ample headroom for live captions.
                    max_bytes = int(max_window_seconds * 32000)
                    window = bytes(offline_pcm[-max_bytes:])
                    offline_pcm.clear()
                    offline_since_decode = 0.0
                    if engine == "moonshine":
                        samples = [sample / 32768.0 for sample in struct.unpack(f"<{len(window) // 2}h", window)]
                        stream = moonshine.create_stream()
                        stream.accept_waveform(16000, samples)
                        moonshine.decode_stream(stream)
                        result_text = stream.result.text
                    elif engine == "parakeet":
                        samples = [sample / 32768.0 for sample in struct.unpack(f"<{len(window) // 2}h", window)]
                        stream = parakeet.create_stream()
                        stream.accept_waveform(16000, samples)
                        parakeet.decode_stream(stream)
                        result_text = stream.result.text
                    else:
                        result_text = whisper_transcribe(window)
                    state.set_transcript(partial=result_text, status="LISTENING")
            measured_audio_seconds += len(pcm16) / 32000.0
            measured_processing_seconds += time.monotonic() - process_started
            if time.monotonic() >= next_performance_report and measured_audio_seconds > 0.05:
                print(
                    f"gl ASR {engine} rtf={measured_processing_seconds / measured_audio_seconds:.2f} "
                    f"queue={audio_queue.qsize()}/{audio_queue.maxsize}",
                    flush=True,
                )
                measured_audio_seconds = 0.0
                measured_processing_seconds = 0.0
                next_performance_report = time.monotonic() + 10.0
        except Exception as exc:
            label = ASR_ENGINE_LABELS.get(active_engine, "ASR")
            state.set_transcript(status=f"{label} ERROR")
            print(f"gl ASR {active_engine}: {exc}", flush=True)
            vosk_recognizer = None
            moonshine = None
            parakeet = None
            close_moonshine_streaming(moonshine_streaming)
            moonshine_streaming = None
            stop_event.wait(1.0)
    if resampler:
        resampler.close()
    close_moonshine_streaming(moonshine_streaming)


def rnnoise_voice_mode(radio_mode):
    """RNNoise is a speech enhancer, not a useful DSP stage for digital/IQ."""
    return str(radio_mode).lower() in ("am", "sam", "lsb", "usb")


def audio_option_at(x, y):
    for name, box in (
        ("mute", AUDIO_MUTE_BOX), ("voice_clean", AUDIO_VOICE_CLEAN_BOX),
        ("squelch", AUDIO_SQUELCH_BOX),
        ("agc", AUDIO_AGC_BOX), ("blanker", AUDIO_BLANKER_BOX),
        ("notch", AUDIO_NOTCH_BOX),
        ("deemphasis", AUDIO_DEEMP_BOX), ("filter", AUDIO_FILTER_BOX),
        ("reset", AUDIO_RESET_BOX),
    ):
        if contains(box, x, y):
            return name
    return None


def draw_audio_panel(text_cache, volume, controls, low_cut, high_cut, output_available):
    """One readable Audio workspace, with the real Kiwi SND path behind it."""
    x0, y0, x1, y1 = AUDIO_PANEL_BOX
    draw_logical_rect(0, sdr_ui.TOP_H, LOGICAL_W, LOGICAL_H, (0, 0, 0, 92))
    draw_logical_rect(x0, y0, x1, y1, (7, 14, 20, 234))
    draw_logical_line(x0, y0, x1, y0, (163, 190, 196, 96), 1)
    draw_logical_line(x0, y1, x1, y1, (163, 190, 196, 96), 1)
    draw_text(text_cache, 36, y0 + 19, "AUDIO", (229, 243, 246), 18, True, True, "lm", family="Liberation Sans")
    output_label = "USB SPEAKER" if output_available else "OUTPUT UNAVAILABLE"
    output_color = (104, 230, 151) if output_available else (242, 163, 104)
    draw_text(text_cache, 148, y0 + 19, output_label, output_color, 13, True, True, "lm", family="Liberation Sans")
    draw_text(text_cache, 906, y0 + 19, "RAW PCM", (151, 180, 187), 12, False, True, "rm", family="Liberation Sans")

    vx0, vy0, vx1, vy1 = AUDIO_VOLUME_BOX
    level = clamp(volume if volume is not None else 0.0, 0.0, 1.0)
    track_y = (vy0 + vy1) / 2 + 9
    draw_text(text_cache, vx0, vy0 + 2, "VOLUME", (164, 193, 198), 14, True, True, "lt", family="Liberation Sans")
    draw_text(text_cache, vx1, vy0 + 2, f"{round(level * 100):.0f}%", (232, 246, 248), 22, True, True, "rt", family="Liberation Sans")
    draw_logical_rect(vx0, track_y - 7, vx1, track_y + 7, (22, 35, 43, 230))
    draw_logical_rect(vx0, track_y - 7, vx0 + (vx1 - vx0) * level, track_y + 7, (68, 209, 151, 226))
    knob_x = vx0 + (vx1 - vx0) * level
    draw_logical_rect(knob_x - 8, track_y - 16, knob_x + 8, track_y + 16, (226, 246, 246, 255))

    def panel_button(box, title, detail, active=False, accent=(92, 229, 174, 220)):
        bx0, by0, bx1, by1 = box
        fill = (28, 78, 67, 230) if active else (18, 29, 38, 210)
        line = accent if active else (115, 140, 151, 78)
        draw_logical_rect(bx0, by0, bx1, by1, fill)
        draw_logical_line(bx0, by0, bx1, by0, line, 1)
        draw_logical_line(bx0, by1, bx1, by1, line, 1)
        draw_logical_line(bx0, by0, bx0, by1, line, 1)
        draw_logical_line(bx1, by0, bx1, by1, line, 1)
        draw_text(text_cache, bx0 + 14, by0 + 17, title, (230, 246, 247), 14, True, True, "lm", family="Liberation Sans")
        draw_text(text_cache, bx0 + 14, by0 + 39, detail, (112, 223, 169) if active else (153, 185, 191), 13, False, True, "lm", family="Liberation Sans")

    def panel_slider(box, title, value, maximum):
        bx0, by0, bx1, by1 = box
        fraction = clamp(value / maximum, 0.0, 1.0)
        draw_logical_rect(bx0, by0, bx1, by1, (18, 29, 38, 220))
        for line_y in (by0, by1):
            draw_logical_line(bx0, line_y, bx1, line_y, (115, 140, 151, 82), 1)
        draw_logical_line(bx0, by0, bx0, by1, (115, 140, 151, 82), 1)
        draw_logical_line(bx1, by0, bx1, by1, (115, 140, 151, 82), 1)
        draw_text(text_cache, bx0 + 14, by0 + 16, title, (230, 246, 247), 14, True, True, "lm", family="Liberation Sans")
        label = "OFF" if value <= 0 else f"{value:02d}"
        draw_text(text_cache, bx1 - 14, by0 + 16, label, (112, 223, 169) if value else (153, 185, 191), 15, True, True, "rm", family="Liberation Sans")
        track_x0, track_x1 = bx0 + 14, bx1 - 14
        track_y = by1 - 15
        draw_logical_rect(track_x0, track_y - 3, track_x1, track_y + 3, (31, 48, 57, 255))
        draw_logical_rect(track_x0, track_y - 3, track_x0 + (track_x1 - track_x0) * fraction, track_y + 3, (76, 221, 159, 230))
        knob_x = track_x0 + (track_x1 - track_x0) * fraction
        draw_logical_rect(knob_x - 4, track_y - 9, knob_x + 4, track_y + 9, (229, 246, 246, 245))

    def denoise_slider(box, level, bypassed=False):
        bx0, by0, bx1, by1 = box
        level = int(clamp(level, 0, len(kiwi.DENOISE_PRESETS) - 1))
        active = level > 0 and not bypassed
        draw_logical_rect(bx0, by0, bx1, by1, (24, 63, 57, 224) if active else (18, 29, 38, 220))
        line = (93, 235, 174, 184) if active else (115, 140, 151, 82)
        for line_y in (by0, by1):
            draw_logical_line(bx0, line_y, bx1, line_y, line, 1)
        draw_logical_line(bx0, by0, bx0, by1, line, 1)
        draw_logical_line(bx1, by0, bx1, by1, line, 1)
        draw_text(text_cache, bx0 + 14, by0 + 16, "DENOISE", (230, 246, 247), 14, True, True, "lm", family="Liberation Sans")
        label = "BYPASS" if bypassed else kiwi.DENOISE_PRESETS[level][0]
        draw_text(text_cache, bx1 - 14, by0 + 16, label, (112, 235, 175) if active else (153, 185, 191), 14, True, True, "rm", family="Liberation Sans")
        track_x0, track_x1 = bx0 + 14, bx1 - 14
        denoise_track_y = by1 - 15
        draw_logical_rect(track_x0, denoise_track_y - 3, track_x1, denoise_track_y + 3, (27, 45, 52, 255))
        current_x = track_x0 + (track_x1 - track_x0) * DENOISE_SLIDER_POSITIONS[level]
        draw_logical_rect(track_x0, denoise_track_y - 3, current_x, denoise_track_y + 3, (80, 226, 164, 235))
        for index, position in enumerate(DENOISE_SLIDER_POSITIONS):
            marker_x = track_x0 + (track_x1 - track_x0) * position
            marker_color = (112, 238, 177, 230) if index <= level else (107, 139, 147, 128)
            draw_logical_line(marker_x, denoise_track_y - 5, marker_x, denoise_track_y + 5, marker_color, 1)
        draw_logical_rect(current_x - 6, denoise_track_y - 10, current_x + 6, denoise_track_y + 10, (229, 246, 246, 255))

    muted = controls["mute"]
    panel_button(AUDIO_MUTE_BOX, "MUTE", "ON" if muted else "OFF", muted, (243, 118, 118, 230))
    voice_clean_level = int(clamp(controls.get("voice_clean_level", 0), 0, len(VOICE_CLEAN_PRESETS) - 1))
    voice_clean = voice_clean_level > 0
    panel_button(
        AUDIO_VOICE_CLEAN_BOX,
        "VOICE",
        VOICE_CLEAN_PRESETS[voice_clean_level],
        voice_clean,
        (123, 193, 250, 230),
    )
    sq = int(controls["squelch_level"])
    panel_slider(AUDIO_SQUELCH_BOX, "SQUELCH", sq, 99)
    agc_detail = "AUTO" if controls["agc"] and not controls["agc_hang"] else ("AUTO HANG" if controls["agc"] else f"MAN {controls['agc_manual_gain']} dB")
    panel_button(AUDIO_AGC_BOX, "AGC", agc_detail, bool(controls["agc"]))
    blanker = ("OFF", "STANDARD", "WILD")[int(controls["nb_algo"])]
    panel_button(AUDIO_BLANKER_BOX, "BLANKER", blanker, controls["nb_algo"] > 0)
    denoise_level = int(controls["denoise_level"])
    denoise_slider(AUDIO_DENOISE_BOX, denoise_level, voice_clean)
    panel_button(AUDIO_NOTCH_BOX, "AUTO NOTCH", "ON" if controls["autonotch"] else "OFF", controls["autonotch"])
    deemp = ("OFF", "75 uS", "50 uS")[int(controls["deemphasis"])]
    panel_button(AUDIO_DEEMP_BOX, "DE-EMPH", deemp, controls["deemphasis"] > 0)
    panel_button(AUDIO_FILTER_BOX, "PASSBAND", format_filter_width(high_cut - low_cut), False)
    panel_button(AUDIO_RESET_BOX, "RESTORE", "KIWI DEFAULTS", False)


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
    draw_text(text_cache, 36, y0 + 22, "TESTS", (229, 243, 246), 18, True, True, "lm")
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
    draw_text(text_cache, 36, y0 + 22, "DJ TUNE", (229, 243, 246), 18, True, True, "lm")
    delta_hz = round((current_khz - origin_khz) * 1000)
    delta_label = f"{delta_hz:+d} Hz" if delta_hz else "CENTRE"
    draw_text(text_cache, 918, y0 + 22, delta_label, (110, 230, 180), 16, True, True, "rm")
    draw_text(text_cache, LOGICAL_W / 2, y0 + 42, sdr_ui.format_freq(current_khz), (232, 246, 247), 28, True, False, "cm")
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
    draw_text(text_cache, 36, y0 + 29, "WATERFALL", (229, 243, 246), 18, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_SPECTRUM_BOX, "SPECTRUM", spectrum_enabled)
    draw_display_control(text_cache, DISPLAY_AUTO_BOX, "AUTO SCALE", auto)
    draw_logical_line(32, y0 + 48, 928, y0 + 48, (149, 171, 177, 56), 1)
    draw_text(text_cache, 36, y0 + 83, "FLOOR", (139, 180, 187), 14, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_FLOOR_MINUS_BOX, "-", False)
    draw_text(text_cache, 276, y0 + 83, f"{floor:.0f}", (224, 241, 243), 22, True, True, "cm")
    draw_display_control(text_cache, DISPLAY_FLOOR_PLUS_BOX, "+", False)
    draw_text(text_cache, 460, y0 + 83, "CEILING", (139, 180, 187), 14, True, True, "lm")
    draw_display_control(text_cache, DISPLAY_CEIL_MINUS_BOX, "-", False)
    draw_text(text_cache, 704, y0 + 83, f"{ceiling:.0f}", (224, 241, 243), 22, True, True, "cm")
    draw_display_control(text_cache, DISPLAY_CEIL_PLUS_BOX, "+", False)
    draw_text(text_cache, 36, y0 + 130, "RATE", (139, 180, 187), 13, True, True, "lm")
    for rate, box, label in DISPLAY_RATE_BOXES:
        draw_display_control(text_cache, box, label, rate == speed)
    draw_text(text_cache, 548, y0 + 130, "PALETTE", (139, 180, 187), 13, True, True, "lm")
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
    digital_factor = kiwi.DIGITAL_ZOOM_FACTORS.get(int(zoom))
    zoom_label = f"ZOOM DIGITAL {digital_factor:.0f}x" if digital_factor else "ZOOM"
    draw_text(text_cache, x0 + 18, y0 + 22, zoom_label, green[:3], 28, True, True, "lm")
    draw_text(text_cache, x1 - 18, y0 + 22, format_zoom_span(span_khz), green[:3], 28, True, True, "rm")

    track_x0 = x0 + 24
    track_x1 = x1 - 24
    base_y = y0 + 81
    draw_logical_line(track_x0, base_y, track_x1, base_y, soft, 3)
    bar_w = 17
    for level in range(kiwi.DISPLAY_MAX_ZOOM + 1):
        x = int(round(track_x0 + (track_x1 - track_x0) * level / kiwi.DISPLAY_MAX_ZOOM))
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
        # A compact, swept spherical wireframe based on the receiver-globe
        # reference, not a set of free-floating orbital rings.
        mono = (218, 228, 230, 225)
        globe_y = cy - 2

        def quadratic_curve(start, control, end, width):
            points = []
            for index in range(21):
                t = index / 20
                inv_t = 1 - t
                points.append((round(inv_t * inv_t * start[0] + 2 * inv_t * t * control[0] + t * t * end[0]), round(inv_t * inv_t * start[1] + 2 * inv_t * t * control[1] + t * t * end[1])))
            pygame.draw.lines(surface, mono, False, points, width)

        pygame.draw.circle(surface, mono, (cx, globe_y), 25, 2)
        # Four diagonal bands echo the attached woven-globe mark.
        quadratic_curve((cx - 18, globe_y - 18), (cx, globe_y - 30), (cx + 20, globe_y - 14), 3)
        quadratic_curve((cx - 25, globe_y - 8), (cx, globe_y + 5), (cx + 25, globe_y - 1), 3)
        quadratic_curve((cx - 25, globe_y + 5), (cx, globe_y + 18), (cx + 22, globe_y + 13), 3)
        quadratic_curve((cx - 17, globe_y + 18), (cx, globe_y + 30), (cx + 18, globe_y + 20), 3)
        # The angled meridians complete the woven spherical form.
        quadratic_curve((cx - 7, globe_y - 24), (cx - 21, globe_y - 1), (cx - 5, globe_y + 25), 3)
        quadratic_curve((cx + 8, globe_y - 24), (cx + 22, globe_y + 1), (cx + 7, globe_y + 24), 3)
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
        # Supplied speaker mark, retained as an outlined horn with two open
        # broadcast arcs and simply inverted for this dark instrument surface.
        speaker = (232, 242, 244, 240)
        pygame.draw.rect(surface, speaker, (cx - 30, cy - 15, 18, 30), 5, border_radius=7)
        pygame.draw.lines(surface, speaker, True, ((cx - 13, cy - 15), (cx + 11, cy - 31), (cx + 11, cy + 31), (cx - 13, cy + 15)), 5)
        pygame.draw.arc(surface, speaker, (cx - 10, cy - 22, 38, 44), math.radians(-58), math.radians(58), 6)
        pygame.draw.arc(surface, speaker, (cx - 17, cy - 34, 62, 68), math.radians(-58), math.radians(58), 6)
    elif kind == "tests":
        # Checklist fallback matching the supplied diagnostics artwork.
        pygame.draw.rect(surface, color, (cx - 23, cy - 31, 46, 62), 3, border_radius=3)
        pygame.draw.line(surface, dim, (cx - 13, cy - 12), (cx - 5, cy - 4), 3)
        pygame.draw.line(surface, dim, (cx - 5, cy - 4), (cx + 8, cy - 19), 3)
        pygame.draw.line(surface, color, (cx - 13, cy + 4), (cx + 13, cy + 4), 3)
        pygame.draw.line(surface, color, (cx - 13, cy + 16), (cx + 13, cy + 16), 3)
    elif kind == "settings":
        pygame.draw.circle(surface, color, (cx, cy), 17, 3)
        pygame.draw.circle(surface, dim, (cx, cy), 6, 3)
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            x0 = cx + round(math.cos(radians) * 20)
            y0 = cy + round(math.sin(radians) * 20)
            x1 = cx + round(math.cos(radians) * 27)
            y1 = cy + round(math.sin(radians) * 27)
            pygame.draw.line(surface, color, (x0, y0), (x1, y1), 4)
    elif kind == "digital":
        # An intentionally simple sampled square-wave mark for digital modes.
        points = ((cx - 29, cy + 15), (cx - 19, cy + 15), (cx - 19, cy - 15), (cx - 2, cy - 15), (cx - 2, cy + 15), (cx + 15, cy + 15), (cx + 15, cy - 15), (cx + 29, cy - 15))
        pygame.draw.lines(surface, color, False, points, 4)
        pygame.draw.circle(surface, dim, (cx - 21, cy - 23), 3)
        pygame.draw.circle(surface, dim, (cx + 18, cy + 23), 3)
    elif kind == "rf":
        # Broadcast antenna: signal elements belong at the mast's upper end.
        pygame.draw.line(surface, color, (cx, cy - 22), (cx, cy + 16), 4)
        pygame.draw.line(surface, color, (cx - 19, cy + 25), (cx + 19, cy + 25), 3)
        pygame.draw.line(surface, color, (cx - 17, cy + 25), (cx, cy + 7), 3)
        pygame.draw.line(surface, color, (cx + 17, cy + 25), (cx, cy + 7), 3)
        pygame.draw.line(surface, color, (cx - 12, cy - 25), (cx, cy - 16), 3)
        pygame.draw.line(surface, color, (cx + 12, cy - 25), (cx, cy - 16), 3)
        pygame.draw.circle(surface, color, (cx, cy - 23), 3)
    elif kind == "stats":
        # Three compact instrument bars denote live receiver/system telemetry.
        for offset, height in ((-20, 17), (0, 29), (20, 39)):
            pygame.draw.rect(surface, color, (cx + offset - 6, cy + 24 - height, 12, height), 3, border_radius=2)
        pygame.draw.line(surface, dim, (cx - 31, cy + 25), (cx + 31, cy + 25), 2)
    else:
        pygame.draw.circle(surface, color, (cx, cy), 24, 3)
        pygame.draw.line(surface, color, (cx, cy - 4), (cx, cy + 20), 3)
        pygame.draw.circle(surface, color, (cx, cy - 20), 3)


def menu_icon_texture(text_cache, kind, label, width=132, height=112):
    """Build a menu tile at its eventual raster size to avoid texture blur."""
    key = f"menu_asset_{kind}_{label}_{width}x{height}"
    cached = text_cache.cache.get(("surface", key))
    if cached is not None:
        return cached
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    asset_path = MENU_ICON_ASSET_DIR / MENU_ICON_FILENAMES.get(kind, f"{kind}.png")
    try:
        icon = pygame.image.load(str(asset_path)).convert_alpha()
        # Keep the supplied vector-derived art deliberately understated in the
        # compact menu. Its transparent alpha allows one clean 30% reduction.
        icon_size = round(icon.get_width() * 0.70)
        icon = pygame.transform.smoothscale(icon, (icon_size, icon_size))
        icon_y = max(0, (height - 26 - icon_size) // 2)
        surface.blit(icon, ((width - icon.get_width()) // 2, icon_y))
    except (pygame.error, OSError):
        # Keep development builds usable if the optional icon package is absent.
        color = (232, 248, 250, 232)
        dim = (82, 235, 231, 150)
        draw_menu_icon(surface, kind, width // 2, max(24, height // 2 - 12), color, dim)
    label_surface = text_cache.font(15, bold=True, family="Liberation Sans").render(label, True, (207, 221, 224))
    surface.blit(label_surface, ((width - label_surface.get_width()) // 2, height - 26))
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
        target_w = min(132, bx1 - bx0 - 12)
        target_h = min(92, by1 - by0 - 4)
        target_x = bx0 + ((bx1 - bx0) - target_w) / 2
        target_y = by0 + ((by1 - by0) - target_h) / 2
        tex, tex_w, tex_h = menu_icon_texture(text_cache, kind, label, int(target_w), int(target_h))
        draw_textured_quad(tex, target_x, target_y, target_x + target_w, target_y + target_h, 0, 0, 1, 1)


def desktop_1280_nav_box(index):
    """Persistent 2-column Home navigation rail for the 1280x480 desktop test."""
    col = index % 2
    row = index // 2
    x0 = DESKTOP_1280_MAIN_W + 7 + col * 125
    y0 = DESKTOP_1280_TOP_H + 8 + row * 96
    return x0, y0, x0 + 117, y0 + 88


def draw_desktop_1280_navigation(text_cache):
    if not DESKTOP_1280_MODE:
        return
    x0 = DESKTOP_1280_MAIN_W
    draw_native_rect(x0, DESKTOP_1280_TOP_H, NATIVE_W, NATIVE_H, (6, 13, 19, 246))
    for index, (kind, label) in enumerate(MENU_ITEMS):
        bx0, by0, bx1, by1 = desktop_1280_nav_box(index)
        draw_native_rect(bx0, by0, bx1, by1, (17, 29, 38, 218))
        draw_native_line(bx0, by0, bx1, by0, (125, 147, 158, 118), 1)
        draw_native_line(bx0, by1, bx1, by1, (32, 50, 61, 170), 1)
        draw_native_line(bx0, by0, bx0, by1, (66, 85, 96, 140), 1)
        draw_native_line(bx1, by0, bx1, by1, (32, 50, 61, 170), 1)
        tile_w = bx1 - bx0 - 8
        tile_h = by1 - by0 - 8
        tex, _tex_w, _tex_h = menu_icon_texture(text_cache, kind, label, tile_w, tile_h)
        draw_native_textured_quad(tex, bx0 + 4, by0 + 4, bx1 - 4, by1 - 4, alpha=0.96)


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


def draw_frequency_keypad(text_cache, value, invalid=False):
    """Render a focused frequency-entry workspace over the live waterfall."""
    layout = frequency_entry_layout()
    if layout is None:
        return
    panel, entry, commands, keys = layout
    x0, y0, x1, y1 = panel
    draw_logical_rect(x0, y0, x1, y1, (6, 17, 24, 235))
    draw_logical_line(x0 + 12, y0, x1 - 12, y0, (132, 166, 175, 112), 1)
    draw_logical_line(x0, y0 + 1, x0, y1, (52, 82, 91, 135), 1)
    draw_logical_line(x1, y0 + 1, x1, y1, (52, 82, 91, 135), 1)
    ex0, ey0, ex1, ey1 = entry
    draw_logical_rect(ex0, ey0, ex1, ey1, (3, 10, 15, 240))
    edge = (236, 142, 105, 255) if invalid else (112, 205, 188, 255)
    draw_logical_line(ex0, ey0, ex1, ey0, edge, 2)
    draw_logical_line(ex0, ey1, ex1, ey1, (83, 123, 131, 140), 1)
    draw_logical_line(ex0, ey0, ex0, ey1, (52, 93, 102, 150), 1)
    draw_logical_line(ex1, ey0, ex1, ey1, (52, 93, 102, 150), 1)
    draw_text(
        text_cache,
        ex0 + 12,
        (ey0 + ey1) / 2,
        value or "0.000000",
        (169, 189, 193),
        32,
        True,
        False,
        "lm",
        family="Liberation Sans",
    )
    draw_text(text_cache, ex1 - 10, (ey0 + ey1) / 2, "MHz", (132, 151, 155), 13, True, False, "rm", family="Liberation Sans")

    def draw_key(box, label, size, active=False):
        bx0, by0, bx1, by1 = box
        fill = (15, 38, 47, 238) if active else (13, 29, 37, 235)
        top = (87, 205, 196, 195) if active else (109, 145, 153, 130)
        side = (42, 78, 88, 165)
        draw_logical_rect(bx0, by0, bx1, by1, fill)
        draw_logical_line(bx0, by0, bx1, by0, top, 1)
        draw_logical_line(bx0, by0, bx0, by1, side, 1)
        draw_logical_line(bx1, by0, bx1, by1, side, 1)
        draw_logical_line(bx0, by1, bx1, by1, (27, 54, 62, 190), 1)
        draw_text(
            text_cache,
            (bx0 + bx1) / 2,
            (by0 + by1) / 2 + 1,
            label,
            (223, 238, 240),
            size,
            True,
            False,
            "cm",
            family="Liberation Sans",
        )

    for label, box in commands:
        caption = {"BACK": "DEL", "CLEAR": "CLR", "CANCEL": "X"}[label]
        draw_key(box, caption, 13 if label != "CANCEL" else 22)
    for label, box in keys:
        draw_key(box, "OK" if label == "ENTER" else label, 17 if label == "ENTER" else 28, active=label == "ENTER")


def fit_station_text(text_cache, text, max_width, size, bold=False, mono=False, family=None):
    """Ellipsize a row label to its measured slot, not an arbitrary count."""
    if text_cache.texture(text, size, (255, 255, 255), bold=bold, mono=mono, family=family)[1] <= max_width:
        return text
    ellipsis = "…"
    while text and text_cache.texture(text + ellipsis, size, (255, 255, 255), bold=bold, mono=mono, family=family)[1] > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def wrap_caption_lines(text_cache, text, max_width, size, max_rows=2):
    """Wrap current ASR text into safe, full-width subtitle rows."""
    words = " ".join(str(text).split()).split()
    rows, current = [], ""
    for word in words:
        # A decoder occasionally emits an implausibly long token. Keep the
        # GPU measurement bounded without placing an ellipsis in normal text.
        word = word[:48]
        candidate = f"{current} {word}".strip()
        too_wide = len(candidate) > 52 or text_cache.texture(
            candidate, size, (255, 255, 255), bold=True, family="Liberation Sans"
        )[1] > max_width
        if current and too_wide:
            rows.append(current)
            if len(rows) == max_rows:
                break
            current = word
        else:
            current = candidate
    if current and len(rows) < max_rows:
        rows.append(current)
    return rows


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
    # The 1024 px desktop canvas has a dedicated right-side instrument lane.
    # Shift the complete calibrated assembly into it without changing the
    # production 960 px layout.
    smeter_x_offset = 50 if DESKTOP_1280_MODE else 0
    meter_x0 = 690 + smeter_x_offset
    # Leave the usual right quiet margin while fitting a full calibrated scale.
    meter_x1 = 915 + smeter_x_offset
    green = (222, 255, 228, 255)
    red = (230, 20, 42, 255)
    rail = (160, 178, 182, 155)
    tick = (192, 211, 214, 220)
    blue = (0, 76, 245, 255)
    dbm_color = (189, 198, 201, 225)
    # The trace is the optical center of one calibrated assembly: S-units
    # above, dBm below. Keep every tick balanced around this datum.
    # The taller desktop scope gives this assembly a little more room below
    # the frequency readout. Keep the entire calibrated instrument together.
    smeter_y_offset = 6 if DESKTOP_1280_MODE else 0
    trace_y = 39 + smeter_y_offset

    def dbx(dbm):
        return meter_x0 + round((meter_x1 - meter_x0) * (smeter_segment_position(dbm) / 36.0))

    # Keep the rail deliberately neutral and flat. The calibration and live
    # level are the information; decorative glass treatment obscures both.
    draw_logical_line(meter_x0, trace_y, meter_x1, trace_y, (27, 43, 51, 230), 6)
    live_x = clamp(dbx(smeter_dbm), meter_x0, meter_x1)
    # The active trace belongs behind the scale too. The calibrated tick
    # geometry must remain uninterrupted at every level. Blue covers the
    # normal S range; only the explicitly red +20-and-up region turns red.
    red_start_x = dbx(SMETER_PLUS20_DBM)
    draw_logical_line(meter_x0, trace_y, min(live_x, red_start_x), trace_y, blue, 4)
    if live_x > red_start_x:
        draw_logical_line(red_start_x, trace_y, live_x, trace_y, red, 4)

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
        draw_text(text_cache, x, 12 + smeter_y_offset, text, color, size, False, True, "cm")

    # Major calibration lines reach equally above and below the trace. The
    # short midpoint ticks use the same symmetric treatment, so the dBm row
    # does not accidentally read as the only side with fine graduation.
    major_ticks = ((-121, tick), (-109, tick), (-97, tick), (-85, tick), (-73, tick), (-53, red), (-33, red))
    for dbm, color in major_ticks:
        x = dbx(dbm)
        draw_logical_line(x, trace_y - 10, x, trace_y + 10, color, 2)
    for dbm in (-115, -103, -91, -79, -63, -43):
        x = dbx(dbm)
        tick_color = red if dbm in (-63, -43) else rail
        draw_logical_line(x, trace_y - 4, x, trace_y + 4, tick_color, 1)

    # A single-line reading is quickest to parse. The scale begins farther
    # right so the large value and its unit do not touch the live trace.
    draw_text(text_cache, meter_x0 - 35, trace_y, f"{int(round(smeter_dbm))}", (194, 211, 214), 24, True, True, "rm")
    draw_text(text_cache, meter_x0 - 32, trace_y, "dBm", (164, 184, 188), 13, True, True, "lm")
    draw_logical_circle(
        live_x,
        trace_y - 1,
        5,
        (139, 234, 255, 255) if smeter_dbm < SMETER_PLUS20_DBM else (255, 174, 178, 255),
    )
    draw_logical_circle(live_x - 1, trace_y - 2.5, 1.6, (237, 254, 255, 245))
    # The retained peak is a quiet vertical reference, independent from the
    # live marker, so a changing signal remains easy to read at a glance.
    if peak_dbm is not None and peak_dbm > smeter_dbm + 0.75:
        peak_x = clamp(dbx(peak_dbm), meter_x0, meter_x1)
        draw_logical_line(peak_x, trace_y - 8, peak_x, trace_y + 8, (182, 197, 200, 178), 2)

    # A simple 20 dB cadence follows the reference instrument style. The
    # labels are calibrated through the same nonlinear S-unit mapping above.
    for dbm in (-120, -100, -80, -60, -40):
        draw_text(text_cache, dbx(dbm), 62 + smeter_y_offset, f"{dbm}", dbm_color[:3], 13, True, True, "cm")
    draw_text(text_cache, meter_x1 + 16, 62 + smeter_y_offset, "dBm", dbm_color[:3], 13, True, True, "lm")


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


def draw_lower_status(text_cache, cpu_percent, temp_c, y0, y1, station_name="", smeter_readout_dbm=None, transcription_enabled=False, asr_engine="off", alpha=1.0):
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
    asr_color = (105, 226, 171) if transcription_enabled else (146, 165, 171)
    asr_label = f"ASR {ASR_ENGINE_LABELS.get(asr_engine, 'OFF')}" if transcription_enabled else "ASR OFF"
    draw_text(text_cache, 944, status_mid_y, asr_label, asr_color, size, False, False, "rm", alpha, family="Cantarell")


def draw_vosk_captions(text_cache, lines, partial, status):
    """Large two-line caption overlay; it never changes waterfall geometry."""
    x0, y0, x1, y1 = VOSK_CAPTION_BOX
    draw_logical_rect(x0, y0, x1, y1, (3, 8, 12, 190))
    # A phrase uses both rows when needed. This reads like subtitles rather
    # than two independently clipping diagnostic strings.
    source = partial or (list(lines)[-1] if lines else "")
    display = wrap_caption_lines(text_cache, source, x1 - x0 - 40, 32)
    if not display:
        draw_text(text_cache, x0 + 20, (y0 + y1) / 2, "LISTENING..." if status == "LISTENING" else status, (133, 180, 190), 24, False, False, "lm", family="Liberation Sans")
        return
    for index, caption in enumerate(display):
        y = (y0 + y1) / 2 if len(display) == 1 else y0 + 29 + index * 47
        color = (166, 204, 213) if partial else (230, 241, 244)
        draw_text(text_cache, x0 + 20, y, caption, color, 32, True, False, "lm", family="Liberation Sans")


def asr_option_at(x, y):
    x0, y0, x1, y1 = ASR_PANEL_BOX
    if not contains(ASR_PANEL_BOX, x, y):
        return None
    index = min(len(ASR_ENGINES) - 1, max(0, int((x - x0) * len(ASR_ENGINES) / (x1 - x0))))
    return ASR_ENGINES[index]


def draw_asr_panel(text_cache, engine):
    """A large explicit ASR selector rather than a mystery on/off toggle."""
    x0, y0, x1, y1 = ASR_PANEL_BOX
    draw_logical_rect(x0, y0, x1, y1, (5, 13, 18, 224))
    cell_w = (x1 - x0) / len(ASR_ENGINES)
    for index, candidate in enumerate(ASR_ENGINES):
        left = x0 + index * cell_w + 4
        right = x0 + (index + 1) * cell_w - 4
        active = candidate == engine
        draw_logical_rect(left, y0 + 5, right, y1 - 5, (24, 82, 61, 230) if active else (20, 32, 39, 210))
        if active:
            draw_logical_rect(left, y1 - 8, right, y1 - 5, (100, 255, 163, 245))
        draw_text(
            text_cache, (left + right) / 2, (y0 + y1) / 2,
            ASR_ENGINE_LABELS[candidate], (180, 248, 207) if active else (197, 211, 215),
            17 if candidate != "whisper" else 15, active, False, "cm", family="Cantarell",
        )


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


def zoomed_spectrum_values(values, source_span_khz, visible_span_khz):
    """Resample the central source span for the local 4x display zoom."""
    if not values or source_span_khz <= visible_span_khz:
        return values
    source_fraction = clamp(visible_span_khz / source_span_khz, 0.001, 1.0)
    left = (1.0 - source_fraction) / 2.0
    last = len(values) - 1
    result = []
    for index in range(len(values)):
        source_index = (left + source_fraction * index / max(1, last)) * last
        low = int(math.floor(source_index))
        high = min(last, low + 1)
        amount = source_index - low
        result.append(values[low] + (values[high] - values[low]) * amount)
    return tuple(result)


def draw_spectrum(
    y0,
    y1,
    values,
    peak_values=(),
    text_cache=None,
    foreground=False,
    source_span_khz=None,
    visible_span_khz=None,
):
    """Draw the amplitude-versus-frequency trace from the Kiwi W/F bins."""
    # In the wide layout the scope intentionally sits over the lower edge of
    # the information strip. Keep its field translucent there so the reading
    # remains behind the live trace rather than becoming a separate hard box.
    field_alpha = 156 if foreground else 236
    draw_logical_rect(0, y0, LOGICAL_W, y1, (2, 7, 12, field_alpha))
    show_dbm_scale = (y1 - y0) >= 120
    scale_fractions = (0.0, 0.25, 0.50, 0.75, 1.0) if show_dbm_scale else (0.25, 0.50, 0.75)
    for fraction in scale_fractions:
        y = y0 + (y1 - y0) * fraction
        draw_logical_line(0, y, LOGICAL_W, y, (89, 139, 155, 48 if show_dbm_scale else 34), 1)
    if show_dbm_scale and text_cache is not None:
        # This is a visual reference scale for the normalized Kiwi spectrum,
        # not a calibrated RF-power meter. Keep it as a compact left-edge
        # instrument ruler, separated from the live trace by its own gutter.
        axis_x = 8
        label_x = 30
        draw_logical_rect(0, y0, 68, y1, (3, 11, 17, 102))
        draw_logical_line(axis_x, y0 + 4, axis_x, y1 - 4, (125, 169, 181, 118), 1)
        for index in range(17):
            fraction = index / 16
            y = y0 + (y1 - y0) * fraction
            major = index % 4 == 0
            tick_length = 14 if major else 6
            tick_color = (163, 203, 211, 172) if major else (100, 151, 165, 106)
            draw_logical_line(axis_x, y, axis_x + tick_length, y, tick_color, 1)
            if major:
                label = f"{-40 - index * 5}"
                if index == 0:
                    label += " dBm"
                # Font ascenders/figures look fractionally low when centered
                # on a 1 px rule, so lift the label optically, not the tick.
                # Let end labels overhang the field slightly rather than
                # distorting their value-to-tick alignment with a clamp.
                label_y = y - 2
                draw_text(text_cache, label_x, label_y, label, (180, 207, 211), 13, True, True, "lm")
    if source_span_khz is not None and visible_span_khz is not None:
        values = zoomed_spectrum_values(values, source_span_khz, visible_span_khz)
        peak_values = zoomed_spectrum_values(peak_values, source_span_khz, visible_span_khz)
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
    bandwidth_hz=2400,
    transcription_enabled=False,
    asr_engine="off",
):
    # Previous comparison color: (5, 9, 14, 252). Keep the instrument strip
    # deliberately pure black until a requested visual comparison restores it.
    if DESKTOP_1280_MODE:
        # The wide unit has one uninterrupted instrument strip spanning the
        # receiver canvas and the navigation rail.
        draw_native_rect(0, 0, NATIVE_W, DESKTOP_1280_TOP_H, (0, 0, 0, 255))
    draw_logical_rect(0, 0, LOGICAL_W, sdr_ui.TOP_H, (0, 0, 0, 255))
    draw_home_button(text_cache, 1.0)
    frequency_text, radio_box = top_instrument_layout(text_cache, freq_khz)
    if DESKTOP_1280_MODE:
        draw_desktop_1280_annunciator_button(text_cache, mode, digital, step_hz, bandwidth_hz)
    else:
        draw_radio_setup_pill(text_cache, mode, digital, step_hz, radio_box)
    # Liberation Sans Bold stays clean and compact at the display's physical
    # pixel density, leaving headroom inside the short instrument strip.
    # Right alignment keeps this cluster locked to the S-meter while the
    # number of MHz digits changes between bands.
    draw_text(text_cache, frequency_right_x(), 39, frequency_text, (169, 189, 193), 50, True, False, "rm", family="Liberation Sans")
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
            transcription_enabled=transcription_enabled,
            asr_engine=asr_engine,
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
            transcription_enabled=transcription_enabled,
            asr_engine=asr_engine,
            alpha=instrument_alpha,
        )
    draw_control_group_background(text_cache, ZOOM_GROUP_BOX, "zoom_group_pill_v7", (64, 156), controls_alpha)
    draw_zoom_button(text_cache, ZOOM_PLUS_BOX, "+", controls_alpha)
    draw_zoom_button(text_cache, ZOOM_MINUS_BOX, "-", controls_alpha)
    draw_text(
        text_cache,
        (ZOOM_MINUS_BOX[2] + ZOOM_PLUS_BOX[0]) / 2,
        (ZOOM_GROUP_BOX[1] + ZOOM_GROUP_BOX[3]) / 2,
        "ZOOM",
        (211, 227, 231),
        16,
        True,
        True,
        "cm",
        controls_alpha,
    )
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
    """Return Kiwi's native default passband for every selectable mode."""
    mode = mode.lower()
    if mode not in KIWI_MODE_FILTERS:
        raise ValueError(f"unsupported Kiwi mode: {mode}")
    return KIWI_MODE_FILTERS[mode]


def kiwi_audio_channels(mode):
    """Return playable channel count; zero denotes complex/extension data."""
    mode = mode.lower()
    if mode in KIWI_STEREO_AUDIO_MODES:
        return 2
    if mode in KIWI_NON_AUDIO_MODES:
        return 0
    return 1


def stereo_s16le_to_mono(data):
    """Downmix interleaved little-endian stereo PCM for the Globe monitor."""
    frame_count = len(data) // 4
    if frame_count <= 0:
        return b""
    samples = struct.unpack(f"<{frame_count * 2}h", data[:frame_count * 4])
    mono = tuple((samples[index] + samples[index + 1]) // 2 for index in range(0, len(samples), 2))
    return struct.pack(f"<{frame_count}h", *mono)


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

    def __init__(self, rate, channels=1):
        import sounddevice

        self.stream = sounddevice.RawOutputStream(
            samplerate=rate,
            channels=channels,
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


def start_audio_player(args, channels=1):
    """Open the SDR's PCM stream on PipeWire's current default sink.

    PipeWire/WirePlumber owns the output choice, so a USB sink selected as the
    system default continues to receive this stream without pinning a volatile
    numeric node id in the renderer configuration.
    """
    if not args.audio:
        return None
    if args.desktop:
        try:
            return DesktopAudioPlayer(args.audio_rate, channels)
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
                "--channels", str(channels),
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


def snd_meter_worker(args, stop_event, state, transcript_queue=None):
    seen_view_generation = -1
    seen_radio_generation = -1
    seen_server_generation = -1
    seen_audio_generation = -1
    player = None
    player_channels = None
    voice_cleaner = None
    voice_clean_requested = None
    while not stop_event.is_set():
        ws = None
        try:
            if state.external_audio_snapshot():
                stop_audio_player(player)
                player = None
                player_channels = None
                stop_event.wait(0.10)
                continue
            server, freq_khz, _zoom, _smeter, view_generation, server_generation = state.snapshot()
            state.connection_attempt(server_generation, "audio")
            radio_mode, low_cut, high_cut, radio_generation = state.radio_snapshot()
            desired_channels = kiwi_audio_channels(radio_mode)
            if desired_channels != player_channels or (player is not None and player.poll() is not None):
                stop_audio_player(player)
                player = start_audio_player(args, desired_channels) if desired_channels else None
                player_channels = desired_channels
            audio_controls, audio_generation = state.audio_controls_snapshot()
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
                desired_channels = kiwi_audio_channels(radio_mode)
                if desired_channels != player_channels or (player is not None and player.poll() is not None):
                    stop_audio_player(player)
                    player = start_audio_player(args, desired_channels) if desired_channels else None
                    player_channels = desired_channels
                audio_controls, audio_generation = state.audio_controls_snapshot()
                want_voice_clean = (
                    bool(audio_controls.get("voice_clean", False))
                    and desired_channels == 1
                    and rnnoise_voice_mode(radio_mode)
                )
                if want_voice_clean != voice_clean_requested:
                    if voice_cleaner is not None:
                        voice_cleaner.close()
                        voice_cleaner = None
                    voice_clean_requested = want_voice_clean
                    if want_voice_clean:
                        try:
                            voice_cleaner = RNNoiseVoiceCleaner()
                            print("gl RNNoise voice clean enabled", flush=True)
                        except (OSError, RuntimeError) as exc:
                            print(f"gl RNNoise unavailable: {exc}", flush=True)
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
                    kiwi.send_snd_setup(ws, snd_freq_khz, radio_mode, low_cut, high_cut, audio_controls)
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
                        kiwi.send_snd_setup(ws, snd_freq_khz, radio_mode, low_cut, high_cut, audio_controls)
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
                    kiwi.send_snd_setup(ws, snd_carrier_khz(freq_khz, low_cut, high_cut), radio_mode, low_cut, high_cut, audio_controls)
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
                packet_is_stereo = bool(flags & kiwi.SND_FLAG_STEREO)
                playable_packet = (
                    not (flags & kiwi.SND_FLAG_COMPRESSED)
                    and (
                        (packet_is_stereo and radio_mode in KIWI_STEREO_AUDIO_MODES)
                        or (
                            not packet_is_stereo
                            and radio_mode not in KIWI_NON_AUDIO_MODES
                            and desired_channels == 1
                        )
                    )
                )
                # Keep mute local as well as informing Kiwi. Some public
                # receivers continue sending raw PCM after SET mute, and this
                # is the final path into PipeWire/the USB audio device.
                if playable_packet:
                    if not (flags & kiwi.SND_FLAG_LITTLE_ENDIAN):
                        audio = kiwi.swap_s16_bytes(audio)
                    denoise_level = int(audio_controls.get("denoise_level", 0))
                    if voice_cleaner is not None:
                        voice_level = int(clamp(audio_controls.get("voice_clean_level", 2), 0, len(VOICE_CLEAN_MIX) - 1))
                        audio = voice_cleaner.process_pcm(audio, mix=VOICE_CLEAN_MIX[voice_level])
                    elif denoise_level > 0:
                        audio = apply_denoise_makeup_gain(audio, denoise_makeup_gain_db(denoise_level))
                    if not audio:
                        continue
                    transcription_enabled, _engine, _lines, _partial, _status, _generation = state.transcription_snapshot()
                    if transcription_enabled and transcript_queue is not None:
                        # Captions must stay current. A congested recognizer is
                        # never allowed to build a delayed replay of the radio.
                        try:
                            transcript_queue.put_nowait(audio)
                        except queue.Full:
                            try:
                                transcript_queue.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                transcript_queue.put_nowait(audio)
                            except queue.Full:
                                pass
                    if player and player.stdin and not audio_controls.get("mute", False):
                        try:
                            player.stdin.write(audio)
                        except (BrokenPipeError, OSError):
                            stop_audio_player(player)
                            player = None
                            player_channels = None
        except Exception as exc:
            print(f"gl SND {exc}", flush=True)
            if state.connection_failed(server_generation, "audio"):
                persist_live_station_health(server, "audio", False)
            if stop_event.wait(2.0):
                break
        finally:
            if ws:
                ws.send_close()
    if voice_cleaner is not None:
        voice_cleaner.close()
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
                if flags & kiwi.SND_FLAG_COMPRESSED or radio_mode in KIWI_NON_AUDIO_MODES:
                    continue
                if not flags & kiwi.SND_FLAG_LITTLE_ENDIAN:
                    audio = kiwi.swap_s16_bytes(audio)
                if flags & kiwi.SND_FLAG_STEREO:
                    if radio_mode not in KIWI_STEREO_AUDIO_MODES:
                        continue
                    # Globe uses one monitor sink for three prewarmed receivers.
                    # Preserve seamless switching by downmixing stereo modes here.
                    audio = stereo_s16le_to_mono(audio)
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
            sent_freq_khz = freq_khz
            sent_kiwi_zoom = kiwi.kiwi_zoom_level(zoom)
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
                    next_kiwi_zoom = kiwi.kiwi_zoom_level(zoom)
                    # Display zooms 15/16 are local crops of Kiwi zoom-14
                    # data, so moving among them must not flush/restart the
                    # live waterfall. A real RF move still goes to Kiwi.
                    if freq_khz != sent_freq_khz or next_kiwi_zoom != sent_kiwi_zoom:
                        drain_queue(line_queue)
                        kiwi.send_wf_setup(ws, freq_khz, zoom, wf_speed)
                        sent_freq_khz = freq_khz
                        sent_kiwi_zoom = next_kiwi_zoom
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
                    row_span = kiwi.zoom_source_span_khz(zoom)
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
    parser.add_argument("--desktop-1280", action="store_true", help="run a local 1280x480 desktop test with a persistent 256 px navigation rail")
    parser.add_argument("--frequency-keypad-preview", action="store_true", help=argparse.SUPPRESS)
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
    parser.add_argument("--max-zoom", type=int, default=kiwi.DISPLAY_MAX_ZOOM)
    parser.add_argument("--station-zoom", type=int, default=13)
    parser.add_argument("--tune-step-hz", type=int, default=100)
    parser.add_argument("--zoom-osd-seconds", type=float, default=ZOOM_OSD_SECONDS)
    parser.add_argument("--user", default="Codex OpenGL SDR display")
    parser.add_argument("--audio", action=argparse.BooleanOptionalAction, default=True, help="play Kiwi PCM through the PipeWire default sink")
    parser.add_argument("--audio-rate", type=int, default=12000, help="Kiwi raw PCM rate for the local PipeWire stream")
    args = parser.parse_args()
    remembered_radio_mode = None
    remembered_preferences = {}
    if args.remember_receiver:
        remembered_view = load_remembered_view(args.receiver_state_file)
        if remembered_view:
            args.server = remembered_view["server"]
            args.freq_khz = remembered_view.get("freq_khz", args.freq_khz)
            args.zoom = remembered_view.get("zoom", args.zoom)
            remembered_radio_mode = remembered_view.get("radio_mode")
            remembered_preferences = remembered_view.get("preferences", {})
            print(
                f"gl remembered receiver: {args.server} "
                f"{args.freq_khz:.3f} kHz zoom {args.zoom}",
                flush=True,
            )
    args.max_zoom = clamp(args.max_zoom, 0, kiwi.DISPLAY_MAX_ZOOM)
    args.station_zoom = clamp(args.station_zoom, 0, kiwi.DISPLAY_MAX_ZOOM)
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

    if args.desktop_1280:
        args.desktop = True
    if args.desktop:
        # Synthetic mouse events are already logical coordinates; do not apply
        # the touchscreen's hardware-specific axis corrections a second time.
        args.invert_x = False
        args.invert_y = False
        args.swap_x_y = False
    configure_output(args.desktop, args.desktop_1280)
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
    transcript_queue = queue.Queue(maxsize=24)
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
    if remembered_preferences:
        filter_preferences = remembered_preferences.get("filter", {})
        if isinstance(filter_preferences, dict):
            state.set_filter(
                low_cut=filter_preferences.get("low_cut"),
                high_cut=filter_preferences.get("high_cut"),
            )
        waterfall_preferences = remembered_preferences.get("waterfall", {})
        if isinstance(waterfall_preferences, dict):
            state.set_waterfall(
                floor=waterfall_preferences.get("floor"),
                ceil=waterfall_preferences.get("ceil"),
                speed=waterfall_preferences.get("speed"),
                auto=waterfall_preferences.get("auto"),
                palette=waterfall_preferences.get("palette"),
            )
        if isinstance(remembered_preferences.get("spectrum_enabled"), bool):
            state.set_spectrum_enabled(remembered_preferences["spectrum_enabled"])
        saved_asr_engine = remembered_preferences.get("asr_engine")
        if saved_asr_engine in ASR_ENGINES:
            state.set_asr_engine(saved_asr_engine)
        elif isinstance(remembered_preferences.get("vosk_enabled"), bool):
            # Migrate the prior Vosk-only preference without surprising the
            # existing operator after a software update.
            state.set_transcription_enabled(remembered_preferences["vosk_enabled"])
        audio_preferences = remembered_preferences.get("audio", {})
        if isinstance(audio_preferences, dict):
            restored_audio = {
                name: value for name, value in audio_preferences.items()
                if name in {
                    "squelch_level", "squelch_tail", "audio_mute", "agc_enabled", "agc_hang",
                    "agc_threshold", "agc_slope", "agc_decay", "agc_manual_gain", "deemphasis",
                    "nb_algo", "nr_algo", "denoise_level", "voice_clean_enabled", "voice_clean_level",
                    "autonotch_enabled",
                }
            }
            # The former four-step control had Light/Medium/Strong. Retain an
            # active saved preference as the new balanced Medium setting.
            if audio_preferences.get("voice_clean_profile") != 2 and restored_audio.get("voice_clean_level", 0):
                restored_audio["voice_clean_level"] = 1
            state.set_audio_controls(**restored_audio)
    globe_mixer = GlobeAudioMixer(args, state)
    scout_probe = ConstellationScoutProbe(args, state)
    wf_thread = threading.Thread(target=waterfall_worker, args=(args, line_queue, stop_event, state), daemon=True)
    snd_thread = threading.Thread(target=snd_meter_worker, args=(args, stop_event, state, transcript_queue), daemon=True)
    caption_thread = threading.Thread(target=asr_caption_worker, args=(stop_event, state, transcript_queue), daemon=True)
    wf_thread.start()
    snd_thread.start()
    caption_thread.start()

    desktop_event_writer = None
    desktop_window = None
    if args.desktop:
        from pygame._sdl2.video import Window

        desktop_window = Window.from_display_module()
        event_read_fd, desktop_event_writer = os.pipe()
        # The Pygame loop creates the synthetic touch events for this pipe.
        # It must therefore never wait here for an event that it has not yet
        # had a chance to poll from the desktop window.
        os.set_blocking(event_read_fd, False)
        ev = os.fdopen(event_read_fd, "rb", buffering=0)
        print(
            f"gl desktop window {NATIVE_W}x{NATIVE_H}; mouse drag tunes, "
            "Command-drag moves, wheel zooms",
            flush=True,
        )
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
    radio_family_open = None
    display_setup_open = False
    audio_panel_open = False
    asr_panel_open = False
    audio_volume = pipewire_default_volume()
    saved_volume = remembered_preferences.get("audio_volume")
    if isinstance(saved_volume, (int, float)):
        restored_volume = set_pipewire_default_volume(saved_volume)
        if restored_volume is not None:
            audio_volume = restored_volume
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
    filter_custom_width = bool(remembered_preferences.get("filter_custom_width", False))
    frequency_entry_open = args.frequency_keypad_preview
    frequency_entry_value = f"{args.freq_khz / 1000.0:.6f}" if frequency_entry_open else ""
    frequency_entry_invalid = False
    frequency_entry_replace_on_digit = False
    station_scroll = 0
    saved_digital_mode = remembered_preferences.get("digital_mode")
    digital_mode = saved_digital_mode if saved_digital_mode in ("DIG", "IQ") else "DIG"
    saved_tune_step_hz = remembered_preferences.get("tune_step_hz")
    tune_step_hz = max(1, int(saved_tune_step_hz)) if isinstance(saved_tune_step_hz, (int, float)) else args.tune_step_hz
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

    # Receiver preferences live in one tiny JSON file. UI changes settle for a
    # moment before writing; frequency gets a much longer dwell so live tuning
    # never becomes a stream of flash writes.
    persisted_frequency_khz = args.freq_khz
    observed_frequency_khz = args.freq_khz
    frequency_changed_at = time.monotonic()
    next_preferences_poll = 0.0
    preferences_due_at = 0.0
    preferences_dirty = bool(args.remember_receiver and "preferences" not in remembered_preferences)
    observed_preferences_signature = None
    saved_preferences_signature = None

    def current_preferences():
        _server, _freq_khz, zoom, _smeter, _generation, _server_generation = state.snapshot()
        _mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
        floor, ceiling, speed, auto, palette, _wf_generation = state.waterfall_snapshot()
        spectrum_enabled, _spectrum_values, _spectrum_peak_values = state.spectrum_snapshot()
        audio_controls, _audio_generation = state.audio_controls_snapshot()
        return {
            "audio": {
                "squelch_level": audio_controls["squelch_level"],
                "squelch_tail": audio_controls["squelch_tail"],
                "audio_mute": audio_controls["mute"],
                "agc_enabled": audio_controls["agc"],
                "agc_hang": audio_controls["agc_hang"],
                "agc_threshold": audio_controls["agc_threshold"],
                "agc_slope": audio_controls["agc_slope"],
                "agc_decay": audio_controls["agc_decay"],
                "agc_manual_gain": audio_controls["agc_manual_gain"],
                "deemphasis": audio_controls["deemphasis"],
                "nb_algo": audio_controls["nb_algo"],
                "nr_algo": audio_controls["nr_algo"],
                "denoise_level": audio_controls["denoise_level"],
                "voice_clean_enabled": audio_controls["voice_clean"],
                "voice_clean_level": audio_controls["voice_clean_level"],
                "voice_clean_profile": 2,
                "autonotch_enabled": audio_controls["autonotch"],
            },
            "audio_volume": None if audio_volume is None else round(float(audio_volume), 3),
            "digital_mode": digital_mode,
            "filter": {"low_cut": low_cut, "high_cut": high_cut},
            "filter_custom_width": bool(filter_custom_width),
            "spectrum_enabled": bool(spectrum_enabled),
            "asr_engine": state.transcription_snapshot()[1],
            "tune_step_hz": int(tune_step_hz),
            "waterfall": {
                "floor": round(float(floor), 1),
                "ceil": round(float(ceiling), 1),
                "speed": int(speed),
                "auto": bool(auto),
                "palette": palette,
            },
            "zoom": int(zoom),
        }

    def preferences_signature(preferences):
        server, _freq_khz, _zoom, _smeter, _generation, _server_generation = state.snapshot()
        payload = {
            "server": server,
            "radio_mode": radio_mode if manual_radio_mode else None,
            "preferences": preferences,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def write_remembered_view(save_current_frequency=False, force=False):
        nonlocal persisted_frequency_khz, preferences_dirty, preferences_due_at, saved_preferences_signature
        if not args.remember_receiver:
            return False
        server, freq_khz, zoom, _smeter, _generation, _server_generation = state.snapshot()
        preferences = current_preferences()
        signature = preferences_signature(preferences)
        frequency_changed = abs(persisted_frequency_khz - freq_khz) > 0.0005
        if not force and not preferences_dirty and signature == saved_preferences_signature and not (save_current_frequency and frequency_changed):
            return False
        if save_current_frequency:
            persisted_frequency_khz = freq_khz
        save_remembered_view(
            args.receiver_state_file,
            server,
            persisted_frequency_khz,
            zoom,
            radio_mode,
            manual_radio_mode,
            preferences,
        )
        saved_preferences_signature = signature
        preferences_dirty = False
        preferences_due_at = 0.0
        return True

    def observe_preferences(now):
        nonlocal observed_frequency_khz, frequency_changed_at, next_preferences_poll
        nonlocal observed_preferences_signature, preferences_dirty, preferences_due_at
        if not args.remember_receiver or now < next_preferences_poll:
            return
        next_preferences_poll = now + PREFERENCES_POLL_SECONDS
        _server, freq_khz, _zoom, _smeter, _generation, _server_generation = state.snapshot()
        if abs(freq_khz - observed_frequency_khz) > 0.0005:
            observed_frequency_khz = freq_khz
            frequency_changed_at = now
        preferences = current_preferences()
        signature = preferences_signature(preferences)
        if signature != observed_preferences_signature:
            observed_preferences_signature = signature
            if signature != saved_preferences_signature:
                preferences_dirty = True
                preferences_due_at = now + PREFERENCES_WRITE_IDLE_SECONDS
        if preferences_dirty and now >= preferences_due_at:
            write_remembered_view()
        elif abs(freq_khz - persisted_frequency_khz) > 0.0005 and now - frequency_changed_at >= FREQUENCY_WRITE_IDLE_SECONDS:
            write_remembered_view(save_current_frequency=True)

    initial_preferences = current_preferences()
    observed_preferences_signature = preferences_signature(initial_preferences)
    saved_preferences_signature = observed_preferences_signature

    def remember_current_view():
        observe_preferences(time.monotonic())

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
        if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or asr_panel_open or tests_panel_open or globe_open or dj_tune_open or filter_panel_open or frequency_entry_open or now <= controls_active_until:
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

    def activate_navigation_item(index):
        """Open a Home tool directly from the persistent 1280 desktop rail."""
        nonlocal menu_open, picker_open, radio_setup_open, display_setup_open
        nonlocal audio_panel_open, asr_panel_open, audio_volume, tests_panel_open, dj_tune_open
        nonlocal filter_panel_open, station_scroll, station_query, station_sort
        nonlocal stations, search_open, radio_family_open
        kind, label = MENU_ITEMS[index]
        wake_controls()
        menu_open = False
        if kind == "rx":
            picker_open = True
            radio_setup_open = display_setup_open = audio_panel_open = asr_panel_open = False
            tests_panel_open = dj_tune_open = filter_panel_open = False
            station_scroll = 0
            station_query = ""
            station_sort = "location"
            stations = filtered_stations(all_stations, station_query, station_sort)
            search_open = False
        elif kind == "display":
            display_setup_open = True
            picker_open = radio_setup_open = audio_panel_open = asr_panel_open = False
            tests_panel_open = dj_tune_open = filter_panel_open = False
        elif kind in ("settings", "digital"):
            radio_setup_open = True
            radio_family_open = None
            picker_open = display_setup_open = audio_panel_open = asr_panel_open = False
            tests_panel_open = dj_tune_open = filter_panel_open = False
        elif kind == "audio":
            audio_volume = pipewire_default_volume()
            audio_panel_open = True
            picker_open = radio_setup_open = display_setup_open = asr_panel_open = False
            tests_panel_open = dj_tune_open = filter_panel_open = False
        elif kind == "tests":
            tests_panel_open = True
            picker_open = radio_setup_open = display_setup_open = audio_panel_open = asr_panel_open = False
            dj_tune_open = filter_panel_open = False
        else:
            print(f"gl navigation {label} pending", flush=True)

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
    desktop_window_drag_button = None

    def desktop_logical_point(position):
        """Map a desktop mouse position directly into logical UI space."""
        window_w, window_h = pygame.display.get_window_size()
        nx = clamp(round(position[0] * NATIVE_W / max(1, window_w)), 0, NATIVE_W - 1)
        ny = clamp(round(position[1] * NATIVE_H / max(1, window_h)), 0, NATIVE_H - 1)
        if DESKTOP_1280_MODE:
            return clamp(nx, 0, LOGICAL_W - 1), clamp(ny, 0, LOGICAL_H - 1)
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

    def desktop_navigation_item(position):
        if not DESKTOP_1280_MODE:
            return None
        window_w, window_h = pygame.display.get_window_size()
        nx = round(position[0] * NATIVE_W / max(1, window_w))
        ny = round(position[1] * NATIVE_H / max(1, window_h))
        if contains(DESKTOP_1280_ANNUNCIATOR_BOX, nx, ny):
            return "annunciators"
        if nx < DESKTOP_1280_MAIN_W:
            return None
        for index in range(len(MENU_ITEMS)):
            if contains(desktop_1280_nav_box(index), nx, ny):
                return index
        return None


    try:
        while not stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    # SDL/Cocoa can emit spurious QUIT events for this
                    # borderless OpenGL development window. Desktop uses
                    # Esc/Q as its deliberate close path; the Pi retains its
                    # normal close behavior.
                    if not args.desktop:
                        stop_event.set()
                    else:
                        print("gl ignored desktop Cocoa QUIT", flush=True)
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                    stop_event.set()
                elif (
                    args.desktop
                    and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1
                    and pygame.key.get_mods() & pygame.KMOD_GUI
                ):
                    desktop_window_drag_button = event.button
                elif args.desktop and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    desktop_window_drag_button = None
                    nav_index = desktop_navigation_item(event.pos)
                    if nav_index == "annunciators":
                        activate_navigation_item(next(index for index, (kind, _label) in enumerate(MENU_ITEMS) if kind == "settings"))
                    elif nav_index is not None:
                        activate_navigation_item(nav_index)
                    else:
                        desktop_pointer_down = True
                        emit_desktop_touch(event.pos, "down")
                elif args.desktop and event.type == pygame.MOUSEMOTION and desktop_window_drag_button is not None:
                    if event.buttons[0]:
                        window_x, window_y = desktop_window.position
                        desktop_window.position = (window_x + event.rel[0], window_y + event.rel[1])
                    else:
                        desktop_window_drag_button = None
                elif args.desktop and event.type == pygame.MOUSEMOTION and desktop_pointer_down:
                    emit_desktop_touch(event.pos, "move")
                elif (
                    args.desktop
                    and event.type == pygame.MOUSEBUTTONUP
                    and event.button == desktop_window_drag_button
                ):
                    desktop_window_drag_button = None
                elif args.desktop and event.type == pygame.MOUSEBUTTONUP and event.button == 1 and desktop_pointer_down:
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
                            start_freq = display_freq if not menu_open and not picker_open and not radio_setup_open and not display_setup_open and not audio_panel_open and not asr_panel_open and not tests_panel_open and not globe_open and not dj_tune_open and not filter_panel_open and not frequency_entry_open else freq_khz
                            start_span = display_span
                            candidate_freq = start_freq
                            if waterfall_focus_progress() > 0.01:
                                wake_controls()
                                gesture = "wake"
                            elif frequency_entry_open and (frequency_layout := frequency_entry_layout()) and contains(frequency_layout[0], x, y):
                                gesture = "frequency_entry"
                            elif frequency_entry_open:
                                gesture = "frequency_entry_outside"
                            elif asr_panel_open and asr_option_at(x, y) is not None:
                                gesture = "asr_select"
                            elif asr_panel_open:
                                gesture = "asr_outside"
                            elif DESKTOP_1280_MODE and contains(frequency_display_box(text_cache, display_freq), x, y):
                                gesture = "frequency_entry_open"
                            elif contains(HOME_BOX, x, y):
                                gesture = "home"
                            elif contains(top_instrument_layout(text_cache, display_freq)[1], x, y):
                                gesture = "radio_toggle"
                            elif audio_panel_open and contains(AUDIO_VOLUME_BOX, x, y):
                                gesture = "audio_volume"
                            elif audio_panel_open and contains(AUDIO_SQUELCH_BOX, x, y):
                                gesture = "audio_squelch_level"
                            elif audio_panel_open and contains(AUDIO_DENOISE_BOX, x, y):
                                gesture = "audio_denoise_level"
                            elif audio_panel_open and audio_option_at(x, y) is not None:
                                gesture = "audio_control"
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
                            elif radio_setup_open and contains(radio_panel_box(), x, y):
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
                            elif not picker_open and contains(ASR_TOGGLE_BOX, x, y):
                                gesture = "asr_toggle"
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
                        elif gesture == "audio_squelch_level":
                            state.set_audio_controls(squelch_level=audio_squelch_at_x(x))
                        elif gesture == "audio_denoise_level":
                            state.set_audio_controls(
                                nr_algo=1,
                                denoise_level=audio_denoise_level_at_x(x),
                                voice_clean_enabled=False,
                                voice_clean_level=0,
                            )
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
                        if touch_started and gesture == "frequency_entry":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                action = frequency_entry_action_at(x, y)
                                if action == "BACK":
                                    frequency_entry_value = frequency_entry_value[:-1]
                                    frequency_entry_invalid = False
                                    frequency_entry_replace_on_digit = False
                                elif action == "CLEAR":
                                    frequency_entry_value = ""
                                    frequency_entry_invalid = False
                                    frequency_entry_replace_on_digit = False
                                elif action == "CANCEL":
                                    frequency_entry_open = False
                                    frequency_entry_invalid = False
                                    frequency_entry_replace_on_digit = False
                                elif action == "ENTER":
                                    entered_khz = parse_frequency_entry_mhz(frequency_entry_value)
                                    if entered_khz is None:
                                        frequency_entry_invalid = True
                                    else:
                                        state.set_view(freq_khz=entered_khz)
                                        display_freq = entered_khz
                                        candidate_freq = entered_khz
                                        animate_to(entered_khz, display_span, 0.16)
                                        apply_band_default(entered_khz)
                                        remember_current_view()
                                        frequency_entry_open = False
                                        frequency_entry_invalid = False
                                        frequency_entry_replace_on_digit = False
                                elif action and action in ".0123456789" and len(frequency_entry_value) < 12:
                                    if frequency_entry_replace_on_digit:
                                        frequency_entry_value = ""
                                        frequency_entry_replace_on_digit = False
                                    if action != "." or "." not in frequency_entry_value:
                                        frequency_entry_value += action
                                        frequency_entry_invalid = False
                            wake_controls()
                        elif touch_started and gesture == "frequency_entry_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                frequency_entry_open = False
                                frequency_entry_invalid = False
                                frequency_entry_replace_on_digit = False
                            wake_controls()
                        elif touch_started and gesture == "frequency_entry_open":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                frequency_entry_value = f"{display_freq / 1000.0:.6f}"
                                frequency_entry_invalid = False
                                frequency_entry_replace_on_digit = True
                                frequency_entry_open = True
                                menu_open = picker_open = radio_setup_open = display_setup_open = False
                                audio_panel_open = tests_panel_open = globe_open = dj_tune_open = filter_panel_open = False
                            wake_controls()
                        elif touch_started and gesture == "home":
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
                                radio_family_open = None
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
                        elif touch_started and gesture == "audio_squelch_level":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                controls, _audio_generation = state.audio_controls_snapshot()
                                state.set_audio_controls(squelch_level=0 if controls["squelch_level"] else 20)
                            wake_controls()
                        elif touch_started and gesture == "audio_denoise_level":
                            state.set_audio_controls(
                                nr_algo=1,
                                denoise_level=audio_denoise_level_at_x(x),
                                voice_clean_enabled=False,
                                voice_clean_level=0,
                            )
                            wake_controls()
                        elif touch_started and gesture == "audio_control":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                choice = audio_option_at(x, y)
                                controls, _audio_generation = state.audio_controls_snapshot()
                                if choice == "mute":
                                    state.set_audio_controls(audio_mute=not controls["mute"])
                                elif choice == "voice_clean":
                                    next_level = (int(controls.get("voice_clean_level", 0)) + 1) % len(VOICE_CLEAN_PRESETS)
                                    state.set_audio_controls(voice_clean_level=next_level)
                                elif choice == "agc":
                                    if not controls["agc"]:
                                        state.set_audio_controls(agc_enabled=True, agc_hang=False)
                                    elif not controls["agc_hang"]:
                                        state.set_audio_controls(agc_hang=True)
                                    else:
                                        state.set_audio_controls(agc_enabled=False, agc_hang=False)
                                elif choice == "blanker":
                                    state.set_audio_controls(nb_algo=(int(controls["nb_algo"]) + 1) % 3)
                                elif choice == "notch":
                                    state.set_audio_controls(nr_algo=1, autonotch_enabled=not controls["autonotch"])
                                elif choice == "deemphasis":
                                    state.set_audio_controls(deemphasis=(int(controls["deemphasis"]) + 1) % 3)
                                elif choice == "filter":
                                    audio_panel_open = False
                                    filter_panel_open = True
                                elif choice == "reset":
                                    state.reset_audio_controls()
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
                                choice = radio_option_at(x, y, radio_family_open)
                                if choice is not None:
                                    kind, value = choice
                                    if kind == "mode_family":
                                        family, modes = value
                                        if len(modes) > 1:
                                            radio_family_open = family
                                        else:
                                            radio_mode = modes[0]
                                            manual_radio_mode = True
                                            filter_custom_width = False
                                            digital_mode = "IQ" if radio_mode == "IQ" else "DIG"
                                            state.set_radio_mode(radio_mode)
                                            remember_current_view()
                                    elif kind == "mode":
                                        radio_mode = value
                                        radio_family_open = None
                                        manual_radio_mode = True
                                        filter_custom_width = False
                                        digital_mode = "IQ" if radio_mode == "IQ" else "DIG"
                                        state.set_radio_mode(radio_mode)
                                        remember_current_view()
                                    elif kind == "back":
                                        radio_family_open = None
                                    else:
                                        tune_step_hz = value
                                    wake_controls()
                                    print(f"gl radio {radio_mode} {digital_mode} step {tune_step_hz} Hz", flush=True)
                        elif touch_started and gesture == "radio_setup_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                radio_setup_open = False
                                radio_family_open = None
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
                                    activate_navigation_item(idx)
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
                        elif touch_started and gesture == "asr_toggle":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                asr_panel_open = not asr_panel_open
                            wake_controls()
                        elif touch_started and gesture == "asr_select":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                selected_engine = asr_option_at(x, y)
                                if selected_engine is not None:
                                    state.set_asr_engine(selected_engine)
                                    drain_caption_audio(transcript_queue)
                                    # ASR selection is an explicit, infrequent
                                    # preference and is worth committing now.
                                    preferences_dirty = True
                                    write_remembered_view(force=True)
                                asr_panel_open = False
                            wake_controls()
                        elif touch_started and gesture == "asr_outside":
                            moved = max(abs(x - start_x), abs(y - start_y))
                            if moved <= args.tap_px:
                                asr_panel_open = False
                            wake_controls()
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
            observe_preferences(now)
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
                        line, row_center_khz, row_span_khz = item
                    else:
                        line = item
                        row_center_khz = display_freq
                        row_span_khz = display_span
                    wf_texture.push_line(line, row_center_khz, row_span_khz)
                    consumed += 1
                except queue.Empty:
                    break

            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            draw_logical_rect(0, 0, LOGICAL_W, LOGICAL_H, (4, 7, 11, 255))
            focus_progress = waterfall_focus_progress(now)
            spectrum_enabled, spectrum_values, spectrum_peak_values = state.spectrum_snapshot()
            _state_mode, low_cut, high_cut, _radio_generation = state.radio_snapshot()
            spectrum_h = (SPECTRUM_WIDE_H if DESKTOP_1280_MODE else SPECTRUM_H) if spectrum_enabled else 0
            # Keep scope compact and behind the top instrumentation. Its lower
            # edge now sits beside the S-meter, freeing the waterfall below.
            top_instrument_h = DESKTOP_1280_TOP_H if DESKTOP_1280_MODE else sdr_ui.TOP_H
            spectrum_raise_y = SPECTRUM_WIDE_RAISE_Y if DESKTOP_1280_MODE else 0
            spectrum_y0 = (
                top_instrument_h - spectrum_raise_y
                if spectrum_enabled
                else top_instrument_h
                + sdr_ui.RULER_H * (1.0 - focus_progress)
                - (
                    WATERFALL_ONLY_WIDE_RAISE_Y
                    if DESKTOP_1280_MODE
                    else SPECTRUM_RAISE_Y
                )
                * (1.0 - focus_progress)
            )
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
            wf_texture.draw(
                0,
                waterfall_y0,
                LOGICAL_W,
                waterfall_y1,
                center_khz=display_freq,
                span_khz=display_span,
                row_offset=row_offset,
            )
            spectrum_foreground = spectrum_enabled and DESKTOP_1280_MODE
            if spectrum_enabled and not spectrum_foreground:
                draw_spectrum(
                    spectrum_y0,
                    spectrum_y1,
                    spectrum_values,
                    spectrum_peak_values,
                    text_cache,
                    source_span_khz=kiwi.zoom_source_span_khz(zoom),
                    visible_span_khz=display_span,
                )
            overlay_low_cut, overlay_high_cut = filter_view_offsets(low_cut, high_cut)
            draw_filter_overlay(
                display_span,
                overlay_low_cut,
                overlay_high_cut,
                waterfall_y0,
                waterfall_y1,
                0.82,
            )
            control_alpha = 0.0 if menu_open or picker_open or radio_setup_open or display_setup_open or audio_panel_open or asr_panel_open or tests_panel_open or globe_open or dj_tune_open or filter_panel_open or frequency_entry_open else controls_alpha(now)
            selected_station_name = next(
                (
                    bottom_station_title(name, location)
                    for name, location, candidate_server, *_capacity in all_stations
                    if candidate_server == server
                ),
                "",
            )
            connection_status = state.connection_snapshot()
            transcription_enabled, asr_engine, transcript_lines, transcript_partial, transcript_status, _transcription_generation = state.transcription_snapshot()
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
                bandwidth_hz=high_cut - low_cut,
                transcription_enabled=transcription_enabled,
                asr_engine=asr_engine,
            )
            if spectrum_foreground:
                draw_spectrum(
                    spectrum_y0,
                    spectrum_y1,
                    spectrum_values,
                    spectrum_peak_values,
                    text_cache,
                    foreground=True,
                    source_span_khz=kiwi.zoom_source_span_khz(zoom),
                    visible_span_khz=display_span,
                )
            if transcription_enabled:
                draw_vosk_captions(
                    text_cache,
                    transcript_lines,
                    transcript_partial,
                    transcript_status,
                )
            if asr_panel_open:
                draw_asr_panel(text_cache, asr_engine)
            if frequency_entry_open:
                draw_frequency_keypad(text_cache, frequency_entry_value, frequency_entry_invalid)
            if menu_open:
                draw_main_menu(text_cache, menu_scroll)
            if picker_open:
                if search_open:
                    draw_station_search(text_cache, all_stations, station_query, station_sort, keyboard_mode)
                else:
                    visible_stations = health_prioritized_stations(stations, station_health, station_sort)
                    draw_station_picker(text_cache, visible_stations, station_scroll, server, station_query, station_sort, station_health)
            if radio_setup_open:
                draw_radio_setup_panel(text_cache, radio_mode, digital_mode, tune_step_hz, radio_family_open)
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
                audio_controls, _audio_generation = state.audio_controls_snapshot()
                _audio_mode, audio_low_cut, audio_high_cut, _audio_radio_generation = state.radio_snapshot()
                draw_audio_panel(
                    text_cache,
                    audio_volume,
                    audio_controls,
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
            draw_desktop_1280_navigation(text_cache)
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
        # An orderly exit commits a genuine last-minute adjustment, including
        # the current frequency, once. Unchanged state produces no write.
        write_remembered_view(save_current_frequency=True)
        globe_mixer.stop()
        scout_probe.stop()
        stop_event.set()
        ev.close()
        if desktop_event_writer is not None:
            os.close(desktop_event_writer)
        wf_thread.join(timeout=1.5)
        snd_thread.join(timeout=1.5)
        caption_thread.join(timeout=1.5)
        elapsed = max(0.001, time.monotonic() - start)
        print(f"gl frames={frames} fps={frames / elapsed:.1f}", flush=True)
        pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
