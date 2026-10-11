"""Directory-only channel metadata survives parsing, saving, and catalog merges."""
import ast
import html
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'UI'))
import receiver_catalog as catalog


class DirectoryCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree=ast.parse((ROOT/'UI/kiwi_gl_display.py').read_text())
        names={'parse_public_directory','parse_listener_capacity','parse_globe_directory',
               'normalize_station','stations_from_globe_receivers','catalog_records_from_stations',
               'merge_station_rows','receiver_directory_badges'}
        cls.env=dict(re=re,html=html,receiver_catalog=catalog,
            prioritize_local_station=lambda x:x,
            station_receiver_type=lambda x:x[7] if len(x)>7 else 'kiwi',
            receiver_source_group=lambda x:x[7] if len(x)>7 else 'kiwi')
        from types import SimpleNamespace
        cls.env.update(RECEIVER_LIST_THEME=SimpleNamespace(secondary_text=(1,2,3)),
                       ReceiverBadge=lambda label,*args:label)
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'directory','exec'),cls.env)

    def test_modes_include_legacy_separator_and_unknowns(self):
        for value,expected in [('rx8.wf3',(8,3)),('rx4_wf4',(4,4)),('rx8.wf0',(8,0))]:
            self.assertEqual(catalog.kiwi_directory_channels(value),expected)
        for value in [None,'','AM','rx8.wf99','rx0.wf0','rx999.wf3']:
            self.assertEqual(catalog.kiwi_directory_channels(value),(None,None))

    def test_map_cache_and_catalog_roundtrip(self):
        script='''var receivers=[{
"name":"Radio","loc":"Romania","gps":"(44.4, 26.0)",
"url":"http://example.test","mode":"rx8.wf3","users":"6","users_max":"8"
}];'''
        rows=self.env['parse_globe_directory'](script)
        self.assertEqual(rows[0]['audio_channels'],8)
        self.assertEqual(rows[0]['waterfall_channels'],3)
        rows=json.loads(json.dumps(rows))
        stations=self.env['stations_from_globe_receivers'](rows)
        merged=self.env['merge_station_rows'](stations)
        record=catalog.records_from_kiwi_directory(merged)[0]
        self.assertEqual((record.audio_channels,record.waterfall_channels),(8,3))
        self.assertEqual(record.listeners_used,6)
        self.assertEqual(self.env['receiver_directory_badges'](merged[0]),('AUDIO 8','WF 3'))

    def test_html_metadata_preserved_without_inventing_gps(self):
        page="""<div class='cl-entry'>
<!-- status=active --><!-- mode=rx4_wf4 --><!-- users=2 --><!-- users_max=4 -->
<a href='http://example.test'>Radio</a><div class='cl-name'>Radio</div></body>"""
        rows=self.env['parse_public_directory'](page)
        normalized=self.env['normalize_station'](json.loads(json.dumps(rows[0])))
        record=catalog.records_from_kiwi_directory([normalized])[0]
        self.assertEqual(record.directory_mode,'rx4.wf4')
        self.assertEqual(record.audio_channels,4)
        self.assertIsNone(record.latitude)

    def test_later_directory_enriches_missing_mode_without_changing_name(self):
        a=catalog.normalize_receiver(dict(server='http://test',name='Preferred',used=1,total=8))
        b=catalog.normalize_receiver(dict(server='http://test/',name='Other',mode='rx8.wf3'))
        merged=catalog.merge_catalogs([a],[b])[0]
        self.assertEqual(merged.name,'Preferred')
        self.assertEqual(merged.directory_mode,'rx8.wf3')
        changed=catalog.normalize_receiver(dict(server='http://test',mode='rx4.wf4'))
        self.assertEqual(catalog.merge_catalogs([changed],[b])[0].directory_mode,'rx4.wf4')

    def test_missing_mode_does_not_claim_capabilities(self):
        record=catalog.normalize_receiver(dict(server='http://test',total=8))
        self.assertIsNone(record.audio_channels)
        self.assertEqual(self.env['receiver_directory_badges'](record.legacy_row()),())
        self.assertEqual(len(record.legacy_row()),8)
        fmdx=catalog.normalize_receiver(dict(server='http://fm',protocol='fmdx',mode='rx8.wf3'))
        self.assertEqual(self.env['receiver_directory_badges'](fmdx.legacy_row()),())

if __name__=='__main__':unittest.main()
