"""Real sweep history persistence, boundaries and honest missing-data rendering."""
import base64
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from spectrum_history import SweepHistory, encode, signature


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'history.sqlite3'
        self.history = SweepHistory(self.path)
        now = time.time()
        self.data = dict(settings=dict(low=100e6, high=101e6, bin=250000, gain=0, ppm=0),
                         device=dict(id='serial:test'), rate=2048000, fft=1024,
                         started=now-20, sweep_started=now-10, finished=now, sweep=1,
                         complete=True, power=[-100.4, -80.2, None, -90], masked=[False]*4)

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, **values):
        return self.history.read(self.data, **values)['rows']

    def codes(self, row):
        return list(base64.b64decode(row['values']))

    def test_persists_individual_power_not_peak_or_average_and_deduplicates(self):
        self.data.update(peak=[-10]*4, average=[-30]*4)
        self.history.append(self.data)
        self.history.append(self.data)
        self.history = SweepHistory(self.path)
        rows = self.rows(columns=4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.codes(rows[0]), [102, 122, 0, 112])
        self.assertEqual(rows[0]['started'], self.data['sweep_started'])
        self.assertEqual(rows[0]['finished'], self.data['finished'])
        self.assertEqual(self.rows(after=rows[0]['id']), [])

    def test_partial_sweeps_are_never_archived_and_settings_do_not_mix(self):
        self.data['complete'] = False
        self.history.append(self.data)
        self.assertEqual(self.rows(), [])
        self.data['complete'] = True
        self.history.append(self.data)
        original = signature(self.data)
        for field, value in [('gain', 10), ('ppm', 1), ('bin', 100000), ('high', 102e6)]:
            with self.subTest(field=field):
                saved = self.data['settings'][field]
                self.data['settings'][field] = value
                self.assertNotEqual(signature(self.data), original)
                self.assertEqual(self.rows(), [])
                self.data['settings'][field] = saved
        self.data['device']['id'] = 'serial:other'
        self.assertEqual(self.rows(), [])

    def test_zoom_column_peak_and_clipping_do_not_invent_valid_data(self):
        self.data['masked'][3] = True
        self.history.append(self.data)
        self.assertEqual(self.codes(self.rows(columns=2)[0]), [122, 1])
        self.assertEqual(self.codes(self.rows(low=100.5e6, high=101e6, columns=2)[0]), [0, 1])
        self.assertEqual(self.codes(self.rows(low=100.25e6, high=100.5e6, columns=4)[0]), [122]*4)
        self.assertEqual(encode([float('nan'), float('inf'), -100], [False, False, True]), bytes([0, 0, 1]))

    def test_count_age_and_payload_bounds(self):
        with patch('spectrum_history.MAX_ROWS', 3):
            for sweep in range(1, 6):
                self.data['sweep'] = sweep
                self.history.append(self.data)
            self.assertEqual([r['sweep'] for r in self.rows()], [3, 4, 5])
        self.assertEqual(self.history.metadata(self.data)['count'], 3)
        self.assertEqual(len(self.codes(self.rows(columns=99999)[0])), 2048)
        with patch('spectrum_history.time.time', return_value=self.data['finished']+86401):
            self.assertEqual(self.rows(), [])
        for values in (dict(low=101e6), dict(high=99e6), dict(low='nan'), dict(high='inf'), dict(after='oops'), dict(columns='oops')):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.rows(**values)

    def test_signature_normalizes_integer_and_float_settings(self):
        old = signature(self.data)
        self.data['settings']['gain'] = 0.0
        self.assertEqual(signature(self.data), old)

    def test_no_prior_survey_returns_an_empty_history_without_a_fake_row(self):
        self.assertEqual(self.history.read({})['rows'], [])
        self.assertEqual(self.history.metadata({})['count'], 0)
