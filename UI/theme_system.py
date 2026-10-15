"""Persistent, versioned appearance profiles for the Pygame interface."""

from dataclasses import fields
import json
import os
from pathlib import Path
import uuid

from ui_style import UIPalette, apply_ui_style
from smeter_styles import DEFAULT_METER_STYLE, normalize_meter_style


DEFAULT_THEME_ID = "default"
STRAIGHT_INVERTED_THEME_ID = "straight-inverted"
GREEN_THEME_ID = "green"
BLACK_WHITE_THEME_ID = "black-white"
REMOVED_THEME_MIGRATIONS = {
    "default-straight": DEFAULT_THEME_ID,
    "rounded-inverted": STRAIGHT_INVERTED_THEME_ID,
    "red": DEFAULT_THEME_ID,
    "instrument": DEFAULT_THEME_ID,
}
TEXT_SCALE_MIN = 80
TEXT_SCALE_MAX = 120
DEFAULT_COLORS = {
    **{field.name: list(getattr(UIPalette(), field.name)) for field in fields(UIPalette)},
    # Quiet instrument controls replace the earlier bright default grid.
    "surface": [0, 0, 0, 255],
    "border": [46, 46, 46, 255],
    "active_surface": [30, 30, 30, 255],
    "active_border": [96, 96, 96, 255],
    "selected_surface": [24, 24, 24, 255],
    "selected_border": [82, 82, 82, 255],
    "pressed_surface": [0, 229, 255, 255],
    "pressed_border": [0, 229, 255, 255],
    "secondary_text": [132, 132, 132],
}
DEFAULT_THEME = {
    "id": DEFAULT_THEME_ID,
    "name": "Default",
    "colors": DEFAULT_COLORS,
    "radius": 0,
    "sidebar": "right",
    "text_scale_percent": 100,
    # The historical UI mixes station miles and WSPR kilometres. Keep the
    # built-in theme visually unchanged; saved themes choose a unified system.
    "units": "original",
    "smeter_style": DEFAULT_METER_STYLE,
}


def invert_colors(colors):
    """Invert RGB while retaining every color's original transparency."""
    return {name: [255 - channel for channel in value[:3]] + list(value[3:])
            for name, value in colors.items()}


def green_colors(colors):
    """Map the original palette's lightness to the green color family."""
    factors = (0.45, 1.0, 0.53)
    result = {}
    for name, value in colors.items():
        lightness = round(0.2126 * value[0] + 0.7152 * value[1] + 0.0722 * value[2])
        result[name] = [round(lightness * factor) for factor in factors] + list(value[3:])
    # The live S-meter trace starts blue in the default palette. Its luminance
    # becomes nearly the same as the dark rail under a monochrome tint.
    signal_colors = {
        "smeter_active": (96, 244, 130),
        "smeter_hot": (171, 255, 189),
        "smeter_marker": (223, 255, 229),
    }
    for name, rgb in signal_colors.items():
        result[name] = [*rgb, *colors[name][3:]]
    return result


def black_white_colors(colors):
    """Use neutral grays throughout the palette while retaining transparency."""
    result = {}
    for name, value in colors.items():
        gray = round(0.2126 * value[0] + 0.7152 * value[1] + 0.0722 * value[2])
        result[name] = [gray, gray, gray, *value[3:]]
    # Keep inactive borders as quiet as Default while giving active states
    # clear neutral edges and preserving a readable live trace.
    for name, gray in (("background", 0), ("section_surface", 24),
                       ("section_border", 205),
                       ("active_border", 255), ("selected_border", 225),
                       ("section_heading", 240), ("frequency", 255),
                       ("smeter_active", 225), ("smeter_hot", 255),
                       ("smeter_marker", 245)):
        result[name][:3] = [gray] * 3
    return result


INVERTED_COLORS = invert_colors(DEFAULT_THEME["colors"])
STRAIGHT_INVERTED_THEME = {**DEFAULT_THEME, "id": STRAIGHT_INVERTED_THEME_ID,
                           "name": "Default Inverted", "colors": INVERTED_COLORS}
GREEN_THEME = {**DEFAULT_THEME, "id": GREEN_THEME_ID, "name": "Green",
               "colors": green_colors(DEFAULT_THEME["colors"])}
