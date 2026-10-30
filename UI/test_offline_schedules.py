import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import zipfile

import offline_schedules as db


def hfcc_fixture(mode='D'):
    row = list(' '*154)
    for start,value in [(0,' 7300'),(6,'2300'),(11,'0100'),(47,'WOF'),(51,' 100'),
                        (72,'2'),(80,'251026'),(87,'280327'),(94,mode),
                        (102,'Eng'),(113,'G'),(117,'BBC')]:
        row[start:start+len(value)] = value
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('B26all00.TXT','; header\n'+''.join(row))
        archive.writestr('broadcas.txt','; header\nBBC BBC\n')
        archive.writestr('admin.txt','G   United Kingdom\n')
        archive.writestr('language.txt','Eng English\n')
        archive.writestr('site.txt','WOF Woofferton                     G   52N19 002W43\n')
    return output.getvalue()


def schedule(**overrides):
    row = dict(frequency_khz=7300.0,station='BBC',transmitter='Woofferton',country='United Kingdom',
               power_kw='',language='English',source='EiBi B26',time='0000-2400',days='',
               day_system='monday',valid_from='2026-10-25',valid_until='2027-03-28')
    row.update(overrides)
    return row


def timestamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class ImportTests(unittest.TestCase):
    def test_season_rollovers_at_last_sundays_and_year_boundary(self):
        self.assertEqual(db.season_for(date(2026,10,24))[0],'a26')
        self.assertEqual(db.season_for(date(2026,10,25))[0],'b26')
        self.assertEqual(db.season_for(date(2027,1,1))[0],'b26')
        self.assertEqual(db.season_for(date(2027,3,28))[0],'a27')

    def test_eibi_resolves_reference_codes_and_excludes_inactive_and_utility(self):
        reference = '''   I) Language codes.
   E     English (400m)
   II) Country codes.
   G    United Kingdom
   IV) Transmitter site codes.
   G: w-Woofferton 52N19-02W43
'''
        text = ('kHz;header\n7300;0000-2400;;G;BBC;E;Eu;w;1;;\n'
                '7301;0000-2400;;G;Inactive;E;Eu;w;8;;\n'
                '7302;0000-2400;;G;Utility;-CW;Eu;w;91;;\n'
                'bad;0000-2400;;G;Bad;E;Eu;w;1;;\n')
        rows = db.parse_eibi(text.encode(),reference,'b26',date(2026,10,25),date(2027,3,28))
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['country'],rows[0]['language'],rows[0]['transmitter']),
                         ('United Kingdom','English','Woofferton'))

    def test_hfcc_fixed_columns_reference_tables_dates_and_modulation(self):
        rows = db.parse_hfcc(hfcc_fixture(),'b26')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['station'],'BBC')
        self.assertEqual(rows[0]['power_kw'],'100')
        self.assertEqual(rows[0]['time'],'2300-0100')
        self.assertEqual(rows[0]['transmitter'],'Woofferton')
        self.assertEqual(rows[0]['valid_until'],'2027-03-29')
        self.assertEqual(db.parse_hfcc(hfcc_fixture('N'),'b26'),[])

    def test_weekday_systems_and_overnight_broadcast_day(self):
        # Monday 26th October starts at 23:00, ending Tuesday 01:00.
        row = schedule(time='2300-0100',days='2',day_system='sunday')
        for moment in ('2026-10-26T23:30','2026-10-27T00:30'):
            self.assertTrue(db.active(row,datetime.fromisoformat(moment)))
        for moment in ('2026-10-26T00:30','2026-10-27T01:00'):
            self.assertFalse(db.active(row,datetime.fromisoformat(moment)))
        row.update(days='1',day_system='monday')
        self.assertTrue(db.active(row,datetime(2026,10,27,0,30)))

    def test_expired_seasons_and_unknown_day_codes_are_not_current_matches(self):
        row = schedule(valid_until='2026-10-25')
        self.assertFalse(db.active(row,datetime(2026,10,29,12)))
        row = schedule(days='ambiguous')
        self.assertFalse(db.active(row,datetime(2026,10,29,12)))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.downloader = Mock(side_effect=OSError('offline'))
        self.store = db.ScheduleStore(self.temp.name,self.downloader)

    def seed(self, provider, rows, fetched_at=0):
        payload = dict(version=1,source=provider,season='B26',rows=rows,fetched_at=fetched_at,url='source')
        (Path(self.temp.name)/(provider+'.json')).write_text(json.dumps(payload))

    def test_restart_lookups_work_offline_and_filter_frequency_and_utc(self):
        self.seed('eibi',[schedule(),schedule(frequency_khz=7305,station='Other')])
        result = self.store.lookup(7300.1,timestamp('2026-10-29T12:00'))[1]
        self.assertEqual([r['station'] for r in result],['BBC'])
        self.assertEqual(self.store.lookup(7300,timestamp('2027-04-01T12:00'))[1],[])
        self.downloader.assert_not_called()

    def test_fractional_carrier_and_larger_offset_match_the_scheduled_channel(self):
        self.seed('hfcc',[schedule(frequency_khz=5880)])
        for measured,kind in ((5879.891,'direct'),(5878.8,'channel'),(5882.2,'channel')):
            with self.subTest(measured=measured):
                rows = self.store.lookup(measured,timestamp('2026-10-29T12:00'))[1]
                self.assertEqual([r['frequency_khz'] for r in rows],[5880])
                self.assertEqual(rows[0]['match_kind'],kind)
                self.assertEqual(rows[0]['measured_frequency_khz'],measured)
        self.downloader.assert_not_called()

    def test_channel_midpoint_and_excessive_offsets_do_not_get_guessed(self):
        self.seed('hfcc',[schedule(frequency_khz=7300),schedule(frequency_khz=7305,station='Other')])
        for measured in (7302.4,7302.5,7302.6):
            self.assertEqual(self.store.lookup(measured,timestamp('2026-10-29T12:00'))[1],[])

    def test_real_off_channel_entries_take_priority_over_grid_rounding(self):
        self.seed('eibi',[schedule(frequency_khz=7301.2,station='Off-channel')])
        rows = self.store.lookup(7301.1,timestamp('2026-10-29T12:00'))[1]
        self.assertEqual(rows[0]['frequency_khz'],7301.2)
        self.assertEqual(rows[0]['match_kind'],'direct')

    def test_nearest_frequency_wins_but_equally_close_options_remain_ambiguous(self):
        self.seed('eibi',[schedule(frequency_khz=7300),schedule(frequency_khz=7300.8,station='Other')])
        self.assertEqual(len(self.store.lookup(7300.1,timestamp('2026-10-29T12:00'))[1]),1)
        self.assertEqual(len(self.store.lookup(7300.4,timestamp('2026-10-29T12:00'))[1]),2)

    def test_lw_and_mw_fallback_use_listed_frequencies_and_time_filter_still_applies(self):
        self.seed('eibi',[schedule(frequency_khz=999),schedule(frequency_khz=1000),
                          schedule(frequency_khz=153),schedule(frequency_khz=5880,time='0900-1000')])
        for measured,listed in ((997.1,999),(1001.9,1000),(151.6,153)):
            rows = self.store.lookup(measured,timestamp('2026-10-29T12:00'))[1]
            self.assertEqual([r['frequency_khz'] for r in rows],[listed])
        self.assertEqual(self.store.lookup(5878.8,timestamp('2026-10-29T12:00'))[1],[])

    def test_two_sources_merge_metadata_without_hiding_different_broadcasters(self):
        self.seed('eibi',[schedule()])
        self.seed('hfcc',[schedule(source='HFCC B26',power_kw='100'),
                          schedule(source='HFCC B26',station='Another broadcaster')])
        rows = self.store.lookup(7300,timestamp('2026-10-29T12:00'))[1]
        self.assertEqual(len(rows),2)
        bbc = next(r for r in rows if r['station']=='BBC')
        self.assertEqual(bbc['power_kw'],'100')
        self.assertIn('HFCC',bbc['source'])

    def test_failed_refresh_preserves_the_last_good_files(self):
        self.seed('eibi',[schedule()])
        before = (Path(self.temp.name)/'eibi.json').read_bytes()
        self.store.refresh(date(2026,10,29))
        self.assertEqual((Path(self.temp.name)/'eibi.json').read_bytes(),before)
        self.assertTrue(self.store.lookup(7300,timestamp('2026-10-29T12:00'))[1])
        self.assertFalse(self.store.refreshing)
        self.assertIn('incomplete',self.store.status()[1])

    def test_successful_bulk_import_is_persistent_and_only_daily(self):
        eibi = b'7300;0000-2400;;G;BBC;E;Eu;w;1;;\n'
        def download(url):
            return hfcc_fixture() if url.endswith('.zip') else b'' if url.endswith('README.TXT') else eibi
        self.store.downloader = Mock(side_effect=download)
        self.store.refresh(date(2026,10,29))
        self.assertEqual(len(self.store.providers),2)
        self.assertTrue((Path(self.temp.name)/'hfcc.json').exists())
        self.store.downloader.reset_mock()
        self.store.refresh_if_due()
        self.store.refresh(date(2026,10,29))
        self.store.downloader.assert_not_called()

    def test_missing_current_eibi_season_is_saved_as_old_and_not_misidentified(self):
        def download(url):
            if url.endswith('.zip'):
                return hfcc_fixture()
            if 'sked-b26' in url:
                raise HTTPError(url,404,'missing',None,None)
            return b'' if url.endswith('README.TXT') else b'7300;0000-2400;;G;Old BBC;E;Eu;;1;;\n'
        self.store.downloader = download
        self.store.refresh(date(2026,10,29))
        self.assertEqual(self.store.providers['eibi']['season'],'A26')
        self.assertIn('old season',self.store.status()[1])
        self.assertFalse(any(r['station']=='Old BBC' for r in self.store.lookup(7300,timestamp('2026-10-29T12:00'))[1]))

    def test_corrupt_cache_is_ignored_and_retry_is_bounded(self):
        (Path(self.temp.name)/'eibi.json').write_text('{bad')
        self.assertEqual(self.store.lookup(7300)[1],[])
        self.store.last_attempt = db.time.time()
        with patch.object(db.threading,'Thread') as thread:
            self.store.refresh_if_due()
            thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
