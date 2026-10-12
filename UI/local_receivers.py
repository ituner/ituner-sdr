"""Bounded local DNS lookup; no HTTP probes or stale-address fallback.
Public hosts and literal IP endpoints retain the standard connection path.
"""

import ipaddress
import socket
import threading
import time


def is_local(host):
    return host.lower().rstrip('.').endswith('.local')


def lan_address(value):
    try:
        ip=ipaddress.ip_address(value.split('%',1)[0])
        return ip.is_private and not (ip.is_unspecified or ip.is_multicast or ip.is_loopback)
    except (ValueError,AttributeError):return False


class LocalReceivers:
    def __init__(self):
        self.lock = threading.Lock()
        self.lookups = {}

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

    def resolve(self, host, port, secure=False, timeout=8):
        host = host.lower().rstrip('.')
        addresses = self.addresses(host, port, timeout)
        if addresses:
            return addresses[0], None
        # Previously a saved IP was verified using a standalone status fetch.
        # Without that identity check, a stale DHCP lease could be another radio.
        raise OSError(f'Local Kiwi {host} name discovery failed. Check mDNS forwarding or use a reserved LAN IP.')


_receivers=LocalReceivers()


def create_connection(host,port,timeout=8,secure=False):
    if not is_local(host):return socket.create_connection((host,port),timeout=timeout)
    started=time.monotonic()
    address,_=_receivers.resolve(host,port,secure,timeout)
    remaining=timeout-(time.monotonic()-started)
    if remaining<=0:raise TimeoutError('Local Kiwi connection timeout')
    return socket.create_connection((address,port),timeout=remaining)
