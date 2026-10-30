"""One read-only USB hotplug watcher and deliberate ID-assignment notices."""
import json
import logging
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid
from rtl_registry import identify, usb_inventory, usb_order, same_usb_attachment

SERVICE=None
CHECK_INTERVAL=2


def require_receiver(owner,selection,devices,configure,start,blocked=()):
    """Only an explicit Start may request assignment; discovery never does."""
    if SERVICE:
        SERVICE.require_receiver(owner,selection,devices,configure,start,blocked)



def scan_status(snapshot,now=None):
    """Explain whether the list is current, rather than silently keeping old rows."""
    now=time.time() if now is None else now
    count=len(snapshot.get('receivers',(snapshot.get('notice') or {}).get('receivers',[])))
    prefix=f'{count} connected · '
    if snapshot.get('scan_error'):return prefix+'USB check failed · '+snapshot['scan_error']
    stamp=snapshot.get('checked_at')
    if not stamp:return prefix+'Checking USB…'
    age=max(0,int(now-stamp))
    if age>10:return prefix+f'Last checked {age}s ago · waiting for USB check'
    return prefix+('Checking USB…' if snapshot.get('checking') else 'Checked just now' if age<2 else f'Checked {age}s ago')+' · Auto refresh'


def descriptors(rows):
    return tuple(sorted((str(r.get('usb_path') or r['id']),r.get('bus',0),r.get('address',0),r.get('serial',''),r.get('product',''),bool(r.get('duplicate')),bool(r.get('persistent'))) for r in rows))


def identity(row):
    serial=row.get('serial') or ''
    return 'serial:'+serial if serial and not row.get('duplicate') else 'port:'+str(row.get('usb_path') or row.get('id'))+':'+serial


def display_row(row):
    return dict(id=row['id'],name=row.get('nickname') or row.get('product') or row.get('name') or 'RTL-SDR',serial=row.get('serial') or 'Unreadable',port=row.get('usb_path') or 'Unknown',conflict=bool(row.get('duplicate')),verified_port=bool(row.get('usb_path') and row.get('bus') is not None and row.get('address') is not None))


