import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from receiver_command_pacing import CommandPolicy, PacedSocket, command_family, receiver_key


class FakeTransport:
    def __init__(self, log):
        self.log = log
        self.sock = self
        self.closed = False

    def send_text(self, text):
        self.log.append((time.monotonic(), text))

    def close(self):
        self.closed = True

    def shutdown(self, how):
        self.closed = True


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.policy = CommandPolicy(Path(self.temp.name)/'policy.json')
        self.log, self.sockets = [], []

    def tearDown(self):
        for s in self.sockets:
            s.close()
        self.temp.cleanup()

    def socket(self, protocol='kiwi', endpoint='http://radio.example:8073'):
        s = PacedSocket(FakeTransport(self.log), endpoint, protocol, self.policy)
        self.sockets.append(s)
        return s

    def wait_count(self, n, timeout=3):
        deadline = time.monotonic() + timeout
        while len(self.log) < n and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertGreaterEqual(len(self.log), n)

    def test_public_combined_budget_across_streams(self):
        sockets = [self.socket() for _ in range(6)]
        for i, s in enumerate(sockets):
            s.send_text(f'SET mod=am freq={i}')
        self.wait_count(6)
        times = [t for t, _ in self.log]
        self.assertTrue(all(b-a >= .199 for a,b in zip(times,times[1:])), times)
        self.assertGreaterEqual(times[5]-times[0], .999)

    def test_latest_only_and_fairness(self):
        a, b = self.socket(), self.socket()
        a.budget.last_sent = time.monotonic()
        before = time.monotonic()
        for i in range(1000):
            a.send_text(f'SET mod=am freq={i}')
            b.send_text(f'SET zoom=4 cf={i}')
        self.assertLess(time.monotonic()-before, .1)
        self.assertLessEqual(len(a.budget.pending), 2)
        self.wait_count(2)
        self.assertEqual([s for _,s in self.log], ['SET mod=am freq=999', 'SET zoom=4 cf=999'])

    def test_local_requires_explicit_choice_and_persists(self):
        endpoint = 'http://192.168.1.20:8073'
        s = self.socket(endpoint=endpoint)
        key = receiver_key(endpoint)
        self.assertEqual(self.policy.rate(key), 5)
        self.policy.set_trusted(key, True)
        self.assertEqual(CommandPolicy(self.policy.path).rate(key), 50)
        self.assertEqual(self.policy.rate(receiver_key('http://different.example')), 5)
        for i in range(3):
            s.send_text(f'SET mod=am freq={i}')
            self.wait_count(i+1)
        intervals = [self.log[i+1][0]-self.log[i][0] for i in range(2)]
        self.assertTrue(all(.019 <= gap < .15 for gap in intervals), intervals)
        self.policy.set_trusted(key, False)
        s.send_text('SET mod=am freq=4')
        self.wait_count(4)
        self.assertGreaterEqual(self.log[3][0]-self.log[2][0], .199)

    def test_keepalive_does_not_wait_and_close_discards_pending(self):
        s = self.socket()
        s.budget.last_sent = time.monotonic()
        s.send_text('SET mod=am freq=123')
        s.send_text('SET keepalive')
        self.assertEqual([x for _,x in self.log], ['SET keepalive'])
        s.close()
        time.sleep(.25)
        self.assertEqual(len(self.log), 1)

    def test_openwebrx_start_after_latest_parameters(self):
        s = self.socket('openwebrx', 'owrx://rx.example:8073')
        s.budget.last_sent = time.monotonic()
        def params(freq):
            return json.dumps({'type':'dspcontrol','params':{'offset_freq':freq}})
        s.send_text(params(1))
        s.send_text(json.dumps({'type':'dspcontrol','action':'start'}))
        s.send_text(params(2))
        self.wait_count(2)
        self.assertEqual(json.loads(self.log[0][1])['params']['offset_freq'], 2)
        self.assertEqual(json.loads(self.log[1][1])['action'], 'start')

    def test_fmdx_and_independent_receivers(self):
        s = self.socket('fmdx', 'http://fm.example:8080')
        s.send_text('T100000')
        other = self.socket(endpoint='http://different.example:8073')
        other.send_text('SET mod=am freq=200')
        self.wait_count(2)
        self.assertLess(abs(self.log[1][0]-self.log[0][0]), .15)

    def test_independent_profile_sliders_and_persistence(self):
        key = receiver_key('http://radio.example:8073')
        self.policy.set_profile_rate('public', 37)
        self.policy.set_profile_rate('local', 82)
        self.assertEqual(self.policy.rate(key), 37)
        self.policy.set_trusted(key, True)
        self.assertEqual(self.policy.rate(key), 82)
        restored = CommandPolicy(self.policy.path)
        self.assertEqual(restored.profile_rate('public'), 37)
        self.assertEqual(restored.rate(key), 82)
        self.policy.set_trusted(key, False)
        self.assertEqual(self.policy.rate(key), 37)
        for profile in ('public', 'local'):
            self.policy.set_profile_rate(profile, 200)
            self.assertEqual(self.policy.profile_rate(profile), 100)
            self.policy.set_profile_rate(profile, 0)
            self.assertEqual(self.policy.profile_rate(profile), 1)

    def test_slider_preview_and_release_save(self):
        self.policy.set_profile_rate('public', 7)
        self.policy.set_profile_rate('public', 91, persist=False)
        self.assertEqual(self.policy.profile_rate('public'), 91)
        self.assertEqual(CommandPolicy(self.policy.path).profile_rate('public'), 7)
        self.policy.set_profile_rate('public', 91, persist=True)
        self.assertEqual(CommandPolicy(self.policy.path).profile_rate('public'), 91)

    def test_legacy_settings_keep_trust_and_default_profiles(self):
        self.policy.path.write_text(json.dumps({'trusted_local': ['local:8073'], 'rates': {'local:8073': 17}}))
        restored = CommandPolicy(self.policy.path)
        self.assertEqual(restored.rate('local:8073'), 50)
        self.assertEqual(restored.rate('public:8073'), 5)

    def test_lower_rate_applies_to_queued_commands(self):
        s = self.socket()
        s.send_text('SET mod=am freq=100')
        self.wait_count(1)
        s.send_text('SET mod=am freq=101')
        self.policy.set_profile_rate('public', 2)
        self.wait_count(2)
        self.assertGreaterEqual(self.log[1][0] - self.log[0][0], .499)

    def test_classification_and_endpoint_normalization(self):
        self.assertEqual(receiver_key('owrx://EXAMPLE:80', 'openwebrx'), receiver_key('http://example', 'openwebrx'))
        self.assertIsNone(command_family('SET keepalive', 'kiwi'))
        self.assertIsNone(command_family('SET auth t=kiwi p=', 'kiwi'))
        self.assertEqual(command_family('T100100', 'fmdx'), 'fm-tune')


if __name__ == '__main__':
    unittest.main()
