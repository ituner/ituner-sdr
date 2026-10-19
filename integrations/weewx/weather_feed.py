"""Weather-only rtl_433 mapping; no USB opens, receiver control or fabricated readings."""
import math
import re

WEATHER=re.compile(r'acurite|fineoffset|fine.off|bresser|oregon|nexus|lacrosse|la.crosse|tfa|ambient|a.*tech|ecowitt|prologue|thermopro|weather|wh[0-9]',re.I)
EXCLUDED=re.compile(r'tpms|toyota|ford|citroen|renault|schrader|remote|door|smoke|security|meter|regency',re.I)
FIELDS={
 'temperature_C':('outTemp',1,-80,80), 'temperature_F':('outTemp',None,-112,176),
 'humidity':('outHumidity',1,0,100),
 'wind_avg_m_s':('windSpeed',1,0,100), 'wind_avg_km_h':('windSpeed',1/3.6,0,360),
 'wind_avg_mi_h':('windSpeed',.44704,0,224),
 'wind_max_m_s':('windGust',1,0,120),'wind_max_km_h':('windGust',1/3.6,0,432),
 'wind_max_mi_h':('windGust',.44704,0,269),
 'wind_dir_deg':('windDir',1,0,360),'wind_dir':('windDir',1,0,360),
 'uv':('UV',1,0,30),'uvi':('UV',1,0,30),'light_W_m2':('radiation',1,0,1600),
}

def identity(row):
 f=row.get('fields',{});return '|'.join(str(f.get(k,'')) for k in ('model','id','channel'))

def observations(fields):
 result={}
 if not isinstance(fields,dict):return result
 model=str(fields.get('model',''));kind=str(fields.get('type',''))
 if EXCLUDED.search(model+' '+kind):return result
 weather_fields=any(k in fields for k in ('humidity','wind_avg_m_s','wind_avg_km_h','wind_avg_mi_h','rain_mm','rain_in','uv','uvi'))
 if not WEATHER.search(model) and not weather_fields:return result
 for key,(name,factor,lo,hi) in FIELDS.items():
  value=fields.get(key)
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:continue
  if name not in result:result[name]=(value-32)*5/9 if factor is None else value*factor
 return result

def candidates(state):
 receivers=state.get('sensor_receivers') or {'ism':state.get('sessions',{}).get('ism',{})}
 found={}
 for receiver,session in receivers.items():
  for row in session.get('records',[]):
   values=observations(row.get('fields',{}))
   if not values:continue
   key=identity(row);old=found.get(key)
   if old and old['time']>=row['time']:continue
   found[key]=dict(id=key,model=row['fields'].get('model'),sensor_id=str(row['fields'].get('id','')),channel=row['fields'].get('channel'),time=row['time'],receiver=receiver,serial=(session.get('assigned') or {}).get('serial'),values=values,rssi=row['fields'].get('rssi'))
 return sorted(found.values(),key=lambda r:r['time'],reverse=True)
