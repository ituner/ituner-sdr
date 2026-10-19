#!/usr/bin/env python3
"""Initialize a local evaluation account and copy the shared receiver location."""
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.request import urlopen

if os.geteuid() != 0:
    raise SystemExit('Run with sudo on CM5.')
with urlopen('http://127.0.0.1:8090/api/station', timeout=3) as response:
    station = json.load(response)
position = station.get('position') or {}
if position.get('lat') is None or position.get('lon') is None:
    raise SystemExit('Set the shared receiver location before setup.')
config = station.get('config') or {}
secret_path = Path('/home/ituner/.config/ituner-sdr/groundstation-evaluation.json')
secret_path.parent.mkdir(parents=True, exist_ok=True)
if secret_path.exists():
    credentials = json.loads(secret_path.read_text())
else:
    credentials = dict(username='ituner', password=secrets.token_urlsafe(18))
    descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as destination:
        json.dump(credentials, destination)
        destination.write('\n')
    os.chown(secret_path, 1000, 1000)
payload = dict(credentials=credentials, timezone=config.get('timezone') or 'Europe/Bucharest',
               location=dict(name='home', lat=position['lat'], lon=position['lon'],
                             alt=round(position.get('altitude_msl_m') or 0),
                             callsign=config.get('callsign') or None,
                             station_type='stationary', horizon_mask=0))
code = 'payload = '+repr(payload)+'''\n
import asyncio
from common import auth
from crud.locations import add_location
from db import AsyncSessionLocal, engine
async def main():
    async with AsyncSessionLocal() as session:
        result = await add_location(session, payload['location'])
        if not result.get('success'): raise RuntimeError(result.get('error'))
    if await auth.is_setup_required(force_refresh=True):
        result = await auth.bootstrap_admin(**payload['credentials'], initial_preferences={'timezone': payload['timezone']})
        if not result.get('success'): raise RuntimeError(result.get('error'))
    await engine.dispose()
    print('Evaluation account ready; receiver location copied from shared settings.')
asyncio.run(main())
'''
subprocess.run(['docker', 'exec', '-i', 'ituner-groundstation', '/app/venv/bin/python', '-'],
               input=code, text=True, check=True)
# Refresh the app's pooled SQLite handles after the one-time bootstrap writer.
subprocess.run(['docker', 'restart', 'ituner-groundstation'], check=True)
print('Login username: '+credentials['username'])
print('Login details: '+str(secret_path))
