import tempfile
import unittest
from pathlib import Path
import numpy as np
from usb_rds import StationStore,MPXConverter

class RDSTests(unittest.TestCase):
    def test_clear_receiver_removes_metadata_and_rejects_old_decoder_results(self):
        store=StationStore();key=('rtl','a',96300000);epoch=store.epoch(key)
        store.ingest(key,{'pi':'0x1234','ps':'OLD'})
        store.observe(('rtl','b',94900000))
        store.clear('rtl','a')
        store.ingest(key,{'pi':'0x1234','ps':'STALE'},epoch)
        self.assertEqual(store.snapshot('rtl','a'),[])
        self.assertEqual(len(store.snapshot('rtl','b')),1)
        store.observe(key)
        self.assertEqual(store.snapshot('rtl','a')[0]['ps'],'')

    def test_pi_change_clears_old_station_text(self):
        store=StationStore();key=('rtl-sdr','a',94900000)
        store.ingest(key,{'pi':'0x1234','ps':'HIT IASI','radiotext':'First message'})
        store.ingest(key,{'pi':'0x5678'})
        row=store.snapshot('rtl-sdr','a')[0]
        self.assertEqual(row['ps'],'');self.assertEqual(row['radiotext'],'')
        store.ingest(key,{'pi':'invalid','ps':'FAKE'})
        self.assertEqual(store.snapshot('rtl-sdr','a')[0]['ps'],'')
    def test_frequency_and_receiver_isolation_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'rds.json';store=StationStore(path)
            store.ingest(('rtl-sdr','a',94900000),{'pi':'0x1234','ps':'HIT IASI','radiotext':'Music'})
            store.observe(('rtl-sdr','b',94900000));store.save();restored=StationStore(path)
            self.assertEqual(restored.snapshot('rtl-sdr','a')[0]['ps'],'HIT IASI')
            self.assertEqual(restored.snapshot('rtl-sdr','b')[0]['ps'],'')
    def test_streaming_mpx_preserves_rds_subcarrier_and_chunk_continuity(self):
        for rate in (1024000,768000):
            t=np.arange(rate//8)/rate
            modulation=10000*np.sin(2*np.pi*1000*t)+2000*np.sin(2*np.pi*57000*t)
            iq=np.exp(2j*np.pi*np.cumsum(modulation)/rate)
            whole=np.frombuffer(MPXConverter(rate).convert(iq),'<i2')
            converter=MPXConverter(rate)
            chunks=np.frombuffer(b''.join(converter.convert(iq[i:i+16384]) for i in range(0,len(iq),16384)),'<i2')
            np.testing.assert_allclose(chunks,whole,atol=1)
            # 57 kHz must survive; it cannot be recovered from 32 kHz audio.
            x=whole[1024:].astype(float);freq=np.fft.rfftfreq(len(x),1/128000);power=abs(np.fft.rfft(x*np.hanning(len(x))))
            peak=power[abs(freq-57000)<100].max()
            self.assertGreater(peak,50*np.median(power))
    def test_store_is_bounded_and_sanitizes_received_text(self):
        store=StationStore()
        for i in range(300):store.observe(('rtl','a',i))
        self.assertEqual(len(store.rows),256)
        store.ingest(('rtl','a',299),{'pi':'0x1234','ps':'ABCDEFGHtoo long','radiotext':'hello\x00world'})
        row=store.snapshot('rtl','a')[-1]
        self.assertEqual(row['ps'],'ABCDEFGH');self.assertEqual(row['radiotext'],'helloworld')

    def test_station_list_selects_frequency_and_back_keeps_station(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usb_station_view import USBStationView
        search=SimpleNamespace(open=True,active=False)
        state=Mock();ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        view=USBStationView(ui,search,Mock(),Mock(),state)
        view.actions=[((0,0,100,100),('station',94900000))]
        view.tap(10,10);state.set_view.assert_called_once_with(freq_khz=94900.)
        self.assertTrue(view.open)
        view.actions=[((0,0,100,100),('back',None))]
        view.tap(10,10);self.assertFalse(view.open)
        state.set_view.assert_called_once()

    def test_scan_follows_new_rows_then_centers_landing_and_preserves_browsing(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usb_station_view import USBStationView
        search=SimpleNamespace(open=True,active=True)
        state=Mock();state.snapshot.return_value=('',90700)
        view=USBStationView(Mock(),search,Mock(),Mock(),state)
        rows=[{'hz':90000000+i*100000} for i in range(12)]
        view.update_scroll(rows[:6]);self.assertEqual(view.first,1)
        view.update_scroll(rows);self.assertEqual(view.first,7)
        view.first=2;view.update_scroll(rows);self.assertEqual(view.first,2)
        rows.append({'hz':96300000});view.update_scroll(rows);self.assertEqual(view.first,8)
        search.active=False;view.update_scroll(rows);self.assertEqual(view.first,5)
        view.first=3;view.update_scroll(rows);self.assertEqual(view.first,3)
        state.snapshot.return_value=('',90900)
        view.update_scroll(rows);self.assertEqual(view.first,7)
        state.snapshot.return_value=('',90000)
        view.update_scroll(rows);self.assertEqual(view.first,0)
        state.snapshot.return_value=('',96300)
        view.update_scroll(rows);self.assertEqual(view.first,8)

    def test_swipe_browses_both_directions_without_tuning(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usb_station_view import USBStationView
        import theme_system
        state=Mock();view=USBStationView(Mock(),SimpleNamespace(open=True,active=True),Mock(),Mock(),state)
        view.max_first=20
        x=300 if theme_system.runtime_theme['sidebar']=='left' else 50
        view.drag_begin(x,500);view.drag_move(x,180)
        self.assertEqual(view.first,5)
        view.release(x,180,tap=False);state.set_view.assert_not_called()
        view.drag_begin(x,180);view.release(x,500,tap=False)
        self.assertEqual(view.first,0);state.set_view.assert_not_called()
        view.drag_begin(x,600);view.release(x,-2000,tap=False)
        self.assertEqual(view.first,20)
    def test_scanning_row_tap_does_not_interrupt_sweep(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usb_station_view import USBStationView
        ui=Mock();ui.contains.return_value=True;state=Mock()
        view=USBStationView(ui,SimpleNamespace(open=True,active=True),Mock(),Mock(),state)
        view.actions=[((0,0,100,100),('station',96300000))]
        view.tap(10,10);state.set_view.assert_not_called()
    def test_scan_border_pulses_with_theme_color_and_radius(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usb_station_view import draw_scan_border
        ui=Mock();ui.APP_UI_STYLE=SimpleNamespace(palette=SimpleNamespace(focus=(0,200,90,200)),button=SimpleNamespace(radius=8))
        draw_scan_border(ui,(0,0,100,50),0)
        self.assertEqual(ui.draw_logical_rounded_rect.call_count,1)
        first=ui.draw_logical_rounded_rect.call_args.args[6]
        ui.reset_mock();draw_scan_border(ui,(0,0,100,50),.45)
        self.assertNotEqual(first,ui.draw_logical_rounded_rect.call_args.args[6])
