from concurrent.futures import CancelledError
import threading
import unittest
from unittest.mock import Mock, patch

from long_scan_search import search_history


class HistorySearchTests(unittest.TestCase):
    def history(self):
        return dict(start=0,end=180,points=[(10,'41 m',7300,20),(70,'31 m',9500,20),(130,'41 m',7300,20)],
                    segments=[(10,130,'41 m',7300,20)],tails=[],tracks=(('41 m',7300),('31 m',9500)))

    def lookup(self, frequency, stamp, **kwargs):
        if frequency==7300:
            row=dict(station='Radio România International',country='Romania') if stamp<60 else dict(station='Other station',country='France')
        else:
            row=dict(station='Other service',country='United States',transmitter='Romania')
        return frequency,[row],None

    def test_country_search_uses_the_observation_time_not_todays_identity(self):
        result=search_history(self.history(),'ROMÂNIA',self.lookup)
        self.assertEqual(result['points'],[(10,'41 m',7300,20)])
        self.assertEqual(result['segments'],[])
        self.assertEqual(result['bands'],{'41 m'})
        self.assertEqual(result['matched_traces'],1)

    def test_station_words_match_together_and_transmitter_text_is_ignored(self):
        self.assertEqual(search_history(self.history(),'radio international',self.lookup)['matched_traces'],1)
        result=search_history(self.history(),'Romania',self.lookup)
        self.assertFalse(any(p[2]==9500 for p in result['points']))

    def test_repeated_points_in_one_schedule_minute_reuse_the_lookup(self):
        history=self.history();history['points']=[(10,'41 m',7300,20),(20,'41 m',7300,20)]
        history['segments']=[(10,20,'41 m',7300,20)]
        lookup=Mock(side_effect=self.lookup)
        result=search_history(history,'Romania',lookup)
        self.assertEqual(len(result['segments']),1)
        self.assertEqual(lookup.call_count,1)

    def test_cancelled_search_stops_without_results(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(CancelledError):search_history(self.history(),'Romania',self.lookup,cancel)

    def test_default_lookup_is_local_and_reports_an_unavailable_index(self):
        with patch('long_scan_search.offline_schedules.store') as store, \
             patch('long_scan_search.offline_schedules.lookup',side_effect=AssertionError('No online refresh')):
            store.rows=[];store.lookup.return_value=(7300,[],None)
            result=search_history(self.history(),'Romania')
            self.assertFalse(result['database_available'])
            self.assertEqual(result['matched_traces'],0)
