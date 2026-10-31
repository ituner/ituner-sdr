#!/usr/bin/env python3
"""Compare scan-grid centering with a simultaneous finer RF reference.

The finer view is a relative reference, not an absolute frequency standard.
Two spare Kiwi channels are isolated from listening and Long Scan.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
spec = importlib.util.spec_from_file_location('live_scan_benchmark',Path(__file__).with_name('benchmark-live-scan.py'))
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
from am_carrier import carrier_peak,rf_view_center_hz
from scan_policy import coverage_windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--seconds',type=float,default=5)
    parser.add_argument('--receiver-state-file',type=Path,default=Path.home()/'.local/state/kiwi-gl-display-receiver.json')
    args = parser.parse_args()
    selected = json.loads(args.receiver_state_file.read_text())
    receiver = selected['server']
    stopped = threading.Event()
    sessions = [live.AuditSession(receiver,live.next_kiwi_session_timestamp(),stopped,model)
                for model in ('baseline','adaptive')]
    report = dict(receiver=receiver,reference='simultaneous narrower RF peak; not an absolute standard',
                  listening_frequency_khz=selected['freq_khz'],measurements=[],errors=[])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        pending = args.output.with_suffix('.next')
        pending.write_text(json.dumps(report,indent=2)+'\n')
        pending.replace(args.output)
    try:
        for session in sessions:
            session.open()
        for lap in range(args.rounds):
            for nominal in (5830.,6015.,6120.):
                bandwidth = sessions[0].bandwidth
                grid = coverage_windows(bandwidth,8,5730,6200)
                centers = [min(grid,key=lambda center:abs(center-nominal)),nominal]
                zooms = [8,min(11,sessions[1].zoom_cap)]
                for session,center,zoom in zip(sessions,centers,zooms):
                    session.set_view(center,zoom)
                rows = [[],[]]
                first = [None,None]
                geometry = [None,None]
                started = time.monotonic()
                while time.monotonic()-started<args.seconds+8:
                    for index,session in enumerate(sessions):
                        frame = session.read(.02)
                        if frame is None or len(frame)!=1040:
                            continue
                        start,flags,_sequence = struct.unpack_from('<III',frame,4)
                        zoom = flags&65535
                        bin_hz = session.bandwidth/(1024*2**zoom)
                        first_hz = start*session.bandwidth/(1024*2**session.zoom_max)
                        expected = rf_view_center_hz(centers[index]*1000,session.bandwidth,zooms[index])
                        if flags>>16&3 or zoom!=zooms[index] or abs(first_hz+512*bin_hz-expected)>max(3,2*bin_hz):
                            continue
                        now = time.monotonic()
                        first[index] = first[index] or now
                        rows[index].append((now,frame[16:]))
                        geometry[index] = first_hz,bin_hz
                    if all(first) and time.monotonic()-max(first)>=args.seconds:
                        break
                common = max((value for value in first if value is not None),default=started)
                estimates = []
                counts = []
                for index in range(2):
                    measured = [row for stamp,row in rows[index] if stamp>=common]
                    counts.append(len(measured))
                    estimates.append(carrier_peak(measured,*geometry[index],nominal*1000,500)/1000
                        if geometry[index] is not None and len(measured)>=5
                        and carrier_peak(measured,*geometry[index],nominal*1000,500) is not None else None)
                result = dict(round=lap+1,target_khz=nominal,scan_khz=estimates[0],reference_khz=estimates[1],
                              rows=counts,bin_hz=[None if g is None else g[1] for g in geometry],
                              difference_hz=None if None in estimates else (estimates[0]-estimates[1])*1000)
                report['measurements'].append(result)
                save()
                print(json.dumps(result),flush=True)
    except Exception as exc:
        report['errors'].append(str(exc))
        save()
        raise
    finally:
        stopped.set()
        for session in sessions:
            session.close()
        report['finished_at'] = time.time()
        save()


if __name__=='__main__':
    main()
