"""Live theme tokens and navigation for native decoder workspaces."""
import theme_system
from ui_style import APP_UI_STYLE
from ui_chrome import (RAIL_BACK_BOX, CANVAS_WIDTH, STATUS_TOP, STATUS_FIRST_Y,
                       STATUS_CLOCK_Y, STATUS_FONT_SIZE, STATUS_FONT, draw_status_clock)


def full_width_back_box():
    """Full-width screens place navigation directly, without moving pixels."""
    x0,y0,x1,y1 = RAIL_BACK_BOX
    return (x0-1024,y0,x1-1024,y1) if theme_system.runtime_theme['sidebar'] == 'left' else RAIL_BACK_BOX


def footer_content_box():
    return (274, 712, 1262, 800) if full_width_back_box()[0] == 10 else (18, 712, 1006, 800)


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
        box=full_width_back_box()
        self.ui.draw_styled_two_line_button(cache,box,'BACK','')
        self.actions.append((box,action))

    def draw_status(self, cache, message, detail='', *, full_width=False):
        """Use HOME's two rows, font, colors and UTC clock position."""
        offset = 256 if full_width and theme_system.runtime_theme['sidebar']=='left' else 0
        ui=self.ui
        ui.draw_logical_rect(offset,STATUS_TOP,offset+CANVAS_WIDTH,800,self.color('footer_background'))
        message=ui.fit_station_text(cache,str(message),988,STATUS_FONT_SIZE,True,False,STATUS_FONT)
        ui.draw_text(cache,offset+18,STATUS_FIRST_Y,message,self.color('footer_primary'),STATUS_FONT_SIZE,True,False,'lm',family=STATUS_FONT)
        draw_status_clock(ui,cache,offset+18)
        detail=ui.fit_station_text(cache,str(detail),666,STATUS_FONT_SIZE,False,False,STATUS_FONT)
        ui.draw_text(cache,offset+340,STATUS_CLOCK_Y,detail,self.color('footer_primary'),STATUS_FONT_SIZE,False,False,'lm',family=STATUS_FONT)