class USBNotices:
    def __init__(self,scanner,registry,broker=None,listeners=()):
        self.scanner,self.registry,self.broker=scanner,registry,broker;self.listeners=listeners
        self.lock=threading.RLock();self.closed=threading.Event();self.wake=threading.Event();self.thread=None;self.event_thread=None
        self.prefix=uuid.uuid4().hex;self.sequence=0;self.token=secrets.token_urlsafe(32)
        self.rows=[];self.previous=None;self.notice=None;self.last_operation=None;self.source='Periodic USB check';self.socket=None;self.assigning=False;self.requests=[];self.failures={}
        self.checked_at=None;self.checking=False;self.scan_error=''
        self.inventory=[];self.details=False;self.selection_request=None
        self.seen_path=registry.root/'notified-receivers.json'
        try:self.seen=set(json.loads(self.seen_path.read_text()))
        except (OSError,ValueError,TypeError):self.seen={identity(r) for r in registry.records.values()}


    def start(self):
        self.thread=threading.Thread(target=self._worker,name='usb-discovery',daemon=True);self.thread.start()
        if hasattr(socket,'AF_NETLINK'):
            self.event_thread=threading.Thread(target=self._events,name='usb-hotplug',daemon=True);self.event_thread.start()
        return self

    def _events(self):
        try:
            s=socket.socket(socket.AF_NETLINK,socket.SOCK_DGRAM,15);s.bind((0,1));s.settimeout(1);self.socket=s
            self.source='Linux USB hotplug events + 2 s fallback'
            while not self.closed.is_set():
                try:fields=s.recv(65536).split(b'\0')
                except socket.timeout:continue
                if b'SUBSYSTEM=usb' in fields and any(v in fields for v in (b'ACTION=add',b'ACTION=remove',b'ACTION=change')):
                    self.wake.set()
        except OSError:self.source='2 s USB fallback check'
        finally:
            if self.socket:self.socket.close();self.socket=None

    def _emit(self,kind,rows,**extra):
        self.sequence+=1
        self.notice=dict(id=self.prefix+':'+str(self.sequence),kind=kind,receivers=[display_row(r) for r in rows],**extra)

    def _pending_reconnects(self,rows):
        pending={}
        with self.registry.lock:
            for record in self.registry.records.values():
                e=record.get('eeprom',{});port=record.get('usb_path');serial=e.get('serial')
                if not port or e.get('status')!='verified' or not serial or serial==record.get('serial'):continue
                if any(r.get('serial')==serial for r in rows):continue
                # Historical records must not flag a different dongle now in this port.
                attached=next((r for r in rows if r.get('usb_path')==port),None)
                if attached and attached.get('serial')!=record.get('serial'):continue
                pending[port]=dict(port=port,serial=serial,name=record.get('nickname') or record.get('product') or 'RTL-SDR')
        return list(pending.values())

    def observe(self,rows,operation=None):
        """Publish current inventory even while writes/reconnects are pending."""
        with self.lock:
            before_seen=set(self.seen)
            unseen=[r for r in rows if identity(r) not in self.seen]
            self.seen.update(identity(r) for r in rows)
            self.seen.update('port:'+str(r.get('usb_path') or r['id'])+':'+(r.get('serial') or '') for r in rows)
            if self.seen!=before_seen or not self.seen_path.exists():
                try:
                    self.seen_path.parent.mkdir(parents=True,exist_ok=True)
                    tmp=self.seen_path.with_suffix('.tmp');tmp.write_text(json.dumps(sorted(self.seen)));tmp.replace(self.seen_path)
                except OSError:logging.getLogger(__name__).warning('Could not save USB discovery history')
            self.rows=[dict(r) for r in rows]
            pending=self._pending_reconnects(rows);by_port={p['port']:p for p in pending}
            queued={r['attachment']['usb_path'] for r in self.requests}
            working=operation and operation.get('running')
            result=json.dumps(operation,sort_keys=True) if operation else None
            if result!=self.last_operation:
                self.last_operation=result
                if operation and not working and operation.get('ok') is False:
                    row=next((r for r in rows if r['id']==operation.get('id')),None)
                    if row:self.failures[row.get('usb_path')]=str(operation.get('message','ID assignment failed'))[:240]
            view=[]
            for row in rows:
                item=display_row(row);port=item['port']
                item['state']='reconnect' if port in by_port else 'queued' if port in queued else 'working' if working and operation.get('id')==row['id'] else 'failed' if port in self.failures else 'conflict' if item['conflict'] else 'ready'
                if port in by_port:item['new_serial']=by_port[port]['serial']
                if port in self.failures:item['error']=self.failures[port]
                item['can_assign']=bool(item['verified_port'] and item['state'] not in ('queued','working','reconnect') and (item['conflict'] or item['serial'] in ('00000000','00000001') or item['state']=='failed'))
                view.append(item)
            actionable=[r for r in view if r['conflict'] and r['can_assign']]
            failed=[r for r in view if r['state']=='failed']
            kind='conflict' if actionable else 'working' if working or queued else 'reconnect' if pending else 'failed' if failed else 'unverified' if any(not r.get('persistent') for r in rows) else 'ready'
            target=next(iter(actionable or failed),None)
            messages=dict(conflict='Connected receivers share a USB ID. Select a receiver, then Yes to give it its own ID.',working='ID changes run one at a time. You can select another receiver and queue its change.',reconnect='New IDs have been verified. Reconnect the listed receivers individually; the hub can stay powered.',failed='An ID change failed. Select that receiver to retry, or close this notice.',unverified='A receiver could not be identified reliably. Reconnect it before assigning an ID.',ready='Receivers are ready to select in your decoders.')
            titles=dict(conflict='Receiver ID conflicts',working='Receiver ID changes',reconnect='Reconnect updated receivers',failed='Receiver ID change needs attention',unverified='Receiver identity needs checking',ready=f"{len(rows)} SDR receiver{'s' if len(rows)!=1 else ''} detected")
            signature=(descriptors(rows),json.dumps([{k:v for k,v in r.items() if k!='name'} for r in view],sort_keys=True),json.dumps(pending,sort_keys=True),kind)
            self.inventory=view
            if signature==self.previous:
                if self.notice and self.notice['kind']=='select':self._selection_notice(reuse=True)
                return
            before=self.previous;self.previous=signature
            if not rows and not pending and not queued and not working and not self.selection_request and not self.details:self.notice=None;return
            # Startup reminds once about real connected duplicates. Known
            # unique devices and historical reconnect records remain quiet.
            attachments={(r[0],r[1],r[2]) for r in before[0]} if before else set()
            arrived=[r for r in rows if before and (str(r.get('usb_path') or r['id']),r.get('bus',0),r.get('address',0)) not in attachments]
            if self.details:
                self._emit(kind,rows,title=titles[kind],message=messages[kind],target=target['id'] if target else None,can_assign=bool(target),pending_reconnects=pending,arrived_ports=[r.get('usb_path') for r in arrived])
                self.notice['receivers']=view
            elif self.selection_request:
                self._selection_notice(reuse=True)
            elif before is None and any(r.get('duplicate') for r in rows):
                duplicates=[r for r in rows if r.get('duplicate')]
                self._emit('arrival',duplicates,title='Duplicate ID found',message='These connected receivers share an ID. Fix it now or choose Later.',duplicate_warning=True,startup=True,target=target['id'] if target else duplicates[0]['id'],timeout_seconds=180,expires_at=time.time()+180)
            elif before is None and unseen:
                self._emit('discovery',unseen,title='New USB receiver' if len(unseen)==1 else 'New USB receivers',message='New to this system. You can review these receivers now or choose Later. Assignment is requested when you start a decoder.',timeout_seconds=180,expires_at=time.time()+180)
            elif arrived:
                duplicate=next((r for r in arrived if r.get('duplicate')),None)
                self._emit('arrival',arrived,title='Duplicate ID found' if duplicate else 'USB receiver detected' if len(arrived)==1 else 'USB receivers detected',message='This receiver shares its ID with another dongle. Fix it now or choose Later.' if duplicate else 'Choose a receiver when starting a decoder.',duplicate_warning=bool(duplicate),target=duplicate['id'] if duplicate else None,timeout_seconds=180 if duplicate else 15,expires_at=time.time()+(180 if duplicate else 15))
            elif self.notice and self.notice['kind']=='arrival':
                live={r['id'] for r in rows}
                self.notice['receivers']=[r for r in self.notice['receivers'] if r['id'] in live]
                if not self.notice['receivers']:self.notice=None

    def review(self,event_id):
        with self.lock:
            if not self.notice or self.notice['id']!=event_id:raise ValueError('USB notice changed.')
            target=self.notice.get('target')
            self.details=True;self.previous=None
            self.observe(self.rows,self.registry.operation)
            if self.notice and any(r['id']==target and r.get('can_assign') for r in self.notice['receivers']):self.notice['target']=target

    def dismiss(self,event_id):
        with self.lock:
            if self.notice and self.notice['id']==event_id:
                self.notice=None;self.details=False;self.selection_request=None

    def require_receiver(self,owner,selection,devices,configure,start,blocked=()):
        # Resolve old IDs after a deliberate EEPROM change, without choosing an
        # arbitrary replacement when an assigned receiver disappears.
        selected=self.registry.resolve(selection,devices)
        row=next((r for r in devices if r['id']==selected and r.get('persistent') and r['id'] not in blocked),None)
        if row:
            if selected!=selection:configure(selected)
            return
        from usb_radios import owner_label
        with self.lock:
            self.selection_request=dict(owner=owner,label=owner_label(owner),configure=configure,start=start,blocked=set(blocked))
            self.details=False
            self._selection_notice()
        self.refresh()
        raise ValueError('Choose a USB receiver to start '+owner_label(owner)+'.')

    def _selection_notice(self,reuse=False):
        request=self.selection_request
        if not request:return
        leases=self.broker.snapshot() if self.broker else {}
        view=[]
        for row in self.rows:
            if row['id'] in request['blocked']:continue
            item=display_row(row);busy=leases.get(row['id']) not in (None,request['owner'])
            item.update(state='busy' if busy else 'conflict' if row.get('duplicate') else 'ready' if row.get('persistent') else 'unverified',can_choose=not busy,can_assign=False)
            view.append(item)
        if not (reuse and self.notice and self.notice['kind']=='select'):
            self._emit('select',[],title='Choose receiver · '+request['label'],message='Select a USB receiver to assign and start. Busy receivers must be stopped first.')
        self.notice['receivers']=view

    def choose(self,event_id,target):
        with self.lock:
            n=self.notice;request=self.selection_request
            if not n or n['id']!=event_id or n['kind']!='select' or not request:raise ValueError('Receiver request changed. Press Start again.')
            shown=next((r for r in n['receivers'] if r['id']==target and r.get('can_choose')),None)
            old=next((r for r in self.rows if r['id']==target),None)
            if not shown or not old:raise ValueError('Receiver is unavailable. Choose another receiver.')
        rows=getattr(self.scanner,'fresh',self.scanner)()
        row=next((r for r in rows if r['id']==target),None)
        if not same_usb_attachment(old,row):raise ValueError('Receiver changed. Refresh the list and choose again.')
        if self.broker and not self.broker.available(request['owner'],target):raise ValueError('Receiver is now in use. Stop it or choose another.')
        with self.lock:
            if self.selection_request is not request or not self.notice or self.notice['id']!=event_id:raise ValueError('Receiver request was cancelled. Press Start again.')
            if not row.get('persistent'):
                self.details=True;self.selection_request=None;self.previous=None
                self.observe(rows,self.registry.operation)
                return
            # Consume once before starting. Duplicate clicks cannot start twice.
            self.selection_request=None;self.notice=None
        request['configure'](target)
        request['start']()

    def _scan_during_write(self):
        # sysfs/libusb descriptors do not claim RF or touch the EEPROM. Keep
        # existing IDs stable while the programming worker owns its target.
        physical=usb_inventory();order=usb_order();by_address={(r['bus'],r['address']):r for r in physical}
        raw=[dict(by_address[k],index=i,name=by_address[k].get('product','RTL-SDR')) for i,k in enumerate(order) if k in by_address]
        rows=identify(raw,physical,order)
        for row in rows:
            old=next((r for r in self.rows if (r.get('bus'),r.get('address'))==(row.get('bus'),row.get('address'))),None)
            if old:
                for key in ('id','nickname','eeprom'):row[key]=old.get(key,row.get(key))
        return rows

    def _dispatch_next(self):
        with self.lock:
            if not self.requests or self.assigning:return
            with self.registry.lock:
                if self.registry.operation and self.registry.operation.get('running'):return
            request=self.requests.pop(0);self.assigning=True
        try:
            rows=getattr(self.scanner,'fresh',self.scanner)()
            row=next((r for r in rows if all(r.get(k)==request['attachment'].get(k) for k in ('usb_path','bus','address','serial'))),None)
            if not row:raise ValueError('Receiver disconnected or changed. Review it and choose Assign ID again.')
            self.registry.assign_id(row['id'],row.get('nickname',''),self.scanner,self.broker,allow_unique=bool(request['attachment'].get('duplicate')))
        except (OSError,ValueError) as exc:
            with self.lock:self.failures[request['attachment']['usb_path']]=str(exc)[:240]
        finally:
            with self.lock:self.assigning=False
        self.observe(self.rows,self.registry.operation)

    def _check(self):
        with self.lock:self.checking=True
        busy=False
        try:
            with self.registry.lock:busy=bool(self.registry.operation and self.registry.operation.get('running'))
            rows=self._scan_during_write() if busy else self.scanner()
            self.observe(rows,self.registry.operation)
            with self.lock:self.checked_at=time.time();self.scan_error=''
            if not busy:
                for listener in self.listeners:
                    listener.devices=rows
                    if hasattr(listener,'wake'):listener.wake.set()
                self._dispatch_next()
        except Exception as exc:
            # A transient descriptor/read failure must not kill hotplug discovery
            # or silently present the last successful list as a current scan.
            with self.lock:
                message=str(exc)[:160] or type(exc).__name__
                if message!=self.scan_error:logging.getLogger(__name__).warning('USB discovery failed: %s',message)
                self.scan_error=message
        finally:
            with self.lock:self.checking=False
        return busy

    def _worker(self):
        if self.closed.wait(1):return
        while not self.closed.is_set():
            busy=self._check()
            signalled=self.wake.wait(.5 if busy or self.requests else CHECK_INTERVAL);self.wake.clear()
            if signalled:self.closed.wait(.35)

    def refresh(self):self.wake.set()

    def snapshot(self):
        with self.lock:
            if self.notice and self.notice.get('expires_at',float('inf'))<=time.time():self.notice=None
            return dict(available=True,receivers=[dict(r) for r in self.inventory],notice=dict(self.notice) if self.notice else None,source=self.source,control_token=self.token,checked_at=self.checked_at,checking=self.checking,scan_error=self.scan_error)

    def assign(self,event_id,target):
        with self.lock:
            notice=self.notice
            if not notice or notice['id']!=event_id:raise ValueError('USB inventory changed. Review the current receiver notice.')
            item=next((r for r in notice['receivers'] if r['id']==target),None)
            row=next((r for r in self.rows if r['id']==target),None)
            if not item or not row or not item.get('can_assign'):raise ValueError('This receiver cannot be assigned now. Review its current USB status.')
            self.details=True
            self.requests.append(dict(attachment=dict(row)))
            self.failures.pop(row.get('usb_path'),None)
            self.observe(self.rows,self.registry.operation)
        self.wake.set()

    def close(self):self.closed.set();self.wake.set()


