"""Configure an isolated, local-only WeeWX station before starting its daemon."""
from pathlib import Path
import configobj
root=Path('/var/lib/ituner-weather');path=root/'weewx.conf';c=configobj.ConfigObj(str(path),encoding='utf-8')
c['Station']['station_type']='ITunerWeather'
c['Station']['week_start']='0'
c.pop('Simulator',None)
c['ITunerWeather']=dict(driver='user.ituner_weather',feed_url='http://127.0.0.1:8094/api/weather')
c['StdConvert']['target_unit']='METRICWX'
c['StdArchive']['record_generation']='software';c['StdArchive']['archive_interval']='300'
for name,section in c['StdRESTful'].items():
 if isinstance(section,dict):
  section['enable']='false'
  if name=='StationRegistry':section['register_this_station']='false'
report=c['StdReport'];report['HTML_ROOT']=str(root/'public_html')
for name,section in report.items():
 if isinstance(section,dict) and name not in ('Defaults','Belchertown'):section['enable']='false'
b=report['Belchertown'];b['HTML_ROOT']=str(root/'public_html');b['enable']='true'
b['Extras']=dict(theme='dark',site_title='iTuner Weather · Bucharest',forecast_enabled='0',earthquake_enabled='0',mqtt_websockets_enabled='0',webpage_autorefresh='300000',homepage_sections=['conditions','snapshot','charts'],radar_html='',radar_html_dark='',show_last_updated_alert='1',last_updated_alert_threshold='600')
b['Generators']=dict(generator_list=['user.ituner_report.EmptyCheetah','weewx.reportengine.CopyGenerator','user.ituner_report.EmptyHighcharts'])
b['Labels']=dict(Generic=dict(home_page_header='Bucharest · RTL-SDR weather',footer_copyright_text='iTuner · Local RF weather observations'))
report.setdefault('Defaults',{}).setdefault('Units',{}).setdefault('Groups',{}).update(dict(group_temperature='degree_C',group_speed='km_per_hour',group_speed2='km_per_hour2',group_rain='mm',group_rainrate='mm_per_hour',group_pressure='hPa'))
# Altitude is unknown. Do not manufacture sea-level pressure from a 0 m placeholder.
c.setdefault('StdWXCalculate',{}).setdefault('Calculations',{}).update(dict(barometer='hardware',altimeter='hardware',pressure='hardware'))
c.write()
# No externally provided forecast/map content is fetched on startup.
for name in ('about.inc','records.inc'):
 file=root/'skins/Belchertown'/name
 if not file.exists():file.write_text('<p>iTuner weather observations received through the shared rtl_433 sensor decoder. Missing sensor readings remain unavailable.</p>')
graphs=root/'skins/Belchertown/graphs.conf'
if not graphs.exists():graphs.write_bytes((root/'skins/Belchertown/graphs.conf.example').read_bytes())
