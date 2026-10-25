"""Consume corrected dump978 uplinks using rand-projects/fisb-decode, no MongoDB."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import re
import signal
import socket
import sys
import time
from adsb_weather import WeatherStore


class FISBDecoder:
    def __init__(self, engine):
        sys.path.insert(0, str(engine))
        import fisb.level0.level0Config as config
        config.CALCULATE_RSR = False
        config.SKIP_EMPTY_FRAMES = False
        from fisb.level0.ground_uplink_message import groundUplinkMessage
        from fisb.level0.utilities import convertRawLongitudeLatitude, GEO_24_BITS
        from fisb.level1.level1 import level1
        from fisb.level2 import level2
        self.decode0, self.decode1, self.decode2 = groundUplinkMessage, level1, level2.level2
        self.errors = []
        self.coordinates = lambda lon, lat: convertRawLongitudeLatitude(lon, lat, GEO_24_BITS)
        level2.dumpRecord = lambda reason, frame: self.errors.append(reason[-400:])

    def decode(self, line):
        self.errors.clear()
        # Detailed mode derives optional slot timing from the host clock. It can
        # reject valid receptions near a second boundary; weather needs no such
        # inference. Read the advertised coordinates directly from the header.
        message = self.decode0(line, False, False)
        if message is None: return None, []
        header = bytes.fromhex(line[1:line.index(';')])
        lat = (header[0]<<15)|(header[1]<<7)|(header[2]>>1)
        lon = ((header[2]&1)<<23)|(header[3]<<15)|(header[4]<<7)|(header[5]>>1)
        message['longitude'], message['latitude'] = self.coordinates(lon, lat)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.decode2(self.decode1(json.dumps(message), None), None)
        return message, [json.loads(row) for row in output.getvalue().splitlines() if row.startswith('{')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--live', type=Path)
    args = parser.parse_args()
    store = WeatherStore(args.root,args.live); decoder = FISBDecoder(args.engine)
    running = True
    def finish(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, finish); signal.signal(signal.SIGINT, finish)
    sock = None; buffer = b''; next_save = retry = 0
    try:
        while running:
            now = time.time()
            if now >= next_save:
                store.save(); next_save = now+5
            if sock is None:
                if now<retry: time.sleep(.2); continue
                try:
                    sock = socket.create_connection(('127.0.0.1', args.port), timeout=1)
                    sock.settimeout(1); store.connected = True; buffer = b''
                except OSError: sock = None; retry = now+3; continue
            try:
                chunk = sock.recv(65536)
                if not chunk: raise ConnectionError('UAT stream closed')
                buffer += chunk
                if len(buffer)>262144: raise ValueError('Oversized UAT stream record')
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    if not raw.startswith(b'+'): continue
                    try:
                        line = raw.decode('ascii').strip()
                        if len(line)>4096: raise ValueError('Oversized UAT uplink')
                        message, products = decoder.decode(line)
                        if message is None: continue
                        received = time.time(); match = re.search(r';rssi=([-\d.]+)', line)
                        store.station(message, received, float(match[1]) if match else None)
                        for product in products: store.ingest(product, received, message['station'])
                        if decoder.errors:
                            store.errors += len(decoder.errors); store.last_error = decoder.errors[-1]
                    except Exception as exc:
                        store.errors += 1; store.last_error = str(exc)[-400:]
            except socket.timeout: pass
            except (OSError, ValueError):
                sock.close(); sock = None; store.connected = False; retry = now+3
    finally:
        if sock: sock.close()
        store.connected = False; store.save(force=True)


if __name__ == '__main__': main()
