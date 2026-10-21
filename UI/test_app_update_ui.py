"""The update screen exposes one source, with explicit install and recovery."""
import unittest
from unittest.mock import Mock
import app_update_ui as view


class UpdateScreenTests(unittest.TestCase):
    def setUp(self):
        self.controller = Mock(busy=False, phase='idle', confirm=None, recovery=False,
                               release=None, notes_page=0, cfg={'root':'/app'})
        self.controller.current.return_value = {'commit': 'a'*40}
        self.controller.rollback_available.return_value = False
        self.ui = Mock()
        self.ui.contains.side_effect = lambda b,x,y: b[0] <= x <= b[2] and b[1] <= y <= b[3]
        self.ui.lcd_drawer_back_box.return_value = (1034,728,1270,792)

    def click(self, name):
        b = view.boxes(self.ui)[name]
        return view.action(self.controller, self.ui, (b[0]+b[2])/2, (b[1]+b[3])/2)

    def available(self):
        self.controller.phase = 'available'
        self.controller.release = {'commit':'b'*40, 'name':'Build bbbbbbbb', 'notes':'A short change'}

    def test_initial_screen_has_only_check_and_no_channels_or_note_paging(self):
        self.assertEqual(view.controls(self.controller), [('check','CHECK FOR UPDATES',True)])
        self.assertNotIn('stable', view.boxes(self.ui))
        self.assertNotIn('development', view.boxes(self.ui))
        self.click('check'); self.controller.check.assert_called_once()

    def test_install_confirmation_can_be_cancelled(self):
        self.available(); self.click('install')
        self.assertEqual(self.controller.confirm, 'install')
        self.controller.launch.assert_not_called()
        self.click('cancel'); self.assertIsNone(self.controller.confirm)
        self.click('install'); self.click('install')
        self.controller.launch.assert_called_once_with('install')

    def test_recovery_is_separate_and_confirmed(self):
        self.controller.rollback_available.return_value = True
        self.click('recovery')
        self.assertTrue(self.controller.recovery)
        self.click('rollback'); self.controller.launch.assert_not_called()
        self.click('rollback'); self.controller.launch.assert_called_once_with('rollback')

    def test_busy_cannot_launch_duplicate_or_show_checking_during_install(self):
        self.available(); self.controller.busy = True; self.controller.phase = 'installing'
        self.assertEqual(view.controls(self.controller), [('check','UPDATE IN PROGRESS',False)])
        self.click('install'); self.controller.launch.assert_not_called()
        self.controller.check.assert_not_called()
        self.assertEqual(self.click('back'), 'back')

    def test_up_to_date_cannot_install_and_errors_can_recheck(self):
        self.available(); self.controller.release['commit'] = 'a'*40
        self.assertEqual(view.controls(self.controller)[0][0], 'check')
        self.available(); self.controller.phase = 'error'
        self.assertEqual(view.controls(self.controller)[0][0], 'check')

    def test_notes_navigation_stays_in_range(self):
        self.available(); self.controller.release['notes'] = '\n'.join(['line']*11)
        self.click('previous_notes'); self.assertEqual(self.controller.notes_page, 0)
        for _ in range(4): self.click('next_notes')
        self.assertEqual(self.controller.notes_page, 2)
        self.click('previous_notes'); self.assertEqual(self.controller.notes_page, 1)
