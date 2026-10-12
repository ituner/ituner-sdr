"""Shared visual tokens and button-state classes for the OpenGL UI.

This module contains no rendering code.  Every screen can consume the same
semantic colors and state resolver without coupling the design system to
OpenGL, pygame, or a particular panel layout.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UIPalette:
    background: tuple = (18, 18, 18, 255)
    sidebar: tuple = (26, 26, 26, 255)
    surface: tuple = (0, 0, 0, 255)
    active_surface: tuple = (42, 42, 42, 255)
    active_border: tuple = (160, 160, 160, 255)
    selected_surface: tuple = (30, 30, 30, 255)
    border: tuple = (88, 88, 88, 255)
    text: tuple = (255, 255, 255)
    secondary_text: tuple = (160, 160, 160)
    section_heading: tuple = (174, 203, 208)
    section_surface: tuple = (11, 20, 27, 255)
    section_border: tuple = (112, 136, 146, 255)
    passband_fill: tuple = (255, 190, 64, 42)
    passband_border: tuple = (255, 196, 86, 136)
    passband_center: tuple = (255, 192, 68, 222)
    focus: tuple = (0, 229, 255, 255)
    focus_text: tuple = (18, 18, 18)
    ready: tuple = (0, 230, 118, 255)
    waiting: tuple = (255, 179, 0, 255)
    untested: tuple = (33, 33, 33, 255)
    untested_text: tuple = (117, 117, 117)
    danger: tuple = (102, 31, 39, 255)
    danger_border: tuple = (252, 103, 111, 255)


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

    def resolve(self, *, active=False, pressed=False, danger=False) -> ButtonVisualState:
        if pressed:
            return ButtonVisualState(
                self.palette.active_surface, self.palette.active_border,
                self.palette.text, 2,
            )
        if active:
            return ButtonVisualState(
                self.palette.active_surface, self.palette.active_border,
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
