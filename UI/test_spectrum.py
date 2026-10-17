"""Survey settings, stepped coverage, lease ownership and comparable saved traces."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from spectrum_monitor import SpectrumSurvey,settings
from soapy_survey import plan,USABLE
from sdr_broker import ReceiverBroker

class SurveyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.device=dict(id='serial:789',serial='789',persistent=True,label='RTL')
  self.hub=Mock(root=Path(self.temp.name),broker=ReceiverBroker(),devices=[self.device]);self.survey=SpectrumSurvey(self.hub)
 def tearDown(self):self.survey.close();self.temp.cleanup()
 def data(self):
  self.survey.data=dict(settings=settings(dict(low=87500000,high=87600000,bin=25000)),device=self.device,started=1,updated=None,power=[None]*4,peak=[None]*4,average=[None]*4,counts=[0]*4,clipped=0,samples=0,complete=False)
 def row(self,value):return dict(kind='chunk',time=2,hop=1,hops=1,frequency=87550000,clipped=0,samples=65536,indices=[0],values=[value])
 def test_settings_bounds_and_work_limits(self):
  for values in (dict(low=24e6),dict(high=1701e6),dict(high=25e6),dict(bin=1000),dict(bin=2500),dict(gain=60),dict(low=float('nan')),dict(repeat='yes')):
   with self.subTest(values=values),self.assertRaises(ValueError):settings(values)
  self.assertEqual(settings(dict(low=87500000,high=108000000,bin=25000))['bin'],25000)
 def test_step_plan_covers_endpoints_and_cropped_edges_without_tuning_outside_range(self):
  for low,high in ((25e6,1700e6),(87.5e6,108e6),(100e6,100.1e6)):
   centers=plan(low,high);self.assertTrue(all(low<=c<=high for c in centers));self.assertLessEqual(centers[0]-USABLE/2,low);self.assertGreaterEqual(centers[-1]+USABLE/2,high)
   self.assertTrue(all(b-a<=USABLE for a,b in zip(centers,centers[1:])))
 def test_fft_power_normalization_and_frequency_axis(self):
  import numpy as np
  from soapy_survey import fft_density,FFT,RATE
  frequency=128000;t=np.arange(FFT*8)/RATE;signal=.5*np.exp(2j*np.pi*frequency*t)
  density=fft_density(signal).mean(axis=0)
  self.assertAlmostEqual(float(density.sum()*RATE/FFT),.25,places=6)
  self.assertEqual(float(np.fft.fftshift(np.fft.fftfreq(FFT,1/RATE))[np.argmax(density)]),frequency)
 def test_retuning_flushes_the_fifo_without_cancelling_usb_streaming(self):
  from soapy_survey import retune
  radio=Mock();retune(radio,'stream',100e6,0)
  self.assertEqual([call[0] for call in radio.method_calls],['setFrequency','activateStream'])
 def test_linear_average_peak_and_saved_baseline_are_not_mutated_by_next_sweep(self):
  self.data();s=self.survey;s.ingest(dict(kind='begin',sweep=1,rate=2048000,fft=1024));s.ingest(self.row(-100));s.ingest(self.row(-90));s.ingest(dict(kind='complete',time=3))
  self.assertEqual(s.data['peak'][0],-90);self.assertAlmostEqual(s.data['average'][0],10*math.log10((1e-10+1e-9)/2),places=2)
  s.ingest(dict(kind='begin',sweep=2,rate=2048000,fft=1024));identity=s.save('Antenna A');trace=s.trace(identity)
  self.assertEqual(trace['sweep'],1);self.assertTrue(trace['complete']);self.assertEqual(trace['label'],'Antenna A');self.assertEqual(s.data['power'][0],None)
 def test_invalid_results_and_incomplete_baseline_are_rejected(self):
  self.data()
  with self.assertRaises(ValueError):self.survey.save('Not yet')
  for value in (float('nan'),float('inf')):
   with self.assertRaises(ValueError):self.survey.ingest(self.row(value))
  for value in ('../settings','/etc/passwd','0'*30):
   with self.assertRaises(ValueError):self.survey.trace(value)
 def test_opening_survey_claims_nothing_and_start_uses_existing_broker(self):
  s=self.survey;self.assertEqual(self.hub.broker.snapshot(),{})
  old=Mock();self.hub.broker.register('ism',old);self.hub.broker.acquire('ism',self.device['id'])
  with patch('spectrum_monitor.threading.Thread') as thread:s.control('start');self.assertTrue(s.enabled);thread.return_value.start.assert_called_once()
  old.assert_called_once();s.thread=None;s.enabled=False;self.hub.broker.release('ism')
 def test_saved_traces_bounded_to_twenty_and_restored_data_preserves_metadata(self):
  self.data();s=self.survey;s.ingest(dict(kind='begin',sweep=1,rate=2048000,fft=1024));s.ingest(self.row(-90));s.ingest(dict(kind='complete',time=3))
  for i in range(23):s.save('Cable '+str(i))
  self.assertEqual(len(s.saved()),20);self.assertEqual(s.trace(s.saved()[0]['id'])['device']['serial'],'789')
 def test_automatic_gain_reset_never_mixes_measurements_from_different_gains(self):
  self.data();s=self.survey;s.ingest(self.row(-50));s.ingest(dict(kind='complete',time=3))
  s.ingest(dict(kind='gain_adjust',gain=18,previous=28,frequency=100e6))
  s.ingest(dict(kind='begin',sweep=1,rate=2048000,fft=1024,gain=18,reset=True))
  self.assertIsNone(s.completed);self.assertEqual(s.data['settings']['gain'],18)
  self.assertEqual(s.data['peak'],[None]*4);self.assertEqual(s.data['counts'],[0]*4)
  s.ingest(self.row(-100));self.assertEqual(s.data['average'][0],-100)
 def test_clipped_window_is_excluded_at_minimum_gain_but_other_bins_survive(self):
  self.data();s=self.survey;s.data['settings']['gain']=0
  good=self.row(-100);good.update(indices=[0,1],values=[-100,-101]);s.ingest(good)
  bad=self.row(-30);bad['clipped']=1000;s.ingest(bad)
  s.ingest(self.row(-90)) # A neighbouring window must not revive a clipped bin.
  self.assertEqual(s.data['power'][:2],[None,-101]);self.assertIsNone(s.data['peak'][0]);self.assertIsNone(s.data['average'][0]);self.assertEqual(s.data['counts'][0],0)
  self.assertTrue(s.data['masked'][0]);self.assertTrue(s.data['quality'][0]['excluded'])
 def test_manual_gain_retains_flagged_data_and_automatic_defaults_and_steps(self):
  from soapy_survey import lower_gain
  self.assertTrue(settings({})['auto_gain']);self.assertEqual([lower_gain(g) for g in (28,18,8,0)],[18,8,0,0])
  with self.assertRaises(ValueError):settings(dict(auto_gain='yes'))
  self.data();s=self.survey;s.data['settings'].update(gain=0,auto_gain=False)
  row=self.row(-30);row['clipped']=1000;s.ingest(row)
  self.assertEqual(s.data['power'][0],-30);self.assertFalse(s.data['quality'][0]['excluded'])
 def test_running_status_requires_a_real_process_and_fresh_current_run_samples(self):
  self.data();s=self.survey;s.enabled=True;s.status='STARTING';s.requested_at=10
  s.data.update(started=1,updated=20);s.process=Mock();s.process.poll.return_value=None
  with patch('spectrum_monitor.time.time',return_value=20):
   self.assertEqual(s.run_state()['phase'],'STARTING') # Previous trace is never live.
   s.data['started']=10;self.assertEqual(s.run_state()['phase'],'RUNNING')
   s.data['updated']=12;self.assertEqual(s.run_state()['phase'],'WAITING FOR DATA')
  s.process=None;s.enabled=False;s.status='ERROR';self.assertEqual(s.run_state()['phase'],'FAILED')
  s.status='COMPLETE';self.assertEqual(s.run_state()['phase'],'COMPLETED')
 def test_stop_reason_is_recorded_for_handoff_diagnostics(self):
  s=self.survey;s.enabled=True;s.stop('Receiver handed to another decoder')
  self.assertFalse(s.enabled);self.assertIn('another decoder',s.detail)
  self.assertEqual(s.snapshot()['activity'][-1]['action'],'stop')
  self.assertIn('another decoder',(s.root/'activity.jsonl').read_text())
 def test_repeated_start_does_not_launch_a_second_worker(self):
  s=self.survey
  with patch('spectrum_monitor.threading.Thread') as thread:
   s.control('start');s.control('start');self.assertEqual(thread.call_count,1)
  s.thread=None;s.enabled=False

 def test_fine_bin_limits_match_the_visible_range_guidance(self):
  self.assertEqual(settings(dict(low=25e6,high=525e6,bin=25000))['bin'],25000)
  self.assertEqual(settings(dict(low=25e6,high=125e6,bin=5000))['bin'],5000)
  with self.assertRaisesRegex(ValueError,'20,001'):
   settings(dict(low=25e6,high=125000001,bin=5000))

 def test_live_frame_stays_visible_until_next_measurement(self):
  self.data();s=self.survey;s.data['settings']['purpose']='investigate'
  s.ingest(dict(kind='begin',sweep=1,rate=2048000,fft=1024));s.ingest(self.row(-90));s.ingest(dict(kind='complete',time=3))
  s.ingest(dict(kind='begin',sweep=2,rate=2048000,fft=1024))
  self.assertEqual(s.data['power'][0],-90);self.assertFalse(s.data['complete']);self.assertEqual(s.comparison_data()['sweep'],1)
  s.ingest(self.row(-100));self.assertEqual(s.data['power'][0],-100)
 def test_watch_tuning_preserves_wide_channels_and_avoids_dc_for_narrow_ones(self):
  from soapy_survey import watch_plan
  watches=[dict(frequency=93.55e6,bandwidth=200000),dict(frequency=134.35e6,bandwidth=25000),dict(frequency=433.92e6,bandwidth=1000000)]
  centers=watch_plan(watches,92.8e6,435.17e6)
  self.assertEqual(len(centers),3)
  for watch,center in zip(watches,centers):
   self.assertLess(abs(watch['frequency']-center)+watch['bandwidth']/2,USABLE/2)
   self.assertGreater(abs(watch['frequency']-center),14000)
