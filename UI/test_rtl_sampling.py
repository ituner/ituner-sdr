import unittest
from unittest.mock import Mock
from rtl_sampling import switch_sampling

class SamplingTests(unittest.TestCase):
    def test_am_scan_switches_once_and_fm_restores_tuner(self):
        lib=Mock();lib.rtlsdr_set_direct_sampling.return_value=0
        mode=switch_sampling(lib,1,531000)
        for hz in (600000,1000000,1602000):mode=switch_sampling(lib,1,hz,mode)
        lib.rtlsdr_set_direct_sampling.assert_called_once_with(1,2)
        mode=switch_sampling(lib,1,96300000,mode)
        self.assertEqual(mode,0)
        lib.rtlsdr_set_direct_sampling.assert_called_with(1,0)
        lib.rtlsdr_set_tuner_gain_mode.assert_called_once_with(1,0)
    def test_failed_switch_is_reported(self):
        lib=Mock();lib.rtlsdr_set_direct_sampling.return_value=-1
        with self.assertRaisesRegex(RuntimeError,'Q-branch'):switch_sampling(lib,1,531000)
