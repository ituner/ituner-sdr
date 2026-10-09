"""Receive-only HF CW starting points, within IARU Region 1 CW segments.
These are listening centers, not fixed calling channels or transmit permissions.
"""
import math
PRESETS=tuple(dict(id=band,band=band+' m',mode='usb',freq_khz=rf-.7,
    cw_mode='SCAN',tone_hz=700,wpm=0,squelch_db=12,max_tracks=4)
    for band,rf in (('160',1830),('80',3525),('60',5353),('40',7025),
                   ('30',10116),('20',14025),('17',18080),('15',21025),('12',24905),('10',28025)))


def settings(payload,preset):
    result={}
    for key,default in [('freq_khz',7024.3),('tone_hz',700),('wpm',0),('squelch_db',12),('max_tracks',4)]:
        try:result[key]=float(payload.get(key,preset.get(key,default)))
        except (ValueError,TypeError):raise ValueError('Enter numeric CW settings')
        if not math.isfinite(result[key]):raise ValueError('CW settings must be finite')
    # The editor offers RF center, while the receiver protocol uses a USB dial.
    if 'rf_khz' in payload:
        try:result['freq_khz']=float(payload['rf_khz'])-.7
        except (ValueError,TypeError):raise ValueError('Enter a valid RF center in kHz')
    if not math.isfinite(result['freq_khz']) or not .001<=result['freq_khz']<=29998.8:raise ValueError('Keep the receiving window within 0–30 MHz')
    if not 200<=result['tone_hz']<=1200:raise ValueError('Locked tone must be 200–1200 Hz')
    if result['wpm']!=0 and not 5<=result['wpm']<=55:raise ValueError('Use Auto (0), or 5–55 WPM')
    if not 6<=result['squelch_db']<=30:raise ValueError('Signal gate must be 6–30 dB')
    if result['max_tracks'] not in (1,2,3,4):raise ValueError('Choose 1–4 simultaneous signals')
    mode=payload.get('cw_mode',preset.get('cw_mode','SCAN'))
    if mode not in ('SCAN','LOCK'):raise ValueError('Choose automatic scan or locked tone')
    result.update(cw_mode=mode,max_tracks=int(result['max_tracks']))
    return result
