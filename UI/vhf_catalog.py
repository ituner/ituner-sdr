"""Receive-only profiles; frequencies can be changed without editing commands."""
from pathlib import Path

MODES = {
    'ais': dict(title='Maritime', label='AIS', engine='AIS-catcher', icon='ship', color='#63dcca',
        description='Dual-channel vessel tracking, identities and navigation reports.',
        hint='Marine VHF antenna · receives AIS A and B together.',
        url='https://github.com/jvde-github/AIS-catcher',
        presets=[dict(id='ais-ab', name='AIS A + B', frequency=162000000, subtitle='161.975 + 162.025 MHz')]),
    'aprs': dict(title='Packet radio', label='APRS', engine='Dire Wolf', icon='pin', color='#efbd75',
        description='Local RF stations, positions, weather and AX.25 packets.',
        hint='144.800 MHz is the European APRS channel. RF reception only.',
        url='https://github.com/wb2osz/direwolf',
        presets=[dict(id='eu', name='Europe · 1200 baud', frequency=144800000),
                 dict(id='na', name='North America · 1200 baud', frequency=144390000),
                 dict(id='iss', name='ISS packet · 1200 baud', frequency=145825000)]),
    'ism': dict(title='Sensor observatory', label='rtl_433', engine='rtl_433', icon='sensor', color='#a5c3ff',
        description='Weather stations, environmental sensors and short-range devices.',
        hint='Listen on one band at a time. Sensor readings appear when a supported device transmits.',
        url='https://github.com/merbanan/rtl_433',
        presets=[dict(id='433', name='433 MHz · Europe', frequency=433920000),
                 dict(id='868', name='868 MHz · Europe', frequency=868300000),
                 dict(id='315', name='315 MHz', frequency=315000000),
                 dict(id='915', name='915 MHz', frequency=915000000)]),
    'meteor': dict(title='Earth observation', label='Meteor-M', engine='SatDump', icon='satellite', color='#b9a5f7',
        description='Decode LRPT passes into multispectral weather imagery.',
        hint='137 MHz satellite antenna · a visible pass is required. Stop finishes the image products.',
        url='https://github.com/SatDump/SatDump',
        # Frequency changes are operational: retain alternate profiles, but prefer
        # the M2-4 downlink reported at https://ub8qbd.satdump.org/wx_report_new.html
        presets=[dict(id='m24-72', name='Meteor-M N2-4 · 137.100 MHz · 72k', frequency=137100000, norad=59051, satellite='M2-4', pipeline='meteor_m2-x_lrpt'),
                 dict(id='auto-72', name='137.900 MHz alternate · Auto 72k', frequency=137900000, norad=57166, norads=[57166,59051], satellite='AUTO', auto_satellite=True, pipeline='meteor_m2-x_lrpt'),
                 dict(id='m23-72', name='Meteor-M N2-3 · 72k', frequency=137900000, norad=57166, satellite='M2-3', pipeline='meteor_m2-x_lrpt'),
                 dict(id='m23-80', name='Meteor-M N2-3 · 80k', frequency=137900000, norad=57166, satellite='M2-3', pipeline='meteor_m2-x_lrpt_80k'),
                 dict(id='m24-80', name='Meteor-M N2-4 · 137.100 MHz · 80k', frequency=137100000, norad=59051, satellite='M2-4', pipeline='meteor_m2-x_lrpt_80k')]),
    'cubesat': dict(title='Orbital telemetry', label='CubeSat', engine='gr-satellites', icon='satellite', color='#88cff5',
        description='Satellite-specific demodulators, telemetry fields and KISS frames.',
        hint='Choose a satellite and its downlink. Catalog support does not imply an active transmitter.',
        url='https://github.com/daniestevez/gr-satellites',
        presets=[dict(id='ao73', name='AO-73 / FUNcube-1', frequency=145935000, satellite='AO-73', norad=39444)]),
    'sonde': dict(title='Upper atmosphere', label='Radiosonde', engine='RS1729', icon='balloon', color='#f69ca6',
        description='Weather-balloon positions, altitude, temperature and humidity.',
        hint='Tune to a local sonde in the 400–406 MHz band. RS41 and DFM are supported.',
        url='https://github.com/rs1729/RS',
        presets=[dict(id='rs41', name='Vaisala RS41', frequency=401500000, decoder='rs41mod'),
                 dict(id='dfm', name='Graw DFM', frequency=403000000, decoder='dfm09mod')]),
}


def satellite_catalog():
    """Use the installed engine's SatYAML files, including protocol/frequency pairs."""
    try:
        import importlib.util
        import yaml
        package = importlib.util.find_spec('satellites')
        if not package: raise ImportError('gr-satellites is not installed')
        base = Path(package.origin).parent/'satyaml'
        rows = []
        for path in sorted(base.glob('*.yml')):
            try:
                item = yaml.safe_load(path.read_text())
                for name, tx in (item.get('transmitters') or {}).items():
                    freq = float(tx.get('frequency', 0))
                    if not 30000000 <= freq <= 1700000000 or float(tx.get('baudrate',0))>19200: continue
                    rows.append(dict(id=path.stem+':'+name, name=item['name']+' · '+name,
                        frequency=int(freq), satellite=item['name'], norad=int(item['norad']),
                        modulation=tx.get('modulation', ''), framing=tx.get('framing', ''),definition=path.name,transmitter=name))
            except (OSError, ValueError, KeyError, TypeError): continue
        return rows or list(MODES['cubesat']['presets'])
    except ImportError:
        return list(MODES['cubesat']['presets'])


def profiles():
    catalog = {key:dict(value, presets=[dict(p) for p in value['presets']]) for key,value in MODES.items()}
    catalog['cubesat']['presets'] = satellite_catalog()
    return catalog


def write_satellite_profile(profile, directory):
    """Run only the chosen downlink, rather than every transmitter on a satellite."""
    if not profile.get('definition'): return profile['satellite']
    import importlib.util
    import yaml
    package=importlib.util.find_spec('satellites')
    base=Path(package.origin).parent/'satyaml'
    item=yaml.safe_load((base/profile['definition']).read_text())
    name=profile['transmitter']
    item['transmitters']={name:item['transmitters'][name]}
    item.pop('telemetry_servers',None)
    path=Path(directory)/'downlink.yml'
    path.write_text(yaml.safe_dump(item))
    return str(path)
