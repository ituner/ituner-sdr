import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from web_app_preview import WebAppPreviews, preview_html


class PreviewTests(unittest.TestCase):
    def setUp(self):
        platform = mock.patch('web_app_preview.sys', mock.Mock(platform='linux'))
        platform.start()
        self.addCleanup(platform.stop)

    def test_mac_uses_separate_chrome_profile_without_wayland(self):
        process=mock.Mock(pid=99999, returncode=None)
        process.poll.return_value=None
        with tempfile.TemporaryDirectory() as root, mock.patch('web_app_preview.sys.platform', 'darwin'), mock.patch('web_app_preview.Path.home', return_value=Path(root)), mock.patch('web_app_preview.Path.is_file', return_value=True), mock.patch('web_app_preview.subprocess.Popen', return_value=process) as launch:
            previews=WebAppPreviews()
            previews.open('groundstation')
            args=launch.call_args.args[0]
            self.assertEqual(args[0], '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            self.assertIn('--window-size=1280,800', args)
            self.assertIn(f'--user-data-dir={root}/Library/Application Support/iTuner/web-app-preview', args)
            self.assertNotIn('--ozone-platform=wayland', args)
            self.assertNotIn('--kiosk', args)
            self.assertEqual(previews.notice[0], 'Loading Ground Station…')

    def test_fixed_destinations_and_landscape_shell(self):
        page=preview_html('groundstation','cm5.local','test-token',touch=True,rotation=90)
        self.assertIn('http://cm5.local:7000/earthview',page)
        self.assertIn('rotate(90deg)',page)
        self.assertIn('← Decoders',page)
        self.assertNotIn('allowfullscreen',page)
        self.assertIn('Loading Ground Station…',page)
        self.assertIn('frame.onload=',page)
        self.assertIn("onclick=loadApp",page)
        self.assertIn('http://[::1]:8095/',preview_html('satvisor','::1','t'))

    def test_launch_is_single_instance_and_restores_touch_after_exit(self):
        process=mock.Mock(pid=99999, returncode=None)
        process.poll.return_value=None
        with tempfile.TemporaryDirectory() as root, mock.patch('web_app_preview.Path.home',return_value=Path(root)), mock.patch('web_app_preview.shutil.which',return_value='/usr/bin/chromium'), mock.patch('web_app_preview.subprocess.Popen',return_value=process) as launch:
            previews=WebAppPreviews();previews.rotation=90
            previews.open('satvisor');previews.open('satvisor')
            self.assertEqual(launch.call_count,1)
            self.assertIn('--app=http://127.0.0.1:8092/apps/satvisor?touch=1&rotation=90',launch.call_args.args[0])
            self.assertTrue(previews.blocks_touch)
            with self.assertRaises(ValueError):previews.open('groundstation')
            self.assertEqual(previews.notice, ('Loading Satvisor…', 'Please wait'))
            process.poll.return_value=0
            process.returncode=0
            self.assertFalse(previews.active)
            self.assertTrue(previews.blocks_touch)
            self.assertTrue(previews.return_to_decoders)
            self.assertIsNone(previews.notice)

    def test_launch_failure_shows_notice_then_expires(self):
        previews=WebAppPreviews()
        with mock.patch('web_app_preview.shutil.which', return_value=None), mock.patch('web_app_preview.time.monotonic', return_value=100):
            with self.assertRaises(ValueError):previews.open('groundstation')
            self.assertEqual(previews.notice[0], 'Could not open Ground Station')
            self.assertIn('Chromium', previews.notice[1])
            self.assertFalse(previews.blocks_touch)
        with mock.patch('web_app_preview.time.monotonic', return_value=109):
            self.assertIsNone(previews.notice)

    def test_browser_crash_clears_loading_and_restores_controls(self):
        previews=WebAppPreviews()
        previews.key='satvisor'
        previews.process=mock.Mock(returncode=1)
        previews.process.poll.return_value=1
        self.assertEqual(previews.notice[0], 'Could not open Satvisor')
        self.assertFalse(previews.active)
        self.assertTrue(previews.return_to_decoders)

    def test_unrecognized_application_never_spawns_process(self):
        with mock.patch('web_app_preview.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):WebAppPreviews().open('https://example.org')
            launch.assert_not_called()

    def test_http_shell_and_control_authentication(self):
        from vhf_monitor import VHFHub
        with tempfile.TemporaryDirectory() as root:
            hub=VHFHub(root=root,port=0,scanner=lambda:[])
            base=f'http://127.0.0.1:{hub.port}'
            try:
                hub.web_apps.hostname='cm5.local'
                with urlopen(base+'/apps/groundstation') as r:
                    self.assertIn(b'http://cm5.local:7000/earthview', r.read())
                with urlopen(base+'/apps/satvisor?touch=1&rotation=90') as r:
                    self.assertIn(b'rotate(90deg)',r.read())
                request=Request(base+'/api/web-app',data=b'{"action":"close"}',headers={'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as error:urlopen(request)
                self.assertEqual(error.exception.code,403)
                request.add_header('X-VHF-Token',hub.token)
                with mock.patch.object(hub.web_apps,'close') as close:
                    with urlopen(request) as r:self.assertTrue(json.load(r)['ok'])
                    close.assert_called_once()
            finally:hub.close()


if __name__=='__main__':unittest.main()
