"""One read-only USB hotplug watcher and deliberate ID-assignment notices."""
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid
from rtl_registry import identify, usb_inventory, usb_order

SERVICE=None


def descriptors(rows):
    return tuple(sorted((str(r.get('usb_path') or r['id']),r.get('bus',0),r.get('address',0),r.get('serial',''),r.get('product',''),bool(r.get('duplicate')),bool(r.get('persistent'))) for r in rows))


def display_row(row):
    return dict(id=row['id'],name=row.get('nickname') or row.get('product') or row.get('name') or 'RTL-SDR',serial=row.get('serial') or 'Unreadable',port=row.get('usb_path') or 'Unknown',conflict=bool(row.get('duplicate')),verified_port=bool(row.get('usb_path') and row.get('bus') is not None and row.get('address') is not None))


class USBNotices:
    def __init__(self,scanner,registry,broker=None,listeners=()):
        self.scanner,self.registry,self.broker=scanner,registry,broker;self.listeners=listeners
        self.lock=threading.RLock();self.closed=threading.Event();self.wake=threading.Event();self.thread=None;self.event_thread=None
        self.prefix=uuid.uuid4().hex;self.sequence=0;self.token=secrets.token_urlsafe(32)
        self.rows=[];self.previous=None;self.notice=None;self.last_operation=None;self.source='Periodic USB check';self.socket=None;self.assigning=False;self.requests=[];self.failures={}

    def start(self):
        self.thread=threading.Thread(target=self._worker,name='usb-discovery',daemon=True);self.thread.start()
        if hasattr(socket,'AF_NETLINK'):
            self.event_thread=threading.Thread(target=self._events,name='usb-hotplug',daemon=True);self.event_thread.start()
        return self

    def _events(self):
        try:
            s=socket.socket(socket.AF_NETLINK,socket.SOCK_DGRAM,15);s.bind((0,1));s.settimeout(1);self.socket=s
            self.source='Linux USB hotplug events + 5 s fallback'
            while not self.closed.is_set():
                try:fields=s.recv(65536).split(b'\0')
                except socket.timeout:continue
                if b'SUBSYSTEM=usb' in fields and any(v in fields for v in (b'ACTION=add',b'ACTION=remove',b'ACTION=change')):
                    self.wake.set()
        except OSError:self.source='5 s USB fallback check'
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
                if any(r.get('usb_path')==port and r.get('serial')==serial for r in rows):continue
                pending[port]=dict(port=port,serial=serial,name=record.get('nickname') or record.get('product') or 'RTL-SDR')
        return list(pending.values())

    def observe(self,rows,operation=None):
        """Publish current inventory even while writes/reconnects are pending."""
        with self.lock:
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
            if signature==self.previous:
                if self.notice:self.notice['receivers']=view
                return
            before=self.previous;self.previous=signature
            if not rows and not pending and not queued and not working:self.notice=None;return
            # Removals update a dismissed notice without forcing it open again.
            previous_rows=before[0] if before else ()
            added=before is None or any(r not in set(previous_rows) for r in signature[0])
            changed_state=before is None or before[2:]!=signature[2:] or before[1]!=signature[1]
            if added or changed_state or self.notice is None:
                self._emit(kind,rows,title=titles[kind],message=(f'{len(rows)} connected. ' if kind!='ready' else '')+messages[kind],target=target['id'] if target else None,can_assign=bool(target and target['can_assign']),pending_reconnects=pending)
            self.notice['receivers']=view
            # Compatibility for clients opened before this update.
            if pending:
                self.notice.update(serial=pending[0]['serial'],port=pending[0]['port'],target_name=pending[0]['name'])

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

    def _worker(self):
        if self.closed.wait(1):return
        while not self.closed.is_set():
            try:
                with self.registry.lock:busy=bool(self.registry.operation and self.registry.operation.get('running'))
                rows=self._scan_during_write() if busy else self.scanner()
                self.observe(rows,self.registry.operation)
                if not busy:
                    for listener in self.listeners:
                        listener.devices=rows
                        if hasattr(listener,'wake'):listener.wake.set()
                    self._dispatch_next()
            except (OSError,ValueError,RuntimeError):pass
            signalled=self.wake.wait(.5 if busy or self.requests else 5);self.wake.clear()
            if signalled:self.closed.wait(.7)

    def snapshot(self):
        with self.lock:return dict(available=True,notice=dict(self.notice) if self.notice else None,source=self.source,control_token=self.token)

    def assign(self,event_id,target):
        with self.lock:
            notice=self.notice
            if not notice or notice['id']!=event_id:raise ValueError('USB inventory changed. Review the current receiver notice.')
            item=next((r for r in notice['receivers'] if r['id']==target),None)
            row=next((r for r in self.rows if r['id']==target),None)
            if not item or not row or not item.get('can_assign'):raise ValueError('This receiver cannot be assigned now. Review its current USB status.')
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
            self.last=notice['id'];self.notice=notice;self.until=now+10 if notice['kind']=='ready' else None
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
        if data.get('action')!='assign_id':raise ValueError('Unknown USB notice action')
        SERVICE.assign(data.get('event'),data.get('target'));respond(handler,b'{"ok":true}')
    except (OSError,ValueError,TypeError) as exc:respond(handler,json.dumps(dict(error=str(exc))).encode(),status=400)
    return True
