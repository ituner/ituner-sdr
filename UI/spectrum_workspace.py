"""Native touch spectrum analyzer, sharing the browser survey and saved sweeps."""
import base64
import json
import math
from pathlib import Path
import queue
import threading
import time

import numpy as np
from PIL import Image, ImageDraw
from sstv_workspace import SSTVWorkspace

PRESETS=(('Full · 25–1700 MHz',25e6,1700e6,100000),('FM · 87.5–108 MHz',87.5e6,108e6,25000),
         ('Airband · 118–139 MHz',118e6,139e6,25000),('VHF · 100–300 MHz',100e6,300e6,25000),
         ('UHF · 300–1000 MHz',300e6,1000e6,100000),('Upper · 1000–1700 MHz',1000e6,1700e6,100000))
PLOT=(80,172,984,348)
WATERFALL=(80,408,984,620)
PALETTE=np.array(((7,21,37),(25,78,145),(32,170,168),(196,225,116),(255,240,188)),dtype=float)


def columns(data,field,view,width=904):
    """Preserve narrow peaks and excluded gaps while reducing a viewport."""
    config=data.get('settings',{});power=data.get(field,[]);masked=data.get('masked',[])
    if not power or not config:return np.zeros(width,dtype=np.uint8)
    result=np.zeros(width,dtype=np.uint8)
    for x in range(width):
        first=max(0,min(len(power)-1,int((view[0]+(view[1]-view[0])*x/width-config['low'])/config['bin'])))
        last=min(len(power),max(first+1,math.ceil((view[0]+(view[1]-view[0])*(x+1)/width-config['low'])/config['bin'])))
        if any(masked[first:last]):result[x]=1;continue
        values=[v for v in power[first:last] if isinstance(v,(float,int)) and math.isfinite(v)]
        if values:result[x]=max(2,min(255,round(max(values))+202))
    return result


def matching(a,b):
    return bool(a.get('settings') and b and b.get('settings') and
                a.get('device',{}).get('id')==b.get('device',{}).get('id') and
                all(a['settings'].get(k)==b['settings'].get(k) for k in ('low','high','bin','gain','ppm')) and
                all(a.get(k)==b.get(k) for k in ('rate','fft')))


def allocations(reference,frequency):
    labels=[]
    for region in ('eu','us'):
        names=[]
        for row in reference.get(region,[]):
            if row['low']<=frequency<row['high'] or frequency==1700e6 and row['high']==frequency:
                for service in row['services']:
                    label=service['name'].capitalize()+' ('+service['priority']+')'
                    if label not in names:names.append(label)
        labels.append(('EU / CEPT' if region=='eu' else 'US')+': '+(' · '.join(names) or 'No reference entry'))
    return labels


