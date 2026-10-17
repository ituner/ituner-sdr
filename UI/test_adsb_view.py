"""Real observation times, display windows and new-arrival semantics."""
import unittest
from adsb_view import TrafficView, aged, positioned, freshness


def plane(key='a', heard=100, position=100):
    p=dict(hex=key,last_seen_at=heard,gs=250)
    if position is not None:p.update(lat=44,lon=26,position_time=position)
    return p


class ViewTests(unittest.TestCase):
    def test_live_contacts_and_positions_age_independently(self):
        view=TrafficView(100)
        planes=[plane('fresh'),plane('speed',110,80),plane('gone',90)]
        view.ingest(planes,110)
        self.assertEqual({p['hex'] for p in view.aircraft(planes,{},110)}, {'fresh','speed'})
        self.assertEqual([p['hex'] for p in view.aircraft(planes,{},110,True)],['fresh'])
        self.assertEqual(view.counts(planes,110),dict(live=2,positions=1,new=0))
        self.assertIn('Position old · 30s ago',freshness(aged(planes[1],110)))
        self.assertFalse(positioned(aged(planes[1],110)))

    def test_cached_snapshot_cannot_keep_radio_or_position_alive(self):
        p=plane();view=TrafficView(100);view.ingest([p],100)
        self.assertEqual(view.aircraft([p],{},115),[])
        self.assertEqual(view.aircraft([p],{},115,True),[])
        self.assertFalse(view.trail_visible('a',[p],115))

    def test_live_hides_history_until_explicitly_requested(self):
        tracks={'old':[dict(time=50,lat=44,lon=26)],'a':[dict(time=101,lat=44,lon=26)]}
        view=TrafficView(100)
        self.assertEqual(view.aircraft([],tracks,110,True),[])
        view.mode='history';view.trail_seconds=86400
        self.assertEqual({p['hex'] for p in view.aircraft([],tracks,110,True)},{'old','a'})
        view.mode='session'
        self.assertEqual([p['hex'] for p in view.aircraft([],tracks,110,True)],['a'])
        self.assertEqual(tracks['old'][0]['time'],50)

    def test_since_opened_excludes_previsit_position_even_with_current_speed(self):
        view=TrafficView(100);view.mode='session'
        p=plane(heard=110,position=99)
        tracks={'a':[dict(time=99,lat=44,lon=26)]}
        view.ingest([p],110)
        self.assertEqual(len(view.aircraft([p],tracks,110)),1)
        self.assertEqual(view.aircraft([p],tracks,110,True),[])
        p['position_time']=111
        self.assertEqual(len(view.aircraft([p],tracks,111,True)),1)

    def test_new_means_new_arrival_after_initial_baseline_not_reappearance(self):
        view=TrafficView(100);view.ingest([plane()],100)
        view.ingest([plane(heard=102),plane('new',102)],102)
        self.assertEqual(view.counts([],102)['new'],1)
        self.assertTrue(view.arrival('new',103));self.assertFalse(view.arrival('a',103))
        self.assertFalse(view.arrival('new',114))
        view.ingest([plane('new',150)],150)
        self.assertEqual(view.counts([],150)['new'],1)
        self.assertFalse(view.arrival('new',150))

    def test_start_fresh_does_not_reintroduce_cached_data_or_delete_tracks(self):
        view=TrafficView(100);view.mode='session';view.ingest([],100)
        view.ingest([plane(heard=105)],105)
        tracks={'a':[dict(time=105,lat=44,lon=26)]}
        view.reset(110);view.ingest([plane(heard=105)],110)
        self.assertEqual(view.aircraft([plane(heard=105)],tracks,110),[])
        self.assertEqual(view.counts([],110)['new'],0)
        view.ingest([plane(heard=112,position=112)],112)
        self.assertEqual(len(view.aircraft([],tracks,112)),1)
        self.assertEqual(tracks['a'][0]['time'],105)
        view.mode='history';view.trail_seconds=300
        self.assertEqual(len(view.aircraft([],tracks,112,True)),1)

    def test_session_keeps_radio_only_contacts_with_accurate_lost_contact_age(self):
        view=TrafficView(100);view.mode='session';view.ingest([],100)
        view.ingest([plane('speed',102,None)],102)
        rows=view.aircraft([],{},180)
        self.assertEqual(len(rows),1)
        self.assertIn('Last heard 1m ago · No position',freshness(rows[0]))
        self.assertEqual(view.aircraft([],{},180,True),[])

    def test_session_retention_and_invalid_track_endpoints(self):
        view=TrafficView(0);view.mode='session'
        tracks={'old':[dict(time=1,lat=44,lon=26)],'bad':[dict(time=90000,lat=float('nan'),lon=26)],'future':[dict(time=999999,lat=44,lon=26)]}
        self.assertEqual(view.aircraft([],tracks,90000,True),[])


if __name__=='__main__':unittest.main()
