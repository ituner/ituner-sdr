#!/usr/bin/env python3
"""Serve the Satvisor evaluation build and a read-only shared station location."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.request import urlopen


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] != '/cm5-station.json':
            return super().do_GET()
        try:
            with urlopen('http://127.0.0.1:8090/api/station', timeout=2) as response:
                station = json.load(response)
            position = station.get('position') or {}
            if position.get('lat') is None or position.get('lon') is None:
                raise ValueError('Set receiver location in Settings / Radio information')
            config = station.get('config') or {}
            # Never expose the upstream control token or operator information.
            data = dict(name=config.get('station_name') or 'iTuner receiver',
                        lat=position['lat'], lon=position['lon'],
                        alt=position.get('altitude_msl_m') or 0)
            body = json.dumps(data).encode()
            status = 200
        except (OSError, ValueError, KeyError):
            body = b'{"error":"Shared station location unavailable"}'
            status = 503
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.endswith(('.html', 'sw.js')) or self.path == '/':
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='/opt/ituner-satvisor')
    parser.add_argument('--port', default=8095, type=int)
    args = parser.parse_args()
    ThreadingHTTPServer(('0.0.0.0', args.port), partial(Handler, directory=args.directory)).serve_forever()
