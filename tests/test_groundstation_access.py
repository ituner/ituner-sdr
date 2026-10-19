"""HTTP/WebSocket parity and private session handling for the evaluation wrapper."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'groundstation_access', Path(__file__).resolve().parents[1] / 'scripts/groundstation-access.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scopes = []
        self.logins = 0

        async def login():
            self.logins += 1
            await asyncio.sleep(0)
            return dict(success=True, token=f'private-token-{self.logins}')

        async def upstream(scope, receive, send):
            self.scopes.append(scope)

        self.access = module.AutomaticAccess(upstream, login)

    async def request(self, kind='http', path='/', headers=None):
        await self.access(dict(type=kind, path=path, headers=headers or []), None, None)

    async def test_http_and_websocket_share_server_session(self):
        await asyncio.gather(self.request(), self.request('websocket', '/socket.io/'))
        self.assertEqual(self.logins, 1)
        for scope in self.scopes:
            self.assertEqual(dict(scope['headers'])[b'cookie'], b'gs_session=private-token-1')

    async def test_stale_browser_credentials_are_replaced_other_cookies_preserved(self):
        headers = [(b'cookie', b'gs_session=expired; theme=dark'),
                   (b'authorization', b'Bearer expired'), (b'origin', b'http://cm5.local:7000')]
        await self.request(headers=headers)
        forwarded = dict(self.scopes[0]['headers'])
        self.assertIn(b'theme=dark', forwarded[b'cookie'])
        self.assertIn(b'gs_session=private-token-1', forwarded[b'cookie'])
        self.assertNotIn(b'authorization', forwarded)
        self.assertEqual(headers[0][1], b'gs_session=expired; theme=dark')

    async def test_lifespan_does_not_create_session(self):
        await self.request('lifespan')
        self.assertEqual(self.logins, 0)

    async def test_logout_does_not_reuse_revoked_token(self):
        await self.request(path='/api/auth/logout')
        await self.request(path='/api/auth/status')
        self.assertEqual(self.logins, 2)
        self.assertIn(b'private-token-2', dict(self.scopes[-1]['headers'])[b'cookie'])

    async def test_failed_login_never_calls_protected_app(self):
        async def failed():
            return dict(success=False, error='invalid password')
        self.access.login = failed
        with self.assertRaises(RuntimeError):
            await self.request()
        self.assertEqual(self.scopes, [])


if __name__ == '__main__':
    unittest.main()
