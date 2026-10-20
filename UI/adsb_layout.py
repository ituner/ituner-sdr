"""Shared touch-action grid for native ADS-B and Airspace screens."""

ACTION_WIDTH = 236
ACTION_HEIGHT = 56
ACTION_GAP = 16
ACTION_ROW_Y = 632


def action_box(index, y=ACTION_ROW_Y, x=24):
    """Match HOME's rail button width, with stable action columns."""
    left = x + index * (ACTION_WIDTH + ACTION_GAP)
    return left, y, left + ACTION_WIDTH, y + ACTION_HEIGHT


# List panels end at x1008; keep a 16 px inner margin from their edge.
CONTENT_RIGHT = 992

def content_right_action(y=ACTION_ROW_Y, column=0):
    right = CONTENT_RIGHT - column * (ACTION_WIDTH + ACTION_GAP)
    return right - ACTION_WIDTH, y, right, y + ACTION_HEIGHT

SCAN_USB_BOX = action_box(0, x=32)
PREVIOUS_BOX = content_right_action(column=1)
NEXT_BOX = content_right_action()
