"""Real-field mapping and source identity, isolated from receiver hardware."""
import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integrations/weewx'))
from weather_feed import observations,candidates

class WeatherTests(unittest.TestCase):
 def test_tpms_and_nonweather_temperature_are_not_promoted(self):
  for model in ('Toyota','Schrader-TPMS','Regency-Remote','Gas-Meter'):
   self.assertEqual(observations(dict(model=model,temperature_C=20,humidity=50)),{})
  self.assertEqual(observations(dict(model='Unrecognized',temperature_C=20)),{})
 def test_known_weather_fields_have_consistent_metricwx_units(self):
  self.assertEqual(observations(dict(model='Bresser-6in1',temperature_F=68,humidity=75,wind_avg_km_h=36,wind_max_mi_h=10,wind_dir_deg=270)),dict(outTemp=20,outHumidity=75,windSpeed=10,windGust=4.4704,windDir=270))
 def test_bad_missing_values_and_unverified_rain_pressure_are_not_invented(self):
  self.assertEqual(observations(dict(model='Acurite',temperature_C=float('nan'),humidity=110,wind_avg_m_s=-1,rain_mm=100,pressure_hPa=1020)),{})
  self.assertEqual(observations(dict(model='Acurite',temperature_C=True,humidity=None)),{})
  self.assertEqual(observations(dict(model='Acurite',temperature_C=0)),dict(outTemp=0))
 def test_multiple_dongles_deduplicate_one_station_without_mixing_channels(self):
  a=dict(time=10,fields=dict(model='Nexus-TH',id=1,channel=1,temperature_C=20))
  b=dict(time=12,fields=dict(model='Nexus-TH',id=1,channel=1,temperature_C=21))
  c=dict(time=11,fields=dict(model='Nexus-TH',id=1,channel=2,temperature_C=10))
  rows=candidates(dict(sensor_receivers={'ism':dict(records=[a,c],assigned=dict(serial='a')),'ism-2':dict(records=[b],assigned=dict(serial='b'))}))
  self.assertEqual(len(rows),2);self.assertEqual(rows[0]['values']['outTemp'],21);self.assertEqual(rows[0]['serial'],'b');self.assertNotEqual(rows[0]['id'],rows[1]['id'])

if __name__=='__main__':unittest.main()
