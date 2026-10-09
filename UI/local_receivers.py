"""Bounded .local resolution with a persistent, verified Kiwi address fallback.
Public hosts and literal IP endpoints retain the standard connection path.
No LAN scan, global DNS changes, redirects, or unverified cached-address reuse.
"""
import fcntl
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time
from urllib.parse import urlparse


def is_local(host):
    return host.lower().rstrip('.').endswith('.local')


def lan_address(value):
    try:
        ip=ipaddress.ip_address(value.split('%',1)[0])
        return ip.is_private and not (ip.is_unspecified or ip.is_multicast or ip.is_loopback)
    except (ValueError,AttributeError):return False


def probe_status(host,port,address,secure,timeout):
    connection=http.client.HTTPConnection(host,port,timeout=timeout)
    raw=socket.create_connection((address,port),timeout=timeout)
    try:
        if secure:raw=ssl.create_default_context().wrap_socket(raw,server_hostname=host)
        connection.sock=raw
        connection.request('GET','/status',headers={'User-Agent':'iTuner-local-receiver/1.0','Connection':'close'})
        response=connection.getresponse()
        if response.status!=200:raise OSError(f'Kiwi status returned HTTP {response.status}')
        data=response.read(32769)
        if len(data)>32768:raise OSError('Kiwi status response too large')
        text=data.decode('utf-8','replace')
        values=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
        if 'KiwiSDR' not in values.get('sdr_hw','') or not values.get('name','').strip():
            raise OSError('Address does not identify a KiwiSDR receiver')
        return values['name'].strip(),text
    finally:
        connection.close();raw.close()


class LocalReceivers:
    def __init__(self,path=None):
        self.path=Path(path or os.environ.get('ITUNER_LOCAL_RECEIVERS_CACHE',
            str(Path.home()/'.cache/ituner-sdr/local-receivers.json')))
        self.lock=threading.Lock();self.lookups={};self.memory={};self.reported=set()

    def load(self):
        try:
            data=json.loads(self.path.read_text())
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def remember(self,key,record):
        with self.lock:
            self.memory[key]=record
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.with_suffix('.lock').open('a') as guard:
                    fcntl.flock(guard,fcntl.LOCK_EX)
                    data=self.load()
                    if data.get(key)==record:return
                    data[key]=record
                    data=dict(list(data.items())[-32:])
                    fd,tmp=tempfile.mkstemp(prefix='.local-receivers-',dir=self.path.parent)
                    try:
                        with os.fdopen(fd,'w') as out:json.dump(data,out)
                        os.replace(tmp,self.path)
                    finally:
                        if os.path.exists(tmp):os.unlink(tmp)
            except OSError:
                # A read-only disk must not stop an otherwise working radio.
                pass

    def addresses(self,host,port,timeout):
        key=(host,port)
        with self.lock:
            job=self.lookups.get(key)
            if job is None or (job['ready'].is_set() and time.monotonic()-job['done']>(30 if job['addresses'] else 5)):
                job={'ready':threading.Event(),'addresses':[],'done':0};self.lookups[key]=job
                def lookup():
                    try:
                        rows=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
                        addresses=[]
                        for family,kind,proto,canon,addr in rows:
                            ip=addr[0]
                            if family==socket.AF_INET6 and len(addr)>3 and addr[3]:ip+='%' + str(addr[3])
                            if lan_address(ip) and ip not in addresses:addresses.append(ip)
                        job['addresses']=addresses[:4]
                    except OSError:pass
                    finally:job['done']=time.monotonic();job['ready'].set()
                threading.Thread(target=lookup,daemon=True,name='kiwi-local-dns').start()
        # The OS resolver can block beyond socket timeouts. Keep it off the
        # connection thread and allow at most one outstanding lookup per host.
        job['ready'].wait(max(0,min(1.0,timeout)))
        return list(job['addresses'])

    def resolve(self,host,port,secure=False,timeout=8):
        host=host.lower().rstrip('.');key=f'{"https" if secure else "http"}://{host}:{port}'
        deadline=time.monotonic()+timeout
        with self.lock:cached=self.memory.get(key)
        cached=self.load().get(key) or cached or {}
        if not isinstance(cached,dict):cached={}
        saved=cached.get('address')
        fresh=self.addresses(host,port,timeout)
        candidates=list(fresh)
        if saved not in candidates and lan_address(saved):candidates.append(saved)
        problem='name discovery did not respond'
        for address in candidates:
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            try:
                name,status=probe_status(host,port,address,secure,min(1.5,remaining))
                fallback=address not in fresh
                if fallback and name!=cached.get('name'):
                    raise OSError('Saved address now belongs to a differently named KiwiSDR')
                self.remember(key,dict(address=address,name=name))
                if fallback:
                    with self.lock:
                        announce=(key,address) not in self.reported;self.reported.add((key,address))
                    if announce:print(f'kiwi local recovery: {host} -> {address} (verified {name})',flush=True)
                return address,status
            except (OSError,http.client.HTTPException) as exc:problem=str(exc)
        raise OSError(f'Local Kiwi {host} unavailable: {problem}. Check receiver power/address or reserve its DHCP address.')


_receivers=LocalReceivers()


def create_connection(host,port,timeout=8,secure=False):
    if not is_local(host):return socket.create_connection((host,port),timeout=timeout)
    started=time.monotonic()
    address,_=_receivers.resolve(host,port,secure,timeout)
    remaining=timeout-(time.monotonic()-started)
    if remaining<=0:raise TimeoutError('Local Kiwi connection timeout')
    return socket.create_connection((address,port),timeout=remaining)


def read_local_status(endpoint,timeout=5):
    """Return verified status for .local endpoints; None for the normal path."""
    parsed=urlparse(endpoint)
    if not parsed.hostname or not is_local(parsed.hostname):return None
    secure=parsed.scheme in ('https','wss')
    _,status=_receivers.resolve(parsed.hostname,parsed.port or (443 if secure else 80),secure,timeout)
    return status