class NoticeView:
    """Per-screen dismiss state; clean notices get ten seconds of actual visibility."""
    def __init__(self):self.last=None;self.notice=None;self.until=None
    def update(self,notice,now):
        if notice is None:self.notice=None;return
        if notice['id']!=self.last:
            self.last=notice['id'];self.notice=notice
            duration=notice.get('timeout_seconds',15 if notice['kind']=='arrival' else 10 if notice['kind']=='ready' else None)
            self.until=now+duration if duration is not None else None
        elif self.notice is not None:self.notice=notice
        if self.until is not None and now>=self.until:self.notice=None
    def dismiss(self):self.notice=None


def inject_notice(data):
    if b'</body>' not in data or b'/dongle-notice.js' in data:return data
    data=data.replace(b'</head>',b'<script src="/usb-radio-select.js"></script><style>.usb-radio-manage{display:inline-block;font:15px system-ui;color:#95ded0;margin:6px 0 12px;text-decoration:none}</style></head>')
    return data.replace(b'</body>',b'<link rel="stylesheet" href="/dongle-notice.css"><script src="/dongle-notice.js" defer></script></body>')


def respond(handler,body,mime='application/json',status=200):
    if hasattr(handler,'send'):handler.send(body,mime,status);return
    handler.send_response(status);handler.send_header('Content-Type',mime);handler.send_header('Content-Length',str(len(body)));handler.send_header('Cache-Control','no-store');handler.send_header('X-Content-Type-Options','nosniff');handler.end_headers();handler.wfile.write(body)


