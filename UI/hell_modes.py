"""Hell modes and editable USB dial presets (audio center stored separately)."""
# Rates/deviations follow fldigi src/feld/feld.cxx. See docs/HELL.md.
MODES = {
    'HELL': dict(label='Feld Hell', columns=17.5, bandwidth=350, shift=0),
    'SLOWHELL': dict(label='Slow Hell', columns=2.1875, bandwidth=45, shift=0),
    'HELLX5': dict(label='Hell ×5', columns=87.5, bandwidth=1750, shift=0),
    'HELLX9': dict(label='Hell ×9', columns=157.5, bandwidth=3150, shift=0),
    'FSKH245': dict(label='FSK Hell 245', columns=17.5, bandwidth=490, shift=122.5),
    'FSKH105': dict(label='FSK Hell 105', columns=17.5, bandwidth=220, shift=55),
    'HELL80': dict(label='Hell 80', columns=35, bandwidth=1200, shift=300),
}
# General activity points are RF centers chosen within the club's published
# areas; dial = RF - 1.5 kHz. The explicitly published EU net values are DIAL.
PRESETS = tuple(dict(id=key, band=band, freq_khz=dial, mode='usb', tone_hz=1500,
                     hell_mode=mode) for key, band, dial, mode in (
    ('160', '160 m', 1842, 'HELL'), ('80', '80 m', 3582.5, 'HELL'),
    ('40', '40 m', 7083.5, 'HELL'), ('30', '30 m', 10139.5, 'HELL'),
    ('20', '20 m', 14061.5, 'HELL'), ('17', '17 m', 18098.5, 'HELL'),
    ('15', '15 m', 21061.5, 'HELL'), ('12', '12 m', 24922.5, 'HELL'),
    ('10', '10 m', 28061.5, 'HELL'),
    ('eu30', 'EU net · 30 m', 10144, 'FSKH105'),
    ('eu20', 'EU net · 20 m', 14068, 'FSKH105'),
))


def selected_modes(config):
    modes = config.get('hell_modes', [config.get('hell_mode', 'HELL')])
    if not isinstance(modes, list) or not modes or len(modes) > len(MODES):
        raise ValueError('Select at least one Hell mode')
    if any(not isinstance(mode, str) or mode not in MODES for mode in modes):
        raise ValueError('Choose supported Hell modes')
    return [mode for mode in MODES if mode in modes]


def fit_modes(config, modes):
    """Changing the audio passband must not move the station's RF center."""
    modes = selected_modes({'hell_modes': modes})
    half = max(MODES[mode]['bandwidth']/2 for mode in modes)
    old_tone = config['tone_hz']
    tone = min(5000-half, max(old_tone, 200, half+150))
    return dict(config, hell_mode=modes[0], hell_modes=modes, tone_hz=tone,
                freq_khz=config['freq_khz']+(old_tone-tone)/1000)


def settings(payload, preset):
    import math
    modes = selected_modes(payload if 'hell_modes' in payload or 'hell_mode' in payload else preset)
    try:
        tone = float(payload.get('tone_hz', preset.get('tone_hz', 1500)))
        freq = float(payload.get('freq_khz', preset['freq_khz']))
    except (ValueError, TypeError):
        raise ValueError('Enter a valid dial frequency and audio center')
    # Preserve the full occupied bandwidth in Kiwi audio, including Hell x9.
    half = max(MODES[mode]['bandwidth']/2 for mode in modes)
    if not math.isfinite(tone) or not max(200, half+100) <= tone <= 5000-half:
        raise ValueError(f'Audio center for selected modes: {max(200, half+100):g}–{5000-half:g} Hz')
    if not math.isfinite(freq) or not 0 < freq <= 30000-tone/1000:
        raise ValueError('Choose a frequency within Kiwi’s 0–30 MHz range')
    reverse = payload.get('reverse', preset.get('reverse', False))
    if type(reverse) is not bool:
        raise ValueError('Invalid reverse setting')
    return dict(hell_mode=modes[0], hell_modes=modes, tone_hz=tone, freq_khz=freq, reverse=reverse)
