"""Additional conventional VIS SSTV modes (timings in seconds).

References: the original Dayton SSTV specifications, QSSTV's SSTVTable,
and the independent PySSTV encoder. See docs/sstv.md for validation scope.
These extend the bundled decoder without adding runtime dependencies.
"""
from sstv_vendor import spec


def raster(name, width, height, scan, sync, porch, gap, color=spec.COL_FMT.RGB, channels=3):
    offsets = [sync+porch+i*(scan+gap) for i in range(channels)]
    return type(name.replace(' ', ''), (), dict(
        NAME=name, LINE_WIDTH=width, LINE_COUNT=height, SCAN_TIME=scan,
        SYNC_PULSE=sync, SYNC_PORCH=porch, SEP_PULSE=gap,
        CHAN_COUNT=channels, CHAN_SYNC=0, CHAN_OFFSETS=offsets,
        LINE_TIME=sync+porch+channels*(scan+gap), PIXEL_TIME=scan/width,
        WINDOW_FACTOR=max(1.0, .001/ (scan/width)), COLOR=color,
        HAS_START_SYNC=False, HAS_HALF_SCAN=False, HAS_ALT_SCAN=False,
        BATCH_SCAN=True))


def pd(name, width, height, pixel):
    mode = raster(name, width, height//2, width*pixel, .020, .00208, 0,
                  spec.COL_FMT.YUV, 4)
    mode.PAIRED_LINES = True
    return mode


ADDITIONAL_MODES = {
    32: type('Martin4', (spec.M2,), {'NAME': 'Martin 4', 'LINE_COUNT': 128}),
    36: type('Martin3', (spec.M1,), {'NAME': 'Martin 3', 'LINE_COUNT': 128}),
    48: type('Scottie4', (spec.S2,), {'NAME': 'Scottie 4', 'LINE_COUNT': 128}),
    52: type('Scottie3', (spec.S1,), {'NAME': 'Scottie 3', 'LINE_COUNT': 128}),
    2: raster('Robot 8 B/W', 160, 120, .060, .007, 0, 0, spec.COL_FMT.BW, 1),
    6: raster('Robot 12 B/W', 160, 120, .093, .007, 0, 0, spec.COL_FMT.BW, 1),
    10: raster('Robot 24 B/W', 320, 240, .093, .007, 0, 0, spec.COL_FMT.BW, 1),
    14: raster('Robot 36 B/W', 320, 240, .143, .007, 0, 0, spec.COL_FMT.BW, 1),
    93: pd('PD 50', 320, 256, .000286),
    99: pd('PD 90', 320, 256, .000532),
    95: pd('PD 120', 640, 496, .000190),
    98: pd('PD 160', 512, 400, .000382),
    96: pd('PD 180', 640, 496, .000286),
    97: pd('PD 240', 640, 496, .000382),
    94: pd('PD 290', 800, 616, .000286),
    59: raster('Wraase SC2-60', 320, 256, .078, .0055225, .0005, 0),
    63: raster('Wraase SC2-120', 320, 256, .156, .0055225, .0005, .0005),
    55: raster('Wraase SC2-180', 320, 256, .235, .0055225, .0005, 0),
}
for code, name, rate in ((113, 'Pasokon P3', 4800), (114, 'Pasokon P5', 3200), (115, 'Pasokon P7', 2400)):
    ADDITIONAL_MODES[code] = raster(name, 640, 496, 640/rate, 25/rate, 5/rate, 5/rate)

# Robot 24 transmits Y, R-Y, B-Y on each of 120 lines.
r24 = type('Robot24', (spec.R72,), dict(NAME='Robot 24', LINE_WIDTH=160, LINE_COUNT=120,
    SCAN_TIME=.092, HALF_SCAN_TIME=.046, SYNC_PULSE=.006, SYNC_PORCH=.002,
    SEP_PULSE=.003, SEP_PORCH=.001, CHAN_OFFSETS=[.008, .104, .154],
    LINE_TIME=.200, PIXEL_TIME=.092/160, HALF_PIXEL_TIME=.046/160, WINDOW_FACTOR=2.0))
ADDITIONAL_MODES[4] = r24
spec.VIS_MAP.update(ADDITIONAL_MODES)

# Extended VIS modes, from their author's public specification (MMSSTV mode.txt).
EXTENDED_VIS_MAP = {}
for code, name, scan in ((0x2523,'MP73',.140),(0x2923,'MP115',.223),
                         (0x2a23,'MP140',.270),(0x2c23,'MP175',.340)):
    mode = raster(name,320,128,scan,.009,.001,0,spec.COL_FMT.YUV,4)
    mode.PAIRED_LINES = True
    EXTENDED_VIS_MAP[code] = mode
for code, name, width, height, scan in (
    (0x4523,'MR73',320,256,.138),(0x4623,'MR90',320,256,.171),
    (0x4923,'MR115',320,256,.220),(0x4a23,'MR140',320,256,.269),
    (0x4c23,'MR175',320,256,.337),(0x8523,'ML180',640,496,.1765),
    (0x8623,'ML240',640,496,.2365),(0x8923,'ML280',640,496,.2775),
    (0x8a23,'ML320',640,496,.3175)):
    mode = raster(name,width,height,scan,.009,.001,.0001,spec.COL_FMT.YUV)
    mode.CHAN_OFFSETS = [.010, .010+scan+.0001, .010+1.5*scan+.0002]
    mode.CHANNEL_PIXEL_TIMES = [scan/width, scan/(2*width), scan/(2*width)]
    mode.LINE_TIME = .010+2*scan+.0003
    EXTENDED_VIS_MAP[code] = mode

NARROW_VIS_MAP = {}
for code, name, scan in ((2,'MP73-N',.140),(4,'MP110-N',.212),(5,'MP140-N',.270)):
    mode = raster(name,320,128,scan,.009,.001,0,spec.COL_FMT.YUV,4)
    mode.PAIRED_LINES = True
    NARROW_VIS_MAP[code] = mode
for code, name, scan in ((0x14,'MC110-N',.140),(0x15,'MC140-N',.180),(0x16,'MC180-N',.232)):
    NARROW_VIS_MAP[code] = raster(name,320,256,scan,.008,.0005,0)
for mode in NARROW_VIS_MAP.values():
    mode.NARROW = True

MODE_COUNT = len(spec.VIS_MAP)+len(EXTENDED_VIS_MAP)+len(NARROW_VIS_MAP)
