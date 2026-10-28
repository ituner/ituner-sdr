"""Paged WSPR history and reporting settings for the 1280 x 800 touchscreen."""
from concurrent.futures import ThreadPoolExecutor
import time
from wspr_history import source_key, local_source
from ui_style import APP_UI_STYLE
from decoder_style import DecoderStyle, full_width_back_box


class WSPRHistoryView(DecoderStyle):
    def __init__(self, ui, history):
        self.ui, self.history = ui, history
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='wspr-history-view')
        self.future = None
        self.selected = None
        self.source = self.band = self.run = ''
        self.scope = '24h'
        self.offset = 0
        self.page = {'spots': [], 'total': 0}
        self.sources = []
        self.next_read = 0
        self.actions = []
        self.settings = None
        self.field = 'call'
        self.message = ''

    def select(self, tile, monitor):
        key = (source_key(tile['server']), str(tile['band']))
        if key != self.selected:
            self.selected = key
            self.source, self.band = key
            self.scope = '24h' if local_source(self.source) else 'session'
            self.offset = 0
            self.settings = None
            self.next_read = 0
        self.run = getattr(monitor, 'run_id', '') if self.source == key[0] else ''

    def text(self, cache, x, y, value, size=18, color=None, width=None):
        if width:
            value = self.ui.fit_station_text(cache,str(value),width,size,False,False,'Liberation Sans')
        self.ui.draw_text(cache,x,y,str(value),self.TEXT if color is None else color,size,False,False,'lm',family='Liberation Sans')

    def button(self, cache, box, label, action, active=False, subtitle=''):
        label = str(label).upper()
        subtitle = str(subtitle).upper()
        style = APP_UI_STYLE.button
        fit = getattr(self.ui, 'fit_station_text', None)
        if callable(fit):
            width = box[2]-box[0]-12
            label = fit(cache, label, width, style.label_size, True, False, style.font_family)
            if subtitle:
                subtitle = fit(cache, subtitle, width, style.label_size, True, False, style.font_family)
        draw_button = getattr(self.ui, 'draw_styled_two_line_button', None)
        if callable(draw_button):
            draw_button(cache, box, label, subtitle, active=active)
        else:
            visual = style.resolve(active=active)
            rounded = getattr(self.ui, 'draw_logical_rounded_rect', None)
            if callable(rounded):
                rounded(*box, style.radius, visual.fill, visual.border, visual.border_width)
            else:
                self.ui.draw_logical_rect(*box, visual.fill)
            self.ui.draw_text(cache, (box[0]+box[2])/2, (box[1]+box[3])/2-(10 if subtitle else 0),
                              label, visual.text, style.label_size, True, False,
                              'cm', family=style.font_family)
            if subtitle:
                self.ui.draw_text(cache, (box[0]+box[2])/2, (box[1]+box[3])/2+10,
                                  subtitle, style.palette.secondary_text, style.label_size,
                                  True, False, 'cm', family=style.font_family)
        self.actions.append((box,action))

    def query_key(self):
        return self.source,self.band,self.scope,self.run if self.scope=='session' else '',self.offset

    def refresh(self):
        if self.future and self.future.done():
            try:
                key,page,sources = self.future.result()
                if key == self.query_key():
                    self.page,self.sources=page,sources
                    self.message=page.get('error','')
            except Exception as exc:
                self.message=str(exc)
            self.future=None
        if not self.future and time.monotonic() >= self.next_read:
            key=self.query_key()
            def read():
                return key,self.history.query(source=key[0],band=key[1],scope=key[2],run=key[3],offset=key[4],limit=12),self.history.sources()
            self.future=self.pool.submit(read)
            self.next_read=time.monotonic()+5

    def draw(self, cache):
        self.refresh();self.actions=[]
        self.ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.text(cache,24,30,'WSPR history',28)
        self.button(cache,full_width_back_box(),'BACK',('back',))
        if self.settings is not None:
            self.draw_settings(cache)
            return
        name=next((r['name'] for r in self.sources if r['source']==self.source),self.source or 'All receivers')
        self.text(cache,24,65,f'{name} · '+(f'{self.band} m' if self.band else 'all bands'),18,width=1040)
        for n,(scope,label) in enumerate((('session','This session'),('today','Today UTC'),('24h','Last 24 hours'),('all','All history'))):
            x = 24+n*122
            self.button(cache,(x,92,x+114,156),label,('scope',scope),self.scope==scope)
        self.button(cache,(512,92,748,156),'Other receiver',('source',))
        self.button(cache,(756,92,992,156),'WSPRnet uploads',('settings',))
        columns=(24,246,408,560,680,840,1030)
        for x,label in zip(columns,('UTC date / time','Callsign','Grid','SNR','MHz','Power dBm','Receiver')):
            self.text(cache,x,171,label,16,self.MUTED)
        for n,row in enumerate(self.page['spots']):
            y=207+n*36
            vals=(time.strftime('%Y-%m-%d %H:%M',time.gmtime(row['cycle_start'])),row.get('callsign','?'),row.get('grid',''),
                  row.get('snr_db',''),f"{row.get('frequency_mhz',0):.6f}",row.get('power_dbm',''),row.get('session_receiver',''))
            for i,(x,value) in enumerate(zip(columns,vals)):
                right=columns[i+1] if i+1<len(columns) else 1258
                self.text(cache,x,y,value,18,width=right-x-12)
        if not self.page['spots']:
            self.text(cache,24,255,'Importing saved logs…' if self.page.get('importing') else 'No spots in this view. Try All history.',22)
        self.button(cache,(24,640,138,704),'Previous',('page',-1))
        self.button(cache,(146,640,260,704),'Next',('page',1))
        self.text(cache,280,672,f"{self.page['total']} saved spots · page {self.offset//12+1}",18,width=700)
        self.draw_status(cache,self.message or "Stop / Start never clears history.","CSV export and date range: web WSPR page.",full_width=True)

    def draw_settings(self,cache):
        p=self.settings
        if getattr(self,'field_keyboard',False):
            self.ui.draw_touch_keyboard(cache,'Reporter callsign' if self.field=='call' else 'Receiver grid',
                'WSPRNET REPORTING',self.field_entry,mode=getattr(self,'keyboard_mode','upper'),submit='Done',rail_title='WSPR')
            return
        self.text(cache,24,90,'WSPRnet reporting · '+p['name'],22,width=1220)
        self.text(cache,24,126,'Use the receiving antenna’s identity and grid, including for remote receivers.',18)
        for i,(key,label) in enumerate((('call','Reporter'),('grid','Receiver grid'))):
            x = 24+i*244
            self.button(cache,(x,155,x+236,219),label,('field',key),self.field==key,subtitle=p[key])
        self.button(cache,(24,235,260,299),'REPORTING PERMISSION',('confirm',),p['confirmed'],
                    subtitle='YES' if p['confirmed'] else 'NO')
        self.text(cache,276,267,'I own / may report for this receiver; its location is correct.',17,width=740)
        self.button(cache,(512,155,748,219),'WSPRNET UPLOADS',('enabled',),p['enabled'],
                    subtitle='ON' if p['enabled'] else 'OFF')
        self.text(cache,24,317,'Only new spots are uploaded. History and uncertain uploads are not sent automatically.',17)
        self.button(cache,(146,646,260,710),'SAVE',('save',))
        self.button(cache,(268,646,382,710),'CANCEL',('cancel',))
        if self.message:self.text(cache,24,356,self.message,17,self.color("waiting"),width=980)
        counts=', '.join(f'{k}: {v}' for k,v in p.get('uploads',{}).items()) or 'No spots submitted'
        self.text(cache,400,674,counts,17,width=620)
        self.text(cache,400,706,p.get('last_error',''),16,width=620)

    def page_by(self,direction):
        maximum=max(0,(self.page['total']-1)//12*12)
        self.offset=max(0,min(maximum,self.offset+12*direction));self.next_read=0

    def tap(self,x,y):
        if self.settings is not None and getattr(self,'field_keyboard',False):
            mode=getattr(self,'keyboard_mode','upper')
            action=self.ui.touch_keyboard_action_at(x,y,mode)
            if action in ('MODE','CAPS'):self.keyboard_mode=self.ui.touch_keyboard_next_mode(mode,action)
            elif action in ('SAVE','CANCEL'):
                if action=='SAVE':self.settings[self.field]=self.field_entry
                self.field_keyboard=False
            elif action=='BACK':self.field_entry=self.field_entry[:-1]
            elif action=='CLEAR':self.field_entry=''
            elif action:self.field_entry=(self.field_entry+(' ' if action=='SPACE' else action))[:16 if self.field=='call' else 6]
            return
        action=next((a for box,a in self.actions if box[0]<=x<=box[2] and box[1]<=y<=box[3]),None)
        if not action:return
        key=action[0]
        if key=='back':
            if self.settings is not None:self.settings=None;return
            return 'back'
        if key=='scope':self.scope=action[1];self.offset=0
        elif key=='page':self.page_by(action[1])
        elif key=='source':
            choices=['']+[r['source'] for r in self.sources]
            self.source=choices[(choices.index(self.source)+1)%len(choices)] if self.source in choices else ''
            self.band='';self.run='';self.offset=0
        elif key=='settings':
            row=next((r for r in self.sources if r['source']==self.source),None)
            if row:self.settings=dict(row);self.message='';self.field_keyboard=False
            else:self.message='Select one receiver first.'
        elif key=='cancel':self.settings=None;self.message=''
        elif self.settings is not None:
            p=self.settings
            if key=='field':self.field=action[1];self.field_entry=p[self.field];self.field_keyboard=True
            elif key=='enabled':p['enabled']=not p['enabled']
            elif key=='confirm':p['confirmed']=not p['confirmed']
            elif key=='key':p[self.field]=(p[self.field]+action[1])[:16 if self.field=='call' else 6]
            elif key=='erase':p[self.field]=p[self.field][:-1]
            elif key=='save':
                try:
                    self.history.configure(p['source'],p['call'],p['grid'],bool(p['enabled']),bool(p['confirmed']))
                    self.message='Settings saved';self.settings=None
                except ValueError as exc:self.message=str(exc)
        self.next_read=0

    def close(self):
        self.pool.shutdown(wait=True)
