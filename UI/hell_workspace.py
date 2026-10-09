"""Hell RX touchscreen: three full-width strips on the 1280 x 800 display."""
import math
from sstv_workspace import SSTVWorkspace
from hell_modes import MODES, PRESETS, settings, selected_modes, fit_modes


class HellWorkspace(SSTVWorkspace):
    def __init__(self, ui, manager):
        super().__init__(ui, manager)
        self.preset = dict(PRESETS[4])
        self.field = None
        self.entry = ''
        self.reporting = None
        self.report_field = 'call'
        self.saved_view = False
        self.visible_strips = None
        self.strip_offset = 0
        self.strip_step = 1
        self.strip_max = 0

    def swipe(self, start_x, start_y, x, y):
        direction = self.gallery_swipe_direction(start_x, start_y, x, y, (16, 86, 1260, 708))
        if not direction:
            return False
        if not self.saved_view:
            if direction > 0:
                self.saved_view = True
                self.page = 0
        elif direction < 0 and self.page == 0:
            self.saved_view = False
        else:
            images = [i for i in self.manager.image_snapshot(self.filter_id) if i['kind']=='saved']
            last = max(0, (len(images)-1)//3)
            self.page = max(0, min(last, self.page+direction))
        self.visible_strips = None
        return True

    def preview(self, cache, item, box):
        self.strip_image(item, box)

    def strip_image(self,item,box,expanded=False):
        # Preserve raster proportions at a fixed height. Long strips are
        # clipped in previews and explicitly panned in the expanded view.
        x0,y0,x1,y1=box
        width,height=item['width'],item['height']
        scale=(y1-y0)/height
        source_width=min(width,(x1-x0)/scale)
        offset=0
        if expanded:
            self.strip_max=max(0,width-source_width)
            self.strip_offset=max(0,min(self.strip_offset,self.strip_max))
            self.strip_step=source_width*.8
            offset=self.strip_offset
        self.ui.draw_logical_rect(*box,(255,255,255,255))
        super().image(item['id'],(x0,y0,x0+source_width*scale,y1),fill=True,
                      source_box=(offset,0,offset+source_width,height))

    def show(self,*args):
        self.visible_strips=None
        super().show(*args)

    def gallery_page(self,images):
        key=(lambda i:i['id']) if self.saved_view else (lambda i:(i['session_id'],i['mode']))
        desired=images[self.page*3:self.page*3+3]
        if self.visible_strips is None:self.visible_strips=desired
        else:
            available={key(i):i for i in images}
            self.visible_strips=[available.get(key(i),i) for i in self.visible_strips]
        changed=[key(i) for i in desired]!=[key(i) for i in self.visible_strips]
        return self.visible_strips,changed

    def kiwi_receivers(self, receivers):
        kind_of = getattr(self.ui, 'station_receiver_type', lambda row: 'kiwi')
        return [row for row in receivers if kind_of(row) == 'kiwi']

    def draw(self, cache, receivers):
        receivers = self.kiwi_receivers(receivers)
        self.actions = []
        self.ui.draw_logical_rect(0,0,1280,800,(7,18,25,255))
        if self.reporting is not None:
            self.draw_report(cache)
            return
        if self.field is not None:
            self.draw_number(cache)
            return
        if self.add_open:
            self.draw_add(cache, receivers)
            return
        if self.enlarged:
            item = next((r for r in self.manager.image_snapshot() if r['id']==self.enlarged),
                        next((r for r in (self.visible_strips or []) if r['id']==self.enlarged),None))
            if item:
                self.text(cache,24,34,f"{MODES[item['mode']]['label']} · {item['band']} · {item['rf_hz']/1e6:.6f} MHz RF",25)
                self.text(cache,24,72,item['receiver']+' · '+item['capture_utc'],18,width=1000)
                self.strip_image(item,(20,160,1260,400),expanded=True)
                self.button(cache,(24,430,244,486),'< LEFT',('pan_strip',-1))
                self.button(cache,(1036,430,1256,486),'RIGHT >',('pan_strip',1))
                self.text(cache,280,458,'Scroll across the strip · fixed letter size',20,width=710)
                self.text(cache,24,530,'Start' if self.strip_offset==0 else 'End' if self.strip_offset>=self.strip_max else 'Middle of strip',18)
                self.button(cache,(1060,16,1258,76),'BACK',('back_image',None))
                self.button(cache,(24,704,330,770),'REPORT STATION',('report',item['id']))
                self.text(cache,354,730,'Read the callsign from the strip; reporting is optional.',18,width=890)
                self.text(cache,354,761,self.message or ('OCR guess: '+item.get('ocr_text','—')),16,width=890)
                return
            self.enlarged = None
        self.text(cache,20,36,'Hell RX',29,(104,234,194))
        self.text(cache,175,36,'Receivers' if self.decoders_open else 'Saved strips' if self.saved_view else 'Latest previews',23)
        self.button(cache,(654,14,842,70),'GALLERY' if self.decoders_open else 'DECODERS',('gallery' if self.decoders_open else 'decoders',None))
        self.button(cache,(854,14,1090,70),'+ ADD DECODER',('add',None))
        self.button(cache,(1102,14,1258,70),'HOME',('home',None))
        if self.decoders_open:
            self.draw_decoders(cache)
            return
        images = self.manager.image_snapshot(self.filter_id)
        if self.saved_view:
            images = [item for item in images if item['kind']=='saved']
        else:
            latest = {}
            for item in images:
                latest.setdefault((item['session_id'],item['mode']),item)
            # New timestamps must not make simultaneous modes trade places.
            receivers_order = {r['id']:i for i,r in enumerate(self.manager.configs)}
            modes_order = {mode:i for i,mode in enumerate(MODES)}
            images = sorted(latest.values(), key=lambda r:(
                receivers_order.get(r['session_id'],len(receivers_order)),
                r['session_id'],modes_order.get(r['mode'],len(modes_order))))
        pages = max(1,math.ceil(len(images)/3))
        if self.visible_strips is None:self.page = min(self.page,pages-1)
        visible,changed=self.gallery_page(images)
        if not images:
            self.text(cache,180,310,'Add a Hell decoder to receive scrolling text images.',26)
            self.text(cache,180,355,'Choose Feld Hell or an FSK Hell variant; there is no automatic mode header.',20)
            self.text(cache,180,395,'Noise is displayed too. A strip is not proof of a decoded transmission.',19)
        for i,item in enumerate(visible):
            y = 86+i*210
            self.ui.draw_logical_rect(16,y,1260,y+202,(17,34,42,255))
            live = ('LIVE' if item['kind']=='receiving' else
                    'POSSIBLE TEXT' if item.get('ocr_status')=='possible_text' else
                    'LATEST PREVIEW' if item['kind']=='preview' else 'SAVED')
            self.text(cache,26,y+17,f"{live} · {MODES[item['mode']]['label']} · {item['band']} · {item['receiver']} · {item['capture_utc']} · tap to scroll",16,width=1215)
            self.strip_image(item,(24,y+34,1252,y+192))
            self.actions.append(((16,y,1260,y+202),('image',item['id'])))
        self.button(cache,(16,730,168,786),'< PREV',('page',-1))
        self.text(cache,188,758,f'{self.page+1} / {pages}',19)
        self.button(cache,(282,730,434,786),'NEXT >',('page',1))
        self.button(cache,(450,730,658,786),'LATEST' if self.saved_view else 'SAVED STRIPS',('saved_view',None))
        self.button(cache,(670,730,870,786),'ALL RECEIVERS',('filter',None))
        self.button(cache,(890,730,1260,786),'SHOW NEW STRIPS' if changed else 'REFRESH STRIPS',('refresh_strips',None))

    def draw_add(self,cache,receivers):
        p = self.preset
        self.text(cache,24,32,'EDIT HELL DECODER' if self.edit_id else 'ADD HELL DECODER',27)
        self.receiver_page = min(self.receiver_page,max(0,math.ceil(len(receivers)/2)-1))
        for i,row in enumerate(receivers[self.receiver_page*2:self.receiver_page*2+2]):
            name,location,server,*_ = self.ui.station_fields(row)
            y = 65+i*65
            self.button(cache,(24,y,1256,y+57),name,('receiver',server),location or server,server==self.selected_server)
        self.button(cache,(24,201,250,246),'< RECEIVERS',('rxpage',-1))
        self.text(cache,490,224,f'Receivers {self.receiver_page+1}/{max(1,math.ceil(len(receivers)/2))}',18)
        self.button(cache,(1020,201,1256,246),'RECEIVERS >',('rxpage',1))
        for i,preset in enumerate(PRESETS):
            x,y=24+i%6*208,260+i//6*60
            self.button(cache,(x,y,x+198,y+53),preset['band'],('hell_preset',preset),active=p['band']==preset['band'])
        if self.current and 0<self.current[1]<30000 and self.current[2]=='usb':
            self.button(cache,(1064,320,1254,373),'CURRENT USB',('current',None))
        self.text(cache,24,400,'HELL MODES · select several; all share one Kiwi channel',18)
        for i,(key,spec) in enumerate(MODES.items()):
            x,y=24+i%4*312,420+i//4*59
            self.button(cache,(x,y,x+300,y+51),spec['label'],('hell_mode',key),active=key in selected_modes(p))
        self.button(cache,(960,479,1260,530),'ALL MODES',('hell_all',None),active=len(selected_modes(p))==len(MODES))
        self.button(cache,(24,548,420,610),f"Dial: {p['freq_khz']:.3f} kHz USB",('number','freq_khz'))
        self.button(cache,(440,548,830,610),f"Audio center: {p['tone_hz']:g} Hz",('number','tone_hz'))
        self.button(cache,(850,548,1256,610),'REVERSE: '+('ON' if p.get('reverse') else 'OFF'),('reverse',None))
        self.text(cache,24,639,f"RF center: {(p['freq_khz']*1000+p['tone_hz'])/1e6:.6f} MHz · {len(selected_modes(p))} modes / one Kiwi channel",19)
        self.text(cache,24,674,'One OCR letter or digit keeps a strip. No text: only the latest preview per mode is kept.',16)
        self.button(cache,(24,714,244,780),'CANCEL',('cancel_add',None))
        self.text(cache,265,748,self.message,17,width=715)
        self.button(cache,(990,714,1256,780),'SAVE' if self.edit_id else 'START DECODER',('create',None))

    def draw_number(self,cache):
        self.text(cache,24,48,'USB dial frequency (kHz)' if self.field=='freq_khz' else 'Audio center (Hz)',28)
        self.text(cache,24,110,self.entry or '0',36)
        for i,c in enumerate('123456789.0'):
            x,y=24+i%3*185,160+i//3*105
            self.button(cache,(x,y,x+170,y+90),c,('digit',c))
        self.button(cache,(620,160,1000,250),'DELETE',('erase_number',None))
        self.button(cache,(620,280,1000,370),'APPLY',('apply_number',None))
        self.button(cache,(620,400,1000,490),'CANCEL',('cancel_number',None))
        self.text(cache,24,660,self.message,22,width=1230)

    def draw_report(self,cache):
        p=self.reporting
        self.text(cache,24,36,'Report a station to PSK Reporter',28)
        self.text(cache,24,83,p['receiver']+' · '+p['server'],18,width=1230)
        self.text(cache,24,121,'Use the receiving antenna’s identity and location, not your own for a remote Kiwi.',18)
        for i,(key,label) in enumerate((('call','Heard callsign'),('reporter','Receiver callsign'),('grid','Receiver grid'))):
            self.button(cache,(24+i*416,151,424+i*416,211),label+': '+p[key],('report_field',key),active=self.report_field==key)
        self.button(cache,(24,234,1256,293),('[YES] ' if p['confirmed'] else '[NO] ')+'Callsign is correct; I may report for this receiver and its location is correct',('confirm_report',None))
        for y,row in enumerate(('1234567890','QWERTYUIOP','ASDFGHJKL','ZXCVBNM/')):
            for x,c in enumerate(row):
                self.button(cache,(24+x*92,322+y*67,108+x*92,381+y*67),c,('report_key',c))
        self.button(cache,(970,322,1256,380),'DELETE CHARACTER',('report_erase',None))
        self.button(cache,(970,416,1256,478),'QUEUE REPORT',('send_report',None))
        self.button(cache,(970,510,1256,572),'CANCEL',('cancel_report',None))
        self.text(cache,24,650,self.message,19,width=1230)
        self.text(cache,24,700,'Only confirmed station reports are sent. Images are never uploaded.',18)
        self.text(cache,24,742,'Sends about every five minutes. PSK Reporter uses UDP; delivery is unconfirmed.',18)

    def tap(self,x,y,receivers):
        receivers = self.kiwi_receivers(receivers)
        action=next((a for box,a in reversed(self.actions) if self.ui.contains(box,x,y)),None)
        if action is None:return
        key,value=action
        if key=='image':self.strip_offset=0
        if key in ('page','filter','gallery','saved_view','refresh_strips'):self.visible_strips=None
        try:
            if key=='refresh_strips':return
            elif key=='pan_strip':self.strip_offset=max(0,min(self.strip_max,self.strip_offset+value*self.strip_step))
            elif key=='hell_preset':self.preset=dict(value)
            elif key=='hell_mode':
                modes=selected_modes(self.preset)
                if value in modes:
                    if len(modes)>1:modes.remove(value)
                else:modes.append(value)
                self.preset=fit_modes(self.preset,modes)
            elif key=='hell_all':self.preset=fit_modes(self.preset,list(MODES))
            elif key=='saved_view':self.saved_view=not self.saved_view;self.page=0
            elif key=='reverse':self.preset['reverse']=not self.preset.get('reverse',False)
            elif key=='current':self.preset.update(band='Current dial',freq_khz=self.current[1])
            elif key=='number':self.field=value;self.entry='';self.message=''
            elif key=='digit':self.entry=(self.entry+value)[:12]
            elif key=='erase_number':self.entry=self.entry[:-1]
            elif key=='cancel_number':self.field=None
            elif key=='apply_number':
                updated=dict(self.preset,**{self.field:float(self.entry)})
                self.preset.update(settings(updated,updated));self.field=None
            elif key=='edit':
                row=next(r for r in self.manager.configs if r['id']==value)
                self.preset={k:row[k] for k in ('band','freq_khz','mode','tone_hz','hell_mode','reverse')}
                self.preset['hell_modes']=selected_modes(row)
                self.edit_id=value;self.selected_server=row['server'];self.add_open=True;self.delete_armed=None
                self.receiver_page=next((i//2 for i,r in enumerate(receivers) if self.ui.station_fields(r)[2]==row['server']),0)
            elif key=='report':
                item=next(r for r in self.manager.image_snapshot() if r['id']==value)
                profile=self.manager.reporter.snapshot()['profiles'].get(item['server'],{})
                self.reporting=dict(image=value,call='',reporter=profile.get('reporter',''),grid=profile.get('grid',''),confirmed=False,receiver=item['receiver'],server=item['server'])
                self.message='';self.report_field='call'
            elif key=='report_field':self.report_field=value
            elif key=='report_key':self.reporting[self.report_field]=(self.reporting[self.report_field]+value)[:16]
            elif key=='report_erase':self.reporting[self.report_field]=self.reporting[self.report_field][:-1]
            elif key=='confirm_report':self.reporting['confirmed']=not self.reporting['confirmed']
            elif key=='cancel_report':self.reporting=None
            elif key=='send_report':
                self.manager.reporter.submit(self.reporting);self.reporting=None;self.message='Report queued. Delivery status is available on the Hell web page.'
            else:
                super().tap(x,y,receivers)
        except (ValueError,StopIteration,OSError) as exc:
            self.message=str(exc) or 'Image is no longer available'
