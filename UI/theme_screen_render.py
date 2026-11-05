"""Theme-aware floating controls over the actual full-size HOME preview."""
from dataclasses import replace

import theme_system
from ui_style import ButtonStyle, UIPalette
from theme_editor import (CARDS_PER_PAGE, FULL_HOME_BOX, INTENSITY_LIMITS, inspector_box,
                          theme_screen_boxes, rainbow_rgb, contrast, COLOR_STRIP_HEIGHT)
from theme_colors import muted_text_color
import colorsys
from theme_fonts import FONT_STYLES


def _text(ui, cache, x, y, value, size=14, color=None, anchor='lm', width=None):
    color = ui.APP_UI_STYLE.palette.text if color is None else color
    if width and isinstance(cache, ui.TextCache):
        value = ui.fit_station_text(cache, str(value), width, size, bold=True, family='Liberation Sans')
    ui.draw_text(cache, x, y, str(value), color, size, True, False, anchor, family='Liberation Sans')


def _button(ui, cache, box, label, active=False, *, enabled=True):
    # The draft styles controls; their physical touch geometry stays fixed.
    if not enabled:
        ui.draw_styled_two_line_button(cache, box, label, '', enabled=False,
            style=replace(ui.APP_UI_STYLE.button, title_size=ui.APP_UI_STYLE.button.label_size))
        return
    ui.draw_styled_text_button(cache, box, label, active=active,
                              style=ui.APP_UI_STYLE.button)


def _home(ui, cache, editor):
    if editor.live_frame is not None:
        editor.live_frame.draw(FULL_HOME_BOX)
    else:
        ui.draw_logical_rect(*FULL_HOME_BOX, ui.APP_UI_STYLE.palette.background)
        _text(ui, cache, 640, 200, 'Waiting for live HOME preview…', 18, anchor='cm')


def _floating_panel(ui, editor):
    p = ui.APP_UI_STYLE.palette
    x0,y0,x1,y1 = inspector_box(editor)
    radius = ui.APP_UI_STYLE.button.radius
    ui.draw_logical_rounded_rect(x0-6,y0-6,x1+6,y1+6,radius+4 if radius else 0,(0,0,0,56))
    ui.draw_logical_rounded_rect(x0,y0,x1,y1,radius,(*p.background[:3],228),p.border,1)
    return x0-16


def _chooser(ui, cache, editor, boxes):
    p = ui.APP_UI_STYLE.palette
    dx = _floating_panel(ui, editor)
    _text(ui, cache, 36+dx, 250, 'THEMES', 22)
    _text(ui, cache, 36+dx, 276, 'Choose a theme to customize on your full-size HOME screen.', 15, p.secondary_text)
    items = editor.themes[editor.page * CARDS_PER_PAGE:(editor.page + 1) * CARDS_PER_PAGE]
    for theme in items:
        box = boxes['theme:' + theme['id']]
        colors = theme['colors']
        palette = UIPalette(**{k: tuple(v) for k,v in colors.items()})
        style = ButtonStyle(replace(palette, surface=palette.background), radius=ui.APP_UI_STYLE.button.radius)
        ui.draw_styled_button_frame(box, style=style)
        x,y,_,_ = box
        _text(ui, cache, x+18, y+26, theme['name'].upper(), 17, palette.text, width=388)
        label = 'Current · tap to customize' if theme['id'] == editor.library.active_id else 'Tap to customize'
        _text(ui, cache, x+18, y+54, label, 13, palette.secondary_text)
        for i,key in enumerate(('background','surface','text','focus','frequency')):
            ui.draw_logical_rect(x+18+i*48, y+78, x+58+i*48, y+96, colors[key])
    _button(ui,cache,boxes['theme_previous'],'PREVIOUS',enabled=editor.page > 0)
    _button(ui,cache,boxes['theme_next'],'NEXT',enabled=editor.page + 1 < editor.page_count)
    _button(ui,cache,boxes['back'],'CANCEL')
    _text(ui,cache,608+dx,666,f'{editor.page + 1} / {editor.page_count}',14,p.secondary_text,'cm')


def _inspector(ui, cache, editor, boxes):
    p = ui.APP_UI_STYLE.palette
    dx = _floating_panel(ui, editor)
    radius = ui.APP_UI_STYLE.button.radius
    _text(ui,cache,36+dx,250,'CUSTOMIZE '+editor.preview['name'].upper(),18,width=760)
    status = editor.error or editor.status or 'Preview only · changes are not saved'
    _text(ui,cache,36+dx,276,status,13,p.danger_border if editor.error else p.secondary_text,width=760)
    for x,label in ((36,'COLORS'),(396,'TEXT SIZE'),(732,'CORNERS')):
        _text(ui,cache,x+dx,320,label,13,p.section_heading)
    for field,label,role in (('accent','ACCENT','focus'),('text','TEXT','text')):
        box=boxes['colors:'+field]
        _button(ui,cache,box,label)
        a,b,c,d=box
        color=editor.preview['colors'][role]
        ui.draw_logical_rect(a+10,d-10,c-10,d-5,tuple(color))
    _text(ui,cache,36+dx,436,'Tap to choose a color',12,p.secondary_text)
    for key,label in (('text:smaller','−'),('text:reset',f"{editor.preview['text_scale_percent']}%"),
                      ('text:larger','+'),('option:straight','STRAIGHT'),('option:rounded','ROUNDED'),
                      ('hide','HIDE CONTROLS'),('reset','RESET THEME'),('choose','CHOOSE THEME'),
                      ('back','CANCEL'),('save','APPLY')):
        active = key=='save' or key=='option:straight' and editor.preview['radius']==0 or key=='option:rounded' and editor.preview['radius']>0
        _button(ui,cache,boxes[key],label,active)
    _text(ui,cache,396+dx,436,'Tap the percentage for 100%',12,p.secondary_text)
    _text(ui,cache,732+dx,436,'Applies to interface controls',12,p.secondary_text)
    _text(ui,cache,36+dx,484,'FONT STYLE',13,p.section_heading)
    for identifier,label in FONT_STYLES:
        style = replace(ui.APP_UI_STYLE.button,font_family='theme-style:'+identifier)
        ui.draw_styled_text_button(cache,boxes['font:'+identifier],label,
            active=editor.preview.get('font_style','current')==identifier,style=style)
    _text(ui,cache,36+dx,600,'AM · 14.250 MHz · −73 dBm',17,width=952)