class SpectrumWorkspace(SSTVWorkspace):
    BG=(8,16,25,255);PANEL=(15,30,44,255);MUTED=(137,164,186);CYAN=(102,226,210)
    def __init__(self,ui,hub):
        super().__init__(ui,hub)
        self.survey=hub.spectrum;self.view=None;self.view_key=None;self.history_page=0;self.depth=120
        self.overlay=None;self.number='';self.edit_field='low';self.draft={};self.overlay_page=0
        self.inspection=None;self.baseline=None;self.screen='chart';self.drag=None
        self.floor=-110;self.ceiling=-90;self.auto_key=None;self.state={};self.rows=[];self.frame=None;self.frame_id=0
        self.texture=None;self.uploaded=-1;self.frame_view=None;self.limits=(-140,-70);self.command_pending='';self.lock=threading.RLock()
        self.commands=queue.Queue();self.wake=threading.Event();self.closed=threading.Event();self.worker=None
        try:self.reference=json.loads(Path(__file__).with_name('spectrum_allocations.json').read_text())
        except (OSError,ValueError):self.reference={}

    def show(self):
        self.open=True;self.overlay=None;self.message='';self.inspection=None
        if not self.worker:
            self.worker=threading.Thread(target=self.run,name='spectrum-touch',daemon=True);self.worker.start()
        self.wake.set()

    def request(self,action,**values):
        if self.command_pending:return
        self.command_pending=action;self.message='';self.commands.put((action,values));self.wake.set()

    def run(self):
        history_key=None;history=[];after=0;version=None
        while not self.closed.is_set():
            self.wake.wait(.75);self.wake.clear()
            if not self.open and self.commands.empty():continue
            try:
                while not self.commands.empty():
                    action,values=self.commands.get_nowait()
                    try:
                        if action=='baseline':self.baseline=self.survey.trace(values['id']) if values['id'] else None
                        else:self.survey.control(action,**values)
                        self.message='Sweep saved as a baseline.' if action=='save' else ''
                    except (ValueError,OSError,RuntimeError) as exc:self.message=str(exc)
                    finally:self.command_pending=''
                state=self.survey.snapshot();data=state['data'];config=data.get('settings',state['settings'])
                with self.lock:
                    key=(config['low'],config['high'],config['bin'])
                    if key!=self.view_key:self.view=(config['low'],config['high']);self.view_key=key;self.history_page=0;self.inspection=None
                    view=self.view;depth=self.depth;page=self.history_page
                current_key=(state['history']['key'],*view)
                if history_key!=current_key:history=[];after=0;history_key=current_key;version=None
                revision=(state['history']['latest_id'],state['history']['count'])
                if revision!=version:
                    value=self.survey.history.read(data,after=after,low=view[0],high=view[1],columns=904)
                    for row in value['rows']:
                        row['values']=np.frombuffer(base64.b64decode(row['values']),dtype=np.uint8).copy();history.append(row)
                    after=value['latest_id'];version=revision
                history=[r for r in history if r['finished']>=time.time()-86400][-720:]
                if history and self.auto_key!=state['history']['key']:
                    self.fit_colors(history);self.auto_key=state['history']['key']
                rows=list(reversed(history))[:depth]
                if data.get('updated') and not data.get('complete') and data['updated']>=data.get('sweep_started',data.get('started',0)):
                    rows.insert(0,dict(id='live',started=data.get('sweep_started',data['started']),finished=data['updated'],
                                      sweep=data['sweep'],partial=True,values=columns(data,'power',view)))
                pages=max(1,math.ceil(len(rows)/60));page=min(page,pages-1);visible=rows[page*60:(page+1)*60]
                frame,limits=self.paint(data,visible,view)
                with self.lock:
                    self.state=state;self.rows=visible;self.pages=pages;self.history_page=page;self.frame=frame;self.frame_view=view;self.frame_id+=1;self.limits=limits
            except Exception as exc:self.message='Spectrum display: '+str(exc)

    def fit_colors(self,rows):
        counts=np.zeros(256,dtype=np.int64)
        for row in rows:counts+=np.bincount(row['values'],minlength=256)
        counts[:2]=0;total=int(counts.sum())
        if not total:return
        cumulative=counts.cumsum();low=int(np.searchsorted(cumulative,total*.1))-202;high=int(np.searchsorted(cumulative,total*.998))-202
        self.floor=max(-180,min(-70,math.floor(low/5)*5));self.ceiling=min(-20,max(-120,self.floor+20,math.ceil(high/5)*5))

    def paint(self,data,rows,view):
        image=Image.new('RGBA',(984,480),(12,22,32,255));draw=ImageDraw.Draw(image)
        # Logical display coordinates minus (20, 140).
        left,right,top,bottom=60,964,32,208
        finite=[v for v in data.get('peak',[]) if isinstance(v,(int,float)) and math.isfinite(v)]
        hi=min(-10,math.ceil(max(finite)/10)*10+5) if finite else -70
        lo=min(hi-30,max(-180,math.floor(min(finite)/10)*10-5)) if finite else -140
        for i in range(6):
            y=top+(bottom-top)*i/5;draw.line((left,y,right,y),fill=(37,54,72),width=1)
        for i in range(7):
            x=left+(right-left)*i/6;draw.line((x,top,x,bottom),fill=(37,54,72),width=1)
        def trace(codes,color):
            points=[]
            for x,code in enumerate(codes):
                if code<2:
                    if len(points)>1:draw.line(points,fill=color,width=1)
                    points=[];continue
                y=max(top,min(bottom,top+(hi-(int(code)-202))/(hi-lo)*(bottom-top)));points.append((left+x,y))
            if len(points)>1:draw.line(points,fill=color,width=1)
        peak=columns(data,'peak',view);power=columns(data,'power',view)
        for x,code in enumerate(power):
            if code==1:draw.line((left+x,top,left+x,bottom),fill=(90,59,38))
        trace(peak,(234,195,130));trace(power,(112,226,192))
        if matching(data,self.baseline):trace(columns(self.baseline,'average',view),(126,186,255))
        if rows:
            codes=np.vstack([row['values'] for row in rows]);t=np.clip((codes.astype(float)-202-self.floor)/max(5,self.ceiling-self.floor),0,1)*4
            index=np.minimum(3,t.astype(int));fraction=(t-index)[...,None];rgb=(PALETTE[index]*(1-fraction)+PALETTE[index+1]*fraction).astype(np.uint8)
            rgb[codes==0]=(8,18,29);rgb[codes==1]=(232,148,72)
            waterfall=Image.fromarray(rgb).resize((904,min(212,len(rows)*20)),resample=Image.Resampling.NEAREST)
            image.paste(waterfall,(60,268))
        return image.tobytes(),(lo,hi)

    def upload(self,frame,identity):
        gl=self.ui.GL
        if self.texture is None:self.texture=gl.glGenTextures(1)
        if identity!=self.uploaded:
            gl.glBindTexture(gl.GL_TEXTURE_2D,self.texture)
            for flag in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_NEAREST)
            gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,984,480,0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,frame);self.uploaded=identity
        self.ui.draw_textured_quad(self.texture,20,140,1004,620,0,0,1,1)

    def inspect(self,x,y):
        if not self.view or self.frame_view!=self.view:return
        if PLOT[0]<=x<=PLOT[2] and PLOT[1]<=y<=PLOT[3]:row=None
        elif WATERFALL[0]<=x<=WATERFALL[2] and self.rows and WATERFALL[1]<=y<WATERFALL[1]+min(212,len(self.rows)*20):
            row=self.rows[min(len(self.rows)-1,int((y-WATERFALL[1])/min(20,212/len(self.rows))))]
        else:return
        fraction=max(0,min(1,(x-80)/904));frequency=self.view[0]+fraction*(self.view[1]-self.view[0])
        code=int(row['values'][min(903,int(fraction*904))]) if row else None
        self.inspection=dict(frequency=frequency,row=row,code=code)

    def drag_begin(self,x,y):self.drag=(x,y,self.view);self.inspect(x,y)
    def drag_move(self,sx,sy,x,y):
        if self.overlay or not self.drag or not self.view:return
        if abs(x-sx)>20 and abs(x-sx)>abs(y-sy)*1.5 and 140<=sy<=620:
            view=self.drag[2];config=self.state.get('data',{}).get('settings',self.state.get('settings',{}))
            if not view or not config:return
            span=view[1]-view[0];low=max(config['low'],min(config['high']-span,view[0]-(x-sx)/904*span));self.view=(low,low+span);self.inspection=None;self.wake.set()
    def swipe(self,sx=None,sy=None,x=None,y=None):
        if sx is None:return False
        if abs(y-sy)>60 and abs(y-sy)>abs(x-sx)*1.5:
            if self.overlay in ('presets','usb','baselines'):self.overlay_page=max(0,self.overlay_page+(1 if y<sy else -1))
            elif not self.overlay:self.history_page=max(0,min(getattr(self,'pages',1)-1,self.history_page+(1 if y<sy else -1)));self.inspection=None;self.wake.set()
            return True
        return abs(x-sx)>20

    def zoom(self,scale):
        if not self.view:return
        config=self.state.get('data',{}).get('settings',self.state.get('settings',{}))
        if not config:return
        center=self.inspection['frequency'] if self.inspection else sum(self.view)/2
        span=min(config['high']-config['low'],max(config['bin']*20,(self.view[1]-self.view[0])*scale))
        low=max(config['low'],min(config['high']-span,center-span/2));self.view=(low,low+span);self.inspection=None;self.wake.set()

    def tap(self,x,y):
        for box,(action,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            try:
                if action=='back':
                    if self.overlay:self.overlay=None
                    else:self.open=False
                elif action=='screen':self.screen=value
                elif action in ('start','stop','save'):self.request(action,**({'label':'Touch baseline '+time.strftime('%d %b %H:%M UTC',time.gmtime())} if action=='save' else {}))
                elif action=='overlay':
                    self.overlay=value;self.overlay_page=0
                    if value=='settings':self.draft=dict(self.state.get('settings',self.survey.settings))
                elif action=='number':self.edit_field=value;self.number=str(self.draft[value]/1e6 if value in ('low','high') else self.draft[value]);self.overlay='number'
                elif action=='key':
                    if value=='DEL':self.number=self.number[:-1]
                    elif value=='CLEAR':self.number=''
                    elif value=='SAVE':
                        number=float(self.number)
                        if not math.isfinite(number):raise ValueError('Enter a finite number')
                        self.draft[self.edit_field]=number*1e6 if self.edit_field in ('low','high') else number;self.overlay='settings'
                    elif len(self.number)<16:self.number+=value
                elif action=='apply':self.request('configure',**self.draft);self.overlay=None
                elif action=='preset':
                    _,low,high,width=PRESETS[value];self.draft.update(low=low,high=high,bin=width);self.overlay='settings'
                elif action=='toggle':self.draft[value]=not self.draft.get(value,False)
                elif action=='bin':self.draft['bin']=value
                elif action=='assign':self.draft['selection']=value;self.overlay='settings'
                elif action=='baseline':self.request('baseline',id=value);self.overlay=None
                elif action=='zoom':self.zoom(value)
                elif action=='full':
                    config=self.state['data'].get('settings',self.state['settings']);self.view=(config['low'],config['high']);self.inspection=None;self.wake.set()
                elif action=='page':
                    if self.overlay:self.overlay_page=max(0,self.overlay_page+value)
                    else:self.history_page=max(0,min(getattr(self,'pages',1)-1,self.history_page+value));self.inspection=None;self.wake.set()
                elif action=='depth':self.depth={30:120,120:720,720:30}[self.depth];self.history_page=0;self.inspection=None;self.wake.set()
                elif action=='contrast':self.fit_colors(self.rows);self.wake.set()
                self.message='' if action not in ('start','stop','save','apply','baseline') else self.message
            except (ValueError,OSError,KeyError) as exc:self.message=str(exc)
            return
        if not self.overlay:self.inspect(x,y)

    def draw_overlay(self,cache):
        ui=self.ui;ui.draw_logical_rect(0,80,1024,724,self.BG)
        if self.overlay=='number':
            self.text(cache,32,110,self.edit_field.upper()+(' · MHz' if self.edit_field in ('low','high') else ''),22,self.CYAN)
            self.text(cache,32,166,self.number or '0',34)
            for i,key in enumerate(('7','8','9','4','5','6','1','2','3','.','0','-')):
                x=32+i%3*180;y=210+i//3*108;self.button(cache,(x,y,x+164,y+94),key,('key',key))
            for i,key in enumerate(('DEL','CLEAR','SAVE')):self.button(cache,(650,210+i*140,984,334+i*140),key,('key',key),active=key=='SAVE')
            return
        if self.overlay=='settings':
            if self.state.get('enabled'):
                self.text(cache,40,160,'STOP THE SURVEY TO EDIT SETTINGS',26,self.CYAN)
                self.text(cache,40,204,'Your live view and saved history remain available.',19,self.MUTED)
                self.button(cache,(40,260,500,340),'STOP & EDIT',('stop',None));return
            for i,(label,action,sub) in enumerate((('PRESET',('overlay','presets'),'POPULAR RANGES'),('USB RECEIVER',('overlay','usb'),self.draft.get('selection','auto')),
                 ('START MHz',('number','low'),self.draft['low']/1e6),('END MHz',('number','high'),self.draft['high']/1e6),
                 ('GAIN dB',('number','gain'),self.draft['gain']),('PPM',('number','ppm'),self.draft['ppm']))):
                x=24+i%2*496;y=94+i//2*104;self.button(cache,(x,y,x+472,y+90),label,action,str(sub))
            for i,width in enumerate((100000,25000,5000)):self.button(cache,(24+i*330,414,338+i*330,482),str(width/1000)+' kHz BINS',('bin',width),active=self.draft['bin']==width)
            self.button(cache,(24,498,496,576),'REPEAT SWEEPS',('toggle','repeat'),'ON' if self.draft.get('repeat') else 'OFF',active=self.draft.get('repeat'))
            self.button(cache,(520,498,992,576),'OVERLOAD PROTECTION',('toggle','auto_gain'),'ON' if self.draft.get('auto_gain') else 'OFF',active=self.draft.get('auto_gain'))
            self.button(cache,(24,598,992,684),'APPLY SETTINGS',('apply',None),'START SEPARATELY WHEN READY',active=True);return
        choices=[]
        if self.overlay=='presets':choices=[(p[0],('preset',i)) for i,p in enumerate(PRESETS)]
        elif self.overlay=='usb':choices=[('Auto · free receiver',('assign','auto'))]+[(d['label'],('assign',d['id'])) for d in self.manager.devices if d.get('persistent')]
        elif self.overlay=='baselines':choices=[('No baseline',('baseline',''))]+[(d['label'],('baseline',d['id'])) for d in self.state.get('saved',[])]
        self.text(cache,32,110,self.overlay.upper(),22,self.CYAN);pages=max(1,math.ceil(len(choices)/8));self.overlay_page=min(self.overlay_page,pages-1)
        for i,(label,action) in enumerate(choices[self.overlay_page*8:(self.overlay_page+1)*8]):
            x=24+i%2*496;y=148+i//2*112;self.button(cache,(x,y,x+472,y+96),label,action)
        self.button(cache,(24,620,496,690),'PREVIOUS',('page',-1));self.button(cache,(520,620,992,690),'NEXT',('page',1))

    def draw(self,cache):
        ui=self.ui;self.actions=[]
        with self.lock:state=self.state;frame=self.frame;identity=self.frame_id;frame_view=self.frame_view
        ui.draw_logical_rect(0,0,1280,800,self.BG);ui.draw_logical_rect(0,0,1280,80,self.PANEL)
        self.text(cache,22,28,'SPECTRUM ANALYZER',26,self.CYAN);self.text(cache,22,59,'SoapySDR · spectrum survey + sweep history',14,self.MUTED)
        data=state.get('data',{});config=data.get('settings',state.get('settings',self.survey.settings));phase=state.get('run',{}).get('phase','CONNECTING')
        if self.command_pending:phase={'start':'STARTING','stop':'STOPPING','configure':'APPLYING'}.get(self.command_pending,'WORKING')
        self.text(cache,650,27,phase,23,self.CYAN if phase=='RUNNING' else self.MUTED)
        self.text(cache,650,58,f"{config['low']/1e6:g}–{config['high']/1e6:g} MHz · pass {data.get('sweep','—')} · {round(data.get('progress',0)*100)}%",14,self.MUTED,width=350)
        if not self.overlay:
            self.button(cache,(20,88,332,132),'SPECTRUM + HISTORY',('screen','chart'),active=self.screen=='chart')
            self.button(cache,(344,88,512,132),'LOGS',('screen','logs'),active=self.screen=='logs')
            self.button(cache,(524,88,760,132),'SAVE BASELINE',('save',None))
            self.button(cache,(772,88,1004,132),f'HISTORY {self.depth}',('depth',None))
        if self.overlay:self.draw_overlay(cache)
        elif self.screen=='logs':
            self.text(cache,32,164,'SURVEY ACTIVITY · UTC',22,self.CYAN)
            for i,row in enumerate(list(reversed(state.get('activity',[])))[:14]):
                self.text(cache,32,206+i*32,time.strftime('%H:%M:%S',time.gmtime(row['time']))+' '+row['action'].upper()+' · '+row['detail'],15,width=960)
            self.text(cache,32,692,'Full receiver log: cm5.local:8092/api/log?mode=spectrum&kind=receiver',14,self.MUTED)
        else:
            if frame and frame_view==self.view:self.upload(frame,identity)
            else:self.text(cache,300,270,'Updating spectrum view…',22,self.MUTED)
            lo,hi=self.limits
            for i in range(6):self.text(cache,24,172+176*i/5,f'{hi-(hi-lo)*i/5:.0f}',12,self.MUTED)
            self.text(cache,80,156,'RELATIVE dBFS/Hz · latest / peak hold / baseline',12,self.MUTED)
            if self.view:
                for i in range(7):self.text(cache,80+904*i/6-12,368,f'{(self.view[0]+(self.view[1]-self.view[0])*i/6)/1e6:.2f}',12,self.MUTED)
            self.text(cache,22,394,'SWEEP HISTORY · UTC · newest first · swipe for older rows',13,self.CYAN)
            self.text(cache,680,394,f'{self.floor} to {self.ceiling} dBFS/Hz',12,self.MUTED)
            for i,row in enumerate(self.rows):
                if i%max(1,math.ceil(len(self.rows)/5))==0:
                    label=('LIVE' if state.get('enabled') else 'PART') if row.get('partial') else time.strftime('%H:%M:%S',time.gmtime(row['finished']))
                    self.text(cache,22,414+min(20,212/max(1,len(self.rows)))*i,label,10,self.MUTED)
            if not self.rows:self.text(cache,230,508,'History starts with the next completed sweep.',20,self.MUTED)
            self.text(cache,22,640,f"{state.get('history',{}).get('count',0)} saved matching sweeps · page {self.history_page+1}/{getattr(self,'pages',1)} · up to 24 h / 720 sweeps",13,self.MUTED)
            self.draw_inspector(cache,data)
        ui.draw_logical_rect(1024,0,1280,800,self.PANEL)
        self.text(cache,1040,26,'SCAN CONTROLS',19,self.CYAN);self.text(cache,1040,58,(data.get('device') or {}).get('serial','NO RECEIVER'),13,self.MUTED,width=224)
        self.button(cache,(1034,84,1270,152),'STOP' if state.get('enabled') else 'START',('stop' if state.get('enabled') else 'start',None),phase,active=state.get('enabled',False))
        self.button(cache,(1034,162,1270,230),'SCAN SETTINGS',('overlay','settings'),f"{config['bin']/1000:g} kHz · {config['gain']:g} dB")
        self.button(cache,(1034,240,1148,306),'ZOOM +',('zoom',.5));self.button(cache,(1156,240,1270,306),'ZOOM −',('zoom',2))
        self.button(cache,(1034,316,1270,382),'FULL RANGE',('full',None))
        self.button(cache,(1034,392,1148,458),'NEWER',('page',-1));self.button(cache,(1156,392,1270,458),'OLDER',('page',1))
        self.button(cache,(1034,468,1270,534),'AUTO CONTRAST',('contrast',None))
        self.button(cache,(1034,544,1270,610),'BASELINE OVERLAY',('overlay','baselines'),'MATCHED' if matching(data,self.baseline) else 'SELECT SAVED SWEEP')
        self.text(cache,1040,640,'Orange: clipping excluded',12,self.MUTED);self.text(cache,1040,665,'Dark: no measurement',12,self.MUTED)
        self.button(cache,(1034,728,1270,792),'BACK',('back',None))
        self.text(cache,22,746,self.message or state.get('detail','Loading shared survey…'),14,self.MUTED,width=980)
        self.text(cache,22,780,'SAME RECEIVER + HISTORY AS cm5.local:8092/spectrum · one row per stepped sweep',12,self.MUTED,width=980)

    def draw_inspector(self,cache,data):
        selection=self.inspection
        if not selection:self.text(cache,22,677,'Tap a spectrum bin or a historical row to inspect frequency, level and EU/US allocations.',16,self.MUTED);return
        frequency=selection['frequency'];row=selection['row'];code=selection['code']
        if row:
            level='No measurement' if code==0 else 'Clipping excluded' if code==1 else f'≈ {code-202} dBFS/Hz · column peak'
            stamp=('Partial · ' if row.get('partial') else 'Sweep '+str(row['sweep'])+' · ')+time.strftime('%d %b %H:%M:%S',time.gmtime(row['started']))+'–'+time.strftime('%H:%M:%S UTC',time.gmtime(row['finished']))
        else:
            config=data.get('settings',{});index=int((frequency-config.get('low',0))/config.get('bin',1));power=data.get('power',[])
            value=power[index] if 0<=index<len(power) else None
            level=f'{value:.1f} dBFS/Hz' if value is not None else 'Clipping excluded' if 0<=index<len(data.get('masked',[])) and data['masked'][index] else 'Not sampled yet';stamp='Latest sweep'
        self.text(cache,22,668,f'{frequency/1e6:.6f} MHz · {level} · {stamp}',16,self.CYAN,width=980)
        for i,line in enumerate(allocations(self.reference,frequency)):self.text(cache,22,693+i*23,line,13,self.MUTED,width=980)

    def close(self):
        self.open=False;self.closed.set();self.wake.set()
        if self.worker:self.worker.join(timeout=2)
        if self.texture is not None:self.ui.GL.glDeleteTextures([self.texture]);self.texture=None
