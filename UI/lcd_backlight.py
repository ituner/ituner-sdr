"""Brightness control for the V4 kernel PWM backlight, without GPIO bit-banging."""
import math
from pathlib import Path


MIN_BRIGHTNESS = 5
MAX_BRIGHTNESS = 100


def clamp_brightness(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite brightness")
        return max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, round(number)))
    except (TypeError, ValueError, OverflowError):
        return MAX_BRIGHTNESS


class LCDBacklight:
    def __init__(self, path="/sys/class/backlight/backlight-v4"):
        self.path = Path(path)
        self.percent = MAX_BRIGHTNESS
        self.available = False
        self.error = ""
        self._maximum = 0
        try:
            self._maximum = int((self.path / "max_brightness").read_text())
            # The old gpio-backlight driver has only 0/1, not PWM dimming.
            if self._maximum < MAX_BRIGHTNESS:
                raise ValueError("PWM brightness is unavailable")
            raw = int((self.path / "brightness").read_text())
            self.percent = clamp_brightness(100 * raw / self._maximum)
            self.available = True
        except (OSError, ValueError) as exc:
            self.error = str(exc)

    def set_percent(self, value, *, force=False):
        value = clamp_brightness(value)
        if not self.available:
            return False
        if value == self.percent and not force:
            return True
        try:
            raw = round(value * self._maximum / 100)
            (self.path / "brightness").write_text(str(raw) + "\n")
        except OSError as exc:
            self.error = str(exc)
            self.available = False
            print(f"LCD brightness unavailable: {exc}", flush=True)
            return False
        self.percent = value
        self.error = ""
        return True
