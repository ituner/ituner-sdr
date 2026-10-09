#!/usr/bin/env python3
"""Repeatable file-based modem comparison. Not a live SDR backend.

FldigiBatch uses the upstream benchmark executable (documented batch-mode compatibility fixes) in a separate
process/config directory. Its mode ID and settings can be reused for other
modems; CW is the first comparison. No rig or sound-device connections.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import wave
import xml.etree.ElementTree as ET

import numpy as np
from scipy.signal import resample_poly

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'UI'))
RATE=8000
ALPHABET=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',[
 '.-','-...','-.-.','-..','.','..-.','--.','....','..','.---','-.-','.-..','--',
 '-.','---','.--.','--.-','.-.','...','-','..-','...-','.--','-..-','-.--','--..',
 '-----','.----','..---','...--','....-','.....','-....','--...','---..','----.']))


def normalize(text):
    return re.sub(r'\s+',' ',text.upper()).strip()


def errors(expected,actual):
    """Levenshtein character error rate including word spaces; no clipping."""
    expected,actual=normalize(expected),normalize(actual)
    previous=list(range(len(actual)+1))
    for i,a in enumerate(expected,1):
        row=[i]
        for j,b in enumerate(actual,1):
            row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=row
    return dict(reference_characters=len(expected),edit_distance=previous[-1],
                cer=previous[-1]/len(expected) if expected else None,
                extra_characters=len(actual) if not expected else None)


def read_wav(path):
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,RATE):
            raise ValueError('Comparison requires mono 16-bit 8000 Hz WAV')
        return np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(float)/32768


def write_wav(path,audio):
    with wave.open(str(path),'wb') as wav:
        wav.setparams((1,2,RATE,0,'NONE','not compressed'))
        wav.writeframes((np.clip(audio,-1,1)*32767).astype('<i2').tobytes())


class FldigiBatch:
    """Generic upstream file decoder, configurable by modem ID and XML options."""
    def __init__(self,binary):
        self.binary=str(Path(binary).resolve())
        with tempfile.TemporaryDirectory(prefix='ituner-fldigi-version-') as work:
            result=subprocess.run([self.binary,'--config-dir',work,'--version'],
                env=dict(os.environ,HOME=work),capture_output=True,text=True,timeout=15)
        match=re.search(r'fldigi\s+(\d+\.\d+\.\d+)',result.stdout+' '+result.stderr)
        self.version=match.group(1) if match else 'unknown'
        if result.returncode or self.version!='4.2.13':
            raise ValueError('This comparison is pinned to fldigi 4.2.13; check --fldigi binary')

    def decode(self,wav,mode,tone,settings=None):
        read_wav(wav)  # Upstream benchmark does not enforce file sample rate.
        with tempfile.TemporaryDirectory(prefix='ituner-fldigi-') as work:
            work=Path(work);config=work/'config';config.mkdir()
            root=ET.Element('FLDIGI_DEFS')
            for key,value in (settings or {}).items():
                ET.SubElement(root,key).text=str(value)
            ET.ElementTree(root).write(config/'fldigi_def.xml',encoding='utf-8',xml_declaration=True)
            output=work/'decoded.txt'
            command=['xvfb-run','-a',self.binary,'--config-dir',str(config),
                     '--benchmark-modem',str(mode),'--benchmark-frequency',str(tone),
                     '--benchmark-afc','0','--benchmark-squelch','0',
                     '--benchmark-input',str(Path(wav).resolve()),'--benchmark-output',str(output)]
            # Isolate all incidental upstream state as well as its main config.
            env=dict(os.environ,HOME=str(work))
            started=time.perf_counter()
            process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                     text=True,start_new_session=True)
            try:
                stdout,stderr=process.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.communicate()
                raise RuntimeError('fldigi file decoding exceeded 90 seconds')
            elapsed=time.perf_counter()-started
            if process.returncode or not output.exists():
                raise RuntimeError(f'fldigi failed ({process.returncode}): {stderr[-2000:]}')
            return output.read_text(errors='replace'),elapsed


def ggmorse(wav,tone):
    from cw_decoder import MorseEngine
    # Same quantized recording, resampled to the existing wrapper's 12 kHz.
    audio=resample_poly(read_wav(wav),3,2)
    pcm=(np.clip(audio,-1,1)*32767).astype('<i2').tobytes()
    engine=MorseEngine(tone,0);parts=[];started=time.perf_counter()
    try:
        for i in range(0,len(pcm),1024):parts.append(engine.feed(pcm[i:i+1024]))
    finally:engine.close()
    return ''.join(parts),time.perf_counter()-started


def synth(text,wpm=20,tone=700,jitter=0):
    rng=np.random.default_rng(381);unit=RATE*1.2/wpm;parts=[np.zeros(RATE)]
    def duration(units):return max(1,round(unit*units*(1+rng.uniform(-jitter,jitter))))
    for word in text.split():
        for character in word:
            for symbol in ALPHABET[character]:
                n=duration(3 if symbol=='-' else 1)
                x=.25*np.sin(np.arange(n)*2*np.pi*tone/RATE)
                ramp=min(40,n//4);x[:ramp]*=np.linspace(0,1,ramp);x[-ramp:]*=np.linspace(1,0,ramp)
                parts.extend([x,np.zeros(duration(1))])
            parts.append(np.zeros(duration(2)))
        parts.append(np.zeros(duration(4)))
    parts.append(np.zeros(8*RATE))
    return np.concatenate(parts)


def corpus(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    message='VVV VVV CQ CQ DE KN6KEZ KN6KEZ TEST 123 73'
    entries=[]
    def add(name,audio,expected=message,tone=700):
        path=directory/(name+'.wav');write_wav(path,audio)
        entries.append(dict(name=name,wav=path.name,tone_hz=tone,expected=expected,
                            provenance='deterministic synthetic fixture',sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for speed in (8,20,35,50):add(f'clean-{speed}wpm',synth(message,speed))
    audio=synth(message)
    t=np.arange(len(audio))/RATE
    add('fading-noisy-20wpm',audio*(.55+.45*np.sin(t*.7))+np.random.default_rng(4).normal(0,.04,len(audio)))
    add('uneven-timing-20wpm',synth(message,jitter=.2))
    other='VVV VVV CQ CQ DE YO3ABC YO3ABC TEST 456 73'
    a=synth(message,20,600);b=synth(other,28,950)
    mixed=np.zeros(max(len(a),len(b)));mixed[:len(a)]+=a;mixed[:len(b)]+=.7*b
    add('two-stations-600hz',mixed,tone=600)
    add('two-stations-950hz',mixed,expected=other,tone=950)
    add('noise-only',np.random.default_rng(52).normal(0,.04,30*RATE),expected='')
    add('steady-carrier',.25*np.sin(np.arange(30*RATE)*2*np.pi*700/RATE),expected='')
    path=directory/'manifest.json';path.write_text(json.dumps(entries,indent=2)+'\n');return path


def compare(manifest,binary,output):
    manifest=Path(manifest).resolve();backend=FldigiBatch(binary);rows=[]
    # Same broad tracking range in every case: no true speed supplied to either
    # decoder. Two fldigi profiles compare its ordinary and SOM character logic.
    settings=dict(CWSPEED=30,CWTRACK=1,CWRANGE=25,CWLOWERLIMIT=5,CWUPPERLIMIT=55,CWBANDWIDTH=150)
    for entry in json.loads(manifest.read_text()):
        wav=manifest.parent/entry['wav'];read_wav(wav)
        sha=hashlib.sha256(wav.read_bytes()).hexdigest()
        if entry.get('sha256') and sha!=entry['sha256']:raise ValueError(f'Changed fixture: {wav}')
        for engine in ('ggmorse','fldigi','fldigi-som'):
            if engine=='ggmorse':text,elapsed=ggmorse(wav,entry['tone_hz'])
            else:text,elapsed=backend.decode(wav,1,entry['tone_hz'],settings|{'CWUSESOMDECODING':int(engine=='fldigi-som')})
            row=dict(case=entry['name'],engine=engine,text=text,elapsed_seconds=round(elapsed,4),
                     sha256=sha,reference=entry.get('expected'),provenance=entry.get('provenance','unspecified'))
            if 'expected' in entry:row.update(errors(entry['expected'],text))
            rows.append(row)
            print(entry['name'],engine,normalize(text),flush=True)
    report=dict(fldigi_binary=str(Path(binary).resolve()),
                fldigi_binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),fldigi_version=backend.version,
                ggmorse_revision='7b4822a8cfdbb1addfe497f3ae8186f142a4ee79',
                settings=settings,
                fldigi_batch_fixes=['std::ofstream namespace','optional viewer null guard','synchronize benchmark carrier'],
                notes=[
                    'Known tone supplied to both engines; tests decoding, not automatic signal acquisition.',
                    'CW mode ID 1 and 8000 Hz input verified against pinned fldigi 4.2.13 source.',
                    'GGMorse uses automatic speed; fldigi tracks 5–55 WPM from a fixed 30 WPM initial setting.',
                    'Squelch is off for fldigi and GGMorse raw output is ungated: noise cases measure raw false text.',
                    'Fldigi elapsed time includes process/Xvfb startup; GGMorse timing is decode-only. Do not compare these as CPU benchmarks.',
                    'Synthetic scores do not establish off-air performance. Recordings without reference text are not scored.'
                ],results=rows)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n')
    md=['# CW engine comparison','',*['- '+n for n in report['notes']],'',
        '| Case | GGMorse CER | fldigi CER | fldigi SOM CER |','|---|---:|---:|---:|']
    for i in range(0,len(rows),3):
        values=[]
        for row in rows[i:i+3]:
            values.append(f"{row['cer']:.1%}" if row.get('cer') is not None else
                          f"{row['extra_characters']} extra chars" if row.get('extra_characters') is not None else 'unscored')
        md.append('| '+rows[i]['case']+' | '+' | '.join(values)+' |')
    output.with_suffix('.md').write_text('\n'.join(md)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate',type=Path,help='Write deterministic WAV fixtures and manifest')
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--fldigi',type=Path)
    parser.add_argument('--output',type=Path,default=Path('cw-comparison.json'))
    args=parser.parse_args()
    if args.generate:args.manifest=corpus(args.generate)
    if args.fldigi and args.manifest:compare(args.manifest,args.fldigi,args.output)
    elif not args.generate:parser.error('Use --generate DIRECTORY or --manifest FILE --fldigi BINARY')
