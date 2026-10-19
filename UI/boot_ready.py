"""Small boot-readiness marker shared by the renderer and CM5 installer."""

from pathlib import Path


def mark_boot_ready(path):
    """Publish readiness after the first complete frame reaches the display."""
    if not path:
        return False
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ready\n", encoding="utf-8")
    except OSError as exc:
        print(f"gl boot ready marker {exc}", flush=True)
        return False
    print(f"gl boot ready {target}", flush=True)
    return True
