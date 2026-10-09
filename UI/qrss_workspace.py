"""QRSS visual/text gallery and receiver controls for a 1280 x 800 touchscreen."""
import math
from sstv_workspace import SSTVWorkspace
from qrss_modes import PRESETS, DOTS, KINDS, settings


class QRSSWorkspace(SSTVWorkspace):
    def __init__(self,ui,manager):
        super().__init__(ui,manager)
        self.preset=dict(PRESETS[2]);self.field=None;self.entry='';self.track_page=0

    def swipe(self, start_x, start_y, x, y):
        direction = self.gallery_swipe_direction(start_x, start_y, x, y, (16, 76, 1264, 788))
        if not direction:
            return False
        images = self.manager.image_snapshot(self.filter_id)
        last = max(0, (len(images)-1)//2)
        self.page = max(0, min(last, self.page+direction))
        return True

    def preview(self,cache,item,box):self.draw_plot(cache,item,box)

    def draw_plot(self,cache,item,box,compact=False):
        # Only the spectrum is stretched. Legends use the UI's regular fonts.
        x0,y0,x1,y1=box
        size=16 if compact or y1-y0<250 else 20
        left,top,right,bottom=x0+118,y0+(24 if compact else 30),x1-6,y1-(22 if compact else 28)
        source=item.get('plot_box',(90,35,item.get('width',1700)-10,355))
        super().image(item['id'],(left,top,right,bottom),fill=True,source_box=source)
        center,half=item['rf_hz'],item['span_hz']/2
        self.text(cache,x0+4,y0+12,'MHz RF',size)
        if not compact:self.text(cache,left,y0+12,item['capture_utc'].replace('T',' ').replace('Z',' UTC'),size,width=420)
        elif item.get('tracks'):self.text(cache,left,y0+12,f"{len(item['tracks'])} signal{'s' if len(item['tracks'])!=1 else ''} · tentative text below",size,width=540)
        window=item.get('window_seconds',item['duration_seconds']) or 1
        self.text(cache,right-250,y0+12,f"Received {item['duration_seconds']:.0f} / {window:g} s",size,width=250)
        for fraction,hz in ((0,center+half),(.5,center),(1,center-half)):
            y=max(top+size/2,min(bottom-size/2,top+fraction*(bottom-top)))
            self.text(cache,x0+4,y,f'{hz/1e6:.6f}',size,width=116)
        self.text(cache,left,y1-12,'Time → 0 s',size)
        self.text(cache,(left+right)/2-24,y1-12,f'{window/2:g} s',size)
        self.text(cache,right-90,y1-12,f'{window:g} s',size,width=90)
        for track in item.get('tracks',[]):
            if not track['active']:continue
            fraction=(center+half-track['rf_hz'])/item['span_hz']
            if not 0<=fraction<=1:continue
            y=top+fraction*(bottom-top)
            self.ui.draw_logical_rect(left,y-1,left+8,y+1,(255,150,40,255))
            self.text(cache,left+10,max(top+size/2,min(bottom-size/2,y-size)),track['id'],size,(255,190,90))

    def draw(self,cache,receivers):
        self.actions=[]
        self.ui.draw_logical_rect(0,0,1280,800,(7,18,25,255))
        receivers=[r for r in receivers if getattr(self.ui,'station_receiver_type',lambda r:'kiwi')(r)=='kiwi']
        if self.field is not None:
            self.text(cache,24,48,self.field.replace('_',' ').upper(),28)
            self.text(cache,24,110,self.entry or '0',36)
            for i,c in enumerate('123456789.0'):
                x,y=24+i%3*185,160+i//3*105
                self.button(cache,(x,y,x+170,y+90),c,('digit',c))
            for i,(label,action) in enumerate((('DELETE','erase'),('APPLY','apply'),('CANCEL','cancel_number'))):
                self.button(cache,(620,160+i*120,1000,250+i*120),label,(action,None))
            self.text(cache,24,660,self.message,22,width=1230);return
        if self.add_open:self.draw_add(cache,receivers);return
        images=self.manager.image_snapshot(self.filter_id)
        if self.enlarged:
            item=next((r for r in self.manager.image_snapshot() if r['id']==self.enlarged),None)
            if item:
                self.text(cache,24,34,f"QRSS · {item['band']} · {item['rf_hz']/1e6:.6f} MHz",25)
                self.text(cache,24,78,item['receiver']+' · '+item['capture_utc'],18,width=1200)
                tracks=item.get('tracks',[])
                if tracks:
                    self.draw_plot(cache,item,(20,115,1260,500))
                    self.text(cache,24,529,'TENTATIVE TEXT · independent signal frequencies and dot timing',19,(104,234,194))
                    pages=max(1,math.ceil(len(tracks)/6));self.track_page=min(self.track_page,pages-1)
                    for j,r in enumerate(tracks[self.track_page*6:self.track_page*6+6]):
                        label=f"{r['id']} · {r['rf_hz']/1e6:.6f} MHz · {r['mode']} · {r['dot_seconds']:g} s/dot"
                        self.text(cache,24,564+j*28,label,17,width=570)
                        self.text(cache,608,564+j*28,r['tentative_text'] or 'Waiting for a complete character…',19,width=640)
                    self.text(cache,24,767,f'{len(tracks)} signals · text {self.track_page+1}/{pages}',18)
                    if pages>1:
                        self.button(cache,(728,16,880,70),'< TEXT',('track_page',-1))
                        self.button(cache,(892,16,1044,70),'TEXT >',('track_page',1))
                else:
                    self.draw_plot(cache,item,(20,115,1260,620))
                    self.text(cache,24,657,'TENTATIVE MORSE TEXT · compare with the waterfall',19,(104,234,194))
                    self.text(cache,24,696,item.get('tentative_text') or 'No text recognized yet',23,width=1210)
                    self.text(cache,24,745,item.get('acquisition',{}).get('detail') or f"{item['mode']} · {item['dot_seconds']:g} s/dot · one selected tone",18,width=1210)
                self.button(cache,(1060,16,1258,76),'BACK',('back_image',None));return
            self.enlarged=None
        if self.decoders_open:
            self.text(cache,20,36,'QRSS · decoders',27,(104,234,194))
            self.button(cache,(654,14,842,70),'GALLERY',('gallery',None))
            self.button(cache,(854,14,1090,70),'+ ADD DECODER',('add',None))
            self.button(cache,(1102,14,1258,70),'HOME',('home',None))
            self.draw_decoders(cache);return
        pages=max(1,math.ceil(len(images)/2));self.page=min(self.page,pages-1)
        self.text(cache,16,35,'QRSS',26,(104,234,194))
        self.button(cache,(116,10,222,62),'< PREV',('page',-1))
        self.text(cache,236,36,f'{self.page+1}/{pages}',19,width=78)
        self.button(cache,(320,10,426,62),'NEXT >',('page',1))
        self.button(cache,(438,10,626,62),'ALL RECEIVERS',('filter',None))
        self.button(cache,(638,10,816,62),'DECODERS',('decoders',None))
        self.button(cache,(828,10,1090,62),'+ ADD DECODER',('add',None))
        self.button(cache,(1102,10,1264,62),'HOME',('home',None))
        if not images:
            self.text(cache,120,300,'Add a QRSS receiver: waterfall and Morse text share one Kiwi channel.',23)
            self.text(cache,120,352,'Start with 30 m and AUTO to find a keyed signal and estimate its timing.',20)
            self.text(cache,120,402,'DFCW and other patterns remain visible; their text is not decoded.',20)
        for i,item in enumerate(images[self.page*2:self.page*2+2]):
            x,y=16,76+i*360
            self.ui.draw_logical_rect(x,y,x+1248,y+352,(17,34,42,255))
            self.text(cache,x+12,y+17,f"{'LIVE' if item['kind']=='receiving' else 'SAVED'} · {item['band']} · {item['mode']} · {item['receiver']}",17,width=890)
            self.text(cache,x+936,y+17,item['capture_utc'][11:19]+' UTC · tap to enlarge',15,width=300)
            self.draw_plot(cache,item,(x+8,y+34,x+1240,y+294),compact=True)
            for n,line in enumerate(self.preview_lines(cache,item)):
                self.text(cache,x+12,y+314+n*23,line,18,(217,233,238),width=1224)
            self.actions.append(((x,y,x+1248,y+352),('image',item['id'])))
        if self.message:self.text(cache,20,70,self.message,12,width=1220)

    def preview_lines(self,cache,item):
        tracks=[t for t in item.get('tracks',[]) if t.get('tentative_text')]
        if tracks:
            parts=[]
            for track in tracks:
                text=' '.join(track['tentative_text'].split())
                parts.append(track['id']+': '+(('… '+text[-160:]) if len(text)>160 else text))
            value='Tentative · '+'  |  '.join(parts)
        else:value='Tentative · '+(' '.join(item.get('tentative_text','').split()) or 'Waiting for complete Morse characters…')
        # Use two measured lines; the expanded view retains every track's text.
        words=value.split();first=[]
        while words:
            candidate=' '.join(first+[words[0]])
            if first and self.ui.fit_station_text(cache,candidate,1224,18,False,False,'Liberation Sans')!=candidate:break
            first.append(words.pop(0))
        return [' '.join(first),' '.join(words)]

    def draw_add(self,cache,receivers):
        p=self.preset
        self.text(cache,24,32,'EDIT QRSS RECEIVER' if self.edit_id else 'ADD QRSS RECEIVER',27)
        self.receiver_page=min(self.receiver_page,max(0,math.ceil(len(receivers)/2)-1))
        for i,row in enumerate(receivers[self.receiver_page*2:self.receiver_page*2+2]):
            name,location,server,*_=self.ui.station_fields(row);y=65+i*65
            self.button(cache,(24,y,1256,y+57),name,('receiver',server),location or server,server==self.selected_server)
        self.button(cache,(24,201,250,246),'< RECEIVERS',('rxpage',-1))
        self.text(cache,490,224,f'Receivers {self.receiver_page+1}/{max(1,math.ceil(len(receivers)/2))}',18)
        self.button(cache,(1020,201,1256,246),'RECEIVERS >',('rxpage',1))
        for i,preset in enumerate(PRESETS):
            x=24+i*312
            self.button(cache,(x,260,x+300,313),preset['band'],('preset',dict(preset)),active=p['band']==preset['band'])
        for i,mode in enumerate(KINDS):
            x=24+i*246
            self.button(cache,(x,329,x+234,382),'Visual only' if mode=='VISUAL' else mode,('set',('qrss_mode',mode)),active=p['qrss_mode']==mode)
        self.button(cache,(1008,329,1260,382),'POLARITY: AUTO' if p['qrss_mode']=='AUTO' else 'REVERSE '+('ON' if p['reverse'] else 'OFF'),('noop',None) if p['qrss_mode']=='AUTO' else ('set',('reverse',not p['reverse'])))
        for i,(key,label) in enumerate((('freq_khz','USB dial kHz'),('tone_hz','Band center Hz' if p['qrss_mode']=='AUTO' else 'Mark tone Hz'),('span_hz','Span Hz'),('shift_hz','FSK shift Hz'))):
            x=24+i*312
            self.button(cache,(x,399,x+300,454),('FSK shift: AUTO' if key=='shift_hz' and p['qrss_mode']=='AUTO' else f'{label}: {p[key]:g}'),('noop',None) if key=='shift_hz' and p['qrss_mode']=='AUTO' else ('number',key))
        self.text(cache,24,480,'AUTO: searches the full span and learns frequency, shift, polarity and dot time' if p['qrss_mode']=='AUTO' else 'Seconds per dot · match the signal for tentative text',18)
        if p['qrss_mode']=='AUTO':self.text(cache,24,529,'Up to six signals with independent timing · one Kiwi channel',20,(104,234,194))
        for i,dot in enumerate(() if p['qrss_mode']=='AUTO' else DOTS):
            x=24+i*246
            self.button(cache,(x,499,x+234,551),f'{dot} s',('set',('dot_seconds',dot)),active=p['dot_seconds']==dot)
        for i,minutes in enumerate((5,10,20,30)):
            x=24+i*312
            self.button(cache,(x,570,x+300,623),f'{minutes} min capture',('set',('minutes',minutes)),active=p['minutes']==minutes)
        self.text(cache,24,651,f"Band center: {(p['freq_khz']*1000+p['tone_hz'])/1e6:.6f} MHz · both outputs use one Kiwi channel",19)
        self.text(cache,24,684,'AUTO finds CW / FSKCW in the span. DFCW and other patterns remain visual only.',17)
        self.button(cache,(24,714,244,780),'CANCEL',('cancel_add',None))
        self.text(cache,265,748,self.message,17,width=715)
        self.button(cache,(990,714,1256,780),'SAVE' if self.edit_id else 'START DECODER',('create',None))

    def tap(self,x,y,receivers):
        receivers=[r for r in receivers if getattr(self.ui,'station_receiver_type',lambda r:'kiwi')(r)=='kiwi']
        action=next((a for box,a in reversed(self.actions) if self.ui.contains(box,x,y)),None)
        if not action:return
        key,value=action
        try:
            if key=='track_page':self.track_page=max(0,self.track_page+value)
            elif key=='set':
                updated=dict(self.preset,**{value[0]:value[1]});self.preset.update(settings(updated,updated))
            elif key=='number':self.field=value;self.entry='';self.message=''
            elif key=='digit':self.entry=(self.entry+value)[:12]
            elif key=='erase':self.entry=self.entry[:-1]
            elif key=='cancel_number':self.field=None
            elif key=='apply':
                updated=dict(self.preset,**{self.field:float(self.entry)})
                self.preset.update(settings(updated,updated));self.field=None
            elif key=='edit':
                row=next(r for r in self.manager.configs if r['id']==value)
                self.preset=dict(row);self.edit_id=value;self.selected_server=row['server'];self.add_open=True;self.delete_armed=None
                self.receiver_page=next((i//2 for i,r in enumerate(receivers) if self.ui.station_fields(r)[2]==row['server']),0)
            else:
                if key=='image':self.track_page=0
                super().tap(x,y,receivers)
        except (ValueError,StopIteration,OSError) as exc:self.message=str(exc) or 'Capture no longer available'
