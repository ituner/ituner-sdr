#!/usr/bin/env python3
"""Display a continuously refreshed view of the live Pi OpenGL SDR screen."""

import argparse
import io
import os
import queue
import subprocess
import threading
import time
import tkinter as tk

from PIL import Image, ImageTk


REMOTE_CAPTURE = r'''
file=/tmp/kiwi-gl-display.png
before=$(stat -c %y "$file" 2>/dev/null || true)
pid=$(systemctl show -p MainPID --value kiwi-gl-display.service)
test "$pid" -gt 0
kill -USR1 "$pid"
for _ in $(seq 1 20); do
    after=$(stat -c %y "$file" 2>/dev/null || true)
    if [ -n "$after" ] && [ "$after" != "$before" ]; then
        # pygame writes the timestamp before the PNG payload is complete.
        sleep 0.15
        cat "$file"
        exit 0
    fi
    sleep 0.05
done
cat "$file"
'''.strip()


def capture_frame(host, user, key, timeout):
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-i",
        key,
        f"{user}@{host}",
        REMOTE_CAPTURE,
    ]
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode:
        error = result.stderr.decode("utf-8", "replace").strip() or "SSH capture failed"
        raise RuntimeError(error)
    frame = Image.open(io.BytesIO(result.stdout)).convert("RGB")
    # Pi framebuffer is 400x960; -90 degrees puts Home at the left. The active
    # 960x320 panel occupies the lower 320 pixels of the resulting 960x400 frame.
    upright = frame.rotate(-90, expand=True)
    return upright.crop((0, 80, 960, 400))


class Preview:
    def __init__(self, root, host, user, key, fps):
        self.root = root
        self.host = host
        self.user = user
        self.key = key
        self.interval = 1.0 / fps
        self.stop = threading.Event()
        self.frames = queue.Queue(maxsize=1)
        self.image_ref = None

        root.title(f"P5 SDR live preview - {host}")
        root.resizable(False, False)
        root.configure(background="black")
        self.canvas = tk.Label(root, width=960, height=320, bg="black", fg="#b7c8cf", font=("Menlo", 16))
        self.canvas.pack()
        self.canvas.configure(text="Connecting to P5...")
        root.bind("<Escape>", self.close)
        root.bind("q", self.close)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.worker = threading.Thread(target=self._refresh_loop, name="p5-live-preview", daemon=True)
        self.worker.start()
        self.poll()

    def _put(self, item):
        try:
            self.frames.get_nowait()
        except queue.Empty:
            pass
        self.frames.put_nowait(item)

    def _refresh_loop(self):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                self._put(("frame", capture_frame(self.host, self.user, self.key, 8)))
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                self._put(("error", str(error)))
            remaining = self.interval - (time.monotonic() - started)
            self.stop.wait(max(0.02, remaining))

    def poll(self):
        try:
            while True:
                kind, payload = self.frames.get_nowait()
                if kind == "frame":
                    self.image_ref = ImageTk.PhotoImage(payload)
                    self.canvas.configure(image=self.image_ref, text="")
                else:
                    self.canvas.configure(image="", text=f"P5 preview unavailable\n{payload}")
        except queue.Empty:
            pass
        if not self.stop.is_set():
            self.root.after(30, self.poll)

    def close(self, _event=None):
        self.stop.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Live 960x320 preview of the Pi SDR OpenGL display.")
    parser.add_argument("--host", default=os.environ.get("P5_HOST", "10.0.0.151"))
    parser.add_argument("--user", default=os.environ.get("P5_USER", "ituner"))
    parser.add_argument("--key", default=os.environ.get("P5_KEY", os.path.expanduser("~/.ssh/id_ed25519_p4")))
    parser.add_argument("--fps", type=float, default=2.0, help="Capture refresh rate, 1 to 5 fps (default: 2).")
    args = parser.parse_args()
    fps = min(5.0, max(1.0, args.fps))

    root = tk.Tk()
    Preview(root, args.host, args.user, args.key, fps)
    root.mainloop()


if __name__ == "__main__":
    main()
