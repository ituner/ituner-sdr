"""Acquisition is tested from raw independently keyed PCM and a saved raster.

The saved-spectrum fixture is reconstructed from the user's 2026-10-09 06:24
UTC PNG, not raw audio: inverse color mapping, 320 image rows, 600.1 seconds.
It checks acquisition on the reported example but cannot establish raw-audio
SNR or confirm a station identity.
"""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from qrss_acquisition import AutoAcquisition
from qrss_decoder import QRSSDecoder,MorseTiming
from qrss_modes import PRESETS


def transmit(dot=4.3,mode='FSKCW',reverse=False,tone=1585,shift=10,noise=.005,carrier=False):
    codes={'S':'...','O':'---','A':'.-','7':'--...'}
    units=[(False,7)]
    for letter in 'SOS A SOS':
        if letter==' ':
            units[-1]=(False,7)
            continue
        for symbol in codes[letter]:units.extend([(True,1 if symbol=='.' else 3),(False,1)])
        units[-1]=(False,3)
    units[-1]=(False,10)
    rng=np.random.default_rng(31);phase=0;sample=0
    for mark,count in units:
        length=round(dot*count*12000)
        for off in range(0,length,12000):
            n=min(12000,length-off);t=np.arange(n)/12000
            f=tone-(shift if mark==reverse else 0)
            signal=.2*np.sin(phase+2*np.pi*f*t) if mark or mode=='FSKCW' else np.zeros(n)
            phase=(phase+2*np.pi*f*n/12000)%(2*np.pi)
            if carrier:signal+=.5*np.sin(2*np.pi*1440*t)
            signal+=rng.normal(0,noise,n);sample+=n
            yield (np.clip(signal,-1,1)*32767).astype('<i2').tobytes()


def keying(t,dot,text='SOS A SOS'):
    codes={'S':'...','O':'---','A':'.-'}
    lengths=[7];states=[False]
    for letter in text:
        if letter==' ':lengths[-1]=7;continue
        for symbol in codes[letter]:
            lengths.extend([1 if symbol=='.' else 3,1]);states.extend([True,False])
        lengths[-1]=3
    lengths[-1]=10
    edges=np.cumsum(lengths)*dot
    return np.array(states)[np.searchsorted(edges,np.asarray(t)%edges[-1],side='right')]


