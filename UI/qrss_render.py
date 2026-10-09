"""Readable QRSS plot annotations, shared by live and archived captures."""
from functools import lru_cache
import time
from PIL import Image, ImageDraw, ImageFont

PLOT_WIDTH, PLOT_HEIGHT = 1600, 280
PLOT_LEFT, PLOT_TOP = 190, 55
CANVAS_SIZE = (1808, 390)
BACKGROUND = (7, 18, 25)
RENDER_VERSION = 2


@lru_cache(maxsize=1)
def legend_font():
    for name in ('DejaVuSans.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/System/Library/Fonts/Supplemental/Arial.ttf'):
        try:
            return ImageFont.truetype(name, 30)
        except OSError:
            pass
    # Older Pillow has only a small bitmap default: scale it rather than
    # silently returning unreadably small annotations.
    try:
        return ImageFont.load_default(size=30)
    except TypeError:
        return None


def annotate_plot(plot, item):
    canvas = Image.new('RGB', CANVAS_SIZE, BACKGROUND)
    canvas.paste(plot.resize((PLOT_WIDTH, PLOT_HEIGHT), Image.Resampling.BOX),
                 (PLOT_LEFT, PLOT_TOP))
    draw = ImageDraw.Draw(canvas)
    font = legend_font()

    def label(x, y, text, color='white', anchor='lt'):
        if font is not None:
            draw.text((x, y), text, font=font, fill=color, anchor=anchor)
            return
        # Compatibility fallback for systems without TrueType fonts.
        small = ImageFont.load_default()
        box = small.getbbox(text)
        tile = Image.new('RGBA', (box[2]-box[0], box[3]-box[1]))
        ImageDraw.Draw(tile).text((-box[0], -box[1]), text, font=small, fill=color)
        tile = tile.resize((tile.width*3, tile.height*3), Image.Resampling.NEAREST)
        if anchor[0]=='r': x -= tile.width
        elif anchor[0]=='m': x -= tile.width/2
        if anchor[1]=='m': y -= tile.height/2
        canvas.paste(tile, (round(x), round(y)), tile)

    center = item['rf_hz']
    half = item['span_hz']/2
    label(8, 8, 'MHz RF')
    for fraction, hz in ((0, center+half), (.5, center), (1, center-half)):
        y = PLOT_TOP + fraction*PLOT_HEIGHT
        label(PLOT_LEFT-12, max(PLOT_TOP+15, min(PLOT_TOP+PLOT_HEIGHT-15, y)),
              f'{hz/1e6:.6f}', anchor='rm')
    started = item['received_at']
    label(PLOT_LEFT, 8, time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(started)))
    duration = item['duration_seconds']
    window = item.get('window_seconds', duration) or 1
    label(PLOT_LEFT, 350, 'Time → 0 s')
    label(PLOT_LEFT+PLOT_WIDTH/2, 350, f'{window/2:g} s', anchor='mt')
    label(PLOT_LEFT+PLOT_WIDTH, 350, f'{window:g} s', anchor='rt')
    label(PLOT_LEFT+PLOT_WIDTH, 8, f'Received {duration:.0f} / {window:g} s', anchor='rt')
    acquisition = item.get('acquisition', {})
    if acquisition.get('state')=='locked':
        label(850, 8, f"AUTO · {acquisition['track_count']} signals", (255,190,90))
        for track in item.get('tracks', []):
            if not track['active']: continue
            y = PLOT_TOP+PLOT_HEIGHT*(center+half-track['rf_hz'])/item['span_hz']
            if not PLOT_TOP<=y<=PLOT_TOP+PLOT_HEIGHT: continue
            draw.line((PLOT_LEFT-5,y,PLOT_LEFT+8,y), fill=(255,150,40), width=3)
            label(PLOT_LEFT+12, max(PLOT_TOP,min(PLOT_TOP+PLOT_HEIGHT-32,y-32)),
                  track['id'], (255,190,90))
    else:
        y = PLOT_TOP+PLOT_HEIGHT/2
        draw.line((PLOT_LEFT-5,y,PLOT_LEFT+5,y), fill=(255,150,40), width=3)
    return canvas


def restyle_capture(image, item):
    """Relabel an older PNG without changing its received spectrum or time span."""
    box = item.get('plot_box', (90, 35, image.width-10, 355))
    return annotate_plot(image.crop(box), item)


def rendering_metadata():
    return dict(render_version=RENDER_VERSION, width=CANVAS_SIZE[0], height=CANVAS_SIZE[1],
                plot_box=[PLOT_LEFT,PLOT_TOP,PLOT_LEFT+PLOT_WIDTH,PLOT_TOP+PLOT_HEIGHT])
