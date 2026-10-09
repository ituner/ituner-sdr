#!/usr/bin/env python3
"""Build the pinned, offline GGMorse library; never alter hardware drivers."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
p=argparse.ArgumentParser();p.add_argument('--ui',type=Path,default=Path(__file__).resolve().parents[1]/'UI');args=p.parse_args()
source=args.ui/'cw_vendor';target=source/('libituner_cw.dylib' if sys.platform=='darwin' else 'libituner_cw.so')
inputs=[source/'bridge.cpp',source/'ggmorse/src/ggmorse.cpp',source/'ggmorse/src/resampler.cpp']
if target.exists() and target.stat().st_mtime>=max(p.stat().st_mtime for p in source.rglob('*') if p.suffix in ('.cpp','.h')):
 print('CW engine already built:',target);sys.exit(0)
tmp=target.with_name(target.name+'.tmp')
try:
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++14','-O3','-fPIC','-shared','-I'+str(source/'ggmorse/include'),'-I'+str(source/'ggmorse/src'),*map(str,inputs),'-o',str(tmp)],check=True)
 tmp.replace(target)
finally:
 tmp.unlink(missing_ok=True)
print('CW engine built:',target)
