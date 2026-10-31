#!/usr/bin/env python3
"""Reproducible synthetic RF benchmark; no receiver connections or audio tuning.

The power-spectrum model keeps carrier and sideband frequencies in hertz as
resolution changes. Noise power scales with bin width. This is a stress model,
not a calibrated Kiwi hardware simulator or proof of live detection accuracy.
Requires numpy only for benchmark generation; runtime scanning does not.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'UI'))
import kiwi_live_display_fb as kiwi
from smart_seek import SmartSeek, detect_stations
from scan_policy import ScanPolicy

_BASELINES = {}


def baseline_engine(source):
    if source is None:
        return SmartSeek
    if source not in _BASELINES:
        spec = importlib.util.spec_from_file_location('_benchmark_frozen_baseline',source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _BASELINES[source] = module.SmartSeek
    return _BASELINES[source]


class RecordingSocket:
    def __init__(self):
        self.commands = []

    def send_text(self, command):
        self.commands.append(command)


def command_benchmark():
    ws = RecordingSocket()
    legacy = []
    for i in range(100):
        center, zoom = 6000+100*(i % 20), 8
        legacy += [f'SET zoom={zoom} cf={center:.3f}', 'SET maxdb=-10 mindb=-110',
                   'SET wf_speed=4', 'SET wf_comp=0', 'SET interp=13']
        for _ in range(3):  # repeated polls must be free, too
            kiwi.send_wf_setup(ws, center, zoom, 4)
    def metrics(commands):
        return dict(commands=len(commands), text_bytes=sum(len(c.encode()) for c in commands),
                    websocket_bytes=sum(len(c.encode())+6 for c in commands))
    # Client text messages here are <126 bytes: 2-byte header + 4-byte mask.
    return dict(legacy=metrics(legacy), optimized=metrics(ws.commands),
                distinct_view_changes=100, repeated_polls=300,
                assumptions='Uncompressed masked WebSocket framing; excludes TCP/TLS and keepalives.')


def rows(center, zoom, stations, seed, count=26, interference=False):
    """Station tuples are (frequency_kHz, carrier_dB, modulated, fading)."""
    span = 30000000/2**zoom
    bin_hz = span/1024
    first = center*1000-span/2
    hz = first+np.arange(1024)*bin_hz
    rng = np.random.default_rng(seed)
    # Average of independent periodograms: residual variation remains visible.
    power = rng.gamma(4, 1/4, size=(count, 1024))*(bin_hz/(30000000/2**8/1024))
    for freq, db, modulated, fading in stations:
        offset = hz-freq*1000
        carrier = 10**(db/10)*np.exp(-.5*(offset/(bin_hz*.55))**2)
        phase = freq
        if modulated is None:
            owners = [f for f,_db,m,_fade in stations if m is True and abs(f-freq)<=8]
            if not owners:
                continue
            phase = min(owners,key=lambda f:abs(f-freq))
        envelope = .15+.85*(.5+.5*np.sin(np.arange(count)*.7+phase))
        fade = (.15+.85*(.5+.5*np.sin(np.arange(count)*.12+freq))) if fading else np.ones(count)
        power += fade[:, None]*carrier*(envelope[:,None] if modulated is None else 1)
        if modulated:
            # AM sideband density, about 30% total carrier power over 4.4 kHz.
            side = (np.abs(offset) >= 300) & (np.abs(offset) <= 2400)
            density = 10**(db/10)*.3*bin_hz/4400
            power += fade[:, None]*envelope[:, None]*side*density
            if any(m is None and abs(f-freq)<=8 for f,_db,m,_fade in stations):
                outer = (np.abs(offset)>2400)&(np.abs(offset)<=8000)
                power += fade[:,None]*envelope[:,None]*outer*density*.1
    if interference:
        power[5] *= 32  # broad impulse / receiver level disturbance
        power[11,rng.integers(0,1024)] += 100000  # single-row narrow spike
    values = np.clip(np.rint(110+10*np.log10(np.maximum(power, 1e-8))), 0, 255).astype(np.uint8)
    return [row.tobytes() for row in values], first, bin_hz


SCENES = {
    'sparse strong': [(7220, 38, True, False), (7400, 36, True, False)],
    'crowded 5 kHz': [(freq, 34+(i % 3)*2, True, False) for i, freq in enumerate(range(7260, 7301, 5))],
    'weak and fading': [(7220, 25, True, True), (7310, 29, True, True), (7400, 32, True, False)],
    'edges': [(7200, 34, True, False), (7205, 38, True, False), (7445, 36, True, False), (7450, 32, True, False)],
    'bare carriers': [(7220, 40, False, False), (7350, 33, False, False)],
    'noise only': [],
    'mixed strengths': [(7220, 24, True, True), (7310, 38, True, False), (7400, 22, True, False)],
    'strong at high edge': [(7430,38,True,False)],
    'mirrored music images': [(7300,44,True,False),(7294,30,None,False),(7306,30,None,False)],
}


def sweep(scene, zoom, seed):
    engine = SmartSeek()
    engine.TARGET_ZOOM = zoom
    engine.start(7200, 7450, '41 m', ('synthetic',), 0, refresh=True)
    found, first_hit = [], None
    for index, center in enumerate(engine.windows):
        spectra, first, bin_hz = rows(center, zoom, scene, seed+index)
        detections = detect_stations(spectra, first, bin_hz, 7200, 7450)
        if detections and first_hit is None:
            first_hit = index+1
        for candidate in detections:
            if all(abs(candidate.frequency_khz-old) >= 2 for old in found):
                found.append(candidate.frequency_khz)
    expected = [freq for freq, _db, modulated, _fading in scene if modulated]
    hit = sum(any(abs(freq-result) < .7 for result in found) for freq in expected)
    false = sum(not any(abs(freq-result) < .7 for freq in expected) for result in found)
    return dict(windows=len(engine.windows), confirmed=hit, expected=len(expected),
                false_detections=false, first_hit_window=first_hit, found=sorted(found))


def feedback_trial(scene, seed, latency, optimized, passes=5, extended=False, baseline_source=None):
    """Drive the actual engine, including its response budgets and policy retry."""
    policy = ScanPolicy() if optimized else None
    ws = RecordingSocket()
    now, sequence, last_target = 0., 0, None
    trials = []
    for pass_index in range(passes):
        engine = SmartSeek(policy) if optimized else baseline_engine(baseline_source)()
        engine.OBSERVE_SECONDS = 2
        engine.start(7200,7450,'41 m',('synthetic',),now,refresh=True)
        start_time, initial_commands = now,len(ws.commands)
        views, first_hit, zooms = 0,None,[]
        # After two passes introduce a new weak station; narrow audits must
        # discover it rather than permanently trusting the first reference.
        current = list(scene)
        if scene and pass_index >= 2:
            current.append((7360,25,True,True))
        if extended:
            current = [(freq, db+(3*math.sin(pass_index*.81+freq+seed) if fading else 0),modulated,fading)
                       for freq,db,modulated,fading in current]
            if 5 <= pass_index < 7 and scene:
                current = [station for station in current if station[0] != scene[0][0]]
            if pass_index >= 7:
                current = [station for station in current if station[0] != 7360]
            if 8 <= pass_index < 10:
                current.append((7390,36,False,False))
            if pass_index >= 10 and not any(abs(station[0]-7290)<5 for station in current):
                current.append((7290,27,True,True))
        for _ in range(2000):
            target = engine.request(('synthetic',),now)
            if target is None:
                break
            if target != last_target:
                center,zoom = target
                zooms.append(zoom)
                views += 1
                if optimized:
                    kiwi.send_wf_setup(ws,center,zoom,4)
                else:
                    ws.commands += [f'SET zoom={zoom} cf={center:.3f}', 'SET maxdb=-10 mindb=-110',
                                    'SET wf_speed=4', 'SET wf_comp=0', 'SET interp=13']
                spectra, first, bin_hz = rows(center,zoom,current,
                    seed+pass_index*100000+round(center*1000)+zoom,count=40,interference=extended)
                row_index = 0
                now += latency
                last_target = target
            else:
                now += .08
            sequence += 1
            start = round(first*1024*2**14/30000000)
            frame = b'W/F\0'+struct.pack('<III',start,zoom,sequence)+spectra[row_index % len(spectra)]
            row_index += 1
            engine.feed(frame,30000000,14,14,now)
            if engine.candidates and first_hit is None:
                first_hit = round(now-start_time,3)
            if not engine.active:
                break
        else:
            raise RuntimeError('benchmark engine did not finish')
        expected = [freq for freq,_db,modulated,_fading in current if modulated]
        found = [c.tuning_khz for c in engine.snapshot()['candidates']]
        trials.append(dict(pass_number=pass_index+1,views=views,zooms=zooms,
            simulated_seconds=round(now-start_time,3),first_hit_seconds=first_hit,
            commands=len(ws.commands)-initial_commands,
            complete=engine.index>=len(engine.windows) and not engine.skipped,
            confirmed=sum(any(abs(freq-result)<.7 for result in found) for freq in expected),
            detected_truth=[freq for freq in expected if any(abs(freq-result)<.7 for result in found)],
            frequency_error_hz=[min(abs(freq-result) for freq in expected)*1000 for result in found
                                if any(abs(freq-result)<.7 for freq in expected)],
            expected=len(expected),false_detections=sum(not any(abs(freq-result)<.7 for freq in expected) for result in found),
            found=found))
        # A continued stream can satisfy the next request without a view
        # command; its new observation still starts after one row interval.
        last_target = None
        now += .08
    return trials


def feedback_job(job):
    name, scene, latency, seed, policy, passes, extended, baseline_source = job
    return dict(scene=name,latency_seconds=latency,seed=seed,policy=policy,
                trials=feedback_trial(scene,seed*1000,latency,policy=='guarded',passes,extended,baseline_source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--seed-offset', type=int, default=0,help='Use unseen noise/fading seeds for an independent audit.')
    parser.add_argument('--passes', type=int, default=5)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--extended', action='store_true',help='Add on/off broadcasts, long fading, impulses, and new spurs.')
    parser.add_argument('--baseline-source',type=Path,help='Installed baseline smart_seek.py; otherwise isolates policy with a shared detector.')
    args = parser.parse_args()
    if min(args.seeds,args.passes,args.workers) < 1:
        parser.error('--seeds, --passes, and --workers must be positive')
    started = time.monotonic()
    source = Path(__file__).resolve().parents[1]/'UI'
    source_hashes = {name:hashlib.sha256((source/name).read_bytes()).hexdigest()
        for name in ('scan_policy.py','smart_seek.py','kiwi_live_display_fb.py','smart_seek_catalogue.py','long_scan.py')}
    results = []
    for name, scene in SCENES.items():
        for zoom in (8, 7, 6, 5):
            trials = [sweep(scene, zoom, seed*100) for seed in range(args.seed_offset,args.seed_offset+args.seeds)]
            results.append(dict(scene=name, zoom=zoom, span_khz=30000/2**zoom,
                                trials=trials,
                                confirmed=sum(t['confirmed'] for t in trials),
                                expected=sum(t['expected'] for t in trials),
                                false_detections=sum(t['false_detections'] for t in trials)))
    jobs = [(name,scene,latency,seed,policy,args.passes,args.extended,
             str(args.baseline_source.resolve()) if args.baseline_source else None)
                    for name,scene in SCENES.items() for latency in (.05,.25,.7)
                    for seed in range(args.seed_offset,args.seed_offset+args.seeds) for policy in ('baseline','guarded')]
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            feedback = list(pool.map(feedback_job,jobs))
    else:
        feedback = [feedback_job(job) for job in jobs]
    lost, false_delta,unique_lost = 0,0,0
    for baseline,guarded in zip(feedback[::2],feedback[1::2]):
        unique_lost += len(set(f for t in baseline['trials'] for f in t['detected_truth'])
                           -set(f for t in guarded['trials'] for f in t['detected_truth']))
        for before,after in zip(baseline['trials'],guarded['trials']):
            lost += len(set(before['detected_truth'])-set(after['detected_truth']))
            false_delta += after['false_detections']-before['false_detections']
    report = dict(kind='synthetic RF power-spectrum stress benchmark', seeds=args.seeds,
                  seed_offset=args.seed_offset,
                  passes=args.passes,extended=args.extended,
                  commands=command_benchmark(), results=results,
                  feedback=feedback,
                  baseline_source=str(args.baseline_source) if args.baseline_source else None,
                  checks=dict(lost_baseline_detections=lost, extra_false_detections=max(0,false_delta),
                    unique_baseline_stations_lost=unique_lost,
                    false_detection_change=false_delta,
                    all_passes_complete=all(t['complete'] for run in feedback for t in run['trials'])),
                  source_sha256=source_hashes,
                  elapsed_seconds=round(time.monotonic()-started, 3),
                  limitations=['No calibrated receiver model or live RF ground truth.',
                               'Trials vary noise; propagation and server settling need live observation.',
                               'Wider windows never bypass modulation checks.'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    for result in results:
        print(f"{result['scene']:18} zoom {result['zoom']} {result['confirmed']}/{result['expected']} false={result['false_detections']}")
    print(json.dumps(report['commands']))
    print(json.dumps(report['checks']))


if __name__ == '__main__':
    main()
