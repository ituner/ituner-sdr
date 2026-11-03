"""System RAM headroom, sampled slowly rather than once per rendered frame."""
from pathlib import Path
import time


def parse_meminfo(text):
    values = {}
    for line in text.splitlines():
        name, _, value = line.partition(':')
        if value.strip():
            try:
                values[name] = int(value.split()[0])
            except ValueError:
                continue
    total = values.get('MemTotal', 0)
    if total <= 0 or 'MemAvailable' not in values:
        return None
    available = max(0, min(total, values['MemAvailable']))
    return (total - available) / 1024, total / 1024


_sample = None
_sampled_at = float('-inf')


def read_system_ram_mb():
    """Used/total MiB; reclaimable cache is available, not application use."""
    global _sample, _sampled_at
    now = time.monotonic()
    if now - _sampled_at >= 2:
        try:
            _sample = parse_meminfo(Path('/proc/meminfo').read_text())
        except OSError:
            _sample = None
        _sampled_at = now
    return _sample


def system_ram_label():
    sample = read_system_ram_mb()
    return f'RAM {sample[0]/1024:.1f}/{sample[1]/1024:.1f} GB' if sample else 'RAM --'