BLACK_WHITE_THEME = {**DEFAULT_THEME, "id": BLACK_WHITE_THEME_ID,
                     "name": "Black & White",
                     "colors": black_white_colors(DEFAULT_THEME["colors"])}
BUILTIN_THEMES = {
    theme["id"]: theme for theme in (
        DEFAULT_THEME, STRAIGHT_INVERTED_THEME, GREEN_THEME, BLACK_WHITE_THEME,
    )
}
BUILTIN_THEME_IDS = tuple(BUILTIN_THEMES)
COLOR_NAMES = tuple(DEFAULT_THEME["colors"])
runtime_theme = dict(DEFAULT_THEME)
runtime_revision = 0


def is_builtin_theme_id(identifier):
    return identifier in BUILTIN_THEMES


def is_reserved_theme_id(identifier):
    return is_builtin_theme_id(identifier) or identifier in REMOVED_THEME_MIGRATIONS


def color_hex(color):
    return "#" + "".join(f"{channel:02X}" for channel in color)


def parse_color(value, fallback):
    if isinstance(value, str):
        raw = value.lstrip("#")
        if len(raw) in (6, 8):
            try:
                value = tuple(bytes.fromhex(raw))
            except ValueError:
                return tuple(fallback)
    if isinstance(value, (tuple, list)) and len(value) == len(fallback):
        if all(type(channel) is int and 0 <= channel <= 255 for channel in value):
            return tuple(value)
    return tuple(fallback)


def normalize_theme(value, *, allow_default=False):
    if not isinstance(value, dict):
        raise ValueError("theme must be an object")
    identifier = str(value.get("id") or "").strip()
    if is_reserved_theme_id(identifier) and not allow_default:
        raise ValueError("the built-in theme cannot be edited")
    if not identifier or len(identifier) > 80:
        raise ValueError("invalid theme identifier")
    name = str(value.get("name") or "").strip()
    if not name or len(name) > 32:
        raise ValueError("theme name must be 1-32 characters")
    given_colors = value.get("colors") if isinstance(value.get("colors"), dict) else {}
    colors = {
        key: list(parse_color(given_colors.get(key), fallback))
        for key, fallback in DEFAULT_THEME["colors"].items()
    }
    text_scale = value.get("text_scale_percent", 100)
    text_scale = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, text_scale)) if type(text_scale) is int else 100
    return {
        "id": identifier,
        "name": name,
        "colors": colors,
        "radius": 0 if value.get("radius") == 0 else 8,
        "sidebar": value.get("sidebar") if value.get("sidebar") in ("left", "right") else "right",
        "text_scale_percent": text_scale,
        "smeter_style": normalize_meter_style(value.get("smeter_style")),
        "units": value.get("units") if value.get("units") in ("original", "imperial", "metric") else "original",
    }


def new_theme(name="New Theme", source=None):
    base = normalize_theme(source or DEFAULT_THEME, allow_default=True)
    base["id"] = uuid.uuid4().hex
    base["name"] = name
    if source is None and base["units"] == "original":
        base["units"] = "imperial"
    return base


def theme_appearance(theme):
    """Meter choice is a display setting, never part of a saved theme."""
    return {key: value for key, value in theme.items() if key != "smeter_style"}


def apply_theme(theme):
    global runtime_revision
    normalized = normalize_theme(theme, allow_default=True)
    runtime_theme.clear()
    runtime_theme.update(normalized)
    palette = UIPalette(**{
        name: tuple(value) for name, value in normalized["colors"].items()
    })
    apply_ui_style(palette, radius=normalized["radius"])
    runtime_revision += 1
    return normalized


def scaled_text_size(size, theme=None):
    """Use one saved percentage for titles, subtitles, and instrument labels."""
    percent = (theme or runtime_theme)["text_scale_percent"]
    return max(1, int(round(float(size) * percent / 100)))


def display_distance(km, theme=None, *, default_unit="km"):
    units = (theme or runtime_theme)["units"]
    metric = units == "metric" or (units == "original" and default_unit == "km")
    return f"{int(round(km if metric else km * 0.621371)):,} {'km' if metric else 'mi'}"


def distance_axis_label(km, theme=None):
    value = km * (0.621371 if (theme or runtime_theme)["units"] == "imperial" else 1.0)
    return f"{value / 1000:g}k" if value >= 1000 else f"{value:.0f}"


