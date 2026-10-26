"""Native touch spectrum analyzer, sharing the browser survey and saved sweeps."""
import base64
import json
import math
from pathlib import Path
import queue
import threading
import time
import theme_system
from decoder_style import DecoderStyle, footer_content_box
from dongle_workspace import DongleWorkspace
from usb_radio_controls import receiver_rows
from usb_radios import choices as radio_choices
import textwrap

import numpy as np
from PIL import Image, ImageDraw
from spectrum_analysis import reduce_values
from spectrum_report import comparison
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


class SpectrumWorkspace(DecoderStyle, SSTVWorkspace):
    """Touch-first Survey → Signals → Investigate workflow; no browser embedding."""
    GRAPH=(24,236,1256,616);PLOT=(92,272,1240,568);HISTORY=(124,272,1240,608)
    TABS=(('survey','Scan'),('signals','Signals'),('tools','Tools'))
    def __init__(self,ui,hub):
        super().__init__(ui,hub)
        self.dongles=DongleWorkspace(ui,hub)
        self.survey=hub.spectrum;self.state={};self.view=None;self.view_key=None;self.frame_view=None;self.frame_kind=None
        self.screen='survey';self.display='spectrum';self.activity_mode='activity';self.report_mode='reports';self.watch_mode='frequencies';self.exit_target='digi'
        self.overlay=None;self.draft={};self.number='';self.edit_field='low';self.overlay_page=0;self.label_value='';self.label_target='watch_label'
        self.selected=None;self.selected_watch=None;self.inspection=None;self.baseline=None;self.compare_data={};self.page=0;self.history_page=0;self.depth=120
        self.floor=-120;self.ceiling=-70;self.auto_key=None;self.rows=[];self.insights={};self.frame=None;self.frame_id=0;self.texture=None;self.uploaded=-1;self.limits=(-140,-60)
        self.command_pending='';self.lock=threading.RLock();self.commands=queue.Queue();self.wake=threading.Event();self.closed=threading.Event();self.worker=None;self.last_paint_key=None;self.prepare_count=0;self.drag=None;self.sort='excess';self.last_report=None
        try:self.reference=json.loads(Path(__file__).with_name('spectrum_allocations.json').read_text())
        except (OSError,ValueError):self.reference={}

    def button(self,cache,box,title,action,subtitle='',active=False):
        self.decoder_button(cache,box,title,action,subtitle,active,font_size=21)

    def show(self):
        self.open=True;self.overlay=None;self.message='';self.inspection=None;self.exit_target='digi'
        if not self.worker:
            self.worker=threading.Thread(target=self.run,name='spectrum-touch',daemon=True);self.worker.start()
        self.wake.set()

    def request(self,action,**values):
        if self.command_pending:return
        self.command_pending=action;self.message='';self.commands.put((action,values));self.wake.set()

    def run(self):
        history=[];history_key=None;after=0;revision=None;analysis_key=None;analysis_at=0
        while not self.closed.is_set():
            live=self.state.get('settings',{}).get('purpose')=='investigate'
            self.wake.wait(.12 if live else .3);self.wake.clear()
            if not self.open and self.commands.empty():continue
            try:
                while not self.commands.empty():
                    action,values=self.commands.get_nowait()
                    try:
                        if action=='baseline':self.baseline=self.survey.trace(values['id']) if values['id'] else None
                        else:
                            result=self.survey.control(action,**values)
                            if action=='report':self.last_report=result
                        self.message='Baseline saved.' if action=='save' else 'Report saved. Open Reports on the web to download or print.' if action=='report' else ''
                    except (ValueError,OSError,RuntimeError) as exc:self.message=str(exc)
                    finally:self.command_pending=''
                state=self.survey.native_snapshot();data=state['data'];config=data.get('settings',state['settings'])
                with self.lock:
                    key=(config['low'],config['high'],config['bin'])
                    if key!=self.view_key:self.view=(config['low'],config['high']);self.view_key=key;self.history_page=0;self.inspection=None
                    view=self.view
                scope='survey' if self.screen=='signals' and state.get('can_return') else 'current'
                next_analysis=(scope,state['history']['key'],view if scope=='current' else None)
                detail='persistence' if self.screen=='activity' and self.activity_mode=='persistence' else 'timeline' if self.screen=='activity' else 'signals'
                next_analysis+=(detail,)
                if self.screen in ('signals','activity') and (next_analysis!=analysis_key or time.monotonic()-analysis_at>3):
                    values={} if scope=='survey' else dict(low=view[0],high=view[1])
                    context=self.survey.context(scope) if scope=='survey' else {k:data[k] for k in ('settings','device','rate','fft') if k in data}
                    self.insights=self.survey.insights.snapshot(context,columns=512,history=self.survey.history,detail=detail,**values);analysis_at=time.monotonic();analysis_key=next_analysis
                if self.screen=='watch' and self.watch_mode=='events':self.insights=dict(self.insights,events=self.survey.insights.events())
                rows=[]
                if self.screen=='survey' and self.display=='waterfall':
                    next_history=(state['history']['key'],view)
                    if next_history!=history_key:history=[];after=0;history_key=next_history;revision=None
                    current_revision=(state['history']['latest_id'],state['history']['count'])
                    if current_revision!=revision:
                        value=self.survey.history.read(data,after=after,low=view[0],high=view[1],columns=640,raw=True)
                        for row in value['rows']:row['values']=np.asarray(row['values'],dtype=np.uint8);history.append(row)
                        history=[r for r in history if r['finished']>=time.time()-86400][-720:];after=value['latest_id'];revision=current_revision
                    rows=list(reversed(history))[:self.depth]
                    if data.get('updated') and not data.get('complete') and data['updated']>=data.get('sweep_started',data.get('started',0)):
                        rows.insert(0,dict(partial=True,started=data.get('sweep_started',data['started']),finished=data['updated'],values=columns(data,'power',view,640)))
                elif self.screen=='activity':
                    if self.activity_mode=='persistence':rows=list(reversed(self.insights.get('persistence',[])))
                    else:
                        for row in reversed(self.insights.get('timeline',[])):
                            item=dict(row)
                            if self.activity_mode in ('peak','mean'):item['values']=np.frombuffer(base64.b64decode(row['mean' if self.activity_mode=='mean' else 'values']),np.uint8).copy()
                            rows.append(item)
                density=self.screen=='activity' and self.activity_mode=='persistence'
                pages=1 if density else max(1,math.ceil(len(rows)/30));page=min(self.history_page,pages-1);visible=rows if density else rows[page*30:(page+1)*30]
                if rows and isinstance(rows[0],dict) and self.auto_key!=state['history']['key'] and self.screen=='survey':self.fit_colors(rows);self.auto_key=state['history']['key']
                if self.screen=='compare':self.compare_data=self.survey.comparison_data()
                paint_kind=(self.screen,self.display,self.activity_mode)
                paint_key=(theme_system.runtime_revision,paint_kind,view,data.get('updated'),data.get('sweep'),state['history']['latest_id'],state['history']['key'],self.insights.get('finished'),page,self.floor,self.ceiling,(self.baseline or {}).get('id'))
                frame=self.frame;limits=self.limits
                changed=paint_key!=self.last_paint_key
                if changed and self.screen in ('survey','activity','compare'):
                    source=self.compare_data if self.screen=='compare' else data
                    frame,limits=self.prepare_native(source,visible,view)
                    self.last_paint_key=paint_key;self.prepare_count+=1
                with self.lock:
                    self.state=state;self.rows=visible;self.pages=pages;self.history_page=page
                    if changed and self.screen in ('survey','activity','compare'):
                        self.frame=frame;self.frame_view=view;self.frame_kind=paint_kind;self.frame_id+=1;self.limits=limits
            except Exception as exc:self.message='Analyzer: '+str(exc)

    def fit_colors(self,rows):
        counts=np.zeros(256,dtype=np.int64)
        for row in rows:
            if 'values' in row:counts+=np.bincount(row['values'],minlength=256)
        counts[:2]=0;total=counts.sum()
        if not total:return
        cumulative=counts.cumsum();lo=int(np.searchsorted(cumulative,total*.1))-202;hi=int(np.searchsorted(cumulative,total*.998))-202
        self.floor=max(-180,min(-70,math.floor(lo/5)*5));self.ceiling=min(-20,max(-120,self.floor+20,math.ceil(hi/5)*5))

    def paint(self,data,rows,view):
        image=Image.new('RGBA',(1232,380),self.color('spectrum_field'));draw=ImageDraw.Draw(image);left,right,top,bottom=68,1216,36,332
        finite=[v for v in data.get('peak',[]) if isinstance(v,(int,float)) and math.isfinite(v)];hi=min(-10,math.ceil(max(finite)/10)*10+5) if finite else -60;lo=min(hi-30,max(-180,math.floor(min(finite)/10)*10-5)) if finite else -140
        if self.screen=='compare':
            result=comparison(data,self.baseline);values=[v for v in result.get('delta',[]) if v is not None];hi=max(5,max((abs(v) for v in values),default=5));lo=-hi
        if self.screen in ('survey','compare') and (self.screen=='compare' or self.display=='spectrum'):
            for i in range(5):
                y=top+(bottom-top)*i/4;draw.line((left,y,right,y),fill=self.color('spectrum_grid')[:3],width=1)
            for i in range(7):
                x=left+(right-left)*i/6;draw.line((x,top,x,bottom),fill=self.color('spectrum_grid')[:3],width=1)
            def line(values,color):
                points=[]
                for x,value in enumerate(values):
                    if value is None:
                        if len(points)>1:draw.line(points,fill=color,width=2)
                        points=[];continue
                    points.append((left+x,top+(hi-max(lo,min(hi,value)))/(hi-lo)*(bottom-top)))
                if len(points)>1:draw.line(points,fill=color,width=2)
            def series(source,field):
                values=np.array([float(v) if v is not None else np.nan for v in source.get(field,[])])
                if not len(values):return [None]*1148
                mask=source.get('masked',[])
                if len(mask)==len(values):values[np.asarray(mask,bool)]=np.nan
                return reduce_values(values,source['settings'],view[0],view[1],1148)
            if self.screen=='compare':
                if result['matched']:
                    zero=top+hi/(hi-lo)*(bottom-top);draw.line((left,zero,right,zero),fill=self.color('spectrum_axis')[:3],width=2)
                    line(series(dict(data,delta=result['delta']),'delta'),self.color('spectrum_line')[:3])
            else:
                line(series(data,'peak'),self.color('spectrum_peak_line')[:3]);line(series(data,'power'),self.color('spectrum_line')[:3])
                if matching(data,self.baseline):line(series(self.baseline,'average'),self.color('focus')[:3])
                for x,code in enumerate(columns(data,'power',view,1148)):
                    if code==1:draw.line((left+x,top,left+x,bottom),fill=(187,119,57),width=1)
        elif rows:
            kind=self.activity_mode if self.screen=='activity' else 'peak'
            if kind=='persistence':
                values=np.asarray(rows,float);t=np.sqrt(values/max(1,self.insights.get('persistence_visits',1)))*4
                missing=np.zeros(values.shape,bool);clipped=missing
            elif kind=='activity':
                values=np.array([[float(v) if v is not None else np.nan for v in r['activity']] for r in rows]);missing=~np.isfinite(values);clipped=np.zeros(values.shape,bool);t=np.nan_to_num(values)/100*4
            else:
                values=np.vstack([r['values'] for r in rows]);missing=values==0;clipped=values==1;t=(values.astype(float)-202-self.floor)/max(5,self.ceiling-self.floor)*4
            t=np.clip(t,0,4);index=np.minimum(3,t.astype(int));f=(t-index)[...,None];rgb=(PALETTE[index]*(1-f)+PALETTE[index+1]*f).astype('uint8');rgb[missing]=(29,38,47);rgb[clipped]=(232,148,72)
            height=336 if kind=='persistence' else min(336,len(rows)*16)
            signal=Image.fromarray(rgb).convert('RGBA')
            mapper=getattr(self.ui,'themed_waterfall_pixels',None)
            mapped=mapper(signal.tobytes()) if callable(mapper) else None
            if isinstance(mapped,bytes):signal=Image.frombytes('RGBA',signal.size,mapped)
            image.paste(signal.resize((1116,height),Image.Resampling.NEAREST),(100,36))
        return image.tobytes(),(lo,hi)

    def prepare_native(self,data,rows,view):
        if self.screen=='activity' or self.display=='waterfall' and self.screen!='compare':
            return self.paint(data,rows,view)
        result=comparison(data,self.baseline) if self.screen=='compare' else None
        values=[v for v in (result.get('delta',[]) if result else data.get('peak',[])) if isinstance(v,(int,float)) and math.isfinite(v)]
        hi=max(5,max((abs(v) for v in values),default=5)) if result else min(-10,math.ceil(max(values)/10)*10+5) if values else -60
        lo=-hi if result else min(hi-30,max(-180,math.floor(min(values)/10)*10-5)) if values else -140
        lines=[]
        def series(source,field,color):
            a=np.asarray([float(v) if v is not None else np.nan for v in source.get(field,[])])
            if not len(a):return
            mask=source.get('masked',[])
            if len(mask)==len(a):a[np.asarray(mask,bool)]=np.nan
            reduced=reduce_values(a,source['settings'],view[0],view[1],1148)
            segments=[];segment=[]
            for x,v in enumerate(reduced):
                if v is None:
                    if len(segment)>1:segments.append(segment)
                    segment=[]
                else:segment.append((92+x,272+(hi-max(lo,min(hi,v)))/(hi-lo)*296))
            if len(segment)>1:segments.append(segment)
            lines.append((segments,color))
        if result:
            if result['matched']:series(dict(data,delta=result['delta']),'delta',self.color('spectrum_line'))
        else:
            series(data,'peak',self.color('spectrum_peak_line'));series(data,'power',self.color('spectrum_line'))
            if matching(data,self.baseline):series(self.baseline,'average',self.color('focus'))
        excluded=columns(data,'power',view,1148)==1 if not result else np.zeros(1148,bool)
        edges=np.diff(np.r_[False,excluded,False].astype(int))
        bands=list(zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))
        return dict(native=True,lines=lines,bands=bands,zero=272+hi/(hi-lo)*296 if result else None),(lo,hi)

    def draw_native_chart(self,frame):
        ui=self.ui;ui.draw_logical_rect(*self.GRAPH,self.color('spectrum_field'))
        for i in range(5):ui.draw_logical_polyline([(92,272+296*i/4),(1240,272+296*i/4)],self.color('spectrum_grid'),1)
        for i in range(7):ui.draw_logical_polyline([(92+1148*i/6,272),(92+1148*i/6,568)],self.color('spectrum_grid'),1)
        for first,last in frame['bands']:ui.draw_logical_rect(92+int(first),272,92+int(last),568,(125,78,39,150))
        if frame['zero'] is not None:ui.draw_logical_polyline([(92,frame['zero']),(1240,frame['zero'])],self.color('spectrum_axis'),2)
        for segments,color in frame['lines']:
            for segment in segments:ui.draw_logical_polyline(segment,color,2)

    def upload(self,frame,identity):
        if isinstance(frame,dict):self.draw_native_chart(frame);return
        gl=self.ui.GL
        if self.texture is None:self.texture=gl.glGenTextures(1)
        if identity!=self.uploaded:
            gl.glBindTexture(gl.GL_TEXTURE_2D,self.texture)
            for flag in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_NEAREST)
            gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,1232,380,0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,frame);self.uploaded=identity
        self.ui.draw_textured_quad(self.texture,*self.GRAPH,0,0,1,1)

    def inspect(self,x,y):
        if not self.view or self.frame_view!=self.view:return
        box=self.PLOT if self.screen=='compare' or self.screen=='survey' and self.display=='spectrum' else self.HISTORY
        if not self.ui.contains(box,x,y):return
        row=None;code=None;frequency=self.view[0]+max(0,min(1,(x-box[0])/(box[2]-box[0])))*(self.view[1]-self.view[0])
        if box==self.HISTORY and self.rows:
            height=336 if self.activity_mode=='persistence' and self.screen=='activity' else min(336,len(self.rows)*16)
            index=int((y-box[1])/height*len(self.rows))
            if not 0<=index<len(self.rows):return
            row=self.rows[index]
            if isinstance(row,dict) and 'values' in row:code=int(row['values'][min(len(row['values'])-1,int((x-box[0])/(box[2]-box[0])*len(row['values'])))])
        self.selected=frequency;self.inspection=dict(frequency=frequency,row=row,code=code)

    def drag_begin(self,x,y):self.drag=(x,y,self.view);self.inspect(x,y)
    def drag_move(self,sx,sy,x,y):
        if self.overlay or not self.drag or not self.view or self.screen not in ('survey','activity','compare'):return
        if abs(x-sx)>24 and abs(x-sx)>abs(y-sy)*1.5 and 236<=sy<=616:
            old=self.drag[2];config=self.state.get('data',{}).get('settings',self.state.get('settings',{}))
            if not old or not config:return
            span=old[1]-old[0];low=max(config['low'],min(config['high']-span,old[0]-(x-sx)/1148*span));self.view=(low,low+span);self.inspection=None;self.wake.set()
    def swipe(self,sx=None,sy=None,x=None,y=None):
        if sx is None:return False
        if abs(y-sy)>60 and abs(y-sy)>abs(x-sx)*1.5:
            field='overlay_page' if self.overlay in ('presets','usb','baselines') else 'history_page' if self.screen in ('survey','activity') else 'page'
            setattr(self,field,max(0,getattr(self,field)+(1 if y<sy else -1)));self.wake.set();return True
        return abs(x-sx)>24

    def zoom(self,scale):
        if not self.view:return
        config=self.state.get('data',{}).get('settings',self.state.get('settings',{}))
        if not config:return
        center=self.selected if self.selected is not None else sum(self.view)/2
        span=min(config['high']-config['low'],max(config['bin']*20,(self.view[1]-self.view[0])*scale));low=max(config['low'],min(config['high']-span,center-span/2))
        self.view=(low,low+span);self.inspection=None;self.history_page=0;self.wake.set()

    def tap(self,x,y):
        if self.dongles.open:return self.dongles.tap(x,y)
        for box,(action,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            try:
                if action=='home':
                    self.overlay=None;self.exit_target='home';self.open=False
                elif action=='back':
                    if self.overlay:self.overlay='report' if self.overlay=='label' and self.label_target.startswith('report_') else 'watch' if self.overlay=='label' or self.overlay=='number' and self.edit_field.startswith('watch_') else 'settings' if self.overlay in ('presets','usb','advanced') or self.overlay=='number' and self.edit_field!='focus' else None
                    elif self.screen in ('activity','compare','watch','reports'):self.screen='tools';self.page=0
                    elif self.screen!='survey':self.screen='survey';self.page=0
                    else:self.exit_target='digi';self.open=False
                elif action=='screen':self.screen=value;self.page=0;self.history_page=0;self.overlay=None;self.inspection=None
                elif action=='display':self.display=value;self.history_page=0
                elif action=='activity':self.activity_mode=value;self.history_page=0
                elif action in ('start','stop','return','watch_start'):self.request(action)
                elif action=='investigate':
                    if self.selected is None:self.edit_field='focus';self.number=str(sum(self.view)/2e6) if self.view else '100';self.overlay='number'
                    else:self.request('investigate',frequency=self.selected);self.screen='survey';self.display='spectrum';self.overlay=None
                elif action=='overlay':
                    self.overlay=value;self.overlay_page=0
                    if value=='settings':self.draft=dict(self.state.get('settings',self.survey.settings));self.edit_field='low'
                    if value=='watch':self.draft.update(watch_frequency=self.selected or (sum(self.view)/2 if self.view else 100e6),watch_width=25000,watch_label='')
                elif action=='settings_back':self.overlay='settings'
                elif action=='number':
                    self.edit_field=value;self.number=str(self.draft[value]/1e6 if value in ('low','high','watch_frequency') else self.draft[value]/1000 if value=='watch_width' else self.draft[value]);self.overlay='number'
                elif action=='key':
                    if value=='DEL':self.number=self.number[:-1]
                    elif value=='CLEAR':self.number=''
                    elif value=='SAVE':
                        number=float(self.number)
                        if not math.isfinite(number):raise ValueError('Enter a finite number')
                        if self.edit_field=='focus':self.request('investigate',frequency=number*1e6);self.overlay=None;self.screen='survey';self.display='spectrum'
                        else:
                            self.draft[self.edit_field]=number*(1e6 if self.edit_field in ('low','high','watch_frequency') else 1000 if self.edit_field=='watch_width' else 1);self.overlay='watch' if self.edit_field.startswith('watch_') else 'advanced' if self.edit_field in ('gain','ppm') else 'settings'
                    elif len(self.number)<16:self.number+=value
                elif action=='label':self.label_target=value or 'watch_label';self.label_value=self.draft.get(self.label_target,'');self.overlay='label'
                elif action=='letter':
                    if value=='DEL':self.label_value=self.label_value[:-1]
                    elif value=='SAVE':self.draft[self.label_target]=self.label_value;self.overlay='report' if self.label_target.startswith('report_') else 'watch'
                    elif len(self.label_value)<(200 if self.label_target=='report_notes' else 60):self.label_value+=value
                elif action=='apply':
                    from spectrum_monitor import settings
                    values={k:v for k,v in self.draft.items() if not k.startswith('watch_')}
                    if math.ceil((values['high']-values['low'])/values['bin'])>20000:
                        values['bin']=next((b for b in (5000,25000,100000) if math.ceil((values['high']-values['low'])/b)<=20000),100000)
                    settings(values);self.request('survey_start' if value else 'configure',**values);self.overlay=None;self.screen='survey'
                elif action=='preset':
                    _,low,high,width=PRESETS[value];self.draft.update(low=low,high=high,bin=width);self.overlay='settings'
                elif action=='toggle':self.draft[value]=not self.draft.get(value,False)
                elif action=='bin':self.draft['bin']={100000:25000,25000:5000,5000:100000}.get(self.draft['bin'],100000)
                elif action=='usb_manage':self.dongles.show()
                elif action=='assign':self.draft['selection']=value;self.overlay='settings'
                elif action=='baseline':self.request('baseline',id=value);self.overlay=None
                elif action=='save':self.request('save',label='Antenna baseline '+time.strftime('%d %b %H:%M UTC',time.gmtime()))
                elif action=='report':
                    if self.overlay=='report':self.request('report',label=self.draft['report_label'],notes=self.draft['report_notes'],baseline_id=(self.baseline or {}).get('id',''));self.overlay=None;self.screen='reports'
                    else:self.draft.update(report_label='RF survey '+time.strftime('%d %b %H:%M UTC',time.gmtime()),report_notes='');self.overlay='report'
                elif action=='zoom':self.zoom(value)
                elif action=='full':
                    c=self.state.get('data',{}).get('settings',self.state['settings']);self.view=(c['low'],c['high']);self.selected=None;self.inspection=None
                elif action=='page':
                    field='overlay_page' if self.overlay else 'history_page' if self.screen in ('survey','activity') else 'page';setattr(self,field,max(0,getattr(self,field)+value))
                elif action=='depth':self.depth={30:120,120:720,720:30}[self.depth];self.history_page=0
                elif action=='contrast':self.fit_colors(self.rows)
                elif action=='select_signal':self.selected=value;self.inspection=dict(frequency=value,row=None,code=None)
                elif action=='sort':self.sort={'excess':'activity','activity':'last','last':'excess'}[self.sort]
                elif action=='select_watch':self.selected_watch=value;watch=next(w for w in self.state['watchlist'] if w['id']==value);self.selected=watch['frequency']
                elif action=='watch_add':self.request('watch_add',frequency=self.draft['watch_frequency'],bandwidth=self.draft['watch_width'],label=self.draft.get('watch_label',''));self.overlay=None;self.screen='watch'
                elif action=='watch_remove':
                    if self.selected_watch:self.request('watch_remove',id=self.selected_watch);self.selected_watch=None
                    else:self.message='Select a watchlist row first.'
                elif action=='watch_view':self.watch_mode=value;self.page=0
                elif action=='report_view':self.report_mode=value;self.page=0
                self.wake.set()
            except (ValueError,OSError,KeyError,StopIteration) as exc:self.message=str(exc)
            return
        if not self.overlay:self.inspect(x,y)

    def draw_overlay(self,cache):
        if self.overlay=='report':
            self.text(cache,32,142,'Export your survey',34,self.CYAN)
            self.button(cache,(24,218,1256,326),'Report title',('label','report_label'),self.draft['report_label'])
            self.button(cache,(24,350,1256,458),'Antenna and cable notes',('label','report_notes'),self.draft['report_notes'] or 'Optional · antenna, coax, placement, changes')
            self.text(cache,32,514,'Includes measured spectrum, history, signals and receiver settings.',23,self.MUTED)
            self.button(cache,(24,600,1256,690),'Generate report',('report',None),active=True);return
        if self.overlay=='info':
            self.text(cache,32,142,f'{(self.selected or 0)/1e6:.6f} MHz',38,self.CYAN)
            self.text(cache,32,204,'Allocation reference · not a decoded transmitter identity',23,self.MUTED)
            for index,line in enumerate(allocations(self.reference,self.selected or 0)):
                for j,part in enumerate(textwrap.wrap(line,90)[:5]):self.text(cache,32,270+index*158+j*28,part,22,self.CYAN if j==0 else self.MUTED)
            self.button(cache,(24,624,616,704),'Investigate this band →',('investigate',None),active=True)
            self.button(cache,(640,624,1256,704),'+ Add to watchlist',('overlay','watch'));return
        if self.overlay=='number':
            names=dict(low='Survey start · MHz',high='Survey end · MHz',gain='Maximum gain · dB',ppm='Frequency correction · PPM',focus='Investigate a frequency · MHz',watch_frequency='Watch frequency · MHz',watch_width='Watch bandwidth · kHz')
            self.text(cache,32,136,names.get(self.edit_field,self.edit_field),30,self.CYAN);self.text(cache,32,200,self.number or '0',40)
            for i,key in enumerate(('7','8','9','4','5','6','1','2','3','.','0','-')):
                x=32+i%3*240;y=250+i//3*110;self.button(cache,(x,y,x+220,y+92),key,('key',key))
            for i,key in enumerate(('DEL','CLEAR','SAVE')):self.button(cache,(820,250+i*145,1248,374+i*145),key,('key',key),active=key=='SAVE')
            return
        if self.overlay=='label':
            self.text(cache,32,140,'Enter report notes' if self.label_target.startswith('report_') else 'Name this watched frequency',30,self.CYAN);self.text(cache,32,205,self.label_value[-70:] or 'Type with the keyboard',30,width=1180)
            for row,letters in enumerate(('QWERTYUIOP','ASDFGHJKL','ZXCVBNM')):
                for i,key in enumerate(letters):
                    x=24+i*122;top=274+row*100;self.button(cache,(x,top,x+112,top+84),key,('letter',key))
            self.button(cache,(24,600,740,684),'Space',('letter',' '));self.button(cache,(752,600,978,684),'Delete',('letter','DEL'));self.button(cache,(990,600,1256,684),'Save name',('letter','SAVE'),active=True);return
        if self.overlay=='watch':
            self.text(cache,32,142,'Add a frequency to your watchlist',30,self.CYAN)
            self.button(cache,(24,218,616,326),'Frequency',('number','watch_frequency'),f"{self.draft['watch_frequency']/1e6:.6f} MHz")
            self.button(cache,(640,218,1256,326),'Measurement bandwidth',('number','watch_width'),f"{self.draft['watch_width']/1000:g} kHz")
            self.button(cache,(24,350,1256,458),'Name',('label',None),self.draft.get('watch_label') or 'Optional · defaults to frequency')
            self.text(cache,32,510,'Normal surveys observe this frequency when it is in range.',22,self.MUTED)
            self.text(cache,32,552,'Watch mode revisits saved bands and logs changes.',22,self.MUTED)
            self.button(cache,(24,600,1256,690),'Add to watchlist',('watch_add',None),active=True);return
        if self.overlay=='advanced':
            self.text(cache,24,144,'Advanced receiver settings',30,self.CYAN)
            self.button(cache,(24,210,616,326),'Gain limit',('number','gain'),f"{self.draft['gain']:g} dB")
            self.button(cache,(640,210,1256,326),'Frequency correction',('number','ppm'),f"{self.draft['ppm']:g} PPM")
            self.button(cache,(24,350,616,466),'Resolution',('bin',None),f"{self.draft['bin']/1000:g} kHz bins")
            self.button(cache,(640,350,1256,466),'Overload protection',('toggle','auto_gain'),'On' if self.draft.get('auto_gain') else 'Off',active=self.draft.get('auto_gain',False))
            self.text(cache,24,528,'Protection lowers gain automatically; clipped data stays excluded.',22,self.MUTED)
            self.button(cache,(24,608,1256,688),'Done · back to scan setup',('settings_back',None),active=True);return
        if self.overlay=='settings':
            if self.state.get('enabled'):
                self.text(cache,40,180,'Stop reception to change the survey.',32,self.CYAN)
                self.text(cache,40,236,'Saved measurements and history will remain available.',24,self.MUTED)
                self.button(cache,(40,310,760,404),'Stop and edit settings',('stop',None),active=True);return
            self.text(cache,24,144,'Choose what to survey.',30,self.CYAN)
            for i,(label,action,sub) in enumerate((('Range preset',('overlay','presets'),'Full / FM / Airband / VHF / UHF'),('USB radio',('overlay','usb'),next((r['name'] for r in radio_choices(self.manager.devices,selection=self.draft.get('selection','auto')) if r['selected']),'Auto')),
                 ('Start frequency',('number','low'),f"{self.draft['low']/1e6:g} MHz"),('End frequency',('number','high'),f"{self.draft['high']/1e6:g} MHz"))):
                x=24+i%2*624;y=180+i//2*108;self.button(cache,(x,y,x+608,y+92),label,action,sub)
            self.button(cache,(24,408,616,496),'Repeat: '+('On' if self.draft.get('repeat') else 'Off'),('toggle','repeat'),active=self.draft.get('repeat',False))
            self.button(cache,(640,408,1256,496),'Advanced settings',('overlay','advanced'),'Gain, resolution, PPM and overload protection')
            self.text(cache,24,544,f"{self.draft['bin']/1000:g} kHz bins · gain limit {self.draft['gain']:g} dB · protection "+('on' if self.draft.get('auto_gain') else 'off'),22,self.MUTED)
            self.button(cache,(24,608,616,688),'Apply settings',('apply',False));self.button(cache,(640,608,1256,688),'Apply and start survey',('apply',True),active=True);return
        choices=[]
        if self.overlay=='presets':choices=[(p[0],('preset',i)) for i,p in enumerate(PRESETS)]
        elif self.overlay=='usb':
            self.text(cache,24,142,'Choose a USB radio',30,self.CYAN)
            self.overlay_page,last=receiver_rows(self,cache,self.manager.devices,self.manager.broker.snapshot(),'spectrum',self.draft.get('selection','auto'),self.overlay_page,top=186)
            self.button(cache,(24,648,420,712),'USB-Radios',('usb_manage',None))
            if last:
                self.button(cache,(436,648,824,712),'Previous',('page',-1));self.button(cache,(840,648,1256,712),'Next',('page',1))
            return
        elif self.overlay=='baselines':choices=[('No baseline',('baseline',''))]+[(d['label'],('baseline',d['id'])) for d in self.state.get('saved',[])]
        self.text(cache,24,142,{'presets':'Survey ranges','usb':'Choose a receiver','baselines':'Choose antenna reference A'}.get(self.overlay,self.overlay),30,self.CYAN)
        last=max(0,math.ceil(len(choices)/8)-1);self.overlay_page=min(self.overlay_page,last)
        for i,(label,action) in enumerate(choices[self.overlay_page*8:(self.overlay_page+1)*8]):
            x=24+i%2*624;y=186+i//2*108;self.button(cache,(x,y,x+608,y+92),label,action)
        self.button(cache,(24,648,616,712),'Previous',('page',-1));self.button(cache,(640,648,1256,712),'Next',('page',1))

    def draw(self,cache):
        if self.dongles.open:return self.dongles.draw(cache)
        ui=self.ui;self.actions=[]
        with self.lock:state=self.state;frame=self.frame;identity=self.frame_id;frame_view=self.frame_view
        data=state.get('data',{});config=data.get('settings',state.get('settings',self.survey.settings));purpose=state.get('settings',{}).get('purpose','survey');phase=state.get('run',{}).get('phase','CONNECTING')
        pending=self.command_pending
        if pending:phase={'start':'STARTING','survey_start':'STARTING','configure':'APPLYING','watch_start':'STARTING WATCH','stop':'STOPPING','investigate':'TUNING','return':'RETURNING','report':'EXPORTING'}.get(pending,'WORKING')
        ui.draw_logical_rect(0,0,1280,800,self.BG);ui.draw_logical_rect(0,0,1280,78,self.PANEL)
        self.text(cache,24,28,'SPECTRUM',30,self.CYAN);self.text(cache,280,28,{'survey':'Broad survey','investigate':'Live investigation','watch':'Watch mode'}[purpose],22)
        self.text(cache,24,60,f"{config['low']/1e6:g}–{config['high']/1e6:g} MHz · {config['bin']/1000:g} kHz bins · {config['gain']:g} dB gain",18,self.MUTED,width=650)
        self.text(cache,558,28,phase,19,self.CYAN if phase=='RUNNING' else self.MUTED,width=126)
        self.draw_back(cache)
        self.button(cache,(1130,10,1256,68),'Home',('home',None))
        if self.overlay:
            self.draw_overlay(cache)
        else:
            self.button(cache,(704,10,836,68),'Stop' if state.get('enabled') else 'Start',('stop' if state.get('enabled') else 'start',None),active=state.get('enabled',False))
            self.button(cache,(848,10,980,68),'Setup',('overlay','settings'))
            for i,(key,label) in enumerate(self.TABS):
                x=24+i*(1232/3);self.button(cache,(x,88,x+1232/3-12,152),label,('screen',key),active=self.screen==key or key=='tools' and self.screen not in ('survey','signals'))
            if self.screen in ('survey','activity','compare'):
                self.draw_graph(cache,data,config,frame,identity,frame_view)
            elif self.screen=='signals':self.draw_signals(cache)
            elif self.screen=='watch':self.draw_watch(cache)
            elif self.screen=='tools':self.draw_tools(cache)
            else:self.draw_reports(cache,state)
        age=state.get('run',{}).get('last_sample_age');detail=('Last IQ '+f'{age:.1f}s ago') if state.get('enabled') and age is not None else 'Measurements retained · receiver idle'
        self.draw_status(cache,self.message,detail+' · USB '+(data.get('device') or {}).get('serial','—'),full_width=True)
        if not self.message and not self.overlay:self.draw_inspector(cache,data)

    def draw_graph(self,cache,data,config,frame,identity,frame_view):
        if self.screen=='compare':data=self.compare_data
        if self.screen=='survey':
            self.button(cache,(24,166,320,222),'Spectrum',('display','spectrum'),active=self.display=='spectrum');self.button(cache,(332,166,628,222),'Recent waterfall',('display','waterfall'),active=self.display=='waterfall')
            self.text(cache,656,196,f"Frame {data.get('sweep','—')}" if config.get('purpose')=='investigate' else f"Pass {data.get('sweep','—')} · {round(data.get('progress',0)*100)}%",22,self.MUTED)
            if self.state.get('can_return'):self.button(cache,(932,166,1256,222),'← Return to '+('watchlist' if self.state.get('return_to')=='watch' else 'survey'),('return',None),active=True)
        elif self.screen=='activity':
            for i,(key,label) in enumerate((('activity','Activity heatmap'),('persistence','Persistence'),('peak','Archive peak'),('mean','Archive mean'))):
                x=24+i*310;self.button(cache,(x,166,x+298,222),label,('activity',key),active=self.activity_mode==key)
        else:
            self.button(cache,(24,166,440,222),'Choose reference A',('overlay','baselines'));self.button(cache,(452,166,852,222),'Save current as baseline',('save',None));self.button(cache,(864,166,1256,222),'Export report',('report',None))
        if frame and frame_view==self.view and self.frame_kind==(self.screen,self.display,self.activity_mode):self.upload(frame,identity)
        else:self.text(cache,360,400,'Loading matching measurements…',26,self.MUTED)
        line_graph=self.screen=='compare' or self.screen=='survey' and self.display=='spectrum'
        if line_graph:
            lo,hi=self.limits
            for i in range(5):self.text(cache,28,272+296*i/4,f'{hi-(hi-lo)*i/4:.0f}',18,self.MUTED)
            self.text(cache,92,254,'Difference · dB' if self.screen=='compare' else 'Relative dBFS/Hz · latest / peak hold',18,self.MUTED)
            if self.view:
                for i in range(7):self.text(cache,min(1170,92+1148*i/6-22),600,f'{(self.view[0]+(self.view[1]-self.view[0])*i/6)/1e6:.2f}',18,self.MUTED)
        else:
            if self.view:
                for i in range(6):self.text(cache,min(1170,124+1116*i/5-20),254,f'{(self.view[0]+(self.view[1]-self.view[0])*i/5)/1e6:.2f}',18,self.MUTED)
            for i,row in enumerate(self.rows):
                if i%max(1,math.ceil(len(self.rows)/6)):continue
                label=str(self.insights.get('persistence_low',-150)+(len(self.insights.get('persistence',[]))-1-(self.history_page*30+i))*3)+' dB' if self.screen=='activity' and self.activity_mode=='persistence' else 'LIVE' if row.get('partial') and self.state.get('enabled') else 'PART' if row.get('partial') else time.strftime('%H:%M',time.gmtime(row['finished']))
                height=336 if self.screen=='activity' and self.activity_mode=='persistence' else min(336,len(self.rows)*16)
                self.text(cache,28,280+height*i/max(1,len(self.rows)),label,18,self.MUTED)
            if not self.rows:self.text(cache,230,400,'Completed visits will build this view.',26,self.MUTED)
        if self.screen=='compare':
            result=comparison(data,self.baseline)
            if not result['matched']:self.text(cache,140,388,'Choose a baseline with matching receiver and settings.',24,self.CYAN)
            self.text(cache,24,638,f"Median {result['median']:+.1f} dB · {result['bins']} valid matched bins" if result.get('median') is not None else 'A/B receive-path comparison · clipped and missing bins excluded',20,self.MUTED)
        elif self.screen=='activity':
            caption='Detected / valid visits · grey = no valid measurement' if self.activity_mode=='activity' else f"Recent density · {self.insights.get('persistence_visits',0)} detailed visits" if self.activity_mode=='persistence' else 'Recorded minute summaries · '+str(self.insights.get('visits',0))+' visits across up to 24 h'
            self.text(cache,24,638,caption,20,self.MUTED,width=800 if self.activity_mode=='activity' else 1200)
            if self.activity_mode=='activity':
                self.text(cache,844,638,'0%',18,self.MUTED);self.text(cache,1176,638,'100%',18,self.MUTED)
                for i in range(48):
                    t=i/47*4;index=min(3,int(t));f=t-index;color=tuple(int(a*(1-f)+b*f) for a,b in zip(PALETTE[index],PALETTE[index+1]))+(255,)
                    self.ui.draw_logical_rect(884+i*6,630,890+i*6,644,color)
        else:self.text(cache,24,638,'Tap a frequency to select it. Drag horizontally to pan; swipe vertically for history.',20,self.MUTED,width=1200)
        for box,title,action in (((24,654,228,712),'Zoom +',('zoom',.5)),((240,654,444,712),'Zoom −',('zoom',2)),((456,654,680,712),'Full range',('full',None))):
            if action[0]=='full' and (not self.view or self.view==(config['low'],config['high'])):continue
            self.button(cache,box,title,action)
        if self.selected is not None:self.button(cache,(884,654,1256,712),'Investigate selected →',('investigate',None),active=True)
        if not line_graph and not (self.screen=='activity' and self.activity_mode=='persistence'):
            self.button(cache,(692,654,880,712),'Older sweeps',('page',1))


    def draw_tools(self,cache):
        self.text(cache,24,194,'Go deeper when you need to.',26,self.CYAN)
        choices=(('Activity & heatmap','Where signals appear over time','activity'),('Compare antennas','Saved reference versus current sweep','compare'),('Watchlist','Revisit selected frequencies and log changes','watch'),('Reports & logs','Save measurements or inspect receiver activity','reports'))
        for i,(title,subtitle,destination) in enumerate(choices):
            x=24+i%2*624;y=250+i//2*176
            self.button(cache,(x,y,x+608,y+148),title,('screen',destination),subtitle)
        self.text(cache,24,656,'Persistence and archived power are inside Activity & heatmap.',22,self.MUTED)

    def draw_signals(self,cache):
        signals=sorted(self.insights.get('signals',[]),key=lambda s:s.get(self.sort) if s.get(self.sort) is not None else -1,reverse=True);last=max(0,math.ceil(len(signals)/5)-1);self.page=min(self.page,last)
        self.text(cache,24,188,'Select a signal → Investigate its band or add it to Watchlist',23,self.CYAN)
        for x,label in ((36,'Frequency'),(340,'Width estimate'),(524,'Above floor'),(726,'Detected / valid'),(1030,'Last UTC')):self.text(cache,x,224,label,18,self.MUTED)
        for i,s in enumerate(signals[self.page*5:(self.page+1)*5]):
            y=244+i*76;box=(24,y,1256,y+68);self.ui.draw_logical_rounded_rect(*box,self.RADIUS,self.color('selected_surface') if self.selected==s['frequency'] else self.PANEL,self.LINE,1);self.actions.append((box,('select_signal',s['frequency'])))
            self.text(cache,36,y+26,f"{s['frequency']/1e6:.6f}",26,self.CYAN);self.text(cache,36,y+52,'MHz',18,self.MUTED)
            self.text(cache,340,y+34,f"{s['width']/1000:g} kHz",22);self.text(cache,524,y+34,f"+{s['excess']:.1f} dB",24,self.CYAN)
            self.text(cache,726,y+24,f"{s['active_visits']}/{s['visits']} · {s['activity'] or 0:.0f}%",22);self.text(cache,726,y+50,'sampled visits',18,self.MUTED)
            self.text(cache,1030,y+34,time.strftime('%H:%M:%S',time.gmtime(s['last'])),20,self.MUTED)
        if not signals:self.text(cache,80,360,'No completed visits with signals above the threshold yet.',26,self.MUTED,width=1150)
        self.text(cache,24,638,f"{len(signals)} signal groups · {self.insights.get('visits',0)} visits · +6 dB local-floor threshold · page {self.page+1}/{last+1}",19,self.MUTED)
        self.button(cache,(24,654,348,712),'Investigate selected →',('investigate',None),active=True);self.button(cache,(360,654,654,712),'+ Watch selected',('overlay','watch'))
        self.button(cache,(666,654,930,712),'Sort: '+self.sort,('sort',None));self.button(cache,(942,654,1092,712),'Previous',('page',-1));self.button(cache,(1104,654,1256,712),'Next',('page',1))

    def draw_watch(self,cache):
        for i,(key,label) in enumerate((('frequencies','Frequencies'),('events','Watch events'))):self.button(cache,(24+i*400,166,412+i*400,222),label,('watch_view',key),active=self.watch_mode==key)
        if self.watch_mode=='events':
            events=self.insights.get('events',[]);last=max(0,math.ceil(len(events)/5)-1);self.page=min(self.page,last)
            for i,e in enumerate(events[self.page*5:(self.page+1)*5]):
                y=258+i*74;self.text(cache,24,y,time.strftime('%H:%M:%S UTC',time.gmtime(e['time']))+' · '+e['label']+' · '+e['kind'],23,self.CYAN,width=1220);self.text(cache,24,y+30,e['detail'],19,self.MUTED,width=1220)
        else:
            watches=self.state.get('watchlist',[]);last=max(0,math.ceil(len(watches)/5)-1);self.page=min(self.page,last)
            for i,w in enumerate(watches[self.page*5:(self.page+1)*5]):
                y=240+i*76;box=(24,y,1256,y+68);self.ui.draw_logical_rounded_rect(*box,self.RADIUS,self.color('selected_surface') if self.selected_watch==w['id'] else self.PANEL,self.LINE,1);self.actions.append((box,('select_watch',w['id'])))
                m=w.get('measurement');self.text(cache,36,y+25,w['label'],23,self.CYAN,width=440);self.text(cache,36,y+52,f"{w['frequency']/1e6:.6f} MHz · {w['bandwidth']/1000:g} kHz",18,self.MUTED)
                self.text(cache,510,y+34,'Not sampled' if w['stale'] else 'Detected' if m['present'] else 'Quiet on visits',23)
                self.text(cache,830,y+25,f"{m['level']:.1f} dBFS/Hz · +{m['excess']:.1f} dB" if m else 'No valid visit yet',21,self.CYAN,width=410)
                self.text(cache,830,y+52,time.strftime('%H:%M:%S UTC',time.gmtime(m['time'])) if m else 'Outside current survey? Start Watch mode.',18,self.MUTED,width=410)
            if not watches:self.text(cache,64,350,'Add a frequency, or select a signal in Results first.',27,self.MUTED)
        self.button(cache,(24,654,320,712),'+ Add frequency',('overlay','watch'));self.button(cache,(332,654,664,712),'Start watch mode',('watch_start',None),active=True)
        self.button(cache,(676,654,982,712),'Remove selected',('watch_remove',None));self.button(cache,(994,654,1118,712),'Prev',('page',-1));self.button(cache,(1130,654,1256,712),'Next',('page',1))

    def draw_reports(self,cache,state):
        self.button(cache,(24,166,436,222),'Saved reports',('report_view','reports'),active=self.report_mode=='reports');self.button(cache,(448,166,852,222),'Receiver activity',('report_view','logs'),active=self.report_mode=='logs')
        if self.report_mode=='logs':
            items=list(reversed(state.get('activity',[])))
            for i,r in enumerate(items[self.page*7:(self.page+1)*7]):self.text(cache,24,264+i*48,time.strftime('%H:%M:%S UTC',time.gmtime(r['time']))+' · '+r['action'].upper()+' · '+r['detail'],20,width=1230)
        else:
            reports=state.get('reports',[]);self.page=min(self.page,max(0,math.ceil(len(reports)/4)-1))
            for i,r in enumerate(reports[self.page*4:(self.page+1)*4]):
                y=268+i*82;self.text(cache,32,y,r['label'],26,self.CYAN,width=1200);self.text(cache,32,y+32,time.strftime('%d %b %H:%M UTC',time.gmtime(r['time']))+' · HTML / CSV / JSON / PNG',20,self.MUTED)
            if not reports:self.text(cache,64,350,'Export a report with your real measurements and signal list.',26,self.MUTED,width=1160)
        self.text(cache,24,628,'Download or print at cm5.local:8092/spectrum → Reports',22,self.MUTED)
        self.button(cache,(24,654,720,712),'Generate survey report',('report',None),active=True);self.button(cache,(732,654,984,712),'Previous',('page',-1));self.button(cache,(996,654,1256,712),'Next',('page',1))

    def draw_inspector(self,cache,data):
        x0,_,x1,_=footer_content_box()
        if self.selected is None:
            self.text(cache,x0,739,'Survey → Signals → Investigate · Watch and compare without changing the display gain.',18,self.MUTED,width=x1-x0);return
        selection=self.inspection or {};row=selection.get('row');code=selection.get('code');level='Selected for investigation'
        if isinstance(row,dict) and code is not None:level='No valid measurement' if code==0 else 'Clipping excluded' if code==1 else f'≈ {code-202} dBFS/Hz · '+time.strftime('%H:%M:%S UTC',time.gmtime(row['finished']))
        elif self.screen=='compare' and self.compare_data.get('settings'):
            current=self.compare_data;result=comparison(current,self.baseline);index=int((self.selected-current['settings']['low'])/current['settings']['bin']);delta=result.get('delta',[])
            level=f'{delta[index]:+.1f} dB vs baseline' if 0<=index<len(delta) and delta[index] is not None else 'No matched valid measurement'
        elif data.get('settings'):
            index=int((self.selected-data['settings']['low'])/data['settings']['bin']);power=data.get('power',[])
            if 0<=index<len(power) and power[index] is not None:level=f'{power[index]:.1f} dBFS/Hz · latest visit'
        self.text(cache,x0,739,f'{self.selected/1e6:.6f} MHz · {level} · tap for allocations',18,self.CYAN,width=x1-x0)
        self.actions.append(((x0,720,x1,756),('overlay','info')))

    def close(self):
        self.open=False;self.closed.set();self.wake.set()
        if self.worker:self.worker.join(timeout=3)
        if self.texture is not None:self.ui.GL.glDeleteTextures([self.texture]);self.texture=None
