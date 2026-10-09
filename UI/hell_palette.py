"""QRSS blue/cyan/white display palette; retain grayscale originals for OCR."""
import os
import threading
import time
from PIL import Image

_lock = threading.Lock()
_next_cleanup = {}
_palette = []
for gray in range(256):
    strength = (255-gray)/255
    _palette.extend(int(min(1,max(0,value))*255) for value in
                    (3*strength-1,2*strength,3*strength))


def display_path(source):
    source = source.resolve()
    directory = source.parent / '.display-qrss-v1'
    target = directory / source.name
    with _lock:
        stamp = source.stat()
        if target.is_file() and target.stat().st_mtime_ns == stamp.st_mtime_ns:
            return target
        directory.mkdir(exist_ok=True)
        with Image.open(source) as original:
            image = original.convert('L').convert('P')
            image.putpalette(_palette)
            image = image.convert('RGB')
        temporary = target.with_suffix('.tmp')
        image.save(temporary,format='PNG')
        os.utime(temporary,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        temporary.replace(target)
        if time.monotonic() >= _next_cleanup.get(directory,0):
            for cached in directory.glob('*.png'):
                if not (source.parent/cached.name).exists():cached.unlink(missing_ok=True)
            _next_cleanup[directory] = time.monotonic()+60
        return target
