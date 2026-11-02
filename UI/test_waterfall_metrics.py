import struct
import threading
import unittest
from unittest.mock import Mock

from waterfall_metrics import WaterfallMetrics
from long_scan import KiwiScanSession
from am_carrier import rf_view_center_hz


class WaterfallMetricTests(unittest.TestCase):
    def test_rate_and_first_row_wait_are_separate_and_idle_expires_the_rate(self):
        clock=[0.0];metrics=WaterfallMetrics(lambda:clock[0])
        for start in (0,2,4):
            clock[0]=start;metrics.sent()
            clock[0]=start+.15;metrics.first_row()
        clock[0]=6
        self.assertEqual(metrics.snapshot()['views_per_second'],.5)
        self.assertAlmostEqual(metrics.snapshot()['first_row_ms'],150)
        clock[0]=40
        self.assertEqual(metrics.snapshot()['views_per_second'],0)

    def test_unchanged_wire_view_and_speed_resume_do_not_count_as_new_views(self):
        clock=[0.0]
        session=KiwiScanSession('http://example.test',1,threading.Event())
        session.metrics=WaterfallMetrics(lambda:clock[0]);session.wf=Mock();session.wf_authenticated=True
        session.set_view(7300,8);session.set_view(7300,8)
        session.pause_waterfall();clock[0]=5;session.set_view(7300,8)
        self.assertEqual(len(session.metrics.changes),1)

    def test_only_a_matching_uncompressed_row_ends_the_wait(self):
        clock=[0.0]
        session=KiwiScanSession('http://example.test',1,threading.Event())
        session.metrics=WaterfallMetrics(lambda:clock[0]);session.wf=Mock();session.snd=Mock();session.wf_authenticated=True
        session.set_view(7300,8)
        def row(center,zoom=8):
            first=rf_view_center_hz(center*1000,session.bandwidth,zoom)-session.bandwidth/(2**zoom)/2
            start=round(first/session.bandwidth*1024*2**session.zoom_max)
            return b'W/F\0'+struct.pack('<III',start,zoom,1)+bytes(1024)
        clock[0]=.1;session._message(session.wf,row(7500))
        self.assertIsNone(session.metrics.snapshot()['first_row_ms'])
        clock[0]=.15;session._message(session.wf,row(7300))
        self.assertAlmostEqual(session.metrics.snapshot()['first_row_ms'],150)
        clock[0]=1;session._message(session.wf,row(7300))
        self.assertAlmostEqual(session.metrics.snapshot()['first_row_ms'],150)
