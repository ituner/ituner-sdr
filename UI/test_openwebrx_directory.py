import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openwebrx_directory as directory


SAMPLE = r'''
<script>
var receivers = [{"label":"Reykjavík <b>SDR</b>","location":{"coordinates":[-21.94,64.15],"type":"Point"},"receivers":[{"label":"HF OpenWebRX Multi-Band Remote SDR","version":"1.2.126","url":"https://rx.example.test/radio/#freq=1000","type":"OpenWebRX"},{"label":"Other","url":"https://other.test/","type":"WebSDR"}]}];
$('.map-container').addReceivers(receivers);
</script>
'''


class OpenWebRxDirectoryTests(unittest.TestCase):
    def test_map_json_becomes_explicit_openwebrx_rows(self):
        self.assertEqual(directory.parse_directory_page(SAMPLE), [{
            "id": "openwebrx:owrxs://rx.example.test/radio",
            "protocol": "openwebrx",
            "source_group": "openwebrx",
            "endpoint": "owrxs://rx.example.test/radio/",
            "name": "HF OpenWebRX Multi-Band Remote SDR",
            "location": "Reykjavík SDR",
            "latitude": 64.15,
            "longitude": -21.94,
            "version": "1.2.126",
        }])

    def test_cached_directory_survives_network_failure(self):
        with tempfile.TemporaryDirectory() as directory_name:
            cache = Path(directory_name) / "receivers.json"
            expected = directory.parse_directory_page(SAMPLE)
            directory.save_directory(expected, cache)
            with mock.patch.object(directory, "fetch_directory", side_effect=OSError("offline")):
                self.assertEqual(directory.load_directory(cache), expected)

    def test_live_directory_survives_read_only_cache(self):
        expected = directory.parse_directory_page(SAMPLE)
        with mock.patch.object(directory, "load_cached_directory", return_value=[]), \
             mock.patch.object(directory, "fetch_directory", return_value=expected), \
             mock.patch.object(directory, "save_directory", side_effect=OSError("read only")):
            self.assertEqual(directory.load_directory("/read-only/cache.json"), expected)

    def test_labels_are_plain_single_line_text(self):
        self.assertEqual(directory.clean_label("<b>  Long\n name </b> &amp; SDR"), "Long name & SDR")


if __name__ == "__main__":
    unittest.main()
