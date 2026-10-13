"""Shared visual tokens and button-state classes for the OpenGL UI.

This module contains no rendering code.  Every screen can consume the same
semantic colors and state resolver without coupling the design system to
OpenGL, pygame, or a particular panel layout.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UIPalette:
    background: tuple = (18, 18, 18, 255)
    sidebar: tuple = (0, 0, 0, 255)
    surface: tuple = (0, 0, 0, 255)
    active_surface: tuple = (42, 42, 42, 255)
    active_border: tuple = (160, 160, 160, 255)
    selected_surface: tuple = (30, 30, 30, 255)
    selected_border: tuple = (160, 160, 160, 255)
    pressed_surface: tuple = (42, 42, 42, 255)
    pressed_border: tuple = (160, 160, 160, 255)
    border: tuple = (88, 88, 88, 255)
    text: tuple = (255, 255, 255)
    secondary_text: tuple = (160, 160, 160)
    section_heading: tuple = (174, 203, 208)
    section_surface: tuple = (11, 20, 27, 255)
    section_border: tuple = (112, 136, 146, 255)
    top_instrument_band: tuple = (0, 0, 0, 144)
    sidebar_title: tuple = (215, 235, 239)
    sidebar_rule: tuple = (72, 101, 112, 160)
    passband_fill: tuple = (255, 190, 64, 42)
    passband_border: tuple = (255, 196, 86, 136)
    passband_center: tuple = (255, 192, 68, 222)
    home_passband_fill: tuple = (42, 154, 176, 88)
    home_passband_border: tuple = (113, 234, 240, 238)
    home_passband_center: tuple = (238, 202, 96, 232)
    focus: tuple = (0, 229, 255, 255)
    focus_text: tuple = (18, 18, 18)
    ready: tuple = (0, 230, 118, 255)
    waiting: tuple = (255, 179, 0, 255)
    untested: tuple = (33, 33, 33, 255)
    untested_text: tuple = (117, 117, 117)
    danger: tuple = (102, 31, 39, 255)
    danger_border: tuple = (252, 103, 111, 255)
    frequency: tuple = (115, 255, 177)
    meter_on: tuple = (92, 221, 231, 238)
    meter_hot: tuple = (244, 104, 90, 238)
    meter_off: tuple = (31, 52, 61, 208)
    notice: tuple = (72, 255, 122)
    slider_track: tuple = (27, 45, 52, 255)
    slider_fill: tuple = (80, 226, 164, 235)
    slider_thumb: tuple = (229, 246, 246, 250)
    slider_marker: tuple = (112, 238, 177, 190)
    footer_background: tuple = (4, 8, 12, 208)
    footer_primary: tuple = (162, 175, 179)
    footer_live: tuple = (120, 255, 179)
    smeter_scale: tuple = (222, 255, 228)
    smeter_hot: tuple = (230, 20, 42, 255)
    smeter_rail: tuple = (27, 43, 51, 230)
    smeter_tick: tuple = (192, 211, 214, 220)
    smeter_minor: tuple = (160, 178, 182, 155)
    smeter_active: tuple = (0, 76, 245, 255)
    smeter_dbm: tuple = (189, 198, 201, 225)
    smeter_marker: tuple = (139, 234, 255, 255)
    smeter_peak: tuple = (182, 197, 200, 178)
    spectrum_field: tuple = (2, 7, 12, 236)
    spectrum_grid: tuple = (89, 139, 155, 48)
    spectrum_axis: tuple = (125, 169, 181, 118)
    spectrum_tick: tuple = (163, 203, 211, 172)
    spectrum_label: tuple = (180, 207, 211)
    spectrum_peak_fill: tuple = (145, 159, 168, 76)
    spectrum_peak_line: tuple = (174, 187, 194, 142)
    spectrum_fill: tuple = (161, 184, 196, 154)
    spectrum_line: tuple = (204, 219, 224, 208)
    waterfall_low: tuple = (0, 0, 0)
    waterfall_high: tuple = (255, 255, 255)
    waterfall_ruler_background: tuple = (10, 15, 21, 185)
    waterfall_ruler_minor: tuple = (157, 182, 192, 196)
    waterfall_ruler_major: tuple = (202, 218, 224, 220)
    waterfall_ruler_label: tuple = (160, 187, 197)


@dataclass(frozen=True)
class ButtonVisualState:
    fill: tuple
    border: tuple
    text: tuple
    border_width: int


@dataclass(frozen=True)
class ButtonStyle:
    palette: UIPalette
    radius: int = 8
    width: int = 114
    height: int = 64
    gap: int = 8
    label_size: int = 13
    font_family: tuple = ("Roboto", "Inter", "DejaVu Sans")

    @property
    def subtitle_color(self):
        return self.palette.secondary_text

    def resolve(self, *, active=False, pressed=False, selected=False, danger=False) -> ButtonVisualState:
        if pressed:
            return ButtonVisualState(
                self.palette.pressed_surface, self.palette.pressed_border,
                self.palette.text, 2,
            )
        if active:
            return ButtonVisualState(
                self.palette.active_surface, self.palette.active_border,
                self.palette.text, 2,
            )
        if selected:
            return ButtonVisualState(
                self.palette.selected_surface, self.palette.selected_border,
                self.palette.text, 2,
            )
        if danger:
            return ButtonVisualState(
                self.palette.danger, self.palette.danger_border,
                self.palette.text, 2,
            )
        return ButtonVisualState(
            self.palette.surface, self.palette.border,
            self.palette.text, 1,
        )


@dataclass(frozen=True)
class AppUIStyle:
    palette: UIPalette = field(default_factory=UIPalette)
    button: ButtonStyle = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "button", ButtonStyle(self.palette))


APP_UI_STYLE = AppUIStyle()


def apply_ui_style(palette, *, radius=8):
    """Update the shared style object so existing importers see the new theme."""
    object.__setattr__(APP_UI_STYLE, "palette", palette)
    object.__setattr__(APP_UI_STYLE, "button", ButtonStyle(palette, radius=radius))
