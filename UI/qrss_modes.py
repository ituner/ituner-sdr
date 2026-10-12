"""QRSS listening presets: RF centers, with an explicit USB audio offset."""
import math

DOTS = (3, 6, 10, 30, 60)
KINDS = ('AUTO', 'CW', 'FSKCW', 'VISUAL')
PRESETS = tuple(dict(id=band, band=band+' m', mode='usb', freq_khz=rf-1.5,
    tone_hz=1500, span_hz=200, dot_seconds=6, shift_hz=5,
    qrss_mode='AUTO', reverse=False, minutes=10) for band, rf in
    (('80',3500.85),('40',7000.85),('30',10140.0),('20',14096.9)))


def settings(payload, preset):
    result = {}
    for key, default in [('freq_khz',10138.5),('tone_hz',1500),('span_hz',200),
                         ('dot_seconds',6),('shift_hz',5),('minutes',10)]:
        try:
            result[key] = float(payload.get(key, preset.get(key, default)))
        except (TypeError,ValueError):
            raise ValueError('Enter valid QRSS frequencies and timing')
        if not math.isfinite(result[key]):
            raise ValueError('Enter finite QRSS values')
    mode = payload.get('qrss_mode',preset.get('qrss_mode','FSKCW'))
    if mode not in KINDS:raise ValueError('Choose Auto, CW, FSKCW or visual only')
    reverse = payload.get('reverse',preset.get('reverse',False))
    if type(reverse) is not bool:raise ValueError('Invalid reverse setting')
    if result['dot_seconds'] not in DOTS:raise ValueError('Choose 3, 6, 10, 30 or 60 seconds per dot')
    if result['minutes'] not in (5,10,20,30):raise ValueError('Choose a 5, 10, 20 or 30 minute capture')
    if not 20 <= result['span_hz'] <= 1000:raise ValueError('Waterfall span: 20–1000 Hz')
    if not 1 <= result['shift_hz'] <= 20:raise ValueError('FSK shift: 1–20 Hz')
    tone,half=result['tone_hz'],result['span_hz']/2
    if not half+100 <= tone <= 5000-half:raise ValueError('Audio center must keep the waterfall inside 100–5000 Hz')
    if not 0 < result['freq_khz'] <= 30000-(tone+half)/1000:raise ValueError('Choose a frequency within 0–30 MHz')
    if result['freq_khz']*1000+tone-half <= 0:raise ValueError('Waterfall extends below 0 Hz RF')
    if mode=='FSKCW' and result['shift_hz'] >= half:raise ValueError('FSK shift must fit inside the waterfall span')
    resolution=12000/(2**int(math.floor(math.log2(12000*result['dot_seconds']/2))))
    if mode=='FSKCW' and result['shift_hz']<2.5*resolution:
        raise ValueError(f'For this dot speed, use at least {2.5*resolution:.2f} Hz FSK shift')
    result.update(qrss_mode=mode,reverse=reverse)
    return result
