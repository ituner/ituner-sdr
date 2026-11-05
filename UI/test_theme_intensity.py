"""Brightness and border visibility remain reversible, independent adjustments."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes, contrast
from theme_system import ThemeLibrary, DEFAULT_THEME, BUILTIN_THEMES, apply_theme, preview_theme


class ThemeIntensityTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory()
        self.path=Path(self.directory.name)/'themes.json'
        self.library=ThemeLibrary(self.path)
        self.editor=ThemeEditor(self.library); self.editor.show(); self.editor.select_theme('green')

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def color_boxes(self):
        if self.editor.overlay != 'colors':
            a,b,c,d=theme_screen_boxes(self.editor)['colors:accent']
            self.editor.tap((a+c)/2,(b+d)/2)
        return theme_screen_boxes(self.editor)

    def tap(self,key):
        if key.split(':')[0] in ('color_intensity','border_intensity'):
            boxes=self.color_boxes()
        else:
            if self.editor.overlay == 'colors':
                a,b,c,d=theme_screen_boxes(self.editor)['color:save']
                self.editor.tap((a+c)/2,(b+d)/2)
            boxes=theme_screen_boxes(self.editor)
        if key.endswith((':smaller',':larger')) and key.split(':')[0] in ('color_intensity','border_intensity'):
            field,step=key.split(':')
            low,high=(50,150) if field=='color_intensity' else (25,200)
            amount=self.editor.preview[field+'_percent']+(-5 if step=='smaller' else 5)
            a,b,c,d=boxes[field]
            x=a+4+(c-a-8)*(amount-low)/(high-low)
            self.editor.drag(x,(b+d)/2,started_at=((a+c)/2,(b+d)/2))
            return
        a,b,c,d=boxes[key]
        self.editor.tap((a+c)/2,(b+d)/2)

    def test_brightness_and_border_are_available_separately(self):
        boxes=self.color_boxes()
        self.assertIn('color_intensity',boxes)
        self.assertIn('border_intensity',boxes)
        before=deepcopy(self.editor.preview)
        self.tap('color_intensity:smaller')
        self.assertEqual(self.editor.preview['color_intensity_percent'],95)
        self.assertEqual(self.editor.preview['colors']['border'],before['colors']['border'])
        self.assertNotEqual(self.editor.preview['colors']['spectrum_line'],before['colors']['spectrum_line'])
        self.tap('border_intensity:larger')
        self.assertEqual(self.editor.preview['border_intensity_percent'],30)
        self.assertNotEqual(self.editor.preview['colors']['border'],before['colors']['border'])
        self.assertFalse(self.path.exists())

    def test_repeated_adjustments_return_exactly_to_original_no_rounding_drift(self):
        self.assertIn('color_intensity',self.color_boxes())
        self.editor.choose_accent('mint')
        original=deepcopy(self.editor.preview)
        for _ in range(10): self.tap('color_intensity:smaller'); self.tap('color_intensity:larger')
        for _ in range(10): self.tap('border_intensity:larger'); self.tap('border_intensity:smaller')
        self.assertEqual(self.editor.preview,original)

    def test_reset_and_cancel_cover_both_intensities(self):
        self.assertIn('border_intensity',self.color_boxes())
        original=deepcopy(self.editor.preview)
        self.editor.choose_accent('mint');self.tap('color_intensity:smaller');self.tap('border_intensity:larger')
        self.tap('option:rounded');self.tap('text:larger');self.tap('reset')
        self.assertEqual(self.editor.preview,original)
        self.tap('color_intensity:smaller');self.tap('back')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.preview,self.editor.entry_theme)
        self.assertFalse(self.path.exists())

    def test_settings_survive_restart_and_remain_adjustable_without_double_scaling(self):
        self.assertIn('color_intensity',self.color_boxes())
        self.tap('color_intensity:smaller');self.tap('border_intensity:larger');self.tap('save')
        persisted=deepcopy(self.library.get('green'))
        restarted=ThemeLibrary(self.path)
        self.editor=ThemeEditor(restarted);self.editor.show();self.editor.select_theme('green')
        self.assertEqual(self.editor.preview,persisted)
        self.tap('color_intensity:larger');self.tap('border_intensity:smaller')
        self.assertEqual(self.editor.preview['colors']['spectrum_line'],BUILTIN_THEMES['green']['colors']['spectrum_line'])

    def test_more_border_intensity_means_more_visible_on_light_themes_too(self):
        self.editor.select_theme('straight-inverted')
        self.assertIn('border_intensity',self.color_boxes())
        # Increasing intensity darkens the outline against a light surface.
        self.tap('border_intensity:larger')
        before=deepcopy(self.editor.preview['colors'])
        self.tap('border_intensity:larger')
        after=self.editor.preview['colors']
        self.assertGreater(contrast(after['border'],after['surface']),contrast(before['border'],before['surface']))

    def test_low_intensity_scales_text_directly_and_keeps_pressed_button_text_readable(self):
        for identifier in BUILTIN_THEMES:
            self.editor.select_theme(identifier)
            for accent in ('original','mint','cyan','amber','white'):
                self.tap('reset');self.editor.choose_accent(accent)
                self.assertIn('color_intensity',self.color_boxes())
                a,b,c,d=self.color_boxes()['color_intensity']
                self.editor.drag(a,(b+d)/2,started_at=(a,(b+d)/2))
                colors=self.editor.preview['colors']
                self.assertEqual(colors['text'],[round(v*.5) for v in BUILTIN_THEMES[identifier]['colors']['text']])
                self.assertGreaterEqual(contrast((0,0,0),colors['pressed_surface']),4.5)

    def test_legacy_saved_theme_intensity_does_not_accumulate_after_restart(self):
        from theme_system import new_theme
        saved=new_theme('Existing theme')
        saved['colors']['spectrum_line']=[120,180,220,208]
        self.library.upsert(saved)
        self.editor.show();self.editor.select_theme(saved['id'])
        self.assertIn('color_intensity',self.color_boxes())
        self.tap('color_intensity:smaller');self.tap('border_intensity:larger');self.tap('save')
        colors=deepcopy(self.editor.preview['colors'])
        self.editor=ThemeEditor(ThemeLibrary(self.path));self.editor.show();self.editor.select_theme(saved['id'])
        self.assertEqual(self.editor.preview['colors'],colors)
        self.tap('color_intensity:larger');self.tap('border_intensity:smaller')
        self.assertEqual(self.editor.preview['colors']['spectrum_line'],saved['colors']['spectrum_line'])

    def test_old_interface_only_override_recovers_its_preset_plot_colors_on_load(self):
        old=deepcopy(BUILTIN_THEMES['green'])
        for key,color in DEFAULT_THEME['colors'].items():
            if key.startswith(('waterfall_','spectrum_')):old['colors'][key]=color
        old['waterfall_style']='default'
        self.path.write_text(json.dumps({'version':1,'active_id':'green','themes':[],
                                        'builtin_overrides':{'green':old}}))
        original=self.path.read_bytes()
        restarted=ThemeLibrary(self.path)
        self.assertEqual(restarted.get('green')['colors']['spectrum_line'],BUILTIN_THEMES['green']['colors']['spectrum_line'])
        self.assertEqual(restarted.get('green')['waterfall_style'],'green')
        self.assertEqual(self.path.read_bytes(),original)

    def test_builtin_inactive_borders_start_bright_and_explicit_dimming_survives_load(self):
        old=deepcopy(DEFAULT_THEME)
        old['colors']['border']=[46,46,46,255]
        old['colors']['active_border']=[96,96,96,255]
        for percent,expected in ((100,255),(50,128)):
            old['border_intensity_percent']=percent
            self.path.write_text(json.dumps({'version':1,'active_id':'default','themes':[],
                                            'builtin_overrides':{'default':old}}))
            before=self.path.read_bytes()
            library=ThemeLibrary(self.path)
            self.assertEqual(library.get('default')['colors']['border'],[expected,expected,expected,255])
            self.assertEqual(library.get('default')['colors']['active_border'],[expected if percent==100 else 142]*3+[255])
            self.assertEqual(self.path.read_bytes(),before)

    def test_slider_drag_keeps_its_original_target_and_clamps_to_limits(self):
        boxes=self.color_boxes()
        self.assertIn('color_intensity',boxes)
        a,b,c,d=boxes['color_intensity']
        self.editor.drag(c+1000,d+100,started_at=((a+c)/2,(b+d)/2))
        self.assertEqual(self.editor.preview['color_intensity_percent'],150)
        self.assertEqual(self.editor.preview['border_intensity_percent'],25)
        self.editor.drag(a-1000,b-100,started_at=((a+c)/2,(b+d)/2))
        self.assertEqual(self.editor.preview['color_intensity_percent'],50)

    def test_default_and_inverted_waterfalls_honor_intensity_without_changing_alpha(self):
        pixels=bytes([20,40,80,73,125,170,200,251])
        for identifier in ('default','straight-inverted','green','black-white'):
            self.editor.select_theme(identifier)
            self.assertIn('color_intensity',self.color_boxes())
            for _ in range(10):self.tap('color_intensity:smaller')
            with preview_theme(self.editor.preview):
                signature=ui.waterfall_theme_signature()
                result=ui.themed_waterfall_pixels(pixels)
                with patch.object(ui,'np',None):
                    self.assertEqual(ui.themed_waterfall_pixels(pixels),result)
                self.assertEqual(result[3::4],pixels[3::4])
            self.tap('reset')
            with preview_theme(self.editor.preview):
                self.assertNotEqual(ui.waterfall_theme_signature(),signature)
                self.assertNotEqual(ui.themed_waterfall_pixels(pixels),result)


if __name__=='__main__': unittest.main()
