import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from web_app_preview import WebAppPreviews, preview_html


class PreviewTests(unittest.TestCase):
    def test_fixed_destinations_and_landscape_shell(self):
        page=preview_html('groundstation','cm5.local','test-token',touch=True,rotation=90)
        self.assertIn('http://cm5.local:7000/earthview',page)
        self.assertIn('rotate(90deg)',page)
        self.assertIn('← Decoders',page)
        self.assertNotIn('allowfullscreen',page)
        self.assertIn('http://[::1]:8095/',preview_html('satvisor','::1','t'))

    def test_launch_is_single_instance_and_restores_touch_after_exit(self):
        process=mock.Mock(pid=99999)
        process.poll.return_value=None
        with tempfile.TemporaryDirectory() as root, mock.patch('web_app_preview.Path.home',return_value=Path(root)), mock.patch('web_app_preview.shutil.which',return_value='/usr/bin/chromium'), mock.patch('web_app_preview.subprocess.Popen',return_value=process) as launch:
            previews=WebAppPreviews();previews.rotation=90
            previews.open('satvisor');previews.open('satvisor')
            self.assertEqual(launch.call_count,1)
            self.assertIn('--app=http://127.0.0.1:8092/apps/satvisor?touch=1&rotation=90',launch.call_args.args[0])
            self.assertTrue(previews.blocks_touch)
            with self.assertRaises(ValueError):previews.open('groundstation')
            process.poll.return_value=0
            self.assertFalse(previews.active)
            self.assertTrue(previews.blocks_touch)
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
