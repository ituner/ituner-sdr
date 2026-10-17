"""Exclusive receiver leases shared by the local VHF/UHF decoders.

Discovery reads USB descriptors; claiming a receiver happens only on Start.
Callbacks request a graceful stop, and a new owner must wait for release.
"""
import threading


def soapy_args(device):
    if device.get('soapy'):
        return device['soapy']
    if device.get('persistent') and device.get('serial'):
        return 'driver=rtlsdr,serial='+device['serial']
    raise ValueError('SoapySDR requires a unique USB serial for each RTL-SDR receiver.')


class ReceiverBroker:
    def __init__(self):
        self.lock = threading.RLock()
        self.leases = {}
        self.stoppers = {}

    def register(self, owner, stop):
        with self.lock: self.stoppers[owner] = stop

    def request(self, owner, devices, selection='auto'):
        """User-requested handoff, preferring an unused receiver for Auto."""
        with self.lock:
            choices = [d for d in devices if selection == 'auto' or d['id'] == selection]
            if not choices: return selection
            target = next((d for d in choices if self.leases.get(d['id']) in (None, owner)), choices[0])
            previous = self.leases.get(target['id'])
            stop = self.stoppers.get(previous) if previous != owner else None
        if stop: stop()
        return target['id']

    def acquire(self, owner, device):
        with self.lock:
            if self.leases.get(device) not in (None, owner): return False
            self.leases[device] = owner
            return True

    def release(self, owner):
        with self.lock:
            self.leases = {key:value for key,value in self.leases.items() if value != owner}

    def available(self, owner, device):
        with self.lock: return self.leases.get(device) in (None, owner)

    def snapshot(self):
        with self.lock: return dict(self.leases)
