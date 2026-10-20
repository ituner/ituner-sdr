"""Shared touch-action grid for native ADS-B and Airspace screens."""

ACTION_WIDTH = 236
ACTION_HEIGHT = 56
ACTION_GAP = 16
ACTION_ROW_Y = 632


def action_box(index, y=ACTION_ROW_Y, x=24):
    """Match HOME's rail button width, with stable action columns."""
    left = x + index * (ACTION_WIDTH + ACTION_GAP)
    return left, y, left + ACTION_WIDTH, y + ACTION_HEIGHT


SCAN_USB_BOX = action_box(0)
PREVIOUS_BOX = action_box(2)
NEXT_BOX = action_box(3)
