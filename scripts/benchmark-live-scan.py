#!/usr/bin/env python3
"""Two concurrent, isolated Kiwi sessions comparing fixed and adaptive sweeps.

Uses two free receiver channels. Never attaches to or retunes listening/Long
Scan. Stores real waterfall rows for replay; live agreement is not ground truth.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
import kiwi_live_display_fb as kiwi
from kiwi_gl_display import SW_BROADCAST_BANDS,next_kiwi_session_timestamp
from long_scan import KiwiScanSession
from smart_seek import SmartSeek
from scan_policy import ScanPolicy,window_count


class AuditSession(KiwiScanSession):
    def __init__(self,server,stamp,stopped,model):
        super().__init__(server,stamp,stopped)
        self.model = model
        self.stats = dict(setup_commands=0,setup_text_bytes=0,commands=0,wf_rows=0,wf_payload_bytes=0)

    def _socket(self,name):
        ws = self.connect(self.server,name,timeout=3,session_timestamp=self.stamp)
        self.sockets.append(ws)
        ws.sock.settimeout(1)
        send = ws.send_text
        def counted(command):
            send(command)
            self.stats['commands'] += 1
            if name=='W/F' and command.startswith(('SET zoom=','SET maxdb=','SET wf_speed=','SET wf_comp=','SET interp=')):
                self.stats['setup_commands'] += 1
                self.stats['setup_text_bytes'] += len(command.encode())
        ws.send_text = counted
        ws.send_text('SET auth t=kiwi p=#')
        # Distinct identities from listening, Long Scan and the other model.
        ws.send_text('SET ident_user='+kiwi.CLIENT_NAME+'-ScanAudit-'+self.model)
        ws.send_text('SET geo=Ituner receiver')
        if self.stopped.is_set():
            raise InterruptedError('Audit stopped')
        return ws

    def set_view(self,center,zoom):
        if self.model!='baseline':
            return super().set_view(center,zoom)
        if self.target==(center,zoom):
            return
        self.target = center,zoom
        if self.wf_authenticated:
            # Exact previous emitter; callers already deduplicated views.
            for command in (f'SET zoom={kiwi.kiwi_zoom_level(zoom)} cf={center:.3f}',
                            'SET maxdb=-10 mindb=-110','SET wf_speed=4',
                            'SET wf_comp=0','SET interp=13'):
                self.wf.send_text(command)

    def _message(self,ws,message):
        if message[:3]==b'W/F':
            self.stats['wf_rows'] += 1
            self.stats['wf_payload_bytes'] += len(message)
        super()._message(ws,message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receiver-state-file',type=Path,
                        default=Path.home()/'.local/state/kiwi-gl-display-receiver.json')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--rounds',type=int,default=6)
    parser.add_argument('--band',help='Broadcast allocation label; defaults to the listening band.')
    parser.add_argument('--baseline-ui',type=Path,default=Path('/opt/ituner-sdr/UI'),
                        help='Freeze the installed SmartSeek implementation for the baseline.')
    parser.add_argument('--timeout',type=float,default=180)
    parser.add_argument('--followups',choices=('full','targeted'),default='full',
                        help='Conservative full fallback is the validated initial live-test policy.')
    parser.add_argument('--fixed-adaptive-zoom',type=int,choices=(6,7,8),
                        help='Isolated resolution experiment: disables policy/fallback for the test channel only.')
    args = parser.parse_args()
    if args.rounds<1:
        parser.error('--rounds must be positive')
    selected = json.loads(args.receiver_state_file.read_text())
    if selected.get('protocol','kiwi')!='kiwi':
        parser.error('The selected receiver must be a Kiwi')
    receiver,frequency = selected['server'],float(selected['freq_khz'])
    band = min(SW_BROADCAST_BANDS,key=lambda b:0 if b[0]<=frequency<=b[1]
               else min(abs(frequency-b[0]),abs(frequency-b[1])))
    if args.band:
        band = next((b for b in SW_BROADCAST_BANDS if b[2].replace(' ','').lower()==args.band.replace(' ','').lower()),None)
        if band is None:
            parser.error('Unknown broadcast band')
    baseline_path = args.baseline_ui/'smart_seek.py'
    if baseline_path.exists():
        spec = importlib.util.spec_from_file_location('_scan_audit_baseline',baseline_path)
        baseline_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline_module
        spec.loader.exec_module(baseline_module)
        BaselineEngine = baseline_module.SmartSeek
    else:
        BaselineEngine = SmartSeek
        baseline_path = Path(__file__).resolve().parents[1]/'UI/smart_seek.py'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    stopped = threading.Event()
    ready = [threading.Event() for _ in range(2)]
    starts = [threading.Event() for _ in range(args.rounds)]
    done = [[threading.Event() for _ in range(2)] for _ in range(args.rounds)]
    lock = threading.Lock()
    report = dict(receiver=receiver,band=list(band),listening_frequency_khz=frequency,
                  followups=args.followups,started_at=time.time(),status='connecting',
                  fixed_adaptive_zoom=args.fixed_adaptive_zoom,
                  rounds=args.rounds,baseline=[],adaptive=[],errors=[],
                  source_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in
                    [('baseline_smart_seek',baseline_path),('adaptive_smart_seek',Path(__file__).resolve().parents[1]/'UI/smart_seek.py'),
                     ('adaptive_policy',Path(__file__).resolve().parents[1]/'UI/scan_policy.py')]},
                  limitations=['Two independent receiver channels share the same antenna and live time.',
                               'Detector agreement is not verified station truth; fading can change between views.',
                               'Measured times include transport, observation and local processing.'])
    def save():
        pending = args.output.with_suffix('.next')
        pending.write_text(json.dumps(report,indent=2)+'\n')
        pending.replace(args.output)
    save()
    sources = args.output.with_name(args.output.stem+'-sources')
    sources.mkdir(exist_ok=True)
    for label,path in [('baseline_smart_seek',baseline_path),
                       ('adaptive_smart_seek',Path(__file__).resolve().parents[1]/'UI/smart_seek.py'),
                       ('adaptive_policy',Path(__file__).resolve().parents[1]/'UI/scan_policy.py')]:
        shutil.copyfile(path,sources/(label+'.py'))
    def run(index,model):
        session = AuditSession(receiver,next_kiwi_session_timestamp(),stopped,model)
        policy = ScanPolicy() if model=='adaptive' and args.fixed_adaptive_zoom is None else None
        if policy is not None and args.followups=='full':
            policy.refinement_windows = lambda *a,**kw:[]
        trace_path = args.output.with_name(args.output.stem+'-'+model+'-rows.jsonl.gz')
        try:
            with gzip.open(trace_path,'wt') as trace:
                session.open()
                while not session.wf_authenticated and not stopped.is_set():
                    session.read(.05)
                ready[index].set()
                for lap in range(args.rounds):
                    while not starts[lap].is_set() and not stopped.is_set():
                        session.read(.05)  # drain idle rows and retain keepalives
                    if stopped.is_set():
                        break
                    started = time.monotonic()
                    previous = dict(session.stats)
                    engine = SmartSeek(policy) if model=='adaptive' else BaselineEngine()
                    engine.OBSERVE_SECONDS = 2
                    if model=='adaptive' and args.fixed_adaptive_zoom is not None:
                        engine.TARGET_ZOOM = args.fixed_adaptive_zoom
                    engine.start(*band,(receiver,),started,refresh=True)
                    target,views,first_hit = None,[],None
                    response_times,requested_at,waiting_for_row = [],started,False
                    while engine.active and not stopped.is_set():
                        now = time.monotonic()
                        request = engine.request((receiver,),now,session.bandwidth,session.zoom_cap)
                        if request is None:
                            break
                        if request!=target:
                            session.set_view(*request)
                            target = request
                            views.append(list(request))
                            requested_at,waiting_for_row = time.monotonic(),True
                        frame = session.read(.05)
                        if frame is not None:
                            now = time.monotonic()
                            before = engine.last_sequence
                            engine.feed(frame,session.bandwidth,session.zoom_max,session.zoom_cap,now)
                            if engine.last_sequence!=before and waiting_for_row:
                                response_times.append(now-requested_at)
                                waiting_for_row = False
                            trace.write(json.dumps(dict(round=lap+1,elapsed=now-started,
                                requested=list(target),frame=base64.b64encode(frame).decode()))+'\n')
                            if engine.candidates and first_hit is None:
                                first_hit = now-started
                    result = dict(round=lap+1,seconds=time.monotonic()-started,first_hit_seconds=first_hit,
                        complete=not stopped.is_set() and engine.index>=len(engine.windows) and engine.skipped==0,
                        skipped=engine.skipped,views=views,response_seconds=response_times,
                        frequencies_khz=[c.tuning_khz for c in engine.snapshot()['candidates']],
                        strengths=[c.prominence for c in engine.snapshot()['candidates']],
                        traffic={key:session.stats[key]-previous[key] for key in previous})
                    if policy is not None and engine.policy_key in policy.profiles:
                        profile = policy.profiles[engine.policy_key]
                        result['policy'] = dict(next_zoom=policy.plan(engine.policy_key,session.bandwidth,
                            session.zoom_cap,band[0],band[1]),cooldown=profile['cooldown'],
                            known_nonqualifying_lines=sum(hits>=2 for hits in profile.get('lines',{}).values()),
                            pending_lines=sum(hits<2 for hits in profile.get('lines',{}).values()),
                            watched_frequencies=len(profile.get('watch',{})),
                            narrow_views=window_count(session.bandwidth,min(8,session.zoom_cap),band[0],band[1]))
                    trace.flush()
                    with lock:
                        report[model].append(result)
                        report['status']='measuring'
                        save()
                    print(json.dumps(dict(model=model,round=lap+1,seconds=round(result['seconds'],2),
                        detections=len(engine.candidates),complete=result['complete'])),flush=True)
                    done[lap][index].set()
                with lock:
                    report[model+'_traffic_total'] = dict(session.stats)
                    report[model+'_capture'] = str(trace_path)
                    save()
        except Exception as exc:
            with lock:
                report['errors'].append(dict(model=model,error=str(exc)))
                save()
            stopped.set()
        finally:
            session.close()
            ready[index].set()
    threads = [threading.Thread(target=run,args=(i,model),daemon=True)
               for i,model in enumerate(('baseline','adaptive'))]
    deadline = time.monotonic()+args.timeout
    for thread in threads:
        thread.start()
    try:
        for lap in range(args.rounds):
            while not all(event.is_set() for event in ready if lap==0) or (lap and not all(event.is_set() for event in done[lap-1])):
                if stopped.wait(.05) or time.monotonic()>deadline:
                    stopped.set()
                    break
            if stopped.is_set():
                break
            starts[lap].set()
            while not all(event.is_set() for event in done[lap]):
                if stopped.wait(.05) or time.monotonic()>deadline:
                    stopped.set()
                    break
            if stopped.is_set():
                break
    finally:
        stopped.set()
        for thread in threads:
            thread.join(5)
        with lock:
            report['finished_at']=time.time()
            report['status']='complete' if not report['errors'] and all(
                len(report[m])==args.rounds and all(p['complete'] for p in report[m])
                for m in ('baseline','adaptive')) else 'incomplete'
            save()
    print(json.dumps(dict(status=report['status'],errors=report['errors'])),flush=True)
    if report['status']!='complete':
        raise SystemExit(1)


if __name__=='__main__':
    main()
