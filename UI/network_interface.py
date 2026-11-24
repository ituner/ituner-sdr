"""Touch interface settings; all NetworkManager work stays on the bridge worker."""
class InterfaceSettings:
    def __init__(self, bridge):
        self.bridge = bridge
        self.open = False
        self.field = None
        self.draft = {}
        self.loading = False
        self.confirm = None
        self.mode = 'symbols'
        self.value = ''
        self.notice = ''

    def show(self, device):
        if not self.bridge.request('interface', {'device': device}):
            return
        self.open = True
        self.device = device
        self.draft = {}
        self.field = self.confirm = None
        self.loading = True
        self.notice = 'Reading interface settings…'

    def poll(self):
        snapshot, busy = self.bridge.snapshot()
        if self.loading and not busy:
            self.loading = False
            data = snapshot.get('interface', {})
            if snapshot.get('ok') and data.get('device') == self.device:
                self.draft = dict(data)
                self.notice = 'Changes apply only to this interface.'
            else:
                self.notice = snapshot.get('notice', 'Could not read interface settings.')
        elif getattr(self, 'pending', False) and not busy:
            self.pending = False
            self.notice = snapshot.get('notice', '')

    def boxes(self, ui):
        b = {'back': ui.network_panel_boxes()['back']}
        if self.confirm:
            b.update(confirm=(370, 380, 910, 444), cancel=(370, 460, 910, 524))
        elif self.draft:
            b.update(auto=(48, 130, 300, 194), manual=(316, 130, 568, 194),
                     addresses=(48, 216, 800, 280), gateway=(48, 292, 800, 356),
                     dns=(48, 368, 800, 432), on=(832, 216, 1232, 280),
                     off=(832, 292, 1232, 356), apply=(832, 368, 1232, 432))
            if self.device == 'eth0':
                b.update(autoneg=(48, 466, 420, 530), speed=(436, 466, 820, 530),
                         duplex=(836, 466, 1232, 530))
        return b

    def action_at(self, ui, x, y):
        if self.field:
            return ui.touch_keyboard_action_at(x, y, self.mode)
        return next((k for k, b in self.boxes(ui).items() if ui.contains(b, x, y)), None)

    def key(self, action, ui):
        if not action:
            return
        if self.field:
            if action == 'CANCEL': self.field = None
            elif action == 'SAVE': self.draft[self.field] = self.value.strip(); self.field = None
            elif action in ('BACK', 'DELETE'): self.value = self.value[:-1]
            elif action == 'CLEAR': self.value = ''
            elif action in ('MODE', 'CAPS'): self.mode = ui.touch_keyboard_next_mode(self.mode, action)
            elif len(self.value) < 128: self.value += ' ' if action == 'SPACE' else action
            return
        if self.bridge.snapshot()[1]:
            return
        if action == 'back':
            if self.confirm: self.confirm = None
            else: self.open = False
        elif action == 'cancel': self.confirm = None
        elif action in ('apply', 'off', 'on'): self.confirm = action
        elif action == 'confirm':
            if self.bridge.request('configure-interface', dict(self.draft, operation=self.confirm)):
                self.pending = True
                self.notice = 'Applying interface settings…'
                self.confirm = None
        elif action in ('auto', 'manual'): self.draft['method'] = action
        elif action in ('addresses', 'gateway', 'dns') and self.draft['method'] == 'manual':
            self.field = action
            self.value = self.draft.get(action, '')
            self.mode = 'symbols'
        elif action == 'autoneg':
            self.draft['autoneg'] = not self.draft['autoneg']
            if not self.draft['autoneg'] and not self.draft['speed']: self.draft['speed'] = 100
        elif action == 'speed':
            values = (0, 10, 100, 1000) if self.draft['autoneg'] else (10, 100, 1000)
            self.draft['speed'] = values[(values.index(self.draft['speed']) + 1) % len(values)]
        elif action == 'duplex': self.draft['duplex'] = 'half' if self.draft['duplex'] == 'full' else 'full'

    def draw(self, ui, cache):
        self.poll()
        title = 'Wi-Fi' if self.device == 'wlan0' else 'Ethernet'
        if self.field:
            detail = {'addresses': 'IPv4 address / prefix (192.168.1.20/24)', 'gateway': 'IPv4 gateway (optional)', 'dns': 'IPv4 DNS servers separated by commas'}[self.field]
            ui.draw_touch_keyboard(cache, title + ' settings', detail, self.value, self.mode, submit='Save')
            return
        p = ui.APP_UI_STYLE.palette
        ui.draw_logical_rect(0, 0, ui.LOGICAL_W, ui.LOGICAL_H, p.background)
        ui.draw_text(cache, 48, 70, title + ' settings', p.text, 30, True, False, 'lm')
        labels = {'back': 'BACK'}
        if self.confirm:
            ui.draw_text(cache, 48, 220, 'This may interrupt connections on ' + title + '.', p.text, 26, False, False, 'lm')
            ui.draw_text(cache, 48, 266, 'Confirm to ' + {'apply':'apply these settings', 'off':'turn this interface off', 'on':'turn this interface on'}[self.confirm] + '.', p.secondary_text, 22, False, False, 'lm')
            labels.update(confirm='Confirm', cancel='Cancel')
        elif self.draft:
            d = self.draft
            labels.update(auto='DHCP', manual='Static', addresses='Address: ' + (d['addresses'] or 'Not set'),
                          gateway='Gateway: ' + (d['gateway'] or 'Not set'), dns='DNS: ' + (d['dns'] or 'Automatic'),
                          on='Turn on', off='Turn off', apply='Apply', autoneg='Autonegotiation: ' + ('ON' if d['autoneg'] else 'OFF'),
                          speed='Speed: ' + (str(d['speed']) + ' Mbps' if d['speed'] else 'Automatic'), duplex='Duplex: ' + d['duplex'])
        for name, box in self.boxes(ui).items():
            ui.draw_network_button(cache, box, labels[name], 22, name == self.draft.get('method'))
        ui.draw_text(cache, 48, 600, ui.fit_station_text(cache, self.notice, 1160, 20, False, False), p.secondary_text, 20, False, False, 'lm')
