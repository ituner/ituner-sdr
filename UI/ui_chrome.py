"""Shared HOME geometry and clock for native app screens."""
import time
from ui_style import APP_UI_STYLE

CANVAS_WIDTH = 1024
RAIL_BACK_BOX = (1034, 728, 1270, 792)
STATUS_TOP = 712
STATUS_FIRST_Y = 739
STATUS_CLOCK_Y = 771
STATUS_FONT_SIZE = 18
STATUS_FONT = 'Liberation Sans'


def draw_status_clock(ui, cache, x=18, y=STATUS_CLOCK_Y, alpha=1.0):
    source = getattr(ui, 'TIME_SOURCE_LABEL', 'UTC')
    if not isinstance(source, str):
        source = 'UTC'
    label = time.strftime('%H:%M:%S', time.gmtime()) + f' UTC ({source})'
    ui.draw_text(cache, x, y, label, APP_UI_STYLE.palette.footer_live,
                 STATUS_FONT_SIZE, False, False, 'lm', alpha, family=STATUS_FONT)
    return label
