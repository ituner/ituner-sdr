"""SSTV touch workspace for the existing 1280 × 800 logical display."""
from collections import OrderedDict
import math
import socket
from sstv_monitor import PRESETS


class SSTVWorkspace:
    def __init__(self, ui, manager):
        self.ui, self.manager = ui, manager
        self.open = False
        self.add_open = False
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

    def image(self, key, box):
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
                while len(self.textures) > 12:
                    _, old = self.textures.popitem(last=False)
                    ui.GL.glDeleteTextures([old[1]])
            self.textures.move_to_end(key)
            _, tex, width, height = cached
            x0, y0, x1, y1 = box
            scale = min((x1-x0)/width, (y1-y0)/height)
            w, h = width*scale, height*scale
            x, y = (x0+x1-w)/2, (y0+y1-h)/2
            ui.draw_textured_quad(tex, x, y, x+w, y+h, 0, 0, 1, 1)
        except (OSError, ValueError, ui.pygame.error):
            pass  # An image may be pruned between snapshot and paint.

    def draw(self, cache, receivers):
        self.actions = []
        ui = self.ui
        ui.draw_logical_rect(0, 0, 1280, 800, (7, 18, 25, 255))
        if self.add_open:
            self.draw_add(cache, receivers)
            return
        if self.enlarged:
            item = next((row for row in self.manager.gallery.snapshot() if row['id'] == self.enlarged), None)
            if item:
                self.text(cache, 24, 34, f"{item['mode']} · {item['band']} · {item['freq_khz']/1000:.3f} MHz", 25)
                self.text(cache, 24, 66, f"{item['receiver']} · {item['capture_utc']} · {item['kind']}", 17, width=990)
                self.image(item['id'], (20, 90, 1260, 778))
                self.button(cache, (1060, 16, 1258, 76), 'BACK', ('back_image', None))
                return
            self.enlarged = None
        self.text(cache, 24, 36, 'SSTV', 32, (104, 234, 194))
        self.text(cache, 142, 36, 'Continuous image decoders', 23)
        self.button(cache, (822, 12, 1088, 72), '+ ADD DECODER', ('add', None))
        self.button(cache, (1104, 12, 1258, 72), 'HOME', ('home', None))
        self.text(cache, 24, 103, 'RECEIVERS', 16, (134, 165, 174))
        rows = self.manager.snapshot()
        if not rows:
            self.text(cache, 24, 150, 'No decoders yet', 23)
            self.text(cache, 24, 185, 'Choose Add decoder', 19)
            self.text(cache, 24, 215, 'to select a receiver', 19)
            self.text(cache, 24, 245, 'and SSTV frequency.', 19)
        for index, row in enumerate(rows):
            y = 124 + index*91
            ui.draw_logical_rect(16, y, 326, y+83, (25, 66, 57, 255) if row['id'] == self.filter_id else (17, 40, 47, 255))
            self.text(cache, 26, y+18, f"{row['band']} · {row['freq_khz']/1000:.3f} {row['mode'].upper()}", 17, width=290)
            self.text(cache, 26, y+41, row['name'], 15, width=162)
            self.text(cache, 26, y+65, row['status'], 14, (104, 234, 194), width=157)
            self.actions.append(((16, y, 186, y+83), ('filter', row['id'])))
            running = row['status'] not in ('STOPPED', 'NO AUDIO', 'DEPENDENCY MISSING', 'QUEUED')
            self.button(cache, (188, y+28, 270, y+80), 'STOP' if running else 'START', ('toggle', row['id']))
            self.button(cache, (274, y+28, 324, y+80), 'X', ('delete', row['id']))
        images = self.manager.gallery.snapshot(self.filter_id)
        self.page = min(self.page, max(0, math.ceil(len(images)/4)-1))
        label = 'ALL IMAGES' if not self.filter_id else 'SELECTED RECEIVER'
        self.button(cache, (354, 88, 674, 140), label, ('filter', None), active=self.filter_id is None)
        self.text(cache, 700, 114, f'{len(images)} saved · tap image to enlarge', 17)
        if not images:
            self.text(cache, 410, 350, 'Waiting for an SSTV transmission', 28)
            self.text(cache, 410, 394, 'Images appear here automatically.', 21)
            self.text(cache, 410, 428, 'Listening continues when you return Home.', 18)
        for index, item in enumerate(images[self.page*4:self.page*4+4]):
            x = 350 + (index % 2)*458
            y = 150 + (index // 2)*276
            box = (x, y, x+442, y+262)
            ui.draw_logical_rect(*box, (17, 34, 42, 255))
            self.image(item['id'], (x+6, y+6, x+436, y+203))
            self.text(cache, x+12, y+221, f"{item['mode']} · {item['band']} · {item['progress_pct']}%", 18, width=418)
            self.text(cache, x+12, y+246, item['capture_utc'].replace('T', ' ').replace('Z', ' UTC'), 15)
            self.actions.append((box, ('image', item['id'])))
        self.button(cache, (354, 715, 506, 769), '< PREV', ('page', -1))
        self.text(cache, 526, 743, f'{self.page+1} / {max(1, math.ceil(len(images)/4))}', 19)
        self.button(cache, (658, 715, 810, 769), 'NEXT >', ('page', 1))
        self.text(cache, 834, 734, 'Browser gallery', 17)
        self.text(cache, 834, 760, f"{socket.gethostname().split('.')[0]}.local:{self.manager.web_port}/sstv", 16, width=425)
        if self.delete_armed:
            ui.draw_logical_rect(8, 670, 338, 790, (49, 30, 28, 255))
            self.text(cache, 20, 691, 'Delete decoder? Images are kept.', 16)
            self.button(cache, (18, 710, 168, 776), 'DELETE', ('confirm_delete', self.delete_armed))
            self.button(cache, (180, 710, 328, 776), 'CANCEL', ('cancel_delete', None))
        else:
            notice = self.message or self.manager.web_error
            if not notice and self.filter_id:
                row = next((row for row in rows if row['id'] == self.filter_id), {})
                notice = row.get('detail') or row.get('last_decode')
            self.text(cache, 20, 700, notice or 'Tap a receiver to filter images.', 15, width=310)
            self.text(cache, 20, 740, 'Martin · Scottie · Robot', 15, width=310)
            self.text(cache, 20, 773, 'Latest 300 images kept', 14, (134, 165, 174))

    def draw_add(self, cache, receivers):
        self.text(cache, 30, 38, 'ADD SSTV DECODER', 29, (104, 234, 194))
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
        self.text(cache, 470, 673, '30 m narrowband modes unsupported. Kiwi: 0–30 MHz.', 17)
        self.button(cache, (30, 716, 242, 782), 'CANCEL', ('cancel_add', None))
        self.text(cache, 270, 750, self.message, 17, width=680)
        self.button(cache, (994, 716, 1250, 782), 'START DECODER', ('create', None), active=True)

    def tap(self, x, y, receivers):
        action = next((a for box, a in reversed(self.actions) if self.ui.contains(box, x, y)), None)
        if action is None:
            return
        kind, value = action
        self.message = ''
        try:
            if kind == 'home': self.open = False
            elif kind == 'add': self.add_open = True
            elif kind == 'cancel_add': self.add_open = False
            elif kind == 'receiver': self.selected_server = value
            elif kind == 'rxpage': self.receiver_page = max(0, self.receiver_page+value)
            elif kind == 'preset': self.preset = value
            elif kind == 'create':
                station = next(row for row in receivers if self.ui.station_fields(row)[2] == self.selected_server)
                name, _, server, _, _ = self.ui.station_fields(station)
                self.manager.add(name, server, self.preset)
                self.add_open = False
                self.filter_id = None
            elif kind == 'toggle': self.manager.toggle(value)
            elif kind == 'delete': self.delete_armed = value
            elif kind == 'cancel_delete': self.delete_armed = None
            elif kind == 'confirm_delete':
                self.manager.delete(value)
                self.delete_armed = None
                if self.filter_id == value: self.filter_id = None
            elif kind == 'filter': self.filter_id, self.page = value, 0
            elif kind == 'image': self.enlarged = value
            elif kind == 'back_image': self.enlarged = None
            elif kind == 'page': self.page = max(0, self.page+value)
        except (ValueError, OSError, StopIteration) as exc:
            self.message = str(exc) or 'Please select a receiver'

    def close(self):
        for _, tex, _, _ in self.textures.values():
            self.ui.GL.glDeleteTextures([tex])
        self.textures.clear()
