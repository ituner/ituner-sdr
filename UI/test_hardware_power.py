import unittest
from unittest.mock import Mock
from hardware_power import PowerButton,EV_KEY,KEY_POWER
from system_power import PowerController

class HardwarePowerTests(unittest.TestCase):
    def setUp(self):self.button=PowerButton('/nonexistent-input','/nonexistent-dev')
    def tearDown(self):self.button.close()
    def test_press_opens_confirmation_without_running_shutdown(self):
        runner=Mock();controller=PowerController(helper=__file__,runner=runner)
        self.button.event(EV_KEY,KEY_POWER,1,10)
        self.assertTrue(self.button.consume());controller.select('poweroff',hardware=True)
        self.assertTrue(controller.open);self.assertTrue(controller.hardware);runner.assert_not_called()
        controller.cancel();self.assertFalse(controller.open);runner.assert_not_called()
    def test_release_autorepeat_and_bounce_never_confirm(self):
        self.button.event(EV_KEY,KEY_POWER,1,10);self.assertTrue(self.button.consume())
        for value in (1,2,2,0,1):self.button.event(EV_KEY,KEY_POWER,value,10.1)
        self.assertFalse(self.button.consume())
        self.button.event(EV_KEY,KEY_POWER,0,11)
        self.button.event(EV_KEY,KEY_POWER,1,12);self.assertTrue(self.button.consume())
        self.assertFalse(self.button.consume())
    def test_other_keys_are_ignored(self):
        self.button.event(EV_KEY,30,1,10);self.button.event(0,KEY_POWER,1,10)
        self.assertFalse(self.button.consume())

if __name__=='__main__':unittest.main()
