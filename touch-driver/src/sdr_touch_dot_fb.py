#!/usr/bin/env python3
import argparse
import errno
import mmap
import os
import select
import struct
import time
from pathlib import Path

from PIL import Image, ImageDraw


FB = Path("/dev/fb0")
SYS = Path("/sys/class/graphics/fb0")
EVENT_ROOT = Path("/sys/class/input")
LOGICAL_W = 960
LOGICAL_H = 320
ACTIVE_H = 400
EVENT_STRUCT = struct.Struct("qqHHi")
EV_KEY = 0x01
EV_ABS = 0x03
EV_SYN = 0x00
SYN_REPORT = 0x00
BTN_TOUCH = 0x14A
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39


def fb_info():
    w, h = map(int, (SYS / "virtual_size").read_text().strip().split(","))
    bpp = int((SYS / "bits_per_pixel").read_text())
    stride = int((SYS / "stride").read_text())
    if bpp != 32:
        raise SystemExit(f"expected 32bpp framebuffer, got {w}x{h}x{bpp}")
    if w < LOGICAL_H or h < LOGICAL_W:
        raise SystemExit(f"framebuffer {w}x{h} cannot hold logical {LOGICAL_W}x{LOGICAL_H}")
    return w, h, stride


def find_touch_event():
    for event in sorted(EVENT_ROOT.glob("event*")):
        name_file = event / "device/name"
        if not name_file.exists():
            continue
        name = name_file.read_text(errors="ignore").strip().lower()
        if "goodix" in name or "touchscreen" in name:
            return Path("/dev/input") / event.name
    raise SystemExit("could not find a Goodix/touchscreen event device")


def load_base(path):
    image = Image.open(path).convert("RGB")
    if image.size != (LOGICAL_W, LOGICAL_H):
        raise SystemExit(f"{path} is {image.size}, expected {(LOGICAL_W, LOGICAL_H)}")
    return image


def draw_frame(base, x=None, y=None, dot_size=130):
    frame = base.copy()
    if x is None or y is None:
        return frame

    d = ImageDraw.Draw(frame, "RGBA")
    radius = dot_size / 2
    box = (x - radius, y - radius, x + radius, y + radius)
    d.ellipse(box, fill=(66, 255, 99, 38), outline=(66, 255, 99, 255), width=4)
    d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(66, 255, 99, 255))
    d.ellipse(box, outline=(5, 16, 7, 220), width=1)
    return frame


def logical_to_native(logical, fb_w, fb_h, stride):
    if (fb_w, fb_h) != (ACTIVE_H, LOGICAL_W):
        raise SystemExit(f"expected framebuffer {(ACTIVE_H, LOGICAL_W)}, got {(fb_w, fb_h)}")

    active = Image.new("RGB", (LOGICAL_W, ACTIVE_H), (0, 0, 0))
    active.paste(logical, (0, 0))
    native = active.rotate(-90, expand=True)

    if stride == fb_w * 4:
        return native.tobytes("raw", "BGRX")

    packed = native.tobytes("raw", "BGRX")
    raw = bytearray(stride * fb_h)
    tight_stride = fb_w * 4
    for y in range(fb_h):
        raw[y * stride:y * stride + tight_stride] = packed[y * tight_stride:(y + 1) * tight_stride]
    return bytes(raw)


def write_frame(fb_map, base, x=None, y=None, dot_size=130):
    fb_w, fb_h, stride, mm = fb_map
    logical = draw_frame(base, x, y, dot_size)
    raw = logical_to_native(logical, fb_w, fb_h, stride)
    mm[:] = raw
    mm.flush()


def clamp(value, low, high):
    return max(low, min(high, value))


def transform_touch(x, y, args):
    if args.swap_x_y:
        x, y = y, x
    if args.invert_x:
        x = LOGICAL_W - 1 - x
    if args.invert_y:
        y = LOGICAL_H - 1 - y
    return clamp(x, 0, LOGICAL_W - 1), clamp(y, 0, LOGICAL_H - 1)


def main():
    parser = argparse.ArgumentParser(description="Draw SDR mockup plus a 60 px touch dot on /dev/fb0.")
    parser.add_argument("--image", type=Path, default=Path("renders/sdr-frontend-960x320.png"))
    parser.add_argument("--event", type=Path, help="input event device, defaults to auto-detected Goodix")
    parser.add_argument("--dot-size", type=int, default=130)
    parser.add_argument("--invert-x", action="store_true")
    parser.add_argument("--invert-y", action="store_true")
    parser.add_argument("--swap-x-y", action="store_true")
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args()

    fb_w, fb_h, stride = fb_info()
    base = load_base(args.image)
    event_path = args.event or find_touch_event()

    with FB.open("r+b") as fb, event_path.open("rb", buffering=0) as ev:
        os.set_blocking(ev.fileno(), False)
        mm = mmap.mmap(fb.fileno(), stride * fb_h)
        fb_map = (fb_w, fb_h, stride, mm)
        write_frame(fb_map, base, dot_size=args.dot_size)
        print(f"showing {args.image} on /dev/fb0; touch input {event_path}", flush=True)

        active = False
        x = y = None
        dirty = False
        min_frame_interval = 1.0 / args.fps if args.fps > 0 else 0
        next_frame = time.monotonic()
        while True:
            timeout = max(0, next_frame - time.monotonic()) if dirty else None
            readable, _, _ = select.select([ev], [], [], timeout)
            if not readable:
                if dirty:
                    if active and x is not None and y is not None:
                        tx, ty = transform_touch(x, y, args)
                        write_frame(fb_map, base, tx, ty, args.dot_size)
                    else:
                        write_frame(fb_map, base, dot_size=args.dot_size)
                    dirty = False
                    next_frame = time.monotonic() + min_frame_interval
                continue

            while True:
                try:
                    data = os.read(ev.fileno(), EVENT_STRUCT.size)
                except BlockingIOError:
                    break
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    raise

                if not data or len(data) != EVENT_STRUCT.size:
                    break

                _, _, event_type, code, value = EVENT_STRUCT.unpack(data)
                if event_type == EV_ABS:
                    if code in (ABS_X, ABS_MT_POSITION_X):
                        x = clamp(value, 0, LOGICAL_W - 1)
                        dirty = True
                    elif code in (ABS_Y, ABS_MT_POSITION_Y):
                        y = clamp(value, 0, LOGICAL_H - 1)
                        dirty = True
                    elif code == ABS_MT_TRACKING_ID and value < 0:
                        active = False
                        dirty = True
                elif event_type == EV_KEY and code == BTN_TOUCH:
                    active = value == 1
                    dirty = True

            if dirty and time.monotonic() >= next_frame:
                if active and x is not None and y is not None:
                    tx, ty = transform_touch(x, y, args)
                    write_frame(fb_map, base, tx, ty, args.dot_size)
                else:
                    write_frame(fb_map, base, dot_size=args.dot_size)
                dirty = False
                next_frame = time.monotonic() + min_frame_interval


if __name__ == "__main__":
    main()
