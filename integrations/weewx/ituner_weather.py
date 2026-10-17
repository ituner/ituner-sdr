"""WeeWX driver reading actual selected weather packets from the local feed."""
import json
import logging
import time
import urllib.request
import weewx
import weewx.drivers

log=logging.getLogger(__name__)

def loader(config_dict,_engine):return ITunerWeather(**config_dict.get('ITunerWeather',{}))

class ITunerWeather(weewx.drivers.AbstractDevice):
 def __init__(self,**config):
  self.url=config.get('feed_url','http://127.0.0.1:8094/api/weather');self.closed=False
 @property
 def hardware_name(self):return 'iTuner shared rtl_433 weather feed'
 def genLoopPackets(self):
  previous=None;last_warning=0
  while not self.closed:
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