def _color_picker(ui, cache, editor, boxes):
    p = ui.APP_UI_STYLE.palette
    dx = _floating_panel(ui, editor)
    # Keep the picker operable even while previewing black text on a dark theme.
    ink = max(((0,0,0),(255,255,255)),key=lambda c:contrast(c,p.background))
    if contrast(p.text,p.background)>=3:
        ink = p.text
    muted = tuple(muted_text_color(ink,p.background))
    _text(ui,cache,36+dx,250,'COLOR',18,ink)
    _text(ui,cache,36+dx,276,'Preview on HOME. Save returns to Customize.',13,muted)
    for field,x,title,role in (('accent',36,'ACCENT COLOR','focus'),('text',524,'TEXT COLOR','text')):
        _text(ui,cache,x+dx,320,title,13,ink)
        chosen = editor.chosen_color(field)
        for choice,rgb in (('black',(0,0,0)),('white',(255,255,255))):
            box = boxes[f'color:{field}:{choice}']
            selected = chosen == list(rgb)
            a,b,c,d = box
            cx,cy = (a+c)/2,(b+d)/2
            half = COLOR_STRIP_HEIGHT/2
            ui.draw_logical_rounded_rect(cx-half,cy-half,cx+half,cy+half,0,(*rgb,255),(*ink,255),2 if selected else 1)
            if selected:
                check = (255,255,255) if choice == 'black' else (0,0,0)
                ui.draw_logical_line(cx-5,cy,cx-1,cy+4,check,2)
                ui.draw_logical_line(cx-1,cy+4,cx+6,cy-5,check,2)
                # An outer bracket remains visible beyond the small swatch.
                ui.draw_logical_rect(cx-half-4,cy-half-4,cx+half+4,cy-half-2,ink)
                ui.draw_logical_rect(cx-half-4,cy+half+2,cx+half+4,cy+half+4,ink)
                ui.draw_logical_rect(cx-half,cy+half+4,cx+half,cy+half+6,ink)
        a,b,c,d = boxes[f'color:{field}:rainbow']
        # A slim color strip with a taller touch lane.
        center_y = (b+d)/2
        b,d = center_y-COLOR_STRIP_HEIGHT/2,center_y+COLOR_STRIP_HEIGHT/2
        for i in range(256):
            ui.draw_logical_rect(a+(c-a)*i/256,b,c-(c-a)*(255-i)/256,d,(*rainbow_rgb(i/255),255))
        ui.draw_logical_rounded_rect(a,b,c,d,0,(0,0,0,0),(*ink,255),1)
        rgb = chosen
        if len(set(rgb)) > 1:
            hue,_,_ = colorsys.rgb_to_hsv(*(v/255 for v in rgb))
            marker_x = a+(c-a)*hue
            ui.draw_logical_rect(marker_x-3,b-4,marker_x+3,d+4,(0,0,0,255))
            ui.draw_logical_rect(marker_x-1,b-4,marker_x+1,d+4,(255,255,255,255))
        name = 'Black' if rgb == [0,0,0] else 'White' if rgb == [255,255,255] else 'Rainbow'
        _text(ui,cache,x+dx,416,'Selected: '+name+' · '+theme_system.color_hex(rgb),12,muted)
    button_ink = ink if contrast(ink,p.surface)>=3 else max(
        ((0,0,0),(255,255,255)),key=lambda c:contrast(c,p.surface))
    style = replace(ui.APP_UI_STYLE.button,palette=replace(p,text=button_ink))
    for field,x,y,title in (('color_intensity',36,460,'COLOR INTENSITY'),
                          ('border_intensity',524,460,'BORDER COLOR INTENSITY'),
                          ('saturation',36,548,'SATURATION')):
        low,high = INTENSITY_LIMITS[field]
        amount = editor.preview.get(field+'_percent',100 if field=='color_intensity' else 25)
        _text(ui,cache,x+dx,y,title,13,ink)
        ui.draw_display_slider_section(cache,boxes[field],f'{low}–{high}%',amount-low,high-low,f'{amount}%',True,
                                       detail_color=ink)
    for key,label in (('color:cancel','CANCEL'),('color:save','SAVE')):
        ui.draw_styled_text_button(cache,boxes[key],label,style=style)


def draw_theme_screen(cache, editor, ui):
    _home(ui,cache,editor)
    # Both floating panels follow the candidate without changing saved settings.
    with theme_system.preview_theme(editor.preview):
        boxes=theme_screen_boxes(editor)
        if editor.overlay == 'colors':
            _color_picker(ui,cache,editor,boxes)
        elif not editor.fullscreen:
            _chooser(ui,cache,editor,boxes)
        elif editor.fullscreen_controls:
            _inspector(ui,cache,editor,boxes)
        else:
            _button(ui,cache,boxes['show'],'SHOW THEME CONTROLS')
