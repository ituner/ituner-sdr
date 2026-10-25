"""Synchronized measurement windows exclude outages and never count old totals."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from adsb_compare import ComparisonMeter,ReceiverComparison,readsb_command,comparison_history,sample as disk_sample,comparison_rates,rate_graph_max,rate_tick_digits,ComparisonGraph,comparison_plot

A=dict(id='serial:11',serial='11',index=1,label='ADS-B',persistent=True)
B=dict(id='serial:978',serial='978',index=0,label='FlightAware',persistent=True)
C=dict(id='serial:333',serial='333',index=2,label='NESDR',persistent=True)


def sample(stamp,packets,run=1,planes=None):
    return dict(stamp=stamp,packets=packets,run=run,aircraft=planes or [],gain=48,signal=-20,noise=-30,strong=0,dropped=0)


class ComparisonTests(unittest.TestCase):
    def test_rate_graph_shows_interval_changes_including_zero_and_falling_rates(self):
        series=[dict(elapsed=0,packets=[100,200,300]),dict(elapsed=2,packets=[150,220,300]),
                dict(elapsed=5,packets=[200,250,300]),dict(elapsed=7,packets=[210,290,320]),
                dict(elapsed=10,packets=[225,350,350])]
        rates=comparison_rates(series,3)
        self.assertEqual(rates[0],dict(elapsed=5,rates=[20,10,0]))
        self.assertEqual(rates[-1],dict(elapsed=10,rates=[12.5,15,5]))
        # Irregular sample times use the real duration; counter resets start a new baseline.
        series=[dict(elapsed=0,packets=[100]),dict(elapsed=7,packets=[170]),
                dict(elapsed=8,packets=[0]),dict(elapsed=13,packets=[25])]
        self.assertEqual(comparison_rates(series,1),[dict(elapsed=7,rates=[10]),dict(elapsed=13,rates=[5])])
        self.assertEqual(comparison_rates([],3),[])

    def test_rolling_average_suppresses_bursts_and_preserves_receiver_ratios(self):
        points=[dict(elapsed=0,packets=[0,0,0])];total=0
        for second in range(1,91):
            total+=200 if second==16 else 20 if second<=60 else 0
            points.append(dict(elapsed=second,packets=[total,2*total,total/2]))
        rates={r['elapsed']:r['rates'] for r in comparison_rates(points,3)}
        self.assertEqual(rates[5],[20,40,10])
        self.assertEqual(rates[16],[31.25,62.5,15.625])
        self.assertEqual(rates[60],[20,40,10])
        self.assertEqual(rates[75],[10,20,5]);self.assertEqual(rates[90],[0,0,0])
        # Exact time weighting when the rolling window edge lies between samples.
        uneven=[dict(elapsed=t,packets=[n]) for t,n in [(0,0),(10,100),(25,400),(35,400)]]
        self.assertAlmostEqual(comparison_rates(uneven,1)[-1]['rates'][0],350/30)
        self.assertEqual(rate_graph_max([dict(rates=[20,30,40])]),50)
        self.assertEqual(rate_graph_max([dict(rates=[20,30,41])]),50)
        self.assertEqual(rate_graph_max([dict(rates=[60])]),80)

    def test_auto_scale_fits_only_the_visible_view_and_resets_without_a_fixed_floor(self):
        for peak in (.02,.4,2,6,60,6000):
            maximum=rate_graph_max([dict(rates=[peak/2,peak])])
            self.assertGreaterEqual(maximum,peak*1.2)
            self.assertLessEqual(maximum,max(.1,peak*2))
            self.assertNotEqual(round(maximum/4,rate_tick_digits(maximum)),0)
        self.assertEqual(rate_graph_max([]),1)
        self.assertEqual(rate_graph_max([dict(rates=[0,0])]),1)
        data=dict(now=4000,receivers=[A,B],rate_history_ids=[A['id'],B['id']],
                  rate_history=[dict(time=1000,rates=[100,200]),dict(time=3998,rates=[1,2]),dict(time=4000,rates=[2,3])])
        self.assertEqual(comparison_plot(data,300)['max'],4)
        self.assertEqual(comparison_plot(data,3600)['max'],250)
        data['graph_reset_at']=3990
        self.assertEqual(comparison_plot(data,86400)['max'],4)

    def test_hour_graph_survives_meter_rollover_and_restart_with_real_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            graph=ComparisonGraph(folder)
            for second in range(100,3802):
                graph.observe([sample(second,second*10),sample(second,second*20),sample(second,second*5)],[A,B,C],second)
            self.assertGreaterEqual(graph.points[0]['time'],100)
            self.assertLessEqual(len(graph.points),1900)
            self.assertEqual(graph.points[-1]['rates'],[10,20,5])
            graph.checkpoint(3801,force=True)
            with patch('adsb_compare.time.time',return_value=3801):fresh=ComparisonGraph(folder)
            self.assertEqual(list(graph.points),list(fresh.points));self.assertEqual(fresh.ids,[A['id'],B['id'],C['id']])
            # An application restart creates an explicit gap, preserving older rates.
            fresh.observe([sample(3802,38020),sample(3802,76040),sample(3802,19010)],[A,B,C],3802)
            self.assertIsNone(fresh.points[-1]['rates'])
            for second in range(3803,3810):fresh.observe([sample(second,second*10),sample(second,second*20),sample(second,second*5)],[A,B,C],second)
            data=dict(now=3809,current=dict(receivers=[A,B,C]),rate_history_ids=fresh.ids,rate_history=list(fresh.points))
            for span in (300,1800,3600,43200,86400):
                plot=comparison_plot(data,span)
                self.assertEqual(plot['seconds'],span);self.assertEqual(plot['rates'],[10,20,5])
                self.assertEqual(len(plot['segments']),2)
                self.assertTrue(all(0<=p['elapsed']<=span for segment in plot['segments'] for p in segment))
            self.assertGreater(len(comparison_plot(data,3600)['segments'][0]),len(comparison_plot(data,300)['segments'][0]))
            data['rate_history_ids']=['different']
            self.assertEqual(comparison_plot(data,3600)['segments'],[])

    def test_daily_graph_is_bounded_retains_outages_and_restores_minute_averages(self):
        with tempfile.TemporaryDirectory() as folder:
            graph=ComparisonGraph(folder);graph.ids=[A['id'],B['id'],C['id']]
            base=100000;end=base+86400
            for stamp in range(base,end+1,2):
                graph.points.append(dict(time=stamp,rates=None if stamp==base+43200 else [10,20,5]))
                if (stamp-base)%600==0:graph.checkpoint(stamp,force=True)
            self.assertLess(len(graph.points),3500)
            coarse=[p for p in graph.points if p.get('period')==60]
            self.assertGreater(len(coarse),1300)
            self.assertTrue(all(p['rates']==[10,20,5] for p in coarse))
            self.assertTrue(any(p['rates'] is None for p in graph.points))
            self.assertTrue(any('period' not in p for p in graph.points if p['time']>end-3600))
            data=dict(now=end,receivers=[A,B,C],rate_history_ids=graph.ids,rate_history=list(graph.points))
            for span in (43200,86400):
                plot=comparison_plot(data,span);self.assertEqual(plot['seconds'],span)
                self.assertEqual(plot['rates'],[10,20,5])
                self.assertEqual(len(plot['segments']),2 if span==86400 else 1)
                self.assertTrue(all(0<=p['elapsed']<=span for s in plot['segments'] for p in s))
            with patch('adsb_compare.time.time',return_value=end):restored=ComparisonGraph(folder)
            self.assertEqual(list(restored.points),list(graph.points))
            # Reset remains a hard visual boundary, including after compaction.
            graph.reset(end);graph.points.append(dict(time=end+6,rates=[20,40,10]));graph.checkpoint(end+6,force=True)
            data.update(now=end+6,graph_reset_at=graph.reset_at,rate_history=list(graph.points))
            self.assertEqual([p['rates'] for s in comparison_plot(data,86400)['segments'] for p in s],[[20,40,10]])
            graph.checkpoint(end+86407,force=True)
            self.assertEqual(list(graph.points),[])

    def test_old_rate_compaction_keeps_sample_weights_and_reset_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            graph=ComparisonGraph(folder);graph.ids=['a'];graph.reset_at=104
            graph.points.extend([dict(time=100,rates=[10]),dict(time=102,rates=[30]),
                                 dict(time=106,rates=[90]),dict(time=108,rates=[110])])
            graph.compact(4000)
            self.assertEqual([p['rates'] for p in graph.points],[[20],[100]])
            self.assertEqual([p['samples'] for p in graph.points],[2,2])
            graph.compact(4000)
            self.assertEqual([p['rates'] for p in graph.points],[[20],[100]])
            graph.points.clear();graph.points.extend([dict(time=100,rates=[10]),dict(time=114,rates=[30])])
            graph.compact(4000)
            self.assertEqual([p['rates'] for p in graph.points],[[10],None,[30]])

    def test_graph_replacement_clears_other_receiver_rates_and_outages_are_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            graph=ComparisonGraph(folder)
            for second in range(100,111):graph.observe([sample(second,second*10),sample(second,second*20)],[A,B],second)
            graph.observe(None,[],111)
            self.assertIsNone(graph.points[-1]['rates'])
            count=len(graph.points);graph.observe(None,[],120);self.assertEqual(len(graph.points),count)
            graph.observe([sample(121,1210),sample(121,2420),sample(121,605)],[A,B,C],121)
            self.assertEqual(list(graph.points),[])
            for second in range(122,128):graph.observe([sample(second,second*10),sample(second,second*20),sample(second,second*5)],[A,B,C],second)
            self.assertEqual(graph.points[-1]['rates'],[10,20,5])

    def test_reset_clears_all_views_and_baselines_without_stopping_receivers(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);compare=ReceiverComparison(root,root,'/bin/readsb')
            compare.control('start',[B['id'],C['id']]);children=[Mock(),Mock()]
            for child in children:child.poll.return_value=None
            with patch('adsb_compare.subprocess.Popen',side_effect=children) as launch:
                for stamp,packets in [(100,100),(106,160)]:
                    with patch('adsb_compare.sample',return_value=sample(stamp,packets)),patch('adsb_compare.time.time',return_value=stamp):compare.step([A,B,C],A,root,None)
                compare.history=[dict(start=50,receivers=[dict(r,packets=10*(i+1)) for i,r in enumerate(compare.meter.current['receivers'])],complete=True,valid=True,duration=300,reason='')]
                with patch('adsb_compare.time.time',return_value=110):compare.reset_graphs()
                snap=compare.snapshot();snap['now']=110
                self.assertTrue(compare.enabled);self.assertIsNone(compare.meter.current)
                self.assertEqual(snap['graph_reset_at'],110);self.assertEqual(comparison_history(snap),[])
                for span in (300,1800,3600,43200,86400):self.assertEqual(comparison_plot(snap,span)['segments'],[])
                self.assertTrue(any(p['rates'] is not None for p in compare.graph.points))
                saved=json.loads((root/'comparison-rates.json').read_text());self.assertEqual(saved['reset_at'],110)
                for stamp,packets in [(112,220),(118,250)]:
                    with patch('adsb_compare.sample',return_value=sample(stamp,packets)),patch('adsb_compare.time.time',return_value=stamp):compare.step([A,B,C],A,root,None)
                self.assertEqual([r['packets'] for r in compare.meter.current['receivers']],[30,30,30])
                self.assertEqual(compare.graph.points[-1]['rates'],[5,5,5]);self.assertEqual(launch.call_count,2)
                for child in children:child.terminate.assert_not_called()
            self.assertIn('ADS-B',compare.csv().decode())
            with patch('adsb_compare.time.time',return_value=118):fresh=ReceiverComparison(root,root,'/bin/readsb')
            self.assertEqual(fresh.graph.reset_at,110)
            compare.stop()

    def test_json_timestamp_rounding_is_tolerated_but_stale_data_is_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'aircraft.json').write_text(json.dumps(dict(now=100.04,messages=10)))
            stats=dict(now=100.04,last1min=dict(local={}),total=dict(start=90,local={}))
            (root/'stats.json').write_text(json.dumps(stats))
            self.assertIsNotNone(disk_sample(root,100))
            self.assertIsNone(disk_sample(root,99))
            self.assertIsNone(disk_sample(root,105))

    def test_dongle_replacement_never_relabels_previous_results(self):
        old=dict(receivers=[A,B],complete=True,valid=True)
        v4=dict(B,id='serial:v4')
        new=dict(receivers=[A,v4],complete=True,valid=True)
        data=dict(selection=v4['id'],history=[old,new],current=None)
        self.assertEqual(comparison_history(data),[new])
        data['current']=dict(receivers=[A,B])
        self.assertEqual(comparison_history(data),[old])

    def test_equal_windows_count_only_new_packets_and_roll_every_five_minutes(self):
        meter=ComparisonMeter();meter.update([sample(100,10000),sample(100,50)],[A,B],100,None)
        plane=dict(hex='abc',lat=37.7,lon=-121.8,seen=0,seen_pos=0)
        meter.update([sample(250,10100,planes=[plane]),sample(250,250,planes=[plane])],[A,B],250,dict(lat=37.6,lon=-121.8))
        result=meter.update([sample(400,10400),sample(400,650)],[A,B],400,None)
        self.assertEqual(len(result),1);self.assertTrue(result[0]['complete']);self.assertTrue(result[0]['valid'])
        a,b=result[0]['receivers'];self.assertEqual((a['packets'],b['packets']),(400,600))
        self.assertEqual(a['aircraft'],['abc']);self.assertEqual(a['positions'],1)
        self.assertAlmostEqual(a['max_range_km'],11.1,delta=.2)
        self.assertEqual(meter.current['start'],400);self.assertEqual(meter.current['receivers'][0]['packets'],0)

    def test_disconnect_and_counter_reset_flag_partial_windows(self):
        meter=ComparisonMeter();meter.update([sample(100,100),sample(100,100)],[A,B],100,None)
        result=meter.update(None,[],160,None)
        self.assertFalse(result[0]['valid']);self.assertFalse(result[0]['complete']);self.assertIsNone(meter.current)
        meter.update([sample(200,200),sample(200,0,run=2)],[A,B],200,None)
        result=meter.update([sample(210,0,run=3),sample(210,10,run=2)],[A,B],210,None)
        self.assertFalse(result[0]['valid']);self.assertEqual(meter.current['start'],210)

    def test_secondary_uses_same_decoder_options_and_does_not_take_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);broker=Mock();broker.available.return_value=True;broker.acquire.return_value=True
            compare=ReceiverComparison(root,root,'/bin/readsb',broker);compare.control('start',B['id'])
            child=Mock();child.poll.return_value=None
            with patch('adsb_compare.subprocess.Popen',return_value=child) as launch:
                compare.step([A,B],A,root,None)
            self.assertEqual(compare.assigned,B)
            command=launch.call_args.args[0];self.assertIn('--device=0',command);self.assertIn('--gain=auto',command)
            self.assertEqual(command,readsb_command('/bin/readsb',B,compare.data/'receiver-978',None))
            broker.acquire.assert_called_once_with('adsb-compare:'+B['id'],B['id'])
            compare.stop();child.terminate.assert_called_once();broker.release.assert_called_with('adsb-compare:'+B['id'])

    def test_three_receivers_share_baselines_and_disconnect_invalidates_all(self):
        meter=ComparisonMeter();devices=[A,B,C]
        meter.update([sample(100,1000),sample(100,4000),sample(100,20)],devices,100,None)
        result=meter.update([sample(400,1100),sample(400,4200),sample(400,320)],devices,400,None)
        self.assertEqual([r['packets'] for r in result[0]['receivers']],[100,200,300])
        self.assertTrue(result[0]['valid']);self.assertTrue(result[0]['complete'])
        self.assertEqual([r['packets'] for r in meter.current['receivers']],[0,0,0])
        result=meter.update(None,[],450,None)
        self.assertFalse(result[0]['valid']);self.assertFalse(result[0]['complete'])
        meter.update([sample(500,1300),sample(500,4500),sample(500,500)],devices,500,None)
        result=meter.update([sample(800,1700),sample(800,5000),sample(800,1100)],devices,800,None)
        self.assertEqual([r['packets'] for r in result[0]['receivers']],[400,500,600])

    def test_three_receiver_roster_cannot_show_two_receiver_history(self):
        old=dict(receivers=[A,B],complete=True,valid=True)
        new=dict(receivers=[A,B,C],complete=True,valid=True)
        data=dict(receivers=[A,B,C],history=[old,new],current=None)
        self.assertEqual(comparison_history(data),[new])

    def test_multi_process_leases_restart_recovery_series_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);broker=Mock();broker.acquire.return_value=True
            compare=ReceiverComparison(root,root,'/bin/readsb',broker)
            compare.control('start',[B['id'],C['id']])
            children=[Mock(),Mock(),Mock()]
            for child in children:child.poll.return_value=None
            with patch('adsb_compare.subprocess.Popen',side_effect=children) as launch, patch('adsb_compare.sample',return_value=sample(100,100)), patch('adsb_compare.time.time',return_value=100):
                compare.step([A,B,C],A,root,None)
            self.assertEqual(launch.call_count,2)
            self.assertEqual([r['id'] for r in compare.snapshot()['current']['receivers']],[A['id'],B['id'],C['id']])
            self.assertEqual(compare.snapshot()['series'][0]['packets'],[0,0,0])
            self.assertEqual(len({c.args[0][-3] for c in launch.call_args_list}),2)
            with patch('adsb_compare.sample',return_value=sample(110,150)), patch('adsb_compare.time.time',return_value=110):
                compare.step([A,B,C],A,root,None)
            self.assertEqual(compare.snapshot()['series'][-1]['packets'],[50,50,50])
            # One transient JSON read is retried without resetting the common baseline.
            with patch('adsb_compare.sample',side_effect=[sample(111,160),None,sample(111,160)]), patch('adsb_compare.time.time',return_value=111):
                compare.step([A,B,C],A,root,None)
            self.assertEqual(compare.meter.current['start'],100);self.assertEqual(compare.history,[])
            with patch('adsb_compare.sample',return_value=sample(112,180)), patch('adsb_compare.time.time',return_value=112):
                compare.step([A,B,C],A,root,None)
            self.assertEqual([r['packets'] for r in compare.meter.current['receivers']],[80,80,80])
            with patch('adsb_compare.sample',return_value=sample(120,170)), patch('adsb_compare.time.time',return_value=120):
                compare.step([A,B],A,root,None)
            children[1].terminate.assert_called_once();children[0].terminate.assert_not_called()
            self.assertIsNone(compare.meter.current);self.assertFalse(compare.history[-1]['valid'])
            self.assertEqual(compare.status,'WAITING FOR RECEIVERS');self.assertEqual(compare.snapshot()['series'],[])
            self.assertEqual(len(compare.snapshot()['receivers']),3)
            fresh=ReceiverComparison(root,root,'/bin/readsb')
            self.assertEqual(fresh.selections,[B['id'],C['id']]);self.assertTrue(fresh.enabled)
            compare.stop();children[0].terminate.assert_called_once()
            released={c.args[0] for c in broker.release.call_args_list}
            self.assertEqual(released,{'adsb-compare:'+B['id'],'adsb-compare:'+C['id']})

    def test_results_and_assignment_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);compare=ReceiverComparison(root,root,'/bin/readsb')
            compare.history=[dict(start=100,receivers=[])];compare.control('start',B['id'])
            fresh=ReceiverComparison(root,root,'/bin/readsb')
            self.assertTrue(fresh.enabled);self.assertEqual(fresh.selection,B['id']);self.assertEqual(fresh.history,compare.history)


if __name__=='__main__':unittest.main()
