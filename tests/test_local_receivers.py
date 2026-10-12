import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
import local_receivers as local


def answer(ip):
    return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,8073))]


class LocalReceiverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = local.LocalReceivers()

    def test_local_dns_resolves_without_http(self):
        with patch.object(socket,'getaddrinfo',return_value=answer('192.168.1.139')):
            self.assertEqual(self.resolver.resolve('kiwisdr.local',8073),('192.168.1.139',None))

    def test_failed_dns_does_not_reuse_stale_address(self):
        with patch.object(socket,'getaddrinfo',side_effect=socket.gaierror('no multicast')):
            with self.assertRaisesRegex(OSError,'name discovery failed'):
                self.resolver.resolve('kiwisdr.local',8073)

    def test_blocked_resolver_bounded_and_not_duplicated(self):
        release=threading.Event()
        def slow(*args,**kwargs):
            release.wait(3)
            return answer('192.168.1.139')
        try:
            with patch.object(socket,'getaddrinfo',side_effect=slow) as lookup:
                started=time.monotonic()
                self.assertEqual(self.resolver.addresses('kiwisdr.local',8073,.05),[])
                self.assertEqual(self.resolver.addresses('kiwisdr.local',8073,.05),[])
                self.assertLess(time.monotonic()-started,.5)
                self.assertEqual(lookup.call_count,1)
        finally:
            release.set()

    def test_public_address_from_local_name_is_rejected(self):
        with patch.object(socket,'getaddrinfo',return_value=answer('8.8.8.8')):
            with self.assertRaises(OSError):
                self.resolver.resolve('kiwisdr.local',8073)

    def test_public_and_literal_endpoints_keep_normal_socket_path(self):
        for host in ('example.com','192.168.1.139'):
            with patch.object(socket,'create_connection',return_value='socket') as connect,patch.object(local._receivers,'resolve') as resolve:
                self.assertEqual(local.create_connection(host,8073,2),'socket')
                connect.assert_called_once_with((host,8073),timeout=2)
                resolve.assert_not_called()

    def test_local_connection_uses_resolved_address_without_probe(self):
        with patch.object(local._receivers,'resolve',return_value=('192.168.1.140',None)),patch.object(socket,'create_connection',return_value='socket') as connect:
            self.assertEqual(local.create_connection('kiwisdr.local',8073,2),'socket')
            self.assertEqual(connect.call_args.args[0],('192.168.1.140',8073))

if __name__=='__main__':unittest.main()