def notice_get(handler,path):
    if path not in ('/api/dongle-notice','/dongle-notice.js','/dongle-notice.css','/usb-radio-select.js'):return False
    if path=='/api/dongle-notice':respond(handler,json.dumps(SERVICE.snapshot() if SERVICE else dict(available=False)).encode())
    else:respond(handler,Path(__file__).with_name(path[1:]).read_bytes(),'text/javascript' if path.endswith('.js') else 'text/css')
    return True


def notice_post(handler):
    if urlsplit(handler.path).path!='/api/dongle-notice':return False
    try:
        origin=handler.headers.get('Origin');token=handler.headers.get('X-USB-Notice-Token','')
        if SERVICE is None or not secrets.compare_digest(token,SERVICE.token) or origin and urlsplit(origin).netloc!=handler.headers.get('Host'):respond(handler,b'{"error":"Reload this SDR page before assigning an ID"}',status=403);return True
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=2048:raise ValueError('Invalid request size')
        data=json.loads(handler.rfile.read(size))
        if data.get('action')=='refresh':SERVICE.refresh()
        elif data.get('action')=='review':SERVICE.review(data.get('event'))
        elif data.get('action')=='dismiss':SERVICE.dismiss(data.get('event'))
        elif data.get('action')=='choose':SERVICE.choose(data.get('event'),data.get('target'))
        elif data.get('action')=='assign_id':SERVICE.assign(data.get('event'),data.get('target'))
        else:raise ValueError('Unknown USB notice action')
        respond(handler,b'{"ok":true}')
    except (OSError,ValueError,TypeError) as exc:respond(handler,json.dumps(dict(error=str(exc))).encode(),status=400)
    return True
