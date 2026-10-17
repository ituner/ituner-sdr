#!/usr/bin/env python3
"""Keep protocol libraries outside the renderer; parse validated KISS payloads."""
import argparse
import contextlib
import io
import json
import math
from pathlib import Path
import sys


def serializable(value):
    if isinstance(value,dict): return {str(k):serializable(v) for k,v in value.items() if not str(k).startswith('_')}
    if isinstance(value,(list,tuple)): return [serializable(v) for v in value]
    if isinstance(value,bytes):return value.hex()
    if isinstance(value,float) and not math.isfinite(value):return None
    if value is None or isinstance(value,(str,int,float,bool)):return value
    return str(value)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--satellite',required=True);args=parser.parse_args()
    import satellites
    from satellites import telemetry
    import yaml
    definitions=[]
    for path in (Path(satellites.__file__).parent/'satyaml').glob('*.yml'):
        sat=yaml.safe_load(path.read_text())
        if args.satellite not in [sat['name']]+(sat.get('alternative_names') or []):continue
        definitions=list(dict.fromkeys(d['telemetry'] for d in sat.get('data',{}).values() if isinstance(d,dict) and 'telemetry' in d))
        break
    for line in sys.stdin:
        try:
            item=json.loads(line);frame=bytes.fromhex(item['hex']);fields=dict(bytes=len(frame),hex=frame.hex())
            for definition in definitions:
                try:
                    captured=io.StringIO()
                    with contextlib.redirect_stdout(captured):decoded=getattr(telemetry,definition).parse(frame)
                    if decoded is not None:
                        fields['telemetry']=serializable(decoded);fields['protocol']=definition;break
                    if captured.getvalue():fields['telemetry']=captured.getvalue();fields['protocol']=definition;break
                except Exception:continue
            print(json.dumps(dict(id=args.satellite,label=args.satellite,kind='satellite',fields=fields)),flush=True)
        except (ValueError,KeyError,TypeError):continue


if __name__=='__main__':main()
