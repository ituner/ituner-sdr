"""Touchscreen companion to the browser Signal Observatory."""
import math
import textwrap
import time
from decoder_style import DecoderStyle
from dongle_workspace import DongleWorkspace
from types import SimpleNamespace
from adsb_workspace import ADSBWorkspace
from sstv_workspace import SSTVWorkspace
from vhf_catalog import MODES
from vhf_monitor import clean_position
from spectrum_workspace import SpectrumWorkspace


class MapAdapter:
    def __init__(self, workspace):self.workspace=workspace
    def track_snapshot(self):
        session=self.workspace.session
        with session.lock:return {k:list(v) for k,v in session.tracks.items()}


class VHFWorkspace(DecoderStyle, SSTVWorkspace):
    def __init__(self,ui,hub):
        super().__init__(ui,hub)
        self.dongles=DongleWorkspace(ui,hub)
        self.mode='ais';self.view='map';self.page=0;self.overlay=None;self.overlay_page=0
        self.map=ADSBWorkspace(ui,MapAdapter(self))
        self.map.trail_seconds=86400  # Independent VHF map keeps its existing history window.
        self.manager.gallery=SimpleNamespace(image_path=lambda key:self.manager.root/key)
        self.number='';self.edit_field='frequency';self.station_edit={}
        self.spectrum=SpectrumWorkspace(ui,hub)

    @property
    def session(self):return self.manager.sessions[self.mode]

    def show(self,mode):
        self.spectrum.open=mode=='spectrum'
        if mode=='spectrum':
            self.mode=mode;self.open=True;self.spectrum.show();return
        self.mode=mode;self.open=True;self.view='map' if mode in ('ais','aprs','sonde') else 'data'
        self.overlay=None;self.page=0;self.map.centered=False;self.map.selected=None;self.map.following=False;self.map.track_time=-float('inf')

    def panel(self,box):self.ui.draw_logical_rounded_rect(*box,self.RADIUS,self.PANEL,self.LINE,1)

    def drag_begin(self,x,y):
        if self.dongles and self.dongles.open:return False
        if self.mode=='spectrum':return self.spectrum.drag_begin(x,y)
        self.map.drag_begin(x,y)
    def drag_move(self,sx,sy,x,y):
        if self.dongles and self.dongles.open:return False
        if self.mode=='spectrum':return self.spectrum.drag_move(sx,sy,x,y)
        if self.view=='map' and not self.overlay:self.map.drag_move(sx,sy,x,y)
    def swipe(self,sx=None,sy=None,x=None,y=None):
        if self.dongles and self.dongles.open:return False
        if self.mode=='spectrum':return self.spectrum.swipe(sx,sy,x,y)
        if sx is None:return self.map.swipe()
        if abs(y-sy)>60 and abs(y-sy)>abs(x-sx)*1.5:
            field='overlay_page' if self.overlay in ('profiles','usb') else 'page'
            setattr(self,field,max(0,getattr(self,field)+(1 if y<sy else -1)));return True
        return self.map.swipe()

    def tap(self,x,y):
        if self.dongles.open:return self.dongles.tap(x,y)
        if self.mode=='spectrum':
            self.spectrum.tap(x,y);self.open=self.spectrum.open;return
        for box,(action,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            try:
                if action=='dongles':self.dongles.show()
                elif action=='home':self.open=False
                elif action=='back':
                    if self.overlay:self.overlay=None
                    else:self.open=False
                elif action=='view':self.view=value;self.page=0;self.overlay=None
                elif action=='overlay':
                    if value=='location' and getattr(self.ui,'station_settings',None):
                        self.ui.station_settings.show();self.open=False;return
                    self.overlay=value;self.overlay_page=0
                    if value=='location':self.station_edit=dict(self.manager.position or dict(lat=0,lon=0))
                    elif value=='profiles':self.overlay_page=next((i//8 for i,p in enumerate(self.manager.catalog[self.mode]['presets']) if p['id']==self.session.settings['profile']),0)
                elif action=='page':
                    field='overlay_page' if self.overlay in ('profiles','usb') else 'page';setattr(self,field,max(0,getattr(self,field)+value))
                elif action=='profile':self.session.control('configure',profile=value);self.overlay=None
                elif action=='assign':self.session.control('configure',selection=value);self.overlay=None
                elif action=='number':
                    self.edit_field=value
                    self.number=str(self.station_edit.get(value,0) if value in ('lat','lon') else self.session.settings[value]/1e6 if value=='frequency' else self.session.settings[value]);self.overlay='number'
                elif action=='key':
                    if value=='DEL':self.number=self.number[:-1]
                    elif value=='CLEAR':self.number=''
                    elif value=='SAVE':
                        number=float(self.number)
                        if self.edit_field in ('lat','lon'):
                            limit=90 if self.edit_field=='lat' else 180
                            if not -limit<=number<=limit:raise ValueError(f'Coordinate must be -{limit} to {limit} degrees')
                            self.station_edit[self.edit_field]=number;self.overlay='location'
                        else:
                            self.session.control('configure',**{self.edit_field:number*1e6 if self.edit_field=='frequency' else number});self.overlay=None
                    elif len(self.number)<14:self.number+=value
                elif action=='continuous':self.session.control('configure',continuous=not self.session.settings.get('continuous'));
                elif action=='save_site':self.manager.control(self.mode,'location',position=self.station_edit);self.overlay=None
                elif action=='zoom':self.map.zoom(value)
                elif action=='fit':self.map.centered=False;self.map.following=False
                elif action=='follow':
                    if self.map.selected:self.map.following=not self.map.following
                    else:self.message='Tap a target to follow it.'
                elif action=='trails':self.map.trail_seconds=0 if self.map.trail_seconds else 900
                elif action=='image':self.enlarged=value;self.overlay='image'
                else:self.session.control(action)
                if action not in ('follow',):self.message=''
            except (ValueError,OSError) as exc:self.message=str(exc)
            return
        if self.view=='map' and not self.overlay:
            near=sorted((math.hypot(px-x,py-y),p['hex'],p) for px,py,p in self.map.points)
            if near and near[0][0]<40:
                _,self.map.selected,self.map.selected_plane=near[0];self.map.following=False

    def header(self,cache,state):
        ui=self.ui;meta=MODES[self.mode]
        ui.draw_logical_rect(0,0,1024,82,self.PANEL)
        ui.draw_text(cache,20,30,meta['title'].upper(),self.TEXT,25,True,False,'lm',family='Oxanium')
        self.text(cache,22,60,meta['label']+' / '+meta['engine'],13,self.MUTED)
        for x,label,value in ((610,'FREQUENCY',f"{state['settings']['frequency']/1e6:.3f} MHz"),(850,'DECODED',state['messages'])):
            self.text(cache,x,22,label,10,self.MUTED);self.text(cache,x,52,value,23,self.CYAN)

    def draw_map(self,cache,state):
        rows=[]
        if state['enabled']:
            rows=[dict(r,hex=r['id'],flight=r['label'],track=r.get('heading') or 0,seen_pos=0) for r in state['records']
                if clean_position(r) and time.time()-r.get('position_time',r['time'])<600]
        # Every decoder exposes MAP, including decoders without position reports.
        title,detail={
            'ais':('WAITING FOR VESSELS','Waiting for fresh position messages.'),
            'aprs':('WAITING FOR RF STATIONS','Waiting for fresh position messages.'),
            'sonde':('WAITING FOR BALLOONS','Waiting for fresh position messages.'),
            'ism':('SENSOR RECEPTION','Open DATA for decoded sensor readings.'),
            'meteor':('METEOR RECEPTION','Open PRODUCTS for decoded imagery.'),
            'cubesat':('SATELLITE TELEMETRY','Open DATA / PRODUCTS for decoded frames.'),
        }.get(self.mode,('WAITING FOR DATA','Waiting for fresh position messages.'))
        adapter=dict(enabled=state['enabled'],aircraft=rows,receiver_position=self.manager.position,
            empty_title=title if state['enabled'] else 'RECEIVER STOPPED',empty_detail=detail)
        self.map.draw_map(cache,adapter,rows)
        if self.map.selected_plane:
            p=self.map.selected_plane;self.panel((20,640,650,700));self.text(cache,36,661,p['flight'],18,self.CYAN)
            self.text(cache,36,686,f"{p['lat']:.4f}°, {p['lon']:.4f}° · tap FOLLOW to track",14,self.MUTED)

    def draw_data(self,cache,state):
        records=list(reversed(state['records']));start_y=106
        if self.mode in ('meteor','cubesat'):
            orbit=state.get('orbit') or {};self.panel((20,96,1004,218))
            if orbit.get('elevation') is not None:
                for x,label,value in ((38,'ELEVATION',str(orbit['elevation'])+'°'),(240,'AZIMUTH',str(orbit['azimuth'])+'°'),(440,'RANGE',str(orbit['range_km'])+' km'),(690,'DOPPLER',str(orbit['doppler_hz'])+' Hz')):
                    self.text(cache,x,120,label,11,self.MUTED);self.text(cache,x,151,value,24,self.CYAN)
                passes=orbit.get('passes') or []
                if passes:self.text(cache,38,191,'NEXT PASS '+time.strftime('%d %b %H:%M UTC',time.gmtime(passes[0]['rise']))+f" · {passes[0]['elevation']}° max",17)
            else:
                self.text(cache,38,124,'SATELLITE RECEPTION',19,self.CYAN)
                self.text(cache,38,158,orbit.get('detail','Set station location and update orbital data in the browser.'),16,self.MUTED,width=940)
                self.text(cache,38,192,'A visible pass and a suitable satellite antenna are required.',16,self.MUTED)
            start_y=240
        if self.mode=='meteor' and state.get('decoder_stats'):
            values={key:value for module in state['decoder_stats'].values() for key,value in module.items()}
            self.panel((20,230,1004,294))
            for x,label,value in ((38,'SNR',f"{(values.get('snr') or 0):.1f} dB"),(270,'VITERBI','LOCKED' if values.get('viterbi_lock') else 'SEARCHING'),(510,'FRAME SYNC','LOCKED' if values.get('deframer_lock') else 'SEARCHING'),(770,'ERROR RATE',f"{(values.get('viterbi_ber') or 0):.3f}")):
                self.text(cache,x,247,label,10,self.MUTED);self.text(cache,x,275,value,19,self.CYAN)
        if not records:
            self.panel((100,start_y+62,924,start_y+250))
            title='DECODING LRPT IMAGERY' if self.mode=='meteor' and state['messages'] and state['enabled'] else 'PASS CAPTURED' if self.mode=='meteor' and state['messages'] else 'LISTENING FOR DATA' if state['enabled'] else 'READY TO RECEIVE'
            self.text(cache,132,start_y+102,title,26,self.CYAN)
            for i,line in enumerate(textwrap.wrap(MODES[self.mode]['hint'],85)):
                self.text(cache,132,start_y+148+i*26,line,18,self.MUTED)
            self.text(cache,132,start_y+222,'Choose PROFILE / USB, then START.',17)
            return
        size=4 if start_y==106 else 2;pages=max(1,(len(records)+size-1)//size);self.page=min(self.page,pages-1)
        for index,row in enumerate(records[self.page*size:(self.page+1)*size]):
            col,r=index%2,index//2;x=20+col*500;y=start_y+r*237
            self.panel((x,y,x+484,y+219));self.text(cache,x+18,y+28,row['label'],20,self.CYAN,width=450)
            self.text(cache,x+18,y+57,time.strftime('%H:%M:%S UTC',time.gmtime(row['time']))+f" · {row['count']} observations",13,self.MUTED)
            priority=('latitude','longitude','altitude','comment','temperature_C','humidity','pressure_hPa','alt','speed','bytes','protocol','telemetry')
            fields=[f'{k}: {row["fields"][k]}' for k in priority if k in row['fields'] and not isinstance(row['fields'][k],(dict,list))]
            fields += [f'{k}: {v}' for k,v in row['fields'].items() if k not in priority+('raw','hex','path') and not isinstance(v,(dict,list))]
            for i,line in enumerate(fields[:5]):self.text(cache,x+18,y+91+i*23,' '.join(line.split()),16,width=448)
        self.text(cache,28,692,f'PAGE {self.page+1} / {pages} · swipe for more',13,self.MUTED)

    def draw_products(self,cache):
        with self.manager.asset_lock:assets=[a for a in self.manager.assets if a['mode']==self.mode]
        if not assets:
            self.panel((100,230,924,490));self.text(cache,132,278,'CAPTURE LIBRARY',28,self.CYAN)
            self.text(cache,132,324,'Images, telemetry and raw frames appear after decoding.',20,self.MUTED)
            self.text(cache,132,362,'Stop a Meteor pass to finish its image products.',18,self.MUTED)
            self.text(cache,132,423,'Download files at cm5.local:8092',18);return
        pages=max(1,(len(assets)+5)//6);self.page=min(self.page,pages-1)
        for index,item in enumerate(assets[self.page*6:(self.page+1)*6]):
            x=20+(index%3)*334;y=104+(index//3)*280;box=(x,y,x+316,y+260);self.panel(box)
            if item['image']:
                self.image(item['path'],(x+6,y+6,x+310,y+205));self.actions.append(((x,y,x+316,y+205),('image',item['path'])))
            else:self.text(cache,x+24,y+100,item['name'].split('.')[-1].upper(),35,self.CYAN)
            self.text(cache,x+14,y+227,item['name'],15,width=285);self.text(cache,x+14,y+248,f"{item['size']/1024:.1f} KB",11,self.MUTED)

    def draw_logs(self,cache,state):
        self.panel((20,98,1004,696));lines=[]
        for item in reversed(state['output']):
            text=time.strftime('%H:%M:%S ',time.gmtime(item['time']))+item['text']
            lines.extend(textwrap.wrap(text,108) or [''])
        pages=max(1,(len(lines)+19)//20);self.page=min(self.page,pages-1)
        if not lines:self.text(cache,40,145,'Receiver diagnostics appear here after Start.',20,self.MUTED)
        for i,line in enumerate(lines[self.page*20:(self.page+1)*20]):self.text(cache,36,126+i*26,line,15,width=950)
        self.text(cache,36,674,f'PAGE {self.page+1} / {pages} · UTC · full logs in browser',13,self.MUTED)

    def draw_overlay(self,cache,state):
        self.ui.draw_logical_rect(0,82,1024,716,self.BG)
        if self.overlay=='image':self.image(self.enlarged,(14,94,1010,704));return
        self.panel((20,98,1004,698))
        if self.overlay=='number':
            self.text(cache,42,127,'FREQUENCY · MHz' if self.edit_field=='frequency' else self.edit_field.upper(),20,self.CYAN)
            self.text(cache,42,181,self.number or '0',34)
            for i,key in enumerate(('7','8','9','4','5','6','1','2','3','.','0','-')):
                x=42+(i%3)*178;y=224+(i//3)*98;self.button(cache,(x,y,x+162,y+82),key,('key',key))
            for i,key in enumerate(('DEL','CLEAR','SAVE')):self.button(cache,(650,224+i*120,970,320+i*120),key,('key',key),active=key=='SAVE')
            return
        if self.overlay=='location':
            self.text(cache,40,136,'RECEIVER LOCATION',24,self.CYAN)
            self.text(cache,40,184,'Coordinates stay on CM5. Used for pass predictions and Doppler.',18,self.MUTED)
            self.button(cache,(40,240,494,350),'LATITUDE',('number','lat'),f"{self.station_edit.get('lat',0):.5f} deg")
            self.button(cache,(520,240,974,350),'LONGITUDE',('number','lon'),f"{self.station_edit.get('lon',0):.5f} deg")
            self.button(cache,(40,406,494,510),'SAVE LOCATION',('save_site',None),active=True)
            if self.mode in ('cubesat','meteor'):self.button(cache,(520,406,974,510),'UPDATE ORBITS',('tle',None))
            if self.mode=='meteor':self.button(cache,(40,550,974,640),'CONTINUOUS RECEPTION',('continuous',None),'ON · SAVE EACH PASS' if state['settings'].get('continuous') else 'OFF · SINGLE CAPTURE',active=state['settings'].get('continuous',False))
            return
        if self.overlay=='usb':
            self.button(cache,(40,626,506,684),'DONGLES / RENAME',('dongles',None))
            for i,(label,action) in enumerate((('GAIN',('number','gain')),('PPM',('number','ppm')),('SITE',('overlay','location')))):
                self.button(cache,(590+i*130,108,712+i*130,150),label,action)
        title='RECEPTION PROFILES' if self.overlay=='profiles' else 'USB RECEIVER ASSIGNMENT'
        self.text(cache,40,130,title,22,self.CYAN)
        choices=self.manager.catalog[self.mode]['presets'] if self.overlay=='profiles' else [dict(id='auto',label='Auto · available receiver')]+self.manager.devices
        pages=max(1,(len(choices)+7)//8);self.overlay_page=min(self.overlay_page,pages-1)
        for index,item in enumerate(choices[self.overlay_page*8:(self.overlay_page+1)*8]):
            x=40+(index%2)*480;y=166+(index//2)*112
            key='profile' if self.overlay=='profiles' else 'assign';label=item.get('name',item.get('label'))
            subtitle=f"{item['frequency']/1e6:.6f} MHz" if 'frequency' in item else self.manager.broker.snapshot().get(item['id'],'available')
            self.button(cache,(x,y,x+458,y+96),label,(key,item['id']),subtitle)
        self.text(cache,40,616,f'PAGE {self.overlay_page+1} / {pages}',14,self.MUTED)
        self.button(cache,(526,626,740,684),'PREVIOUS',('page',-1));self.button(cache,(754,626,968,684),'NEXT',('page',1))

    def draw(self,cache):
        if self.dongles.open:return self.dongles.draw(cache)
        if self.mode=='spectrum':return self.spectrum.draw(cache)
        ui=self.ui;self.actions=[];state=self.session.snapshot()
        ui.draw_logical_rect(0,0,1280,800,self.BG);self.header(cache,state)
        if self.overlay:self.draw_overlay(cache,state)
        elif self.view=='map':self.draw_map(cache,state)
        elif self.view=='data':self.draw_data(cache,state)
        elif self.view=='products':self.draw_products(cache)
        else:self.draw_logs(cache,state)
        ui.draw_logical_rect(1024,0,1280,800,self.PANEL)
        self.text(cache,1038,32,MODES[self.mode]['label'].upper(),23,self.CYAN)
        self.text(cache,1038,62,state['status'],12,self.MUTED,width=226)
        items=[('START' if not state['enabled'] else 'STOP',('start' if not state['enabled'] else 'stop',None),state['status']),
            ('PROFILE',('overlay','profiles'),self.session.profile()['name']),
            ('USB RECEIVER',('overlay','usb'),state['assigned']['serial'] if state['assigned'] else 'AUTO / SELECT'),
            ('FREQUENCY',('number','frequency'),f"{state['settings']['frequency']/1e6:.6f} MHz")]
        for index,(label,action,sub) in enumerate(items):self.button(cache,(1034,82+index*78,1270,150+index*78),label,action,sub,active=index==0 and state['enabled'])
        for i,(label,value) in enumerate((('MAP','map'),('DATA','data'),('PRODUCTS','products'),('LOGS','logs'))):
            x=1034+(i%2)*122;y=402+(i//2)*78;self.button(cache,(x,y,x+114,y+68),label,('view',value),active=self.view==value)
        if self.view=='map' and not self.overlay:
            for i,(label,action) in enumerate((('ZOOM +',('zoom',1.4)),('ZOOM -',('zoom',1/1.4)),('FIT ALL',('fit',None)),('FOLLOW',('follow',None)))):
                x=1034+(i%2)*122;y=558+(i//2)*78;self.button(cache,(x,y,x+114,y+68),label,action,active=label=='FOLLOW' and self.map.following)
        else:
            self.button(cache,(1034,558,1148,626),'PREV',('page',-1));self.button(cache,(1156,558,1270,626),'NEXT',('page',1))
            if self.mode in ('meteor','cubesat'):self.button(cache,(1034,636,1270,704),'SITE / ORBITS',('overlay','location'))
        self.button(cache,(1034,728,1270,792),'BACK',('back',None))
        dashboard='RTL433-UI · cm5.local:8093' if self.mode=='ism' and getattr(self.manager,'rtl433_ui_installed',False) else 'SIGNAL OBSERVATORY · cm5.local:8092'
        self.draw_status(cache,self.message or state['detail'],dashboard)

    def close(self):
        self.spectrum.close();super().close();self.manager.close()
