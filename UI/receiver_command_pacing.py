"""Shared, latest-value command pacing per receiver; never sleep in audio/UI loops."""
from collections import OrderedDict, deque
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse


def receiver_key(endpoint, protocol='kiwi'):
    value = str(endpoint).replace('owrxs://', 'https://').replace('owrx://', 'http://')
    parsed = urlparse(value if '://' in value else 'http://' + value)
    default = 443 if parsed.scheme in ('https', 'wss') else (8073 if protocol == 'kiwi' else 80)
    return f'{(parsed.hostname or "unknown").lower()}:{parsed.port or default}'


def command_family(text, protocol):
    if protocol == 'kiwi':
        if text.startswith('SET mod=') and ' freq=' in text:
            return 'audio-tune'
        if text.startswith('SET zoom='):
            return 'waterfall-view'
    elif protocol == 'fmdx' and re.fullmatch(r'T\d+', text):
        return 'fm-tune'
    elif protocol == 'openwebrx':
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return None
        if isinstance(value, dict) and value.get('type') == 'dspcontrol':
            # Start stays behind the initial parameters; later params coalesce.
            if value.get('action') == 'start':
                return 'dsp-start'
            if isinstance(value.get('params'), dict):
                return 'dsp-parameters'
    return None


class CommandPolicy:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home()/'.config/ituner-sdr/receiver-command-policy.json'
        self.lock = threading.Lock()
        self.budgets = {}
        self.profile_rates = {'public': 5, 'local': 50}
        try:
            value = json.loads(self.path.read_text())
            self.trusted = set(value.get('trusted_local', []))
            rates = value.get('profile_rates', {})
            if isinstance(rates, dict):
                for profile in self.profile_rates:
                    rate = rates.get(profile)
                    if isinstance(rate, int) and not isinstance(rate, bool):
                        self.profile_rates[profile] = max(1, min(100, rate))
        except (OSError, ValueError, TypeError, AttributeError):
            self.trusted = set()

    def is_trusted(self, key):
        with self.lock:
            return key in self.trusted

    def profile_rate(self, profile):
        with self.lock:
            return self.profile_rates[profile]

    def rate(self, key):
        with self.lock:
            return self.profile_rates['local' if key in self.trusted else 'public']

    def _save_locked(self, trusted, rates):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'trusted_local': sorted(trusted), 'profile_rates': rates}) + '\n')
        os.replace(tmp, self.path)

    @staticmethod
    def _wake(budget):
        if budget:
            with budget.condition:
                budget.condition.notify_all()

    def set_trusted(self, key, enabled):
        with self.lock:
            updated = set(self.trusted)
            updated.add(key) if enabled else updated.discard(key)
            self._save_locked(updated, self.profile_rates)
            self.trusted = updated
            budget = self.budgets.get(key)
        self._wake(budget)

    def set_profile_rate(self, profile, rate, persist=True):
        if profile not in ('public', 'local'):
            raise ValueError('Unknown receiver profile')
        with self.lock:
            rates = dict(self.profile_rates)
            rates[profile] = max(1, min(100, int(rate)))
            if persist:
                self._save_locked(self.trusted, rates)
            self.profile_rates = rates
            budgets = list(self.budgets.values())
        for budget in budgets:
            self._wake(budget)

    def budget(self, key):
        with self.lock:
            if key not in self.budgets:
                self.budgets[key] = ReceiverBudget(self, key)
            return self.budgets[key]


class ReceiverBudget:
    def __init__(self, policy, key):
        self.policy, self.key = policy, key
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.last_sent = float('-inf')
        self.thread = None
        self.sent_times = deque(maxlen=512)
        self.sent_total = 0
        self.last_report = 0.0

    def submit(self, owner, family, text):
        with self.condition:
            if owner.closed:
                return
            # Replacing in place preserves fairness between audio and waterfall.
            self.pending[(owner, family)] = text
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='receiver-command-pacer', daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def cancel(self, owner):
        with self.condition:
            for key in list(self.pending):
                if key[0] is owner:
                    del self.pending[key]
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                if not self.pending:
                    self.condition.wait(5)
                    if not self.pending:
                        self.thread = None
                        return
                delay = self.last_sent + 1.0/self.policy.rate(self.key) - time.monotonic()
                if delay > 0:
                    self.condition.wait(delay)
                    continue
                (owner, family), text = self.pending.popitem(last=False)
            try:
                sent = owner.deliver(text)
            except Exception as exc:
                owner.failed(exc)
                sent = False
            if sent:
                now = time.monotonic()
                with self.condition:
                    # Pace from completion, so a stalled write cannot create a burst.
                    self.last_sent = now
                    self.sent_times.append(now)
                    self.sent_total += 1
                    recent = sum(t > now - 1 for t in self.sent_times)
                if now - self.last_report >= 5:
                    print(f'Receiver pacing {self.key} limit={self.policy.rate(self.key)}/s '
                          f'sent_last_second={recent} total={self.sent_total}', flush=True)
                    self.last_report = now


POLICY = CommandPolicy()


class PacedSocket:
    def __init__(self, transport, endpoint, protocol, policy=POLICY):
        self.transport = transport
        self.protocol = protocol
        self.budget = policy.budget(receiver_key(endpoint, protocol))
        self.closed = False
        self.error = None
        self.send_lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def send_text(self, text):
        if self.error:
            raise OSError(f'Paced receiver send failed: {self.error}')
        if self.closed:
            raise OSError('Receiver transport closed')
        family = command_family(text, self.protocol)
        if family is None:
            return self.deliver(text)
        self.budget.submit(self, family, text)

    def deliver(self, text):
        with self.send_lock:
            if self.closed:
                return False
            self.transport.send_text(text)
            return True

    def failed(self, error):
        self.error = error
        self.closed = True
        self.budget.cancel(self)
        try:
            self.transport.sock.shutdown(2)
        except (OSError, AttributeError):
            pass

    def send_close(self):
        self.closed = True
        self.budget.cancel(self)
        with self.send_lock:
            if hasattr(self.transport, 'send_close'):
                self.transport.send_close()
            else:
                self.transport.close()

    def close(self):
        self.closed = True
        self.budget.cancel(self)
        with self.send_lock:
            if hasattr(self.transport, 'close'):
                self.transport.close()
            else:
                self.transport.send_close()
                self.transport.sock.close()


def paced_socket(transport, endpoint, protocol):
    return PacedSocket(transport, endpoint, protocol)
