#!/usr/bin/env python3
"""Reversible, server-side automatic access for the pinned CM5 evaluation."""
import asyncio
from http.cookies import SimpleCookie
import json
from pathlib import Path
import time


class AutomaticAccess:
    """Supply a private upstream session to HTTP and Socket.IO, never to JS."""

    def __init__(self, app, login):
        self.app = app
        self.login = login
        self.token = None
        self.expires = 0
        self.lock = asyncio.Lock()

    async def session_token(self):
        async with self.lock:
            if not self.token or time.monotonic() >= self.expires:
                result = await self.login()
                if not result.get('success') or not result.get('token'):
                    raise RuntimeError('Automatic access failed; check the local account credentials.')
                self.token = result['token']
                # Upstream keep_session_active sessions expire after 365 days.
                self.expires = time.monotonic() + 360 * 86400
            return self.token

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        token = await self.session_token()
        cookie = SimpleCookie()
        headers = []
        for name, value in scope.get('headers', []):
            if name.lower() == b'cookie':
                cookie.load(value.decode('latin1'))
            elif name.lower() != b'authorization':
                headers.append((name, value))
        cookie['gs_session'] = token
        headers.append((b'cookie', cookie.output(header='', sep=';').strip().encode('latin1')))
        scope = dict(scope, headers=headers)
        if scope.get('path') == '/api/auth/logout':
            # Logout revokes the injected session; the next request creates another.
            # Returning to actual login mode requires the host toggle + restart.
            self.token = None
        await self.app(scope, receive, send)


def main():
    import app as upstream
    config = Path('/app/backend/data/configs/ituner_access.json')
    settings = json.loads(config.read_text()) if config.exists() else {}
    # Missing/invalid flags retain normal upstream login. No upstream files change.
    if settings.get('login_required') is False:
        from common import auth
        credentials = json.loads(Path('/run/ituner-groundstation-login.json').read_text())

        async def login():
            return await auth.login(
                username=credentials['username'], password=credentials['password'],
                user_agent='iTuner automatic local access', keep_session_active=True)

        upstream.socket_app = AutomaticAccess(upstream.socket_app, login)
        print('iTuner: automatic local access enabled; use the host toggle to require login.', flush=True)
    upstream.main()


if __name__ == '__main__':
    main()
