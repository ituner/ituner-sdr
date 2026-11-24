"""Explicit, confirmed appliance power actions; no polling or desktop shutdown."""
from pathlib import Path
import queue
import subprocess
import threading

HELPER = '/usr/local/sbin/ituner-power'
ACTIONS = {'reboot': 'REBOOT', 'poweroff': 'SHUT DOWN'}


class PowerController:
    def __init__(self, helper=HELPER, runner=subprocess.run):
        self.helper = helper
        self.runner = runner
        self.available = Path(helper).is_file()
        self.open = False
        self.action = None
        self.busy = False
        self.message = ''
        self.results = queue.SimpleQueue()

    def select(self, action):
        if action not in ACTIONS or self.busy:
            return
        self.action = action
        self.message = ''
        self.open = True

    def cancel(self):
        if not self.busy:
            self.open = False
            self.action = None
            self.message = ''

    def confirm(self):
        if self.busy or self.action not in ACTIONS:
            return
        if not self.available:
            self.message = 'Power controls are not installed on this device.'
            return
        self.busy = True
        self.message = 'Restarting the device...' if self.action == 'reboot' else 'Shutting down the device...'
        threading.Thread(target=self._run, args=(self.action,), name='device-power', daemon=True).start()

    def _run(self, action):
        try:
            result = self.runner(['sudo', '-n', self.helper, action], capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or 'Power request was rejected.').strip()[:240])
        except Exception as exc:
            self.results.put(str(exc))

    def poll(self):
        try:
            self.message = self.results.get_nowait()
            self.busy = False
        except queue.Empty:
            pass


def boxes(ui):
    back = ui.lcd_drawer_back_box()
    return {'back': back, 'confirm': (32, 304, 368, 371)}


def action_at(controller, ui, x, y):
    if controller.busy:
        return None
    for name, box in boxes(ui).items():
        if ui.contains(box, x, y) and (name != 'confirm' or controller.available):
            return name
    return None


def draw(controller, ui, cache):
    controller.poll()
    p = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, ui.LOGICAL_W, ui.LOGICAL_H, p.surface)
    ui.draw_logical_rect(ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LOGICAL_H, p.sidebar)
    ui.draw_sidebar_header(cache, 'SYSTEM')
    if controller.action == 'reboot':
        prompt = ((160, 'Restart the device?', 30, p.text),
                  (216, 'It will start again automatically.', 22, p.secondary_text))
    else:
        prompt = ((160, 'Shut down the device?', 30, p.text),
                  (216, 'Use the power button', 22, p.secondary_text),
                  (254, 'to start it again.', 22, p.secondary_text))
    for y, text, size, color in prompt:
        ui.draw_text(cache, 32, y, text, color, size, False, False, 'lm', family=ui.APP_UI_STYLE.button.font_family)
    message = controller.message or ('' if controller.available else 'Power controls are not installed on this device.')
    if message:
        import textwrap
        for i, line in enumerate(textwrap.wrap(message, 68)[:4]):
            ui.draw_text(cache, 32, 464 + i * 28, line, p.text, 20, False, False, 'lm', family=ui.APP_UI_STYLE.button.font_family)
    b = boxes(ui)
    enabled = controller.available and not controller.busy
    visual = ui.draw_styled_button_frame(
        b['confirm'], danger=enabled,
        pressed=enabled and ui.ui_button_pressed(b['confirm']))
    caption = 'PLEASE WAIT' if controller.busy else 'CONFIRM ' + ACTIONS.get(controller.action, 'POWER')
    ui.draw_text(cache, (b['confirm'][0] + b['confirm'][2]) / 2,
                 (b['confirm'][1] + b['confirm'][3]) / 2, caption,
                 visual.text if enabled else p.untested_text, 19, True, False, 'cm',
                 family=ui.APP_UI_STYLE.button.font_family)
    ui.draw_styled_two_line_button(cache, b['back'], 'BACK', '', enabled=not controller.busy)
