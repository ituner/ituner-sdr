"""Paged WSPR history and reporting settings for the 1280 x 800 touchscreen."""
from concurrent.futures import ThreadPoolExecutor
import time
from wspr_history import source_key, local_source


class WSPRHistoryView:
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

    def text(self, cache, x, y, value, size=18, color=(217,233,238), width=None):
        if width:
            value = self.ui.fit_station_text(cache,str(value),width,size,False,False,'Liberation Sans')
        self.ui.draw_text(cache,x,y,str(value),color,size,False,False,'lm',family='Liberation Sans')

    def button(self, cache, box, label, action, active=False):
        self.ui.draw_logical_rect(*box,(29,80,66,255) if active else (21,46,56,255))
        self.ui.draw_text(cache,(box[0]+box[2])/2,(box[1]+box[3])/2,label,(225,241,241),18,True,False,'cm',family='Liberation Sans')
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
        self.ui.draw_logical_rect(0,0,1280,800,(2,11,16,255))
        self.text(cache,24,30,'WSPR history',28)
        self.button(cache,(1102,10,1178,66),'BACK',('back',))
        self.button(cache,(1186,10,1262,66),'HOME',('home',))
        if self.settings is not None:
            self.draw_settings(cache)
            return
        name=next((r['name'] for r in self.sources if r['source']==self.source),self.source or 'All receivers')
        self.text(cache,24,65,f'{name} · '+(f'{self.band} m' if self.band else 'all bands'),18,width=1040)
        for n,(scope,label) in enumerate((('session','This session'),('today','Today UTC'),('24h','Last 24 hours'),('all','All history'))):
            self.button(cache,(24+n*178,92,192+n*178,140),label,('scope',scope),self.scope==scope)
        self.button(cache,(750,92,960,140),'Other receiver',('source',))
        self.button(cache,(980,92,1256,140),'WSPRnet uploads',('settings',))
        columns=(24,246,408,560,680,840,1030)
        for x,label in zip(columns,('UTC date / time','Callsign','Grid','SNR','MHz','Power dBm','Receiver')):
            self.text(cache,x,171,label,16,(112,181,184))
        for n,row in enumerate(self.page['spots']):
            y=207+n*40
            vals=(time.strftime('%Y-%m-%d %H:%M',time.gmtime(row['cycle_start'])),row.get('callsign','?'),row.get('grid',''),
                  row.get('snr_db',''),f"{row.get('frequency_mhz',0):.6f}",row.get('power_dbm',''),row.get('session_receiver',''))
            for i,(x,value) in enumerate(zip(columns,vals)):
                right=columns[i+1] if i+1<len(columns) else 1258
                self.text(cache,x,y,value,18,width=right-x-12)
        if not self.page['spots']:
            self.text(cache,24,255,'Importing saved logs…' if self.page.get('importing') else 'No spots in this view. Try All history.',22)
        self.button(cache,(24,720,174,773),'Previous',('page',-1))
        self.button(cache,(190,720,340,773),'Next',('page',1))
        self.text(cache,365,744,f"{self.page['total']} saved spots · page {self.offset//12+1}",18)
        self.text(cache,365,775,self.message or 'Stop / Start never clears history. CSV export and date range: web WSPR page.',15,width=880)

    def draw_settings(self,cache):
        p=self.settings
        self.text(cache,24,90,'WSPRnet reporting · '+p['name'],22,width=1220)
        self.text(cache,24,126,'Use the receiving antenna’s identity and grid, including for remote receivers.',18)
        for i,(key,label) in enumerate((('call','Reporter'),('grid','Receiver grid'))):
            self.button(cache,(24+i*430,155,434+i*430,214),label+': '+p[key],('field',key),self.field==key)
        self.button(cache,(24,235,850,289),('[YES] ' if p['confirmed'] else '[NO] ')+'I own / may report for this receiver; its location is correct',('confirm',))
        self.button(cache,(880,155,1256,214),'Uploads: '+('ON' if p['enabled'] else 'OFF'),('enabled',),p['enabled'])
        self.text(cache,24,317,'Only new spots are uploaded. History and uncertain uploads are not sent automatically.',17)
        for y,row in enumerate(('1234567890','QWERTYUIOP','ASDFGHJKL','ZXCVBNM/-')):
            for x,char in enumerate(row):
                self.button(cache,(24+x*92,350+y*65,108+x*92,407+y*65),char,('key',char))
        self.button(cache,(970,350,1256,410),'Delete character',('erase',))
        self.button(cache,(970,435,1256,495),'Save settings',('save',))
        self.button(cache,(970,520,1256,580),'Cancel',('cancel',))
        self.text(cache,24,660,self.message,19,width=1230)
        counts=', '.join(f'{k}: {v}' for k,v in p.get('uploads',{}).items()) or 'No spots submitted'
        self.text(cache,24,706,counts,18,width=1230)
        self.text(cache,24,754,p.get('last_error',''),16,width=1230)

    def page_by(self,direction):
        maximum=max(0,(self.page['total']-1)//12*12)
        self.offset=max(0,min(maximum,self.offset+12*direction));self.next_read=0

    def tap(self,x,y):
        action=next((a for box,a in self.actions if box[0]<=x<=box[2] and box[1]<=y<=box[3]),None)
        if not action:return
        key=action[0]
        if key=='home':self.settings=None;return 'home'
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
            if row:self.settings=dict(row);self.message=''
            else:self.message='Select one receiver first.'
        elif key=='cancel':self.settings=None;self.message=''
        elif self.settings is not None:
            p=self.settings
            if key=='field':self.field=action[1]
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
