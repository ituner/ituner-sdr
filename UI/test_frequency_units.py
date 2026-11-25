import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui

class FrequencyUnitTests(unittest.TestCase):
    def test_explicit_units_do_not_guess_from_receiver_range(self):
        self.assertEqual(ui.parse_frequency_entry('1000','kHz',1766000),1000)
        self.assertEqual(ui.parse_frequency_entry('1000','MHz',1766000),1000000)
        self.assertEqual(ui.parse_frequency_entry('100100','kHz',1766000),100100)
        self.assertIsNone(ui.parse_frequency_entry('100100','MHz',1766000))
        for value in ('nan','inf','-1',''):
            self.assertIsNone(ui.parse_frequency_entry(value,'kHz'))

    def test_conversion_preserves_frequency_and_decimal_precision(self):
        self.assertEqual(ui.convert_frequency_entry('100.1','MHz','kHz'),'100100')
        self.assertEqual(ui.convert_frequency_entry('145500.125','kHz','MHz'),'145.500125')
        self.assertEqual(ui.convert_frequency_entry('','kHz','MHz'),'')
        self.assertEqual(ui.frequency_entry_preview_khz('1000',0,False,1766000,'kHz'),1000)
        self.assertEqual(ui.frequency_entry_preview_khz('1000',0,False,1766000,'MHz'),1000000)

    def test_unit_buttons_are_touchable_without_overlapping_readout_or_keys(self):
        for legacy in (False,True):
            for unit,box in ui.frequency_unit_boxes(legacy):
                hit=ui.frequency_entry_action_at if legacy else ui.frequency_drawer_action_at
                self.assertEqual(hit((box[0]+box[2])/2,(box[1]+box[3])/2),'unit_'+unit)
                if not legacy:self.assertLessEqual(box[3],ui.frequency_drawer_boxes()['readout'][1])

if __name__=='__main__':unittest.main()
