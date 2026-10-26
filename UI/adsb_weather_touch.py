"""Native touch FIS-B reports, received radar grids and ground-station status."""
import datetime as dt
import math
import textwrap
import time
import numpy as np
from adsb_weather import RADAR_COLOURS
from adsb_coverage_gl import draw as draw_mesh


def age(value, now):
    if not isinstance(value, (int,float)): return 'never'
    seconds = max(0, int(now-value))
    return f'{seconds}s ago' if seconds<60 else f'{seconds//60}m ago' if seconds<3600 else f'{seconds//3600}h ago'


def rectangles(blocks):
    result = []
    for b in sorted(blocks, key=lambda b:-b['scale']):
        w,s,e,n = b['bounds']; dx,dy = (e-w)/32,(n-s)/4
        for y in range(4):
            x=0
            while x<32:
                start=x; level=b['bins'][y*32+x]
                while x<32 and b['bins'][y*32+x]==level:x+=1
                if 0<=level<8:result.append(((w+start*dx,n-(y+1)*dy,w+x*dx,n-y*dy),level))
    return result


class WeatherTouch:
    MAP=(0,88,1280,712)
    def __init__(self,parent):
        self.parent=parent;self.tab='reports';self.page=0;self.report=None;self.filter='All'
        self.yaw=math.radians(-121.8747);self.pitch=math.radians(37.6624);self.scale=8
        self.rectangles=[];self.data_key=None;self.frame=None;self.frame_key=None;self.drag_origin=None

    def action(self,kind,value):
        if kind=='weather_tab':self.tab=value;self.page=0;self.report=None
        elif kind=='weather_page':self.page=max(0,self.page+value)
        elif kind=='weather_report':self.report=value;self.page=0
        elif kind=='weather_close_report':self.report=None;self.page=0
        elif kind=='weather_filter':
            filters=('All','METAR','TAF','Advisories');self.filter=filters[(filters.index(self.filter)+1)%4];self.page=0
        elif kind=='weather_zoom':self.scale=max(.55,min(12000,self.scale*value))
        elif kind=='weather_center':
            site=self.parent.manager.snapshot().get('receiver_position')
            if site:self.yaw=math.radians(site['lon']);self.pitch=math.radians(site['lat']);self.scale=8

    def drag_begin(self,x,y):self.drag_origin=(self.yaw,self.pitch)
    def drag_move(self,sx,sy,x,y):
        if self.tab=='radar' and self.drag_origin:
            self.yaw,self.pitch=self.parent.ui.radiogarden_pan_angles(*self.drag_origin,x-sx,y-sy,self.MAP,self.scale)

    def draw_radar(self,cache,data):
        p=self.parent;ui=p.ui
        ui.draw_receiver_map_satellite(cache,self.yaw,self.pitch,self.MAP,self.scale,interactive=p.dragged)
        ui._globe_borders.draw(ui.globe_gpu_matrix(self.yaw,self.pitch,self.MAP,self.scale),(160,190,180,140))
        key=tuple((b['product'],b['block'],b['received_at']) for b in data['radar'])
        if key!=self.data_key:self.rectangles=rectangles(data['radar']);self.data_key=key;self.frame_key=None
        camera=(self.yaw,self.pitch,self.scale)
        if self.frame_key!=camera:
            verts=[];colours=[]
            for (w,s,e,n),level in self.rectangles:
                points=[ui.radiogarden_project(dict(lon=lon,lat=lat),self.yaw,self.pitch,self.MAP,self.scale) for lon,lat in ((w,s),(e,s),(e,n),(w,n))]
                if any(q is None for q in points):continue
                if all(q[0]<0 for q in points) or all(q[0]>1280 for q in points) or all(q[1]<88 for q in points) or all(q[1]>712 for q in points):continue
                colour=(90/255,165/255,210/255,.055) if level==0 else tuple(int(RADAR_COLOURS[level][i:i+2],16)/255 for i in (1,3,5))+(.72,)
                verts.extend(points[i][:2] for i in (0,1,2,0,2,3));colours.extend([colour]*6)
            self.frame=dict(batches=[('triangles',np.asarray(verts,dtype=np.float32).reshape(-1,2),np.asarray(colours,dtype=np.float32).reshape(-1,4))],native=None)
            self.frame_key=camera
        if self.frame['batches'][0][1].size:draw_mesh(ui,self.frame,(0,0,1280,800))
        p.surface((24,106,510,228));p.ink(cache,44,138,'RADIO RADAR · '+str(len(data['radar']))+' BLOCKS',23)
        p.text(cache,44,178,'No blocks received ≠ clear weather' if not data['radar'] else 'Received grids only · gaps are unknown',19,p.MUTED,width=450)
        p.text(cache,44,208,'Ground uplink '+age(data['last_uplink_at'],data['now']),18,p.CYAN,width=450)
        p.surface((24,552,714,628));p.text(cache,42,577,'Light',18,p.TEXT)
        for index,c in enumerate(RADAR_COLOURS[1:]):ui.draw_logical_rect(108+index*38,568,140+index*38,582,tuple(int(c[i:i+2],16) for i in (1,3,5))+(210,))
        p.text(cache,390,577,'Extreme',18,p.TEXT)
        p.text(cache,42,608,'Faint blue: received, no echo · Transparent: unknown',18,p.MUTED,width=650)
        for box,label,kind,value in (((24,642,96,698),'−','weather_zoom',1/1.6),((108,642,308,698),'Receiver','weather_center',None),((320,642,392,698),'+','weather_zoom',1.6)):
            p.button(cache,box,label,(kind,value))

    def draw(self,cache):
        p=self.parent;ui=p.ui;data=p.manager.weather.snapshot();now=data['now']
        ui.draw_logical_rect(0,0,1280,800,p.BG)
        if self.tab=='radar':self.draw_radar(cache,data)
        ui.draw_logical_rect(0,0,1280,88,p.BG)
        p.ink(cache,24,32,'UAT WEATHER',27);p.ink(cache,24,65,'978 MHz · direct radio reception',16,p.CYAN)
        for index,(name,label) in enumerate((('reports','Reports'),('radar','Radar'),('stations','Ground stations'))):
            x=500+index*250;p.button(cache,(x,16,x+232,72),label,('weather_tab',name),active=self.tab==name)
        if self.tab!='radar':
            status='Ground uplink received' if data['status']=='RECEIVING' else 'Listening for ground stations' if data['status']=='LISTENING' else data['status'].capitalize()
            p.ink(cache,24,120,status,26,p.CYAN,width=900)
            p.ink(cache,24,157,f"{data['uplinks']:,} uplinks · last {age(data['last_uplink_at'],now)} · {len(data['reports'])} reports · {len(data['radar'])} radar blocks",19,p.MUTED,width=1120)
            if self.tab=='reports':self.draw_reports(cache,data)
            else:self.draw_stations(cache,data)
        p.draw_back(cache)
        p.draw_status(cache,'UAT WEATHER · '+data['status'],'Received over radio · delayed weather · hobby display',full_width=True)

    def pagination(self,cache,total,size):
        p=self.parent;pages=max(1,math.ceil(total/size));self.page=min(self.page,pages-1)
        p.ink(cache,640,671,f'{self.page+1} / {pages}',20,p.MUTED,anchor='cm')
        p.button(cache,(24,642,264,698),'Previous',('weather_page',-1),enabled=self.page>0)
        p.button(cache,(1016,642,1256,698),'Next',('weather_page',1),enabled=self.page+1<pages)

    def draw_reports(self,cache,data):
        p=self.parent
        rows=[r for r in data['reports'] if self.filter=='All' or r['type']==self.filter or (self.filter=='Advisories' and r['type'] not in ('METAR','TAF'))]
        if self.report is not None:
            r=self.report;p.ink(cache,24,208,r['type']+' · '+r['name'],25,width=850)
            p.button(cache,(1000,184,1256,240),'All reports',('weather_close_report',None))
            stamp=dt.datetime.fromtimestamp(r['expires_at'],dt.timezone.utc).strftime('%H:%M UTC')
            p.text(cache,24,251,'Received '+age(r['received_at'],data['now'])+' · expires '+stamp,19,p.MUTED,width=1100)
            lines=[line for paragraph in r['text'].splitlines() for line in (textwrap.wrap(paragraph,92) or [''])]
            self.pagination(cache,len(lines),12)
            for i,line in enumerate(lines[self.page*12:(self.page+1)*12]):p.text(cache,24,286+i*28,line,20,p.TEXT,width=1220)
            return
        p.button(cache,(1000,184,1256,240),self.filter,('weather_filter',None))
        if not rows:
            p.ink(cache,40,316,'Waiting for received weather',28)
            p.text(cache,40,369,'METARs, TAFs and advisories appear when an FAA uplink is received.',21,p.MUTED,width=1180)
            p.text(cache,40,410,'Aircraft packets and weather uplinks are separate. No Internet data is mixed in.',20,p.MUTED,width=1180)
            return
        self.pagination(cache,len(rows),3)
        for index,r in enumerate(rows[self.page*3:(self.page+1)*3]):
            y=244+index*126
            p.button(cache,(24,y,1256,y+64),r['type']+' · '+r['name'],('weather_report',r),'Received '+age(r['received_at'],data['now']))
            p.text(cache,40,y+91,r['text'].replace('\n',' '),20,p.MUTED,width=1190)

    def draw_stations(self,cache,data):
        p=self.parent;rows=data['stations']
        if not rows:
            p.ink(cache,40,308,'No FAA ground station received yet',28)
            p.text(cache,40,365,'The weather decoder is listening alongside aircraft reception.',21,p.MUTED,width=1160)
            p.text(cache,40,406,'Ground-station reception requires a suitable line of sight from your antenna.',20,p.MUTED,width=1160)
            return
        self.pagination(cache,len(rows),3)
        for index,s in enumerate(rows[self.page*3:(self.page+1)*3]):
            y=220+index*130;p.ink(cache,40,y,s['id'],25,width=1100)
            p.text(cache,40,y+38,f"{'Receiving' if s['live'] else 'Previously heard'} · {s['packets']:,} uplinks · last {age(s['last_heard'],data['now'])}",21,p.CYAN,width=1160)
            p.text(cache,40,y+74,'Advertised position'+(' · validity flag unset' if not s.get('position_valid') else ''),18,p.MUTED,width=1160)
