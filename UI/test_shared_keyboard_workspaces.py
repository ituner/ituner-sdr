"""Shared keyboard integration keeps each field's save and cancel semantics."""
import unittest
from unittest.mock import Mock

from hell_workspace import HellWorkspace
from wspr_history_view import WSPRHistoryView
from station_workspace import StationWorkspace
from dongle_workspace import DongleWorkspace
from spectrum_workspace import SpectrumWorkspace


class KeyboardWorkflowTests(unittest.TestCase):
    def press(self, workspace, action, *args):
        workspace.ui.touch_keyboard_action_at.return_value=action
        workspace.tap(0,0,*args)

    def test_hell_identity_done_edits_draft_without_queuing_report(self):
        w=HellWorkspace.__new__(HellWorkspace);w.ui=Mock();w.manager=Mock()
        w.reporting={'call':'OLD','confirmed':False};w.report_field='call';w.report_entry='OLD';w.report_keyboard=True
        self.press(w,'CLEAR',[]);self.press(w,'a',[]);self.press(w,'SAVE',[])
        self.assertEqual(w.reporting['call'],'a');self.assertFalse(w.report_keyboard)
        self.assertFalse(w.reporting['confirmed']);w.manager.reporter.submit.assert_not_called()
        w.report_keyboard=True;w.report_entry='DISCARD';self.press(w,'CANCEL',[])
        self.assertEqual(w.reporting['call'],'a')

    def test_wspr_grid_done_keeps_reporting_permission_and_save_separate(self):
        w=WSPRHistoryView.__new__(WSPRHistoryView);w.ui=Mock();w.history=Mock()
        w.settings={'grid':'AA00','confirmed':False};w.field='grid';w.field_entry='BB11';w.field_keyboard=True
        self.press(w,'SAVE')
        self.assertEqual(w.settings['grid'],'BB11');w.history.configure.assert_not_called()
        self.assertFalse(w.settings['confirmed'])
        w.field_keyboard=True;w.field_entry='CC22';self.press(w,'CANCEL')
        self.assertEqual(w.settings['grid'],'BB11')

    def test_station_cancel_keeps_original_draft(self):
        w=StationWorkspace(Mock(),Mock());w.field='station_name';w.value='Unsaved';w.draft={'station_name':'Saved'}
        self.press(w,'CANCEL');self.assertIsNone(w.field);self.assertEqual(w.draft['station_name'],'Saved')

    def test_dongle_cancel_does_not_rename(self):
        w=DongleWorkspace(Mock(),Mock());w.field='Nickname · optional';w.value='Unsaved';w.submit=Mock()
        self.press(w,'CANCEL');self.assertIsNone(w.field);w.submit.assert_not_called()

    def test_spectrum_notes_cancel_and_save_return_to_report(self):
        w=SpectrumWorkspace.__new__(SpectrumWorkspace);w.ui=Mock();w.overlay='label'
        w.label_target='report_notes';w.draft={'report_notes':'Saved'};w.label_value='Unsaved'
        self.press(w,'CANCEL');self.assertEqual(w.overlay,'report');self.assertEqual(w.draft['report_notes'],'Saved')
        w.overlay='label';self.press(w,'SAVE');self.assertEqual(w.draft['report_notes'],'Unsaved')

if __name__=='__main__':unittest.main()