class AutoTests(unittest.TestCase):
    def test_off_center_unknown_speed_shift_and_reverse(self):
        for mode,reverse,dot in [('FSKCW',False,4.3),('FSKCW',True,7.2),('CW',False,4.3),('FSKCW',False,30)]:
            with self.subTest(mode=mode,reverse=reverse,dot=dot):
                d=QRSSDecoder(dict(PRESETS[2],qrss_mode='AUTO'))
                for pcm in transmit(mode=mode,reverse=reverse,dot=dot,carrier=True):d.feed(pcm)
                status=d.auto.status
                self.assertEqual(status['state'],'locked',status)
                self.assertEqual(status['mode'],mode)
                self.assertAlmostEqual(status['dot_seconds'],dot,delta=max(.45,.06*dot))
                self.assertAlmostEqual(status['tone_hz'],1575 if reverse else 1585,delta=1)
                if mode=='FSKCW':self.assertAlmostEqual(status['shift_hz'],10,delta=1)
                self.assertIn('SOS', ''.join(c for t,c in d.morse.events))

    def test_three_raw_audio_stations_with_independent_cadences_and_levels(self):
        # Strong FSK, 18 dB weaker reversed FSK, 24 dB weaker CW, plus
        # a louder unkeyed carrier. All share one actual PCM/FFT stream.
        d=QRSSDecoder(dict(PRESETS[2],qrss_mode='AUTO'))
        rng=np.random.default_rng(718);phases=[0.,0.,0.]
        specs=[(1585,4.3,.24,'FSKCW',False),(1485,7.2,.03,'FSKCW',True),(1435,12.5,.015,'CW',False)]
        identities={}
        for sec in range(720):
            t=sec+np.arange(12000)/12000
            pcm=rng.normal(0,.005,12000)+.32*np.sin(2*np.pi*1540*t)
            for i,(tone,dot,amp,mode,reverse) in enumerate(specs):
                marks=keying(t,dot)
                freq=tone-10*(marks==reverse) if mode=='FSKCW' else np.full(len(t),tone)
                phase=phases[i]+np.cumsum(2*np.pi*freq/12000)
                pcm+=amp*np.sin(phase)*(marks if mode=='CW' else 1)
                phases[i]=phase[-1]%(2*np.pi)
            d.feed((pcm*32767).astype('<i2').tobytes())
            if sec==500:identities={round(r['tone_hz']):r['id'] for r in d.auto.tracks if r['active']}
        rows=[r for r in d.auto.tracks if r['active']]
        self.assertEqual(len(rows),3,[(r['mode'],r['tone_hz'],r['dot']) for r in rows])
        for tone,dot,amp,mode,reverse in specs:
            mark=tone-10 if reverse else tone
            row=min(rows,key=lambda r:abs(r['tone_hz']-mark))
            self.assertAlmostEqual(row['tone_hz'],mark,delta=1)
            self.assertAlmostEqual(row['dot'],dot,delta=.5)
            self.assertEqual(row['mode'],mode)
            self.assertIn('SOS',''.join(c for t,c in row['events']))
            self.assertEqual(row['id'],identities[round(row['tone_hz'])])
        # Taking one station away must not interrupt the other cadences or
        # erase that station's already decoded text.
        removed=min(rows,key=lambda r:abs(r['tone_hz']-1585))['id']
        before={r['id']:r['dot'] for r in rows}
        for sec in range(720,930):
            t=sec+np.arange(12000)/12000;pcm=rng.normal(0,.005,12000)
            for i,(tone,dot,amp,mode,reverse) in enumerate(specs[1:],1):
                marks=keying(t,dot)
                freq=tone-10*(marks==reverse) if mode=='FSKCW' else np.full(len(t),tone)
                phase=phases[i]+np.cumsum(2*np.pi*freq/12000)
                pcm+=amp*np.sin(phase)*(marks if mode=='CW' else 1);phases[i]=phase[-1]%(2*np.pi)
            d.feed((pcm*32767).astype('<i2').tobytes())
        active=[r for r in d.auto.tracks if r['active']]
        self.assertEqual(len(active),2)
        self.assertNotIn(removed,[r['id'] for r in active])
        self.assertTrue(any(r['id']==removed and r['tentative_text'] for r in d.auto.snapshot(0,930)))
        for r in active:self.assertAlmostEqual(r['dot'],before[r['id']],delta=.5)

    def test_nearby_unrelated_cw_is_not_paired_and_track_limit(self):
        frequencies=np.arange(1400.,1600.,.75)
        a=AutoAcquisition(frequencies,MorseTiming,.5)
        rng=np.random.default_rng(418)
        for k in range(1600):
            t=k*.5;db=rng.normal(0,2,len(frequencies))
            for j in range(8):
                if keying(t,3+j*.7):db[abs(frequencies-(1420+10*j))<1]=20+j*2
            a.feed(t,db)
        rows=[r for r in a.tracks if r['active']]
        self.assertEqual(len(rows),a.MAX_TRACKS)
        self.assertTrue(all(r['mode']=='CW' for r in rows))
        self.assertEqual(len(set(r['id'] for r in rows)),a.MAX_TRACKS)
        a.reset();self.assertFalse(a.tracks)

    def test_late_acquisition_backfills_saved_captures(self):
        import tempfile
        from qrss_monitor import QRSSManager,QRSSSession,QRSSAssembler
        with tempfile.TemporaryDirectory() as root:
            m=QRSSManager(None,'test',root)
            c=dict(PRESETS[2],id='test',name='Local',server='http://kiwi.local')
            session=QRSSSession(c,None,m.gallery,'test');session.config['minutes']=.5
            a=QRSSAssembler(session,m.gallery);a.decoder.auto.next_analysis=130
            for pcm in transmit():a.feed(pcm)
            a.flush()
            early=[r for r in m.image_snapshot() if r['sample_end']<100]
            self.assertTrue(any('S' in r['tentative_text'] for r in early),early)
            m.stop()

    def test_multiple_track_text_survives_capture_rollover_and_reload(self):
        import tempfile,time,uuid
        from qrss_monitor import QRSSManager,QRSSSession,QRSSAssembler
        with tempfile.TemporaryDirectory() as root:
            m=QRSSManager(None,'test',root)
            c=dict(PRESETS[2],id='test',name='Synthetic multi-signal',server='http://kiwi.local')
            a=QRSSAssembler(QRSSSession(c,None,m.gallery,'test'),m.gallery)
            freq=a.decoder.frequencies
            rng=np.random.default_rng(75)
            for k in range(1600):
                t=k*.5;db=rng.normal(0,2,len(freq))
                for f,dot in [(1585,4.3),(1465,12.5)]:
                    mark=keying(t,dot);db[abs(freq-(f if mark else f-10))<1]=30
                a.decoder.auto.feed(t,db)
                if a.key is None:
                    a.key=uuid.uuid4().hex;a.start_sample=t;a.started=time.time()
                a.times.append(t);a.columns.append(db)
                if k%400==399:a.flush()
            rows=m.image_snapshot()
            self.assertEqual(len(rows),4)
            self.assertTrue(any(len(r['tracks'])==2 for r in rows))
            ids={r['id'] for row in rows for r in row['tracks']}
            self.assertEqual(len(ids),2)
            for row in rows:
                for r in row['tracks']:
                    self.assertAlmostEqual(r['rf_hz'],c['freq_khz']*1000+r['tone_hz'])
                    if r['tentative_text']:
                        self.assertIn(r['id']+' ',row['tentative_text'])
                        self.assertIn(r['tentative_text'],row['tentative_text'])
            restored=QRSSManager(None,'test',root)
            self.assertEqual({r['id']:r['tracks'] for r in restored.image_snapshot()},{r['id']:r['tracks'] for r in rows})
            restored.stop();m.stop()

    def test_noise_and_steady_carriers_do_not_lock(self):
        rng=np.random.default_rng(84)
        for carriers in ([],[1500],[1480,1490]):
            a=AutoAcquisition(np.arange(1400,1600,.75),MorseTiming,.5)
            for i in range(500):
                db=rng.normal(0,3,len(a.frequencies))
                for f in carriers:db[abs(a.frequencies-f)<1]=25+rng.normal(0,.5)
                a.feed(i*.5,db)
            self.assertNotEqual(a.status['state'],'locked');self.assertFalse(a.events)

    def test_live_audio_spectrum_short_fragment(self):
        # 120-second real PCM capture converted to FFT frames, not pixels.
        # A short fragment has ambiguous polarity before a long word gap.
        fixture=np.load(Path(__file__).parent/'fixtures/qrss_live_spectrum.npz')
        a=AutoAcquisition(fixture['frequencies'],MorseTiming,16384/4/12000)
        for t,db in zip(fixture['times'],fixture['db']):a.feed(t,db.astype(float))
        self.assertEqual(a.status['mode'],'FSKCW')
        self.assertFalse(a.status['reverse'])
        self.assertAlmostEqual(a.status['dot_seconds'],4.3,delta=.3)
        self.assertEqual(''.join(c for t,c in a.events).strip(),'AB')

    def test_saved_spectrum_finds_s52ab_without_frequency_or_timing_hint(self):
        fixture=np.load(Path(__file__).parent/'fixtures/qrss_saved_spectrum.npz')
        a=AutoAcquisition(fixture['frequencies'],MorseTiming,.682)
        for t,db in zip(fixture['times'],fixture['relative_db']):a.feed(t,db)
        self.assertEqual(a.status['mode'],'FSKCW')
        self.assertAlmostEqual(a.status['tone_hz'],1585,delta=1)
        self.assertAlmostEqual(a.status['dot_seconds'],4.3,delta=.3)
        self.assertAlmostEqual(a.status['shift_hz'],10,delta=1)
        self.assertIn('S52AB',''.join(c for t,c in a.events))
        # A long signal loss clears the live lock, without inventing new text.
        old=list(a.events)
        for i in range(200):a.feed(601+i,np.zeros(len(a.frequencies)))
        self.assertEqual(a.status['state'],'searching')
        self.assertEqual(list(a.events),old)
        a.reset();self.assertFalse(a.events);self.assertFalse(a.history)

if __name__=='__main__':unittest.main()
