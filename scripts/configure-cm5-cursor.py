#!/usr/bin/env python3
"""Hide the appliance session pointer without changing touch/input mapping."""
import argparse
from pathlib import Path
import struct


def configure(home, icons=Path('/usr/share/icons')):
    home = Path(home)
    theme = home / '.icons/ituner-invisible'
    cursors = theme / 'cursors'
    cursors.mkdir(parents=True, exist_ok=True)
    # Xcursor header, one image TOC entry, 1x1 transparent ARGB image.
    image_type = 0xfffd0002
    data = struct.pack('<4sIII', b'Xcur', 16, 0x10000, 1)
    data += struct.pack('<III', image_type, 24, 28)
    data += struct.pack('<IIIIIIIII', 36, image_type, 24, 1, 1, 1, 0, 0, 0)
    data += struct.pack('<I', 0)
    names = {'default', 'left_ptr', 'arrow', 'top_left_arrow', 'watch', 'wait',
             'progress', 'left_ptr_watch', 'hand1', 'hand2', 'pointer', 'text',
             'xterm', 'crosshair', 'move', 'not-allowed', 'none'}
    # Cover aliases in installed themes too, avoiding fallback visible shapes.
    names.update(p.name for p in Path(icons).glob('*/cursors/*'))
    for name in names:
        (cursors / name).write_bytes(data)
    (theme / 'index.theme').write_text('[Icon Theme]\nName=iTuner invisible cursor\n')
    env = home / '.config/labwc/environment.d/99-ituner-cursor.env'
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('XCURSOR_THEME=ituner-invisible\nXCURSOR_SIZE=24\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args()
    configure(args.home)
