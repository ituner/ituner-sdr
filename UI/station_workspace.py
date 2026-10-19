"""Touch-first shared Radio / User Information, with a local keyboard."""
import time
from station_profile import FIELDS

PAGES=(('identity','Identity'),('location','Location'),('gps','GPS & movement'))
IDENTITY=(('station_name','Radio / station name'),('operator_name','Operator name · optional'),('callsign','Callsign · optional'),('site_label','Site / QTH label'),('timezone','Timezone · IANA name'),('local_kiwi_url','Local KiwiSDR URL'))
LOCATION=(('latitude','Latitude · decimal degrees'),('longitude','Longitude · decimal degrees'),('elevation_m','Site elevation · m above sea level'),('antenna_height_m','Antenna height · m above ground'),('ellipsoid_height_m','Antenna WGS84 ellipsoid height · m'),('gps_height_offset_m','RF antenna height above GPS antenna · m'))
NUMERIC={k for k,_ in LOCATION}


class StationWorkspace:
    BG=(8,16,25,255);PANEL=(16,33,48,255);TEXT=(222,239,251);MUTED=(151,179,199);CYAN=(117,229,208)
    def __init__(self,ui,station):
        self.ui=ui;self.station=station;self.open=False;self.page='identity';self.draft={};self.field=None;self.caps=False;self.value='';self.message='';self.actions=[];self.dirty=False
    def show(self):
        self.draft=dict(self.station.snapshot()['config']);self.open=True;self.field=None;self.message='';self.dirty=False
    def ink(self,cache,x,y,text,size=20,color=None,anchor='lm',width=None):
        text=str(text)
        if width:text=self.ui.fit_station_text(cache,text,width,size,size>=20,False,'Liberation Sans')
        self.ui.draw_text(cache,x,y,text,color or self.TEXT,size,size>=20,False,anchor,family='Liberation Sans')
    def button(self,cache,box,label,action,active=False):
        self.ui.draw_logical_rounded_rect(*box,8,(29,74,68,255) if active else self.PANEL,(*self.CYAN,255) if active else (48,76,98,255),1)
        self.ink(cache,(box[0]+box[2])/2,(box[1]+box[3])/2,label,21,self.CYAN if active else self.TEXT,'cm',box[2]-box[0]-24)
        self.actions.append((box,action))
    def drag_begin(self,*args):pass
    def drag_move(self,*args):pass
    def swipe(self,*args):return False
    def key(self,value):
        if self.field is None:return
        if value=='SHIFT':self.caps=not self.caps
        elif value=='DELETE':self.value=self.value[:-1]
        elif value=='CLEAR':self.value=''
        elif value=='CANCEL':self.field=None
        elif value=='DONE':
            try:
                candidate=float(self.value) if self.field in NUMERIC and self.value.strip() else None if self.field in NUMERIC else self.value
                from station_profile import validate
                validate({self.field:candidate},self.draft) if self.field not in ('latitude','longitude') else None
                self.draft[self.field]=candidate;self.dirty=True;self.field=None;self.message='Press Save to apply to all local applications.'
            except ValueError as exc:self.message=str(exc)
        elif len(self.value)<(200 if self.field=='local_kiwi_url' else 120):self.value+=value
    def tap(self,x,y):
        for box,(kind,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if kind=='back':self.open=False
            elif kind=='page':self.page=value;self.message=''
            elif kind=='edit':self.field=value;self.value='' if self.draft[value] is None else str(self.draft[value]);self.message=''
            elif kind=='key':self.key(value)
            elif kind=='toggle':self.draft[value]=not self.draft[value];self.dirty=True
            elif kind=='save':
                try:self.station.update(self.draft);self.dirty=False;self.message='Saved · all local applications updated.'
                except (ValueError,OSError) as exc:self.message=str(exc)
            return
    def keyboard(self,cache):
        ui=self.ui;ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.ink(cache,24,34,dict(IDENTITY+LOCATION).get(self.field,self.field),26)
        value=self.value or ('Unknown / blank' if self.field in NUMERIC else 'Blank')
        ui.draw_logical_rounded_rect(24,78,1256,150,8,self.PANEL,(80,139,157,255),1)
        self.ink(cache,42,113,value[-90:],25,width=1180)
        rows=['1234567890','QWERTYUIOP','ASDFGHJKL','ZXCVBNM./-']
        for r,row in enumerate(rows):
            if not self.caps:row=row.lower()
            width=104;offset=(1280-len(row)*114+10)/2
            for col,key in enumerate(row):self.button(cache,(offset+col*114,190+r*88,offset+col*114+width,264+r*88),key,('key',key))
        for box,label,key in (((24,560,172,630),'Space',' '),((184,560,324,630),'Shift','SHIFT'),((336,560,426,630),':',':'),((438,560,598,630),'Delete','DELETE'),((610,560,750,630),'Clear','CLEAR'),((762,560,942,630),'Cancel','CANCEL'),((954,560,1256,630),'Done','DONE')):
            self.button(cache,box,label,('key',key),key=='DONE')
        self.ink(cache,24,690,self.message or 'Blank numeric fields mean unknown. GPS may supply the antenna position.',18,self.MUTED,width=1230)
    def draw(self,cache):
        self.actions=[]
        if self.field is not None:self.keyboard(cache);return
        ui=self.ui;data=self.station.snapshot();p=data['position'];g=data['gps']
        if not self.dirty:self.draft=dict(data['config'])
        ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.ink(cache,24,32,'RADIO / USER INFORMATION',27)
        source=('GPS · LAST KNOWN / STALE' if p and p['source']=='gps' and p['stale'] else 'GPS · AUTOMATIC' if p and p['source']=='gps' else 'MANUAL')
        self.ink(cache,24,67,(f"{p['lat']:.6f}°, {p['lon']:.6f}° · {data['grid']} · {source}" if p else 'Location not set · enter coordinates or connect GPS'),18,self.CYAN,width=994)
        self.button(cache,(1050,16,1256,80),'Back to Settings',('back',None))
        for i,(key,title) in enumerate(PAGES):self.button(cache,(24+i*312,100,320+i*312,158),title,('page',key),self.page==key)
        if self.page in ('identity','location'):
            fields=IDENTITY if self.page=='identity' else LOCATION
            for i,(key,label) in enumerate(fields):
                y=181+i*75;value=self.draft.get(key);display='Unknown' if key in NUMERIC and value is None else 'Optional · not set' if not value and key not in NUMERIC else str(value)
                self.ink(cache,32,y+30,label,20,self.MUTED,width=480)
                self.button(cache,(516,y,1256,y+61),display,('edit',key))
            if self.page=='location':self.ink(cache,32,642,'WGS84 ellipsoid height differs from sea-level elevation. Leave unknown values blank.',17,self.MUTED,width=1210)
        else:
            for box,label,key in (((24,184,626,248),'GPS receiver monitoring','gps_enabled'),((646,184,1256,248),'Automatic GPS location updates','gps_auto')):
                self.button(cache,box,label+(' · ON' if self.draft[key] else ' · OFF'),('toggle',key),self.draft[key])
            self.ink(cache,32,290,g['status'],24,self.CYAN,width=1210)
            age=f"{g['fix_age_s']:.0f} seconds ago" if g['fix_age_s'] is not None else 'No fix yet'
            for y,label,value in ((338,'Last fix',age),(394,'Fix / accuracy',(f"{g['mode']}D / " if g['mode']>=2 else "No fix / ")+(f"±{g['accuracy_m']:.1f} m" if g['accuracy_m'] is not None else 'unknown')),(450,'Satellites used / visible',f"{g['used'] if g['used'] is not None else '—'} / {g['satellites'] if g['satellites'] is not None else '—'}"),(506,'GPS device',', '.join(d['path'] for d in g['devices']) or 'No USB GPS receiver detected')):
                self.ink(cache,32,y,label,20,self.MUTED);self.ink(cache,516,y,value,20,width=730)
            self.ink(cache,32,573,'Connect a gpsd-compatible USB GNSS receiver. No fix keeps the saved location.',18,self.MUTED,width=1210)
        self.ink(cache,24,669,self.message or 'Shared across local SDRs, decoder maps, satellite predictions and weather.',18,self.CYAN if self.message else self.MUTED,width=1220)
        self.button(cache,(820,707,1256,775),'Save radio information',('save',None),True)
        self.ink(cache,24,738,'Callsign optional · no reporting or transmitting is enabled.',17,self.MUTED,width=770)
