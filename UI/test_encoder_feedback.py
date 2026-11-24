"""Hardware volume feedback must survive modal screens and final composition."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui

SOURCE = Path(__file__).with_name('kiwi_gl_display.py')


def statements_code(nodes):
    return compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                   str(SOURCE), 'exec')


class EncoderFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text())
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Compare)
                      and isinstance(n.test.left, ast.Name) and n.test.left.id == 'knob_role'
                      and isinstance(n.test.comparators[0], ast.Constant)
                      and n.test.comparators[0].value == 'volume')
        cls.volume_code = statements_code(branch.body)
        # Execute the real final compositing stage, including the relocation
        # operation which formerly could hide or displace physical feedback.
        loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While)
                    and any(isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                            and isinstance(s.value.func, ast.Name)
                            and s.value.func.id == 'draw_home_rail_restore_tab' for s in ast.walk(n)))
        start = next(i for i,s in enumerate(loop.body) if isinstance(s, ast.If)
                     and isinstance(s.test, ast.Call) and isinstance(s.test.func, ast.Name)
                     and s.test.func.id == 'rail_relocation_active')
        stop = next(i for i,s in enumerate(loop.body) if isinstance(s, ast.If)
                    and isinstance(s.test, ast.Call) and isinstance(s.test.func, ast.Attribute)
                    and isinstance(s.test.func.value, ast.Name)
                    and s.test.func.value.id == 'screenshot_requested')
        cls.foreground_code = statements_code(loop.body[start:stop])

    def volume_env(self, value=.5, delta=1, applied=.51):
        return dict(audio_volume=value, knob_delta=delta, clamp=ui.clamp,
                    apply_main_volume=Mock(return_value=applied),
                    args=SimpleNamespace(output_volume=value, zoom_osd_seconds=2),
                    time=SimpleNamespace(monotonic=lambda: 10), volume_osd_until=0,
                    MAIN_VOLUME_MUTE_THRESHOLD=ui.MAIN_VOLUME_MUTE_THRESHOLD,
                    web_apps=SimpleNamespace(publish_encoder_notice=Mock()),
                    preferences_dirty=False, wake_controls=Mock(), print=Mock())

    def test_volume_changes_publish_feedback_even_with_screen_blockers(self):
        env=self.volume_env()
        env.update(shared_keyboard_open=lambda:True, picker_open=True,
                   theme_editor=SimpleNamespace(open=True), dual_vfo_open=True)
        exec(self.volume_code, env)
        env['apply_main_volume'].assert_called_once_with(.51)
        self.assertEqual(env['volume_osd_until'], 12)
        self.assertEqual(env['zoom_osd_until'], 0)
        self.assertEqual(env['encoder_zoom_osd_until'], 0)
        self.assertEqual(env['zoom_unavailable_osd_until'], 0)
        env['web_apps'].publish_encoder_notice.assert_called_once_with('VOLUME','51%',2)
        self.assertTrue(env['preferences_dirty'])

    def test_limit_detents_refresh_feedback_and_zero_reports_mute(self):
        for value,delta,applied,detail in ((1,5,1,'100%'),(0,-5,0,'MUTED  0%')):
            env=self.volume_env(value,delta,applied)
            exec(self.volume_code,env)
            env['apply_main_volume'].assert_called_once_with(applied)
            self.assertEqual(env['volume_osd_until'],12)
            env['web_apps'].publish_encoder_notice.assert_called_once_with('VOLUME',detail,2)

    def test_batched_detents_preserve_one_percentage_point_each(self):
        for delta, applied in ((10, .60), (-10, .40)):
            env = self.volume_env(delta=delta, applied=applied)
            exec(self.volume_code, env)
            env['apply_main_volume'].assert_called_once_with(applied)

    def test_failed_volume_application_does_not_report_success(self):
        env=self.volume_env(applied=None)
        exec(self.volume_code,env)
        self.assertEqual(env['volume_osd_until'],0)
        env['web_apps'].publish_encoder_notice.assert_not_called()

    def test_feedback_draws_after_relocation_and_other_notices(self):
        order=[]
        env=dict(rail_relocation_active=lambda:True,
                 sidebar_composer=SimpleNamespace(compose_left=lambda:order.append('compose')),
                 web_apps=SimpleNamespace(notice=('LOADING','Please wait'),active=True),
                 draw_web_app_notice_osd=lambda *a:order.append(a[1][0]),
                 draw_home_rail_restore_tab=lambda *a:order.append('restore'),
                 draw_volume_osd=lambda *a,**k:order.append('volume'),
                 draw_muted_waterfall_badge=lambda *a,**k:order.append('red-mute'),
                 mute_badge_touch_enabled=False, muted_rf_notice_visible=lambda:True,
                 theme_editor=SimpleNamespace(open=False),
                 state=SimpleNamespace(audio_controls_snapshot=lambda:({'mute':False},0)),
                 volume_osd_title='VOLUME',
                 text_cache=None, now=10, encoder_zoom_osd_until=12,
                 encoder_zoom_feedback_visible=lambda:True,
                 encoder_zoom_osd_context=('map',),
                 encoder_zoom_osd_title='ZOOM', encoder_zoom_osd_detail='MAP  2x', zoom_unavailable_osd_until=12,
                 volume_osd_until=12, audio_volume=.5,
                 green_osd_alpha=ui.green_osd_alpha,args=SimpleNamespace(zoom_osd_seconds=2))
        exec(self.foreground_code,env)
        self.assertEqual(order,['compose','LOADING','restore','ZOOM','ZOOM','volume'])
        order.clear();env.update(encoder_zoom_osd_until=0,zoom_unavailable_osd_until=0,volume_osd_until=0)
        exec(self.foreground_code,env)
        self.assertEqual(order,['compose','LOADING','restore'])
        order.clear()
        env['volume_osd_until']=12
        env['state']=SimpleNamespace(audio_controls_snapshot=lambda:({'mute':True},0))
        exec(self.foreground_code,env)
        self.assertEqual(order,['compose','LOADING','restore','red-mute'])
        order.clear(); env['muted_rf_notice_visible'] = lambda: False
        exec(self.foreground_code, env)
        self.assertEqual(order, ['compose','LOADING','restore'])

    def test_home_zoom_preserves_bars_span_and_step_caption(self):
        with patch.object(ui,'draw_green_osd_panel') as panel, patch.object(ui,'draw_text') as text, \
             patch.object(ui,'draw_logical_rect') as bars, patch.object(ui,'draw_logical_line'):
            ui.draw_home_encoder_zoom_osd(None,'ZOOM IN',30,'kiwi',220)
            panel.assert_called_once_with(ui.ZOOM_OSD_BOX,220)
            self.assertEqual([c.args[3] for c in text.call_args_list],
                             ['ZOOM IN','30.0 kHz','10% STEP'])
            right=text.call_args_list[1]
            self.assertEqual(right.args[1],ui.ZOOM_OSD_BOX[2]-18)
            self.assertEqual(right.args[-1],'rm')
            self.assertEqual(bars.call_count,ui.kiwi.DISPLAY_MAX_ZOOM+1)

    def test_home_zoom_bar_interpolates_fractional_span_and_digital_gap(self):
        for lower,upper in ((7,8),(14,15)):
            wide=ui.receiver_display_span(lower,'kiwi')
            narrow=ui.receiver_display_span(upper,'kiwi')
            with patch.object(ui,'draw_zoom_osd') as draw:
                ui.draw_home_encoder_zoom_osd(None,'ZOOM OUT',(wide*narrow)**.5,'kiwi',220)
                self.assertAlmostEqual(draw.call_args.args[1],lower+.5)
                self.assertEqual(draw.call_args.kwargs,dict(title='ZOOM OUT',step_text='10% STEP'))

    def test_volume_panel_uses_zoom_position_theme_and_fade(self):
        with patch.object(ui,'draw_green_osd_panel') as panel, patch.object(ui,'draw_text') as text, \
             patch.object(ui,'draw_logical_rect') as bars, patch.object(ui,'draw_logical_line'):
            ui.draw_volume_osd(None,.5,110)
            panel.assert_called_once_with(ui.ZOOM_OSD_BOX,110)
            self.assertEqual([c.args[3] for c in text.call_args_list],['VOLUME','50%'])
            self.assertTrue(all(c.args[4] == ui.APP_UI_STYLE.palette.notice for c in text.call_args_list))
            self.assertTrue(all(c.kwargs['alpha']==110/255 for c in text.call_args_list))
            self.assertEqual(bars.call_count,20)
            self.assertEqual(sum(c.args[4][3]==110 for c in bars.call_args_list),10)
            panel.reset_mock();ui.draw_volume_osd(None,.5,0);panel.assert_not_called()

    def test_muted_volume_retains_level_but_does_not_show_lit_bars(self):
        with patch.object(ui,'draw_green_osd_panel'), patch.object(ui,'draw_text') as text, \
             patch.object(ui,'draw_logical_rect') as bars, patch.object(ui,'draw_logical_line'):
            ui.draw_volume_osd(None,.73,220,muted=True,title='MUTE')
            self.assertEqual([c.args[3] for c in text.call_args_list],['MUTE','MUTED'])
            self.assertTrue(all(c.args[4][3] < 220 for c in bars.call_args_list))


if __name__ == '__main__':
    unittest.main()
