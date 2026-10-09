"""SSTV touch workspace for the existing 1280 × 800 logical display."""
from collections import OrderedDict
import math
import socket
from sstv_monitor import PRESETS
from sstv_modes import MODE_COUNT


GALLERY_COLUMNS = 5
GALLERY_ROWS = 3
GALLERY_PAGE_SIZE = GALLERY_COLUMNS * GALLERY_ROWS


class SSTVWorkspace:
    def __init__(self, ui, manager):
        self.ui, self.manager = ui, manager
        self.open = False
        self.add_open = False
        self.edit_id = None
        self.decoders_open = False
        self.receiver_page = 0
        self.selected_server = ''
        self.preset = PRESETS[4]
        self.current = None
        self.page = 0
        self.filter_id = None
        self.enlarged = None
        self.delete_armed = None
        self.message = ''
        self.actions = []
        self.textures = OrderedDict()

    def show(self, server, frequency, mode):
        self.open = True
        self.decoders_open = False
        self.delete_armed = None
        self.current = ('Current dial', frequency, mode.lower())
        self.selected_server = self.ui.LOCAL_KIWI_SERVER or server
        self.manager.ensure_web()

    def text(self, cache, x, y, value, size=18, color=(217, 233, 238), width=None):
        if width:
            value = self.ui.fit_station_text(cache, str(value), width, size, False, False, 'Liberation Sans')
        self.ui.draw_text(cache, x, y, str(value), color, size, False, False, 'lm', family='Liberation Sans')

    def button(self, cache, box, title, action, subtitle='', active=False):
        x0, y0, x1, y1 = box
        self.ui.draw_logical_rect(*box, (29, 80, 66, 255) if active else (21, 46, 56, 255))
        size = 16 if y1-y0 < 45 else 20
        title = self.ui.fit_station_text(cache, title, x1-x0-12, size, True, False, 'Liberation Sans')
        self.ui.draw_text(cache, (x0+x1)/2, (y0+y1)/2-(11 if subtitle else 0), title,
                          (222, 243, 240), size, True, False, 'cm', family='Liberation Sans')
        if subtitle:
            subtitle = self.ui.fit_station_text(cache, subtitle, x1-x0-12, 15, False, False, 'Liberation Sans')
            self.ui.draw_text(cache, (x0+x1)/2, (y0+y1)/2+16, subtitle,
                              (160, 197, 202), 15, False, False, 'cm', family='Liberation Sans')
        self.actions.append((box, action))

    def image(self, key, box, *, fill=False):
        ui = self.ui
        try:
            path = self.manager.gallery.image_path(key)
            stamp = path.stat().st_mtime_ns
            cached = self.textures.get(key)
            if not cached or cached[0] != stamp:
                if cached:
                    ui.GL.glDeleteTextures([cached[1]])
                surface = ui.pygame.image.load(str(path)).convert_alpha()
                width, height = surface.get_size()
                tex = ui.GL.glGenTextures(1)
                ui.GL.glBindTexture(ui.GL.GL_TEXTURE_2D, tex)
                for flag in (ui.GL.GL_TEXTURE_MIN_FILTER, ui.GL.GL_TEXTURE_MAG_FILTER):
                    ui.GL.glTexParameteri(ui.GL.GL_TEXTURE_2D, flag, ui.GL.GL_LINEAR)
                ui.GL.glTexImage2D(ui.GL.GL_TEXTURE_2D, 0, ui.GL.GL_RGBA, width, height, 0,
                                  ui.GL.GL_RGBA, ui.GL.GL_UNSIGNED_BYTE, ui.pygame.image.tostring(surface, 'RGBA', False))
                cached = stamp, tex, width, height
                self.textures[key] = cached
                while len(self.textures) > 2 * GALLERY_PAGE_SIZE + 1:
                    _, old = self.textures.popitem(last=False)
                    ui.GL.glDeleteTextures([old[1]])
            self.textures.move_to_end(key)
            _, tex, width, height = cached
            x0, y0, x1, y1 = box
            if fill:
                x, y, w, h = x0, y0, x1-x0, y1-y0
            else:
                scale = min((x1-x0)/width, (y1-y0)/height)
                w, h = width*scale, height*scale
                x, y = (x0+x1-w)/2, (y0+y1-h)/2
            ui.draw_textured_quad(tex, x, y, x+w, y+h, 0, 0, 1, 1)
        except (OSError, ValueError, ui.pygame.error):
            pass  # An image may be pruned between snapshot and paint.

    def preview(self, cache, item, box):
        x0, y0, x1, y1 = box
        live = item['kind'] in ('receiving', 'processing')
        if item.get('has_image', True):
            self.image(item['id'], box)
        else:
            self.ui.draw_logical_rect(*box, (10, 25, 32, 255))
            self.text(cache, x0+8, (y0+y1)/2-10, item['mode'], 17, width=x1-x0-16)
            self.text(cache, x0+8, (y0+y1)/2+13, 'Waiting for first lines…', 14, width=x1-x0-16)
        if live:
            label = 'Processing…' if item['kind'] == 'processing' else f"Receiving · {item['progress_pct']}%"
            self.ui.draw_logical_rect(x0, y0, x1, y0+25, (15, 67, 55, 255))
            self.text(cache, x0+6, y0+13, label, 15, (126, 255, 212), width=x1-x0-12)
            self.ui.draw_logical_rect(x0, y1-5, x1, y1, (31, 69, 72, 255))
            self.ui.draw_logical_rect(x0, y1-5, x0+(x1-x0)*item['progress_pct']/100, y1, (104, 234, 194, 255))

    def draw(self, cache, receivers):
        self.actions = []
        ui = self.ui
        ui.draw_logical_rect(0, 0, 1280, 800, (7, 18, 25, 255))
        if self.add_open:
            self.draw_add(cache, receivers)
            return
        if self.enlarged:
            item = next((row for row in self.manager.image_snapshot() if row['id'] == self.enlarged), None)
            if item:
                self.text(cache, 24, 34, f"{item['mode']} · {item['band']} · {item['freq_khz']/1000:.3f} MHz", 25)
                self.text(cache, 24, 66, f"{item['receiver']} · {item['capture_utc']} · {item['kind']}", 17, width=990)
                self.preview(cache, item, (20, 90, 1260, 778))
                self.button(cache, (1060, 16, 1258, 76), 'BACK', ('back_image', None))
                return
            self.enlarged = None
        self.text(cache, 20, 37, 'SSTV', 30, (104, 234, 194))
        self.text(cache, 138, 37, 'Decoders' if self.decoders_open else 'Image gallery', 24)
        self.button(cache, (654, 14, 842, 70), 'GALLERY' if self.decoders_open else 'DECODERS',
                    ('gallery' if self.decoders_open else 'decoders', None))
        self.button(cache, (854, 14, 1090, 70), '+ ADD DECODER', ('add', None))
        self.button(cache, (1102, 14, 1258, 70), 'HOME', ('home', None))
        if self.decoders_open:
            self.draw_decoders(cache)
            return
        images = self.manager.image_snapshot(self.filter_id)
        pages = max(1, math.ceil(len(images) / GALLERY_PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        self.text(cache, 330, 37, f'{len(images)} images · newest first', 16, width=305)
        if not images:
            self.text(cache, 330, 350, 'Waiting for an SSTV transmission', 28)
            self.text(cache, 330, 394, 'Images appear here automatically.', 21)
            self.text(cache, 330, 428, 'Listening continues when you return Home.', 18)
        offset = self.page * GALLERY_PAGE_SIZE
        for index, item in enumerate(images[offset:offset + GALLERY_PAGE_SIZE]):
            x = 16 + (index % GALLERY_COLUMNS) * 250
            y = 88 + (index // GALLERY_COLUMNS) * 210
            box = (x, y, x+242, y+202)
            ui.draw_logical_rect(*box, (17, 34, 42, 255))
            self.preview(cache, item, (x+4, y+4, x+238, y+164))
            self.text(cache, x+8, y+178, f"{item['mode']} · {item['band']} · {item['progress_pct']}%", 15, width=226)
            self.text(cache, x+8, y+194, item['capture_utc'].replace('T', ' ').replace('Z', ' UTC'), 13, width=226)
            self.actions.append((box, ('image', item['id'])))
        self.button(cache, (16, 730, 168, 786), '< PREV', ('page', -1))
        self.text(cache, 188, 758, f'{self.page+1} / {pages}', 19)
        self.button(cache, (282, 730, 434, 786), 'NEXT >', ('page', 1))
        self.button(cache, (450, 730, 690, 786), 'ALL IMAGES', ('filter', None), active=self.filter_id is None)
        notice = self.message or self.manager.web_error
        if notice:
            self.text(cache, 712, 758, notice, 16, width=546)
        else:
            self.text(cache, 712, 744, 'Tap an image to enlarge' if not self.filter_id else 'Showing selected decoder · tap All images to clear', 15, width=546)
            self.text(cache, 712, 772, f"Browser: {socket.gethostname().split('.')[0]}.local:{self.manager.web_port}/sstv", 15, width=546)

    def draw_decoders(self, cache):
        """Keep receiver operation on its own page, leaving gallery space for images."""
        ui = self.ui
        rows = self.manager.snapshot()
        images = self.manager.image_snapshot()
        if not rows:
            self.text(cache, 330, 340, 'No decoders yet', 28)
            self.text(cache, 330, 384, 'Choose Add decoder to select a receiver and frequency.', 21)
        for index, row in enumerate(rows):
            x = 16 + (index % 2) * 630
            y = 96 + (index // 2) * 202
            ui.draw_logical_rect(x, y, x+612, y+188, (17, 40, 47, 255))
            item = next((item for item in images if item['session_id'] == row['id']), None)
            width = 370 if item else 580
            self.text(cache, x+16, y+24, f"{row['band']} · {row['freq_khz']/1000:.3f} MHz {row['mode'].upper()}", 21, width=width)
            self.text(cache, x+16, y+54, row['name'], 18, width=width)
            self.text(cache, x+16, y+83, row['status'], 17, (104, 234, 194), width=width)
            self.text(cache, x+16, y+109, row.get('detail') or row.get('last_decode') or '', 15, width=width)
            if item:
                box = (x+412, y+8, x+596, y+118)
                self.preview(cache, item, box)
                self.actions.append((box, ('image', item['id'])))
            running = row.get('running', False)
            self.button(cache, (x+16, y+128, x+130, y+180), 'STOP' if running else 'START', ('toggle', row['id']))
            self.button(cache, (x+142, y+128, x+256, y+180), 'EDIT', ('edit', row['id']))
            self.button(cache, (x+268, y+128, x+424, y+180), 'IMAGES', ('filter', row['id']))
            self.button(cache, (x+436, y+128, x+596, y+180), 'DELETE', ('delete', row['id']))
        if self.delete_armed:
            ui.draw_logical_rect(16, 714, 1258, 792, (49, 30, 28, 255))
            self.text(cache, 32, 754, 'Delete decoder? Saved images are kept.', 20, width=690)
            self.button(cache, (814, 726, 1018, 782), 'DELETE', ('confirm_delete', self.delete_armed))
            self.button(cache, (1030, 726, 1242, 782), 'CANCEL', ('cancel_delete', None))
        else:
            self.text(cache, 24, 756, self.message or 'Decoders keep listening while you browse the gallery or return Home.', 18, width=1220)

    def draw_add(self, cache, receivers):
        self.text(cache, 30, 38, 'EDIT SSTV DECODER' if self.edit_id else 'ADD SSTV DECODER', 29, (104, 234, 194))
        self.text(cache, 30, 72, 'Choose receiver and frequency · one audio slot per decoder', 19)
        self.receiver_page = min(self.receiver_page, max(0, math.ceil(len(receivers)/3)-1))
        for index, station in enumerate(receivers[self.receiver_page*3:self.receiver_page*3+3]):
            name, location, server, used, total = self.ui.station_fields(station)
            y = 102+index*76
            self.button(cache, (30, y, 1250, y+64), name[:65], ('receiver', server),
                        (location or server)[:90], server == self.selected_server)
        self.button(cache, (30, 338, 212, 392), '< RECEIVERS', ('rxpage', -1))
        self.text(cache, 540, 365, f'{self.receiver_page+1} / {max(1, math.ceil(len(receivers)/3))}', 19)
        self.button(cache, (1058, 338, 1250, 392), 'RECEIVERS >', ('rxpage', 1))
        self.text(cache, 30, 425, 'ANALOG SSTV PRESETS · USB / LSB SELECTED AUTOMATICALLY', 18)
        for index, preset in enumerate(PRESETS):
            x, y = 30+(index%5)*246, 448+(index//5)*80
            self.button(cache, (x, y, x+232, y+68), preset[0], ('preset', preset),
                        f'{preset[1]/1000:.3f} MHz {preset[2].upper()}', preset == self.preset)
        if self.current and 0 < self.current[1] <= 30000 and self.current[2] in ('usb', 'lsb'):
            self.button(cache, (30, 618, 440, 678), 'USE CURRENT RADIO DIAL', ('preset', self.current),
                        f'{self.current[1]/1000:.3f} MHz {self.current[2].upper()}', self.preset == self.current)
        self.text(cache, 470, 644, 'Regional activity varies; presets are receive-only.', 18)
        self.text(cache, 470, 673, f'{MODE_COUNT} analog modes · automatic detection · Kiwi: 0–30 MHz.', 17)
        self.button(cache, (30, 716, 242, 782), 'CANCEL', ('cancel_add', None))
        self.text(cache, 270, 750, self.message, 17, width=680)
        self.button(cache, (994, 716, 1250, 782), 'SAVE CHANGES' if self.edit_id else 'START DECODER', ('create', None), active=True)

    def tap(self, x, y, receivers):
        action = next((a for box, a in reversed(self.actions) if self.ui.contains(box, x, y)), None)
        if action is None:
            return
        kind, value = action
        self.message = ''
        try:
            if kind == 'home': self.open = False
            elif kind == 'decoders': self.decoders_open = True
            elif kind == 'gallery':
                self.decoders_open = False
                self.delete_armed = None
            elif kind == 'edit':
                row = next(row for row in self.manager.configs if row['id'] == value)
                self.edit_id = value
                self.selected_server = row['server']
                self.preset = (row['band'], row['freq_khz'], row['mode'])
                self.receiver_page = next((i//3 for i, r in enumerate(receivers) if self.ui.station_fields(r)[2] == row['server']), 0)
                self.add_open = True
                self.delete_armed = None
            elif kind == 'add':
                self.edit_id = None
                self.add_open = True
                self.delete_armed = None
            elif kind == 'cancel_add': self.add_open = False
            elif kind == 'receiver': self.selected_server = value
            elif kind == 'rxpage': self.receiver_page = max(0, self.receiver_page+value)
            elif kind == 'preset': self.preset = value
            elif kind == 'create':
                station = next((row for row in receivers if self.ui.station_fields(row)[2] == self.selected_server), None)
                if station is not None:
                    name, _, server, _, _ = self.ui.station_fields(station)
                elif self.edit_id:
                    saved = next(row for row in self.manager.configs if row['id'] == self.edit_id and row['server'] == self.selected_server)
                    name, server = saved['name'], saved['server']
                else:
                    raise ValueError('Please select a receiver')
                if self.edit_id:
                    self.manager.update(self.edit_id, name, server, self.preset)
                else:
                    self.manager.add(name, server, self.preset)
                self.add_open = False
                self.filter_id = None
                self.decoders_open = True
                self.edit_id = None
                self.page = 0
            elif kind == 'toggle': self.manager.toggle(value)
            elif kind == 'delete': self.delete_armed = value
            elif kind == 'cancel_delete': self.delete_armed = None
            elif kind == 'confirm_delete':
                self.manager.delete(value)
                self.delete_armed = None
                if self.filter_id == value: self.filter_id = None
            elif kind == 'filter':
                self.filter_id, self.page = value, 0
                self.decoders_open = False
                self.delete_armed = None
            elif kind == 'image': self.enlarged = value
            elif kind == 'back_image': self.enlarged = None
            elif kind == 'page': self.page = max(0, self.page+value)
        except (ValueError, OSError, StopIteration) as exc:
            self.message = str(exc) or 'Please select a receiver'

    def close(self):
        for _, tex, _, _ in self.textures.values():
            self.ui.GL.glDeleteTextures([tex])
        self.textures.clear()
