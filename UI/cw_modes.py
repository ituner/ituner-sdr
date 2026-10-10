"""Receive-only HF CW starting points, within IARU Region 1 CW segments.
These are listening centers, not fixed calling channels or transmit permissions.
"""
import math
PRESETS=tuple(dict(id=band,band=band+' m',mode='usb',freq_khz=rf-.7,
    engine='ggmorse',cw_mode='SCAN',tone_hz=700,wpm=0,squelch_db=12,max_tracks=4)
    for band,rf in (('160',1830),('80',3525),('60',5353),('40',7025),
                   ('30',10116),('20',14025),('17',18080),('15',21025),('12',24905),('10',28025)))


VIEW_SPANS=(3,5,10,20,50)


def overview_bounds(config):
    span=float(config.get("view_span_khz",3))*1000
    dial=config.get("freq_khz",7024.3)*1000
    low=max(-dial,min(1700-span/2,30000000-dial-span))
    return low,low+span


def center_offset(config):
    return 1.7 if config.get("engine")=="fldigi" else .7

def bounds(config):
    return (200,3200) if config.get("engine")=="fldigi" else (200,1200)

def display_bounds(config=None):
    """Overview bandwidth, independent of a decoder engine's acquisition range."""
    return 200,3200


def signal_markers(row, selected=None):
    """Map tracked audio tones into the overview without clamping off-screen signals."""
    low,high=row.get('display_low_hz',200),row.get('display_high_hz',3200)
    markers=[]
    for index,track in enumerate(row.get('tracks',[])[:4]):
        tone=track.get('tone_hz',track['rf_hz']-row['freq_khz']*1000)
        if low<=tone<=high:
            markers.append(dict(id=track['id'],slot=index+1,fraction=(tone-low)/(high-low),
                                selected=track['id']==selected,active=bool(track.get('active'))))
    return markers


def settings(payload,preset):
    engine=payload.get("engine",preset.get("engine","ggmorse"))
    if engine not in ("ggmorse","fldigi"):raise ValueError("Choose GGMorse or fldigi")
    span=payload.get('view_span_khz',preset.get('view_span_khz',3))
    if isinstance(span,bool) or span not in VIEW_SPANS:raise ValueError('Choose a 3, 5, 10, 20 or 50 kHz view')
    result={"engine":engine,"view_span_khz":span}
    for key,default in [('freq_khz',7024.3),('tone_hz',700),('wpm',0),('squelch_db',12),('max_tracks',4)]:
        try:result[key]=float(payload.get(key,preset.get(key,default)))
        except (ValueError,TypeError):raise ValueError('Enter numeric CW settings')
        if not math.isfinite(result[key]):raise ValueError('CW settings must be finite')
    if "freq_khz" not in payload:
        result["freq_khz"]+=center_offset(preset)-center_offset(result)
    if "tone_hz" not in payload and engine!=preset.get("engine","ggmorse"):
        result["tone_hz"]+=(center_offset(result)-center_offset(preset))*1000
    # The editor offers RF center, while the receiver protocol uses a USB dial.
    if 'rf_khz' in payload:
        try:result['freq_khz']=float(payload['rf_khz'])-center_offset(result)
        except (ValueError,TypeError):raise ValueError('Enter a valid RF center in kHz')
    if not math.isfinite(result['freq_khz']) or not .001<=result['freq_khz']<=30000-display_bounds(result)[1]/1000:raise ValueError('Keep the receiving window within 0–30 MHz')
    if not 200<=result['tone_hz']<=bounds(result)[1]:raise ValueError(f'Locked tone must be 200–{bounds(result)[1]} Hz')
    if result['wpm']!=0 and not 5<=result['wpm']<=55:raise ValueError('Use Auto (0), or 5–55 WPM')
    if not 6<=result['squelch_db']<=30:raise ValueError('Signal gate must be 6–30 dB')
    if result['max_tracks'] not in (1,2,3,4):raise ValueError('Choose 1–4 simultaneous signals')
    mode=payload.get('cw_mode',preset.get('cw_mode','SCAN'))
    if mode not in ('SCAN','LOCK'):raise ValueError('Choose automatic scan or locked tone')
    result.update(cw_mode=mode,max_tracks=int(result['max_tracks']))
    return result
