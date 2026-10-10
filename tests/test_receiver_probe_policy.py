"""Verify directory browsing cannot open public receiver health probes."""
import ast
import ipaddress
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock
from urllib.parse import urlparse
from urllib.request import Request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'UI'))
import kiwi_station_health

class ReceiverProbePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'directory.json'
        self.local_status=Mock(return_value='users=2\nusers_max=8\ngrid=KN34AL\n')
        self.http=Mock(side_effect=AssertionError('Unexpected public receiver HTTP request'))
        self.env=dict(ipaddress=ipaddress,urlparse=urlparse,json=json,re=re,Request=Request,
            STATIONS=[],GLOBE_DIRECTORY_CACHE=self.path,
            WSPR_CAPACITY_TIMEOUT_SECONDS=4,urlopen=self.http,
            kiwi=types.SimpleNamespace(read_local_status=self.local_status))
        tree=ast.parse((ROOT/'UI/kiwi_gl_display.py').read_text())
        wanted={'local_status_allowed','cached_receiver_metadata','kiwi_status_metadata',
                'kiwi_status_grid','wspr_grid_is_valid','maidenhead_grid_from_latlon','station_fields'}
        selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
        exec(compile(ast.Module(body=selected,type_ignores=[]),'policy','exec'),self.env)
    def tearDown(self):self.tmp.cleanup()

    def test_public_and_proxy_endpoints_only_read_cached_metadata(self):
        for server in ('http://remote.example:8073','http://123.proxy.kiwisdr.com:8073','http://8.8.8.8:8073'):
            self.path.write_text(json.dumps([dict(server=server,used=2,total=4,grid='FN42')]))
            self.assertEqual(self.env['kiwi_status_metadata'](server),(2,4,'FN42'))
        self.local_status.assert_not_called();self.http.assert_not_called()

    def test_missing_public_entry_remains_unknown_without_network(self):
        self.assertEqual(self.env['kiwi_status_metadata']('http://remote.example:8073'),(None,None,None))
        self.local_status.assert_not_called();self.http.assert_not_called()

    def test_only_explicit_local_names_or_addresses_allow_status(self):
        policy=self.env['local_status_allowed']
        for server in ('http://kiwisdr.local:8073','http://192.168.1.100:8073','http://[fd00::1]:8073'):
            self.assertTrue(policy(server))
        for server in ('http://kiwisdr.local.evil.example','http://receiver.example','http://0.0.0.0','http://224.0.0.1'):
            self.assertFalse(policy(server))
        self.assertEqual(self.env['kiwi_status_metadata']('http://kiwisdr.local:8073'),(2,8,'KN34AL'))
        self.local_status.assert_called_once();self.http.assert_not_called()

    def test_retired_checker_has_no_network_imports_or_probes(self):
        source=(ROOT/'UI/kiwi_station_health.py').read_text()
        self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom)) for n in ast.walk(ast.parse(source))))
        kiwi_station_health.main()
        for name in ('install.sh','install-cm5-app-only.sh'):
            source=(ROOT/'scripts'/name).read_text()
            self.assertIn('systemctl disable --now ituner-sdr-health.service',source)
            self.assertIn('ln -s /dev/null /etc/systemd/system/ituner-sdr-health.service',source)
            for line in source.splitlines():
                if line.startswith(('systemctl enable ','systemctl restart ')):
                    self.assertNotIn('ituner-sdr-health',line)

if __name__=='__main__':unittest.main()
