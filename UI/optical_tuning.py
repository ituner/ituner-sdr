"""Zoom-relative optical tuning with fractional-Hz movement retention."""
import math

COUNTS_PER_REVOLUTION = 1440
SENSITIVITY = {'fine': .1, 'normal': 1.0, 'coarse': 4.0}


def step_hz(span_hz, mode='auto', sensitivity='normal', manual_hz=100):
    if mode == 'manual':
        return max(1.0, float(manual_hz)) * SENSITIVITY.get(sensitivity, 1.0)
    return max(1.0, float(span_hz)) * .25 * SENSITIVITY.get(sensitivity, 1.0) / COUNTS_PER_REVOLUTION


class OpticalTuning:
    def __init__(self):
        self.reset()

    def reset(self):
        self.remainder = 0.0
        self.context = None
        self.expected = None

    def target(self, current_khz, counts, span_hz, mode, sensitivity, manual_hz,
               identity, low_khz, high_khz, quantum_hz=1):
        increment = step_hz(span_hz, mode, sensitivity, manual_hz)
        context = (identity, mode, increment, low_khz, high_khz, quantum_hz)
        if (context != self.context or self.expected is None
                or abs(current_khz - self.expected) > 1e-8):
            self.remainder = 0.0
        self.context = context
        total = self.remainder + int(counts) * increment
        # Retain sub-Hz motion across UI frames, including reverse corrections.
        units = total / quantum_hz
        nearest = round(units)
        if abs(units - nearest) < 1e-9:
            units = nearest
        delta_hz = math.trunc(units) * quantum_hz
        requested = current_khz + delta_hz / 1000.0
        target = max(low_khz, min(high_khz, requested))
        self.remainder = total - delta_hz if target == requested else 0.0
        self.expected = target
        return target
