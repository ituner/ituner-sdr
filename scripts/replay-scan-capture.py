#!/usr/bin/env python3
"""Compare detector changes on identical recorded narrow-view RF packets."""
import argparse
import base64
from collections import defaultdict
import gzip
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from smart_seek import SmartSeek


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',required=True,type=Path)
    parser.add_argument('--baseline-source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--low',type=float,default=5730)
    parser.add_argument('--high',type=float,default=6200)
    parser.add_argument('--bandwidth',type=int,default=30000000)
    parser.add_argument('--zoom-max',type=int,default=14)
    parser.add_argument('--zoom-cap',type=int,default=11)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('frozen_scan_replay',args.baseline_source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    groups = defaultdict(list)
    with gzip.open(args.capture,'rt') as source:
        for line in source:
            packet = json.loads(line)
            groups[packet['round']].append(packet)
    results = []
    for lap,packets in sorted(groups.items()):
        result = dict(round=lap)
        for label,cls in (('baseline',baseline.SmartSeek),('new',SmartSeek)):
            engine = cls()
            engine.OBSERVE_SECONDS = 2
            engine.start(args.low,args.high,'Replay',('capture',),0,refresh=True)
            for packet in packets:
                now = packet['elapsed']
                engine.request(('capture',),now,args.bandwidth,args.zoom_cap)
                engine.feed(base64.b64decode(packet['frame']),args.bandwidth,args.zoom_max,args.zoom_cap,now)
            result[label] = [c.tuning_khz for c in engine.snapshot()['candidates']]
            result[label+'_suppressed'] = sorted(engine.suppressed)
        result['removed'] = [f for f in result['baseline'] if not any(abs(f-g)<.75 for g in result['new'])]
        result['added'] = [f for f in result['new'] if not any(abs(f-g)<.75 for g in result['baseline'])]
        results.append(result)
    report = dict(kind='Identical-packet replay, not independently verified station truth',
                  capture=str(args.capture),results=results,
                  baseline_detections=sum(len(row['baseline']) for row in results),
                  new_detections=sum(len(row['new']) for row in results),
                  removed=sum(len(row['removed']) for row in results),
                  added=sum(len(row['added']) for row in results))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('capture','results')}))


if __name__=='__main__':
    main()
