"""WeeWX driver reading actual selected weather packets from the local feed."""
import json
import logging
import time
import os
import urllib.request
import weewx
import weewx.drivers
import weewx.units

log=logging.getLogger(__name__)

def loader(config_dict,_engine):return ITunerWeather(engine=_engine,**config_dict.get('ITunerWeather',{}))

class ITunerWeather(weewx.drivers.AbstractDevice):
 def __init__(self,**config):
  self.url=config.get('feed_url','http://127.0.0.1:8094/api/weather');self.closed=False
  self.engine=config.get('engine');self.station_url=config.get('station_url','http://127.0.0.1:8092/api/station');self.next_station=0;self.station_state=None
 @property
 def hardware_name(self):return 'iTuner shared rtl_433 weather feed'
 def sync_station(self):
  if time.monotonic()<self.next_station:return
  self.next_station=time.monotonic()+10
  try:
   with urllib.request.urlopen(self.station_url,timeout=1) as response:shared=json.load(response)
   p=shared.get('position');c=shared['config'];self.station_state=shared
   if not p or self.engine is None:return
   station=self.engine.config_dict['Station'];label=c['site_label'] or c['station_name']
   station.update(dict(latitude=p['lat'],longitude=p['lon'],location=label))
   info=getattr(self.engine,'stn_info',None)
   if info is not None:
    info.latitude_f=p['lat'];info.longitude_f=p['lon'];info.location=label
   altitude=p.get('altitude_msl_m')
   # WeeWX requires an altitude for almanac calculations. Zero remains an
   # internal fallback when unknown; pressure synthesis stays disabled.
   station['altitude']=[str(altitude if altitude is not None else 0),'meter']
   if info is not None:
    info.ituner_altitude_known=altitude is not None
    info.altitude_vt=weewx.units.ValueTuple(altitude if altitude is not None else 0,'meter','group_altitude')
   report=self.engine.config_dict.get('StdReport',{}).get('Belchertown',{})
   report.setdefault('Extras',{})['site_title']=c['station_name']+' Weather'
   report.setdefault('Labels',{}).setdefault('Generic',{})['home_page_header']=label+' · RTL-SDR weather'
   if os.environ.get('TZ')!=c['timezone']:
    os.environ['TZ']=c['timezone']
    if hasattr(time,'tzset'):time.tzset()
  except (OSError,ValueError,KeyError,AttributeError,TypeError):pass
 def genLoopPackets(self):
  previous=None;last_warning=0
  while not self.closed:
   self.sync_station()
   try:
    with urllib.request.urlopen(self.url,timeout=5) as response:state=json.load(response)
    row=state.get('reading')
    if row and state.get('fresh') and row.get('values'):
     key=(row['id'],row['time'])
     if key!=previous:
      previous=key
      yield dict(dateTime=int(row['time']),usUnits=weewx.METRICWX,**row['values'])
   except (OSError,ValueError,KeyError) as exc:
    if time.time()-last_warning>60:log.warning('Weather feed unavailable: %s',exc);last_warning=time.time()
   time.sleep(2)
 def closePort(self):self.closed=True