def display_temperature(celsius, theme=None, *, compact=False):
    units = (theme or runtime_theme)["units"]
    if units == "original":
        return f"{celsius:.0f}{'' if compact else ' '}C"
    metric = units == "metric"
    return f"{celsius:.0f}°C" if metric else f"{celsius * 9 / 5 + 32:.0f}°F"


def display_to_logical_x(x, width=1280, rail_width=256, theme=None):
    """Reverse a left-rail layout at the input boundary."""
    if (theme or runtime_theme)["sidebar"] != "left":
        return x
    return x + (width - rail_width) if x < rail_width else x - rail_width


class ThemeLibrary:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.themes = []
        self.active_id = DEFAULT_THEME_ID
        self.smeter_style = DEFAULT_METER_STYLE
        self.load()

    def get(self, identifier):
        if is_builtin_theme_id(identifier):
            theme = normalize_theme(BUILTIN_THEMES[identifier], allow_default=True)
        else:
            theme = next((theme for theme in self.themes if theme["id"] == identifier), None)
        return {**theme, "smeter_style": self.smeter_style} if theme is not None else None

    def new_theme(self, source=None, *, name="New Theme"):
        """Give each new editor draft a name that can be saved immediately."""
        used_names = {item["name"].casefold()
                      for item in (*BUILTIN_THEMES.values(), *self.themes)}
        base = str(name).strip()[:32] or "New Theme"
        name, suffix = base, 2
        while name.casefold() in used_names:
            ending = f" {suffix}"
            name = base[:32 - len(ending)] + ending
            suffix += 1
        draft = new_theme(name, source=source)
        if source is None:
            draft["smeter_style"] = self.smeter_style
        return draft

    def load(self):
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("version") != 1:
                return
            themes = []
            for raw in document.get("themes", []):
                try:
                    normalized = normalize_theme(raw)
                except (ValueError, TypeError):
                    continue
                if normalized["id"] not in {item["id"] for item in themes}:
                    themes.append(normalized)
            self.themes = themes
            active_id = str(document.get("active_id") or DEFAULT_THEME_ID)
            active_id = REMOVED_THEME_MIGRATIONS.get(active_id, active_id)
            self.active_id = active_id if self.get(active_id) else DEFAULT_THEME_ID
            legacy_active = next((theme for theme in themes if theme["id"] == self.active_id), {})
            self.smeter_style = normalize_meter_style(document.get("smeter_style", legacy_active.get("smeter_style")))
            self.themes = [theme_appearance(theme) for theme in themes]
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        apply_theme(self.get(self.active_id))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        document = {"version": 1, "active_id": self.active_id,
                    "smeter_style": self.smeter_style, "themes": self.themes}
        temporary.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def _commit(self, themes, active_id, *, smeter_style=None):
        previous_themes, previous_id, previous_meter = self.themes, self.active_id, self.smeter_style
        self.themes, self.active_id = themes, active_id
        if smeter_style is not None:
            self.smeter_style = normalize_meter_style(smeter_style)
        try:
            self.save()
        except OSError:
            self.themes, self.active_id, self.smeter_style = previous_themes, previous_id, previous_meter
            raise
        apply_theme(self.get(active_id))

    def activate(self, identifier, *, smeter_style=None):
        theme = self.get(identifier)
        if theme is None:
            raise ValueError("unknown theme")
        self._commit(self.themes, identifier, smeter_style=smeter_style)

    def set_smeter_style(self, identifier):
        self._commit(self.themes, self.active_id, smeter_style=identifier)

    def upsert(self, theme, *, smeter_style=None):
        normalized = theme_appearance(normalize_theme(theme))
        if normalized["name"].casefold() in {
            item["name"].casefold() for item in BUILTIN_THEMES.values()
        }:
            raise ValueError("a theme with that name already exists")
        if any(item["name"].casefold() == normalized["name"].casefold()
               and item["id"] != normalized["id"] for item in self.themes):
            raise ValueError("a theme with that name already exists")
        themes = [item for item in self.themes if item["id"] != normalized["id"]]
        themes.append(normalized)
        self._commit(themes, normalized["id"], smeter_style=smeter_style)

    def delete(self, identifier):
        if is_builtin_theme_id(identifier):
            raise ValueError("Built-in themes cannot be deleted")
        themes = [item for item in self.themes if item["id"] != identifier]
        active_id = DEFAULT_THEME_ID if self.active_id == identifier else self.active_id
        self._commit(themes, active_id)
