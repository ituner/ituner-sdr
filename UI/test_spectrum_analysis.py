"""Survey observations, not fabricated airtime: detection, retention and mode transitions."""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import numpy as np
from spectrum_analysis import SpectrumInsights,detect,reduce_values
from spectrum_monitor import SpectrumSurvey,settings
from spectrum_report import comparison,create_report
from sdr_broker import ReceiverBroker


class InsightsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.insights=SpectrumInsights(self.root);self.now=time.time()
  self.config=settings(dict(low=100e6,high=103e6,bin=25000,gain=0))
 def tearDown(self):self.insights.flush();self.temp.cleanup()
 def data(self,sweep=1,power=None):
  values=[-110.0]*120 if power is None else list(power)
  return dict(settings=dict(self.config),device=dict(id='serial:test',serial='test'),rate=2048000,fft=1024,started=self.now-20,sweep_started=self.now-2,finished=self.now+sweep*.1,updated=self.now+sweep*.1,sweep=sweep,power=values,average=list(values),peak=list(values),masked=[False]*len(values),complete=True)
 def test_local_floor_groups_signals_and_does_not_detect_tilt_as_activity(self):
  d=self.data(power=np.linspace(-120,-100,120));self.assertEqual(detect(d)['signals'],[])
  d=self.data();d['power'][40:43]=[-92,-90,-93];r=detect(d)
  self.assertEqual(len(r['signals']),1);self.assertEqual(r['signals'][0]['width'],75000);self.assertEqual(r['signals'][0]['frequency'],101037500);self.assertAlmostEqual(r['signals'][0]['excess'],20)
  d['masked'][41]=True;r=detect(d);self.assertFalse(r['active'][41]);self.assertFalse(r['valid'][41])
 def test_detection_fraction_excludes_missing_and_clipped_visits_and_deduplicates(self):
  a=self.data();a['power'][40]=-90;self.insights.observe(a);self.insights.observe(a)
  b=self.data(2);self.insights.observe(b)
  c=self.data(3);c['power'][40]=None;self.insights.observe(c)
  d=self.data(4);d['masked'][40]=True;self.insights.observe(d)
  result=self.insights.snapshot(a,columns=120);signal=result['signals'][0]
  self.assertEqual(result['visits'],4);self.assertEqual(signal['visits'],2);self.assertEqual(signal['active_visits'],1);self.assertEqual(signal['activity'],50)
  self.assertEqual(result['activity'][40],50)
 def test_minute_retention_survives_many_fast_frames_and_restart(self):
  for i in range(80):
   d=self.data(i+1);d['finished']=self.now-180+(i//20)*60;d['sweep_started']=d['finished']-.2;d['power'][40]=-90;self.insights.observe(d)
  self.insights.flush();restored=SpectrumInsights(self.root);result=restored.snapshot(d,columns=120)
  self.assertEqual(result['visits'],80);self.assertEqual(len(result['timeline']),4);self.assertEqual(sum(r['visits'] for r in result['timeline']),80)
  with patch('spectrum_analysis.time.time',return_value=self.now+86401):restored.prune();self.assertEqual(restored.snapshot(d,columns=120)['visits'],0)
 def test_settings_are_isolated_and_partial_captures_are_not_visits(self):
  d=self.data();d['power'][40]=-90;self.insights.observe(d)
  partial=self.data(2);partial['complete']=False;self.insights.observe(partial)
  self.assertEqual(self.insights.snapshot(d)['visits'],1)
  other=self.data(3);other['settings']['gain']=10;self.assertEqual(self.insights.snapshot(other)['visits'],0)
 def test_watch_transitions_require_valid_visits_and_two_quiet_observations(self):
  identity=self.insights.add_watch(101e6,'Test');w=self.insights.watch[0]
  def sample(t,excess,clipped=False,key='same'):self.insights.watch_measure(w,dict(level=-100+excess,excess=excess,time=self.now+t,clipped=clipped),key)
  sample(0,10);sample(1,0,True);self.assertTrue(self.insights.watches()[0]['measurement']['present'])
  sample(2,0);self.assertTrue(self.insights.watches()[0]['measurement']['present'])
  sample(3,0);self.assertFalse(self.insights.watches()[0]['measurement']['present'])
  sample(4,12);sample(5,24);sample(6,0,key='gain changed')
  self.assertEqual([e['kind'] for e in reversed(self.insights.events())],['detected','disappeared','appeared','level changed'])
  self.insights.remove_watch(identity);self.assertEqual(self.insights.watches(),[])
 def test_report_uses_real_measurements_and_escapes_labels(self):
  d=self.data();d['power'][40]=-90;self.insights.observe(d)
  fake=SimpleNamespace(root=self.root,lock=__import__('threading').RLock(),completed=d,data=d,insights=self.insights,history=None,event=Mock())
  identity=create_report(fake,'<script>bad</script>');report=self.root/'reports'/identity
  self.assertTrue((report/'waterfall.png').is_file());self.assertIn('&lt;script&gt;bad&lt;/script&gt;',(report/'index.html').read_text());self.assertNotIn('<script>bad</script>',(report/'index.html').read_text())
  self.assertEqual(json.loads((report/'report.json').read_text())['data']['power'][40],-90)
 def test_comparison_requires_identical_measurements_and_excludes_invalid_cells(self):
  a=self.data();b=self.data();a['power'][1]=-100;b['power'][1]=-106;a['masked'][2]=True;b['power'][3]=None
  result=comparison(a,b);self.assertTrue(result['matched']);self.assertEqual(result['delta'][1],6);self.assertIsNone(result['delta'][2]);self.assertIsNone(result['delta'][3])
  b['settings']['gain']=10;self.assertFalse(comparison(a,b)['matched'])


class TransitionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.device=dict(id='serial:test',serial='test',persistent=True)
  self.hub=SimpleNamespace(root=Path(self.temp.name),devices=[self.device],broker=ReceiverBroker());self.survey=SpectrumSurvey(self.hub)
 def tearDown(self):self.survey.thread=None;self.survey.enabled=False;self.survey.close();self.temp.cleanup()
 def test_investigation_uses_fixed_span_off_dc_and_return_restores_survey(self):
  s=self.survey;original=dict(s.settings);s.enabled=True
  with patch('spectrum_monitor.threading.Thread'):
   s.control('investigate',frequency=125e6)
   self.assertEqual(s.settings['purpose'],'investigate');self.assertLessEqual(s.settings['high']-s.settings['low'],1536000)
   self.assertNotEqual((s.settings['low']+s.settings['high'])/2,125e6);self.assertTrue(s.enabled);self.assertEqual(len(s.parents),1)
   s.thread=None;s.control('return');self.assertEqual(s.settings,original);self.assertTrue(s.enabled);self.assertFalse(s.parents)
 def test_watch_mode_only_starts_explicitly_and_can_return_after_investigating(self):
  s=self.survey
  with self.assertRaisesRegex(ValueError,'Add a frequency'):s.control('watch_start')
  s.control('watch_add',frequency=433.92e6);self.assertFalse(s.enabled)
  with patch('spectrum_monitor.threading.Thread'):
   s.control('watch_start');self.assertEqual(s.settings['purpose'],'watch')
   s.thread=None;s.control('investigate',frequency=433.92e6);self.assertEqual(len(s.parents),2)
   s.thread=None;s.control('return');self.assertEqual(s.settings['purpose'],'watch')

class ReductionContractTests(unittest.TestCase):
 def test_vector_reduction_matches_reference_with_gaps_and_partial_bins(self):
  import math
  rng=np.random.default_rng(4);values=rng.normal(-100,10,97);values[::7]=np.nan
  config=dict(low=25e6,bin=25000,high=25e6+97*25000)
  for low,high,columns in ((25e6,config['high'],14),(25e6+12345,26e6+6789,129),(25e6,config['high'],1)):
   for method in ('max','mean'):
    expected=[]
    for x in range(columns):
     a=max(0,min(len(values)-1,int((low+(high-low)*x/columns-config['low'])/config['bin'])))
     b=min(len(values),max(a+1,math.ceil((low+(high-low)*(x+1)/columns-config['low'])/config['bin'])))
     cell=values[a:b];cell=cell[np.isfinite(cell)]
     expected.append(float((np.mean if method=='mean' else np.max)(cell)) if len(cell) else None)
    actual=reduce_values(values,config,low,high,columns,method)
    self.assertEqual([v is None for v in actual],[v is None for v in expected])
    np.testing.assert_allclose([v for v in actual if v is not None],[v for v in expected if v is not None])

class AnalysisDetailTests(unittest.TestCase):
 def test_signals_query_keeps_counts_without_building_history_or_persistence(self):
  with tempfile.TemporaryDirectory() as name:
   insights=SpectrumInsights(Path(name));now=time.time()
   d=dict(settings=dict(low=100e6,high=100.3e6,bin=25000,gain=0,ppm=0),device=dict(id='test'),complete=True,started=now-1,finished=now,sweep=1,power=[-110]*12)
   d['power'][5]=-80;insights.observe(d);history=Mock()
   small=insights.snapshot(d,history=history,columns=12,detail='signals')
   history.read.assert_not_called();self.assertEqual(small['timeline'],[]);self.assertEqual(small['persistence'],[])
   full=insights.snapshot(d,columns=12)
   self.assertEqual(small['signals'],full['signals']);self.assertEqual(small['visits'],full['visits'])
