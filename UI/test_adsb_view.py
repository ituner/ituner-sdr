"""Real observation times, display windows and new-arrival semantics."""
import unittest
from adsb_view import TrafficView, aged, positioned, freshness, dome_contact, dome_altitude, reception_age


def plane(key='a', heard=100, position=100):
    p=dict(hex=key,last_seen_at=heard,gs=250)
    if position is not None:p.update(lat=44,lon=26,position_time=position)
    return p


class ViewTests(unittest.TestCase):
    def test_dome_reception_ages_are_readable_and_do_not_show_raw_timestamps(self):
        for seconds,label in ((0,'0 s ago'),(3.9,'3 s ago'),(65,'1 min 5 s ago'),(3670,'1 h 1 min ago'),(90000,'1 d 1 h ago')):
            self.assertEqual(reception_age(seconds),label)
        self.assertEqual(reception_age(float('nan')),'Unknown')

    def test_selected_dome_altitude_follows_actual_reports_and_ages_without_new_geometry(self):
        first=dict(hex='a',last_seen_at=100,alt_geom=10000,gs=230)
        contact=dome_contact([first],'a',102);self.assertTrue(contact['live']);self.assertIn('10,000',dome_altitude(contact))
        newer=dict(first,last_seen_at=104,alt_geom=10500)
        contact=dome_contact([newer],'a',105,contact);self.assertIn('10,500',dome_altitude(contact))
        contact=dome_contact([first],'a',110,contact);self.assertEqual(contact['alt_geom'],10500)
        contact=dome_contact([],'a',120,contact);self.assertFalse(contact['live']);self.assertEqual(contact['seen'],16)
        self.assertIsNone(dome_contact([],'other',120,contact))
        self.assertIsNone(dome_contact([dict(hex='a',seen=0,alt_baro=10000)],'a',120))
        self.assertIsNone(dome_contact([dict(first,last_seen_at=500)],'a',120))
        self.assertIn('BARO',dome_altitude(dict(alt_geom=None,alt_baro=9500)))
        self.assertEqual(dome_altitude(dict(alt_baro='ground')),'On ground')
        self.assertIsNone(dome_altitude(dict(alt_geom=float('nan'))))

    def test_history_icons_can_be_hidden_without_changing_names_trails_or_records(self):
        view=TrafficView(100);view.mode='history';tracks={'old':[dict(time=90,lat=44,lon=26)]}
        self.assertTrue(view.icons_visible(False))
        view.history_icons=False;self.assertFalse(view.icons_visible(True))
        self.assertFalse(view.history_labels);self.assertFalse(view.history_trails)
        self.assertEqual(view.aircraft([],tracks,110,True)[0]['hex'],'old')
        view.mode='live';self.assertTrue(view.icons_visible(True))
        view.mode='history';self.assertFalse(view.icons_visible(True))

    def test_history_labels_default_off_and_have_a_separate_live_preference(self):
        view=TrafficView(100)
        self.assertTrue(view.labels_visible(True));self.assertFalse(view.labels_visible(False))
        view.mode='history';self.assertFalse(view.labels_visible(True))
        view.history_labels=True;self.assertTrue(view.labels_visible(False))
        self.assertFalse(view.history_trails)
        view.mode='live';self.assertFalse(view.labels_visible(False))
        view.mode='history';self.assertTrue(view.labels_visible(False))

    def test_history_trails_default_off_without_hiding_aircraft_or_affecting_live(self):
        view=TrafficView(100);tracks={'old':[dict(time=90,lat=44,lon=26)]}
        view.mode='history'
        self.assertFalse(view.trail_visible('old',[],110,tracks['old']))
        self.assertEqual([p['hex'] for p in view.aircraft([],tracks,110,True)],['old'])
        view.history_trails=True
        self.assertTrue(view.trail_visible('old',[],110,tracks['old']))
        view.mode='live';p=plane(heard=110,position=110)
        self.assertTrue(view.trail_visible('a',[p],110))
        view.mode='history';self.assertTrue(view.trail_visible('old',[],110))
        self.assertEqual(tracks['old'][0]['time'],90)

    def test_live_button_confirms_then_cycles_and_history_preserves_duration(self):
        view=TrafficView(100);self.assertFalse(view.press_live());self.assertEqual(view.live_seconds,15)
        for seconds in (30,60,120,300,15):
            self.assertTrue(view.press_live());self.assertEqual(view.live_seconds,seconds)
            self.assertEqual(view.trail_seconds,300)
        view.live_seconds=60;view.mode='history'
        self.assertFalse(view.press_live());self.assertEqual(view.live_seconds,60)
        self.assertTrue(view.press_live());self.assertEqual(view.live_seconds,120)

    def test_extended_live_keeps_last_known_positions_but_speed_does_not_extend_them(self):
        view=TrafficView(100);view.ingest([plane()],100)
        view.press_live();view.press_live()
        rows=view.aircraft([],{},120,True)
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['historical']);self.assertEqual(rows[0]['seen_pos'],20)
        self.assertTrue(view.trail_visible('a',[],120));self.assertEqual(view.counts([],120)['live'],0)
        speed=plane(heard=129,position=None);view.ingest([speed],129)
        self.assertEqual(view.aircraft([speed],{},129,True)[0]['position_time'],100)
        self.assertEqual(view.aircraft([speed],{},130,True),[])
        self.assertFalse(view.trail_visible('a',[speed],130))
        tracks={'a':[dict(time=120,lat=44,lon=26)]}
        self.assertTrue(view.aircraft([],tracks,140,True)[0]['historical'])
        view.start_fresh(141)
        self.assertEqual(view.aircraft([],tracks,142,True),[])

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

    def test_fresh_live_filters_old_positions_trails_and_coverage_until_history(self):
        view=TrafficView(90);view.backdrop=True;view.start_fresh(110)
        self.assertEqual(view.mode,'live');self.assertFalse(view.backdrop)
        old=plane(heard=111,position=109);fresh=plane('new',112,112)
        self.assertEqual(view.aircraft([old],{},112,True),[])
        self.assertEqual(view.counts([old],112)['positions'],0)
        self.assertEqual(view.aircraft([fresh],{},112,True)[0]['hex'],'new')
        self.assertEqual(view.cutoff(112),110);self.assertEqual(view.coverage_since(112),110)
        view.mode='history';view.trail_seconds=86400
        self.assertLess(view.coverage_since(112),110)
        self.assertEqual(view.aircraft([old],{},112,True)[0]['hex'],'a')

    def test_session_retention_and_invalid_track_endpoints(self):
        view=TrafficView(0);view.mode='session'
        tracks={'old':[dict(time=1,lat=44,lon=26)],'bad':[dict(time=90000,lat=float('nan'),lon=26)],'future':[dict(time=999999,lat=44,lon=26)]}
        self.assertEqual(view.aircraft([],tracks,90000,True),[])


if __name__=='__main__':unittest.main()
