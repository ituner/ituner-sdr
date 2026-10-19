"""Live theme tokens and navigation for native decoder workspaces."""
import theme_system
from ui_style import APP_UI_STYLE


def full_width_back_box():
    """Full-width screens place navigation directly, without moving pixels."""
    x = 10 if theme_system.runtime_theme['sidebar'] == 'left' else 1034
    return (x, 728, x + 236, 792)


def footer_content_box():
    return (270, 728, 1256, 792) if full_width_back_box()[0] == 10 else (24, 728, 1010, 792)


class DecoderStyle:
    # Properties deliberately read the live palette, including theme previews.
    BG = property(lambda self: APP_UI_STYLE.palette.background)
    PANEL = property(lambda self: APP_UI_STYLE.palette.section_surface)
    TEXT = property(lambda self: APP_UI_STYLE.palette.text)
    MUTED = property(lambda self: APP_UI_STYLE.palette.secondary_text)
    CYAN = property(lambda self: APP_UI_STYLE.palette.focus[:3])
    GOLD = property(lambda self: APP_UI_STYLE.palette.waiting[:3])
    LINE = property(lambda self: APP_UI_STYLE.palette.section_border)
    RADIUS = property(lambda self: APP_UI_STYLE.button.radius)

    def color(self, role):
        return getattr(APP_UI_STYLE.palette, role)

    def decoder_button(self, cache, box, title, action, subtitle='', active=False,
                       enabled=True, font_size=20, uppercase=True):
        ui = self.ui
        style = APP_UI_STYLE.button
        pressed = getattr(ui, 'ui_button_pressed', lambda box: False)(box) is True
        visual = style.resolve(active=active, pressed=pressed and enabled)
        ui.draw_logical_rounded_rect(*box, style.radius, visual.fill, visual.border, visual.border_width)
        color = visual.text if enabled else self.color('untested_text')
        x0, y0, x1, y1 = box
        family = style.font_family
        title = str(title).upper() if uppercase else str(title)
        title = ui.fit_station_text(cache, title, x1-x0-20, font_size, True, False, family)
        ui.draw_text(cache, (x0+x1)/2, (y0+y1)/2-(10 if subtitle else 0), title,
                     color, font_size, True, False, 'cm', family=family)
        if subtitle:
            size = min(18, font_size)
            sub = ui.fit_station_text(cache, str(subtitle), x1-x0-20, size, False, False, family)
            ui.draw_text(cache, (x0+x1)/2, (y0+y1)/2+15, sub,
                         self.MUTED if enabled else color, size, False, False, 'cm', family=family)
        if enabled:
            self.actions.append((box, action))

    def draw_back(self, cache, action=('back', None)):
        self.decoder_button(cache, full_width_back_box(), 'BACK', action)
