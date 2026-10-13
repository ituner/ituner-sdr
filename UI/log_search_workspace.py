"""Shared touch search overlay; keeps receiver screens and their gestures intact."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import textwrap
from sstv_workspace import SSTVWorkspace
from ui_style import APP_UI_STYLE


class SearchView(SSTVWorkspace):
    def __init__(self, ui, service):
        super().__init__(ui, SimpleNamespace(gallery=None))
        self.service=service;self.mode='all';self.query='';self.offset=0
        self.result={'results':[],'total':0};self.future=None;self.keyboard=False;self.picture=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='log-search-view')

    def submit(self):
        if self.future and not self.future.done(): self.future.cancel()
        self.future=self.pool.submit(self.service.query,q=self.query,mode=self.mode,offset=self.offset,limit=3)
        self.message='Searching…'

    def draw(self,cache,*unused):
        if self.future and self.future.done():
            try:self.result=self.future.result();self.message=self.result['notice']
            except Exception:self.message='Could not read logs. Tap Search to retry.'
            self.future=None
        self.actions=[];self.ui.draw_logical_rect(0,0,1280,800,(7,18,25,255))
        self.text(cache,20,34,'SEARCH SAVED LOGS',27,(104,234,194))
        self.button(cache,(1034,728,1270,792),'BACK',('back',None))
        if self.picture:
            self.manager.gallery=self.service.galleries()[self.picture['mode']]
            self.image(self.picture['image_id'],(20,90,1020,780));return
        self.button(cache,(20,82,256,146),'CALLSIGN',('keyboard',None),
                    self.query or 'ALL SAVED RESULTS')
        self.button(cache,(264,82,500,146),'MODE',('mode',None),self.mode)
        self.button(cache,(508,82,744,146),'SEARCH',('search',None))
        if self.keyboard:
            for y,row in enumerate(('1234567890','QWERTYUIOP','ASDFGHJKL','ZXCVBNM/ ')):
                for x,char in enumerate(row):
                    left,top=24+x*122,205+y*72
                    self.button(cache,(left,top,left+114,top+64),char if char!=' ' else 'SPACE',('key',char))
            for i,(label,kind) in enumerate((('DELETE','erase'),('CLEAR','clear'),('SEARCH','done'))):
                left=24+i*122
                self.button(cache,(left,501,left+114,565),label,(kind,None))
            self.text(cache,24,640,'Use a full or partial callsign. Matching ignores upper / lower case.',20);return
        for i,row in enumerate(self.result['results']):
            y=168+i*175;self.ui.draw_logical_rect(20,y,1260,y+159,(17,38,48,255))
            self.text(cache,32,y+25,row['mode'].upper()+' · '+row['utc']+' · '+row['band'],20,(104,234,194),width=995)
            self.text(cache,32,y+54,row['receiver']+' · '+f"{row['frequency_hz']/1e6:.6f} MHz"+' · '+row['source'],16,width=990)
            snippet=row['text'] or 'No recognized text'
            match=snippet.upper().find(self.query.strip().upper()) if self.query.strip() else 0
            if match>110:snippet='…'+snippet[max(0,match-80):]
            for n,line in enumerate(textwrap.wrap(snippet,95)[:3]):self.text(cache,32,y+84+n*24,line,20,width=1040)
            if row.get('image_url'):self.button(cache,(1010,y+15,1246,y+79),'IMAGE',('image',row))
        total=self.result['total']
        if not total:self.text(cache,30,250,'No matching saved results. Try part of the callsign.',24,width=1200)
        self.button(cache,(20,728,134,792),'PREVIOUS',('page',-1))
        self.button(cache,(142,728,256,792),'NEXT',('page',1))
        self.text(cache,280,749,f'{total} results · page {self.offset//3+1}',18)
        self.text(cache,280,779,self.message or 'OCR and Morse text are tentative. Tap a mode to search across all decoders.',15,width=736)

    def tap(self,x,y,*unused):
        a=next((a for box,a in self.actions if self.ui.contains(box,x,y)),None)
        if not a:return
        kind,value=a
        if kind=='back':
            if self.picture:self.picture=None
            elif self.keyboard:self.keyboard=False
            else:self.open=False
        elif kind=='keyboard':self.keyboard=True
        elif kind=='key':self.query=(self.query+value)[:80]
        elif kind=='erase':self.query=self.query[:-1]
        elif kind=='clear':self.query=''
        elif kind=='mode':
            modes=['all','wspr','sstv','hell','qrss','cw'];self.mode=modes[(modes.index(self.mode)+1)%len(modes)];self.offset=0;self.submit()
        elif kind in ('search','done'):self.keyboard=False;self.offset=0;self.submit()
        elif kind=='page':
            self.offset=max(0,min(max(0,(self.result['total']-1)//3*3),self.offset+value*3));self.submit()
        elif kind=='image':self.picture=value

    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)
        super().close()


def install_search(workspace, mode, service):
    """Decorate only workspace entry points; no app input or audio changes."""
    view=SearchView(workspace.ui,service)
    original_draw,original_tap,original_close=workspace.draw,workspace.tap,workspace.close
    box=(424,8,538,72) if mode in ('sstv','hell') else (1034,656,1270,720)
    visible=False
    def draw(cache,*args):
        nonlocal visible
        if view.open:view.draw(cache);return
        original_draw(cache,*args)
        visible=not any(getattr(workspace,key,None) for key in ('add_open','enlarged','reporting','settings'))
        if mode!='wspr' and getattr(workspace,'field',None):visible=False
        if visible:
            label=mode.upper()+' FIND'
            if hasattr(workspace,'button'):
                workspace.button(cache,box,label,('search',None))
            else:
                visual=APP_UI_STYLE.button.resolve()
                rounded=getattr(workspace.ui,'draw_logical_rounded_rect',None)
                if callable(rounded):
                    rounded(*box,APP_UI_STYLE.button.radius,visual.fill,visual.border,visual.border_width)
                else:workspace.ui.draw_logical_rect(*box,visual.fill)
                workspace.ui.draw_text(cache,(box[0]+box[2])/2,(box[1]+box[3])/2,label,
                                       visual.text,APP_UI_STYLE.button.label_size,True,False,'cm',
                                       family=APP_UI_STYLE.button.font_family)
    def tap(x,y,*args):
        if view.open:return view.tap(x,y)
        if visible and workspace.ui.contains(box,x,y):
            view.open=True;view.mode=mode;view.offset=0;view.submit();return
        return original_tap(x,y,*args)
    def close():view.close();original_close()
    workspace.draw,workspace.tap,workspace.close=draw,tap,close
    if hasattr(workspace,'swipe'):
        swipe=workspace.swipe
        workspace.swipe=lambda sx,sy,x,y: max(abs(x-sx),abs(y-sy))>30 if view.open else swipe(sx,sy,x,y)
    if hasattr(workspace,'page_by'):
        page_by=workspace.page_by
        workspace.page_by=lambda direction: None if view.open else page_by(direction)
    workspace.log_search_view=view
