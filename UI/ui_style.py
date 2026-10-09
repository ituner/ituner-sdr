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
    surface: tuple = (38, 38, 38, 255)
    selected_surface: tuple = (30, 30, 30, 255)
    border: tuple = (88, 88, 88, 255)
    text: tuple = (255, 255, 255)
    secondary_text: tuple = (160, 160, 160)
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
    label_size: int = 14
    font_family: tuple = ("Roboto", "Inter", "DejaVu Sans")

    def resolve(self, *, active=False, pressed=False, danger=False) -> ButtonVisualState:
        if pressed or active:
            return ButtonVisualState(
                self.palette.focus, self.palette.focus,
                self.palette.focus_text, 2,
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
