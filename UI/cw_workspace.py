"""1280×800 CW console: stable waterfall, four signal rows and readable text."""
import math
from sstv_workspace import SSTVWorkspace
from cw_modes import PRESETS,settings,center_offset,bounds,display_bounds,signal_markers


class CWWorkspace(SSTVWorkspace):
    def __init__(self,ui,manager):
        super().__init__(ui,manager)
        self.preset=dict(PRESETS[3]);self.field=None;self.entry='';self.history_open=False
        self.selected_track=None;self.receiver_index=0

    def lines(self,cache,value,x,y,width=1210,count=5,size=22):
        words=value.split();lines=[];line=''
        for word in words:
            candidate=(line+' '+word).strip()
            if line and self.ui.fit_station_text(cache,candidate,width,size,False,False,'Liberation Sans')!=candidate:
                lines.append(line);line=word
            else:line=candidate
        if line:lines.append(line)
        for i,line in enumerate(lines[-count:]):self.text(cache,x,y+i*(size+10),line,size,width=width)

    def swipe(self,sx,sy,x,y):
        direction=self.gallery_swipe_direction(sx,sy,x,y,(16,150,1260,780))
        if not direction:return False
        if not self.history_open:
            if direction>0:self.history_open=True;self.page=0
        elif direction<0 and self.page==0:self.history_open=False
        else:self.page=max(0,min(max(0,(len(self.manager.history())-1)//3),self.page+direction))
        return True

    def draw(self,cache,receivers):
        self.actions=[];self.ui.draw_logical_rect(0,0,1280,800,(7,18,25,255))
        receivers=[r for r in receivers if getattr(self.ui,'station_receiver_type',lambda r:'kiwi')(r)=='kiwi']
        if self.field:
            self.text(cache,24,44,self.field.replace('_',' ').upper()+' · 0 WPM = AUTO',26)
            self.text(cache,24,110,self.entry or '0',36)
            for i,c in enumerate('123456789.0'):
                x,y=24+i%3*185,160+i//3*105;self.button(cache,(x,y,x+170,y+90),c,('digit',c))
            for i,(label,action) in enumerate((('DELETE','erase'),('APPLY','apply'),('CANCEL','cancel_number'))):
                self.button(cache,(620,160+i*120,1000,250+i*120),label,(action,None))
            self.text(cache,24,680,self.message,20,width=1220);return
        if self.add_open:self.draw_add(cache,receivers);return
        self.text(cache,20,35,'CW · MORSE',28,(104,234,194))
        self.button(cache,(296,10,470,65),'LIVE',('live',None),active=not self.history_open and not self.decoders_open)
        self.button(cache,(482,10,656,65),'HISTORY',('history',None),active=self.history_open)
        self.button(cache,(668,10,842,65),'RECEIVERS',('decoders',None),active=self.decoders_open)
        self.button(cache,(854,10,1090,65),'+ ADD DECODER',('add',None))
        self.button(cache,(1102,10,1260,65),'HOME',('home',None))
        if self.decoders_open:self.draw_receivers(cache);return
        if self.history_open:
            rows=self.manager.history();pages=max(1,math.ceil(len(rows)/3));self.page=min(self.page,pages-1)
            self.button(cache,(16,78,184,132),'< PREV',('page',-1));self.text(cache,204,106,f'{self.page+1} / {pages}',20)
            self.button(cache,(316,78,484,132),'NEXT >',('page',1))
            self.text(cache,508,106,'Saved across restarts · latest 200 entries · export from /cw',18,width=735)
            for i,row in enumerate(rows[self.page*3:self.page*3+3]):
                y=146+i*210;self.ui.draw_logical_rect(16,y,1260,y+198,(17,34,42,255))
                self.text(cache,30,y+24,f"{row['rf_hz']/1e6:.6f} MHz · {row['wpm']:g} WPM · {row['receiver']} · {row.get('engine','ggmorse')}",20,width=1200)
                self.text(cache,30,y+55,row['start_utc']+' → '+row['end_utc'],17)
                self.lines(cache,row['text'],30,y+92,count=3,size=24)
            if not rows:self.text(cache,220,320,'Decoded text is saved here automatically.',27)
            return
        rows=self.manager.snapshot()
        if not rows:
            self.text(cache,150,280,'Listen to Morse conversations with a full-width live waterfall.',29)
            self.text(cache,150,330,'Add a receiver · automatic signal acquisition · 5–55 WPM',23)
            self.text(cache,150,378,'Up to four signals share one Kiwi channel. Text is saved locally.',21)
            return
        self.receiver_index=min(self.receiver_index,len(rows)-1);row=rows[self.receiver_index]
        self.button(cache,(16,78,150,132),'< RX',('rx',-1))
        self.button(cache,(162,78,296,132),'RX >',('rx',1))
        self.text(cache,312,100,f"{row['name']} · {row['band']} · {row['freq_khz']+center_offset(row):.3f} kHz center",21,width=716)
        self.text(cache,312,126,row['status']+' · '+row.get('detail',''),15,width=716)
        self.button(cache,(1050,78,1260,132),'STOP' if row['running'] else 'START',('toggle',row['id']))
        tracks=row.get('tracks',[])
        if not any(t['id']==self.selected_track for t in tracks):self.selected_track=tracks[0]['id'] if tracks else None
        self.ui.draw_logical_rect(16,150,1260,524,(10,29,38,255))
        if row.get('image_version'):self.image(row['id'],(18,152,1258,490),fill=True)
        lo,hi=display_bounds(row)
        decode_lo,decode_hi=bounds(row)
        if decode_hi<hi:
            edge=18+1240*(decode_hi-lo)/(hi-lo)
            self.ui.draw_logical_rect(edge,152,1258,490,(4,12,20,110))
            self.ui.draw_logical_line(edge,152,edge,490,(144,172,189,220),1)
            self.text(cache,edge+12,185,'OVERVIEW ONLY',17,(164,185,194))
        for i in range(7):
            fraction=i/6;x=18+1240*fraction
            self.ui.draw_logical_line(x,480,x,490,(172,205,217,255),1)
            self.text(cache,max(24,min(1130,x-59)),510,
                      f"{(row['freq_khz']*1000+lo+(hi-lo)*fraction)/1e6:.6f}",17)
        for marker in signal_markers(row,self.selected_track):
            x=18+1240*marker['fraction']
            color=(255,210,103) if marker['selected'] else ((104,234,194) if marker['active'] else (151,163,176))
            if marker['active']:self.ui.draw_logical_line(x,152,x,490,(*color,220),2 if marker['selected'] else 1)
            else:
                for y in range(152,490,16):self.ui.draw_logical_line(x,y,x,min(y+8,490),(*color,210),2 if marker['selected'] else 1)
            bx=max(18,min(1220,x-18));self.ui.draw_logical_rect(bx,154,bx+36,184,(*color,255))
            self.text(cache,bx+10,175,str(marker['slot']),19,(7,18,25))
            self.actions.append(((max(18,x-22),152,min(1258,x+22),490),('track',marker['id'])))
        self.text(cache,24,543,f"3 kHz view · {row.get('engine','ggmorse').upper()} scans {(decode_hi-decode_lo)/1000:g} kHz · Yellow: selected · Green: active · Dashed: fading",17)
        for i in range(4):
            x=16+i*314
            if i<len(tracks):
                t=tracks[i]
                self.button(cache,(x,563,x+302,633),f"{i+1} · {t['rf_hz']/1e6:.6f} MHz",('track',t['id']),
                    f"{t['wpm']:g} WPM · "+('TRACKING' if t['active'] else 'FADING'),self.selected_track==t['id'])
            else:
                self.ui.draw_logical_rect(x,563,x+302,633,(17,34,42,255))
                self.text(cache,x+12,598,'Searching…' if not i else 'Available signal slot',17,width=278)
        chosen=next((t for t in tracks if t['id']==self.selected_track),None)
        self.ui.draw_logical_rect(16,647,1260,784,(17,34,42,255))
        self.text(cache,30,669,'DECODED TEXT · '+(f"{chosen['rf_hz']/1e6:.6f} MHz" if chosen else 'waiting'),20,(104,234,194))
        self.lines(cache,(chosen['text'] if chosen else '') or 'Text appears after several seconds of Morse. Tap a signal to follow it.',30,704,count=3,size=22)

    def draw_receivers(self,cache):
        for i,row in enumerate(self.manager.snapshot()):
            x=16+i%2*630;y=90+i//2*202
            self.ui.draw_logical_rect(x,y,x+612,y+188,(17,34,42,255))
            self.text(cache,x+14,y+26,f"{row['band']} · {row['freq_khz']+center_offset(row):.3f} kHz · {row['cw_mode']}",22,width=580)
            self.text(cache,x+14,y+60,row['name'],18,width=580)
            self.text(cache,x+14,y+90,row['status']+' · '+row.get('detail',''),16,width=580)
            for dx,label,action in ((14,'STOP' if row['running'] else 'START','toggle'),(160,'EDIT','edit'),(304,'LIVE','select_rx'),(448,'DELETE','delete')):
                self.button(cache,(x+dx,y+126,x+dx+140,y+178),label,(action,row['id']))
        if self.delete_armed:
            self.text(cache,24,748,'Remove receiver? Saved text is kept.',21)
            self.button(cache,(824,716,1020,780),'REMOVE',('confirm_delete',self.delete_armed))
            self.button(cache,(1032,716,1260,780),'CANCEL',('cancel_delete',None))
        else:self.text(cache,24,744,self.message or 'One Kiwi channel per receiver · all selected signals share its audio.',19,width=1215)

    def draw_add(self,cache,receivers):
        self.text(cache,24,32,'EDIT CW RECEIVER' if self.edit_id else 'ADD CW RECEIVER',28,(104,234,194))
        self.receiver_page=min(self.receiver_page,max(0,(len(receivers)-1)//2))
        for i,r in enumerate(receivers[self.receiver_page*2:self.receiver_page*2+2]):
            name,location,server,*_=self.ui.station_fields(r);y=63+i*64
            self.button(cache,(24,y,1256,y+56),name,('receiver',server),location or server,server==self.selected_server)
        self.button(cache,(24,196,250,246),'< RECEIVERS',('rxpage',-1));self.button(cache,(1020,196,1256,246),'RECEIVERS >',('rxpage',1))
        self.text(cache,470,220,f'Receivers {self.receiver_page+1}/{max(1,math.ceil(len(receivers)/2))}',19)
        for i,p in enumerate(PRESETS):
            x=24+i%5*248;y=264+i//5*62
            self.button(cache,(x,y,x+236,y+54),p['band'],('preset',dict(p)),active=self.preset['band']==p['band'])
        p=self.preset
        self.button(cache,(24,392,616,442),'GGMORSE · 1 kHz decode',('set',('engine','ggmorse')),active=p.get('engine','ggmorse')=='ggmorse')
        self.button(cache,(632,392,1256,442),'FLDIGI · 3 kHz decode',('set',('engine','fldigi')),active=p.get('engine')=='fldigi')
        self.button(cache,(24,450,616,502),'AUTO SCAN · UP TO 4 SIGNALS',('set',('cw_mode','SCAN')),active=p['cw_mode']=='SCAN')
        self.button(cache,(632,450,1256,502),'LOCK TO ONE TONE',('set',('cw_mode','LOCK')),active=p['cw_mode']=='LOCK')
        for i,(key,label,value) in enumerate((('rf_khz','RF center kHz',p['freq_khz']+center_offset(p)),('tone_hz','Locked tone Hz',p['tone_hz']),('wpm','Speed WPM (0 = Auto)',p['wpm']),('squelch_db','Signal gate dB',p['squelch_db']))):
            x=24+i%2*632;y=514+i//2*64
            self.button(cache,(x,y,x+600,y+58),f'{label}: {value:g}',('number',key))
        self.text(cache,24,648,f"{(bounds(p)[1]-200)/1000:g} kHz decode · 3 kHz overview · up to four signals · speed 5–55 WPM",20)
        self.text(cache,24,681,'Presets are starting points. CW activity is spread across each band.',18)
        self.button(cache,(24,718,244,780),'CANCEL',('cancel_add',None))
        self.text(cache,266,746,self.message,17,width=690)
        self.button(cache,(984,718,1256,780),'SAVE' if self.edit_id else 'START DECODER',('create',None))

    def tap(self,x,y,receivers):
        action=next((a for box,a in reversed(self.actions) if self.ui.contains(box,x,y)),None)
        if not action:return
        key,value=action
        try:
            if key=='live':self.history_open=self.decoders_open=False
            elif key=='history':self.history_open=True;self.decoders_open=False;self.page=0
            elif key=='decoders':self.history_open=False;super().tap(x,y,receivers)
            elif key=='select_rx':self.receiver_index=next(i for i,r in enumerate(self.manager.configs) if r['id']==value);self.decoders_open=False;self.history_open=False
            elif key=='rx':self.receiver_index=max(0,min(len(self.manager.configs)-1,self.receiver_index+value));self.selected_track=None
            elif key=='track':self.selected_track=value
            elif key=='preset':
                engine=self.preset.get('engine','ggmorse');self.preset=dict(value);self.preset.update(settings({'engine':engine},self.preset))
            elif key=='set':self.preset.update(settings({value[0]:value[1]},self.preset))
            elif key=='number':self.field=value;self.entry='';self.message=''
            elif key=='digit':self.entry=(self.entry+value)[:12]
            elif key=='erase':self.entry=self.entry[:-1]
            elif key=='cancel_number':self.field=None
            elif key=='apply':self.preset.update(settings({self.field:float(self.entry)},self.preset));self.field=None
            elif key=='edit':
                row=next(r for r in self.manager.configs if r['id']==value)
                self.preset=dict(row);self.edit_id=value;self.selected_server=row['server'];self.add_open=True
            else:super().tap(x,y,receivers)
        except (ValueError,OSError,StopIteration) as exc:self.message=str(exc) or 'Receiver unavailable'
