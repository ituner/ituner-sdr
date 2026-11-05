"""Small, bundled label-font choices; numeric instrument faces stay fixed."""
from pathlib import Path

FONT_STYLES = (('current','Current'),('clean','Clean'),('instrument','Instrument'),
               ('classic','Classic'),('readable','Readable'))
FONT_ROOT = Path(__file__).resolve().parent.parent/'assets'/'fonts'
FONT_FILES = {'current':('roboto','Roboto'), 'clean':('liberation','LiberationSans'),
              'instrument':('liberation','LiberationMono'),
              'classic':('liberation','LiberationSerif'), 'readable':('dejavu','DejaVuSans')}
LABEL_FAMILIES = {'Roboto','Inter','DejaVu Sans','Liberation Sans','Cantarell','sans','sans-serif'}


def resolve_font_path(style, *, family=None, mono=False, bold=False):
    """Resolve labels or explicit samples, leaving dedicated instrument fonts alone."""
    if isinstance(family,str) and family.startswith('theme-style:'):
        style = family.split(':',1)[1]
    else:
        families = (family,) if isinstance(family,str) else tuple(family or ())
        if style == 'current' or mono or (families and not set(families).issubset(LABEL_FAMILIES)):
            return None
    directory,name = FONT_FILES.get(style,FONT_FILES['current'])
    suffix = '-Bold.ttf' if bold else '.ttf' if directory == 'dejavu' else '-Regular.ttf'
    return str(FONT_ROOT/directory/(name+suffix))
