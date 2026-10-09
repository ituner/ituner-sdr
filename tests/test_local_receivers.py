import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
import local_receivers as local

KEY='http://kiwisdr.local:8073'
NAME='KN6KEZ Romania KiwiSDR'
STATUS='name='+NAME+'\nsdr_hw=KiwiSDR 2\nusers=1\nusers_max=8\n'

def answer(ip):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,8073))]

class LocalReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'cache.json'
        self.resolver=local.LocalReceivers(self.path)
    def tearDown(self):self.tmp.cleanup()
    def seed(self):self.resolver.remember(KEY,{'address':'192.168.1.139','name':NAME})

    def test_learn_then_recover_after_restart_and_dns_failure(self):
        with patch.object(socket,'getaddrinfo',return_value=answer('192.168.1.139')),patch.object(local,'probe_status',return_value=(NAME,STATUS)):
            self.assertEqual(self.resolver.resolve('kiwisdr.local',8073)[0],'192.168.1.139')
        restarted=local.LocalReceivers(self.path)
        with patch.object(socket,'getaddrinfo',side_effect=socket.gaierror('no multicast')),patch.object(local,'probe_status',return_value=(NAME,STATUS)) as probe:
            self.assertEqual(restarted.resolve('kiwisdr.local',8073)[0],'192.168.1.139')
            self.assertEqual(probe.call_args.args[2],'192.168.1.139')

    def test_changed_dhcp_address_updates_cache(self):
        self.seed()
        with patch.object(socket,'getaddrinfo',return_value=answer('192.168.1.140')),patch.object(local,'probe_status',return_value=(NAME,STATUS)):
            self.assertEqual(self.resolver.resolve('kiwisdr.local',8073)[0],'192.168.1.140')
        self.assertEqual(json.loads(self.path.read_text())[KEY]['address'],'192.168.1.140')

    def test_old_address_now_different_receiver_is_rejected(self):
        self.seed()
        with patch.object(socket,'getaddrinfo',side_effect=socket.gaierror()),patch.object(local,'probe_status',return_value=('Different Kiwi',STATUS)):
            with self.assertRaisesRegex(OSError,'differently named'):self.resolver.resolve('kiwisdr.local',8073)

    def test_dead_receiver_is_reported_without_inventing_address(self):
        self.seed()
        with patch.object(socket,'getaddrinfo',side_effect=socket.gaierror()),patch.object(local,'probe_status',side_effect=TimeoutError('offline')):
            with self.assertRaisesRegex(OSError,'offline'):self.resolver.resolve('kiwisdr.local',8073)

    def test_blocked_resolver_bounded_and_not_duplicated(self):
        release=threading.Event()
        def slow(*args,**kwargs):release.wait(3);return answer('192.168.1.139')
        try:
            with patch.object(socket,'getaddrinfo',side_effect=slow) as lookup:
                started=time.monotonic()
                self.assertEqual(self.resolver.addresses('kiwisdr.local',8073,.05),[])
                self.assertEqual(self.resolver.addresses('kiwisdr.local',8073,.05),[])
                self.assertLess(time.monotonic()-started,.5)
                self.assertEqual(lookup.call_count,1)
        finally:release.set()

    def test_corrupt_cache_and_public_address_not_used(self):
        self.path.write_text('broken')
        with patch.object(socket,'getaddrinfo',return_value=answer('8.8.8.8')),patch.object(local,'probe_status') as probe:
            with self.assertRaises(OSError):self.resolver.resolve('kiwisdr.local',8073)
            probe.assert_not_called()

    def test_public_and_literal_endpoints_keep_normal_socket_path(self):
        for host in ('example.com','192.168.1.139'):
            with patch.object(socket,'create_connection',return_value='socket') as connect,patch.object(local._receivers,'resolve') as resolve:
                self.assertEqual(local.create_connection(host,8073,2),'socket')
                connect.assert_called_once_with((host,8073),timeout=2);resolve.assert_not_called()
            self.assertIsNone(local.read_local_status('http://'+host+':8073'))

    def test_status_request_retains_hostname_and_requires_kiwi(self):
        sock=Mock();connection=Mock();response=connection.getresponse.return_value
        response.status=200;response.read.return_value=STATUS.encode()
        with patch.object(socket,'create_connection',return_value=sock),patch.object(local.http.client,'HTTPConnection',return_value=connection) as http:
            self.assertEqual(local.probe_status('kiwisdr.local',8073,'192.168.1.139',False,1)[0],NAME)
            http.assert_called_once_with('kiwisdr.local',8073,timeout=1)
            response.read.return_value=b'name=Not a radio\nsdr_hw=other'
            with self.assertRaisesRegex(OSError,'does not identify'):local.probe_status('kiwisdr.local',8073,'192.168.1.139',False,1)
        sock.close.assert_called()

if __name__=='__main__':unittest.main()
