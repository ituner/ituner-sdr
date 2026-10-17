"""WeeWX station metadata follows the shared profile without synthetic readings."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class WeatherStationTests(unittest.TestCase):
 def test_driver_updates_shared_site_and_preserves_weather_data_path(self):
  package=types.ModuleType('weewx');package.__path__=[];drivers=types.ModuleType('weewx.drivers');units=types.ModuleType('weewx.units')
  drivers.AbstractDevice=object;units.ValueTuple=lambda *args:args;package.drivers=drivers;package.units=units
  with patch.dict(sys.modules,{'weewx':package,'weewx.drivers':drivers,'weewx.units':units}):
   spec=importlib.util.spec_from_file_location('station_driver_test',ROOT/'integrations/weewx/ituner_weather.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   engine=types.SimpleNamespace(config_dict={'Station':{},'StdReport':{'Belchertown':{}}},stn_info=types.SimpleNamespace())
   driver=module.ITunerWeather(engine=engine)
   snapshot=dict(config=dict(station_name='Test radio',site_label='Test QTH',timezone='UTC'),position=dict(lat=44.4,lon=26.1,altitude_msl_m=110))
   with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(snapshot).encode())):driver.sync_station()
   self.assertEqual(engine.stn_info.latitude_f,44.4);self.assertEqual(engine.stn_info.longitude_f,26.1)
   self.assertEqual(engine.stn_info.altitude_vt,(110,'meter','group_altitude'))
   self.assertEqual(engine.config_dict['Station']['location'],'Test QTH')
   self.assertEqual(engine.config_dict['StdReport']['Belchertown']['Extras']['site_title'],'Test radio Weather')
   self.assertFalse(driver.closed);self.assertEqual(driver.url,'http://127.0.0.1:8094/api/weather')
 def test_unavailable_profile_does_not_break_weather_driver(self):
  package=types.ModuleType('weewx');package.__path__=[];drivers=types.ModuleType('weewx.drivers');units=types.ModuleType('weewx.units')
  drivers.AbstractDevice=object;package.drivers=drivers;package.units=units
  with patch.dict(sys.modules,{'weewx':package,'weewx.drivers':drivers,'weewx.units':units}):
   spec=importlib.util.spec_from_file_location('station_driver_failure_test',ROOT/'integrations/weewx/ituner_weather.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   driver=module.ITunerWeather()
   with patch.object(module.urllib.request,'urlopen',side_effect=OSError('offline')):driver.sync_station()
   self.assertFalse(driver.closed)

if __name__=='__main__':unittest.main()
