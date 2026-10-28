"""Master volume and mute share one remembered audible level."""
class MainVolumeControl:
    def __init__(self, volume, setter, set_muted, threshold=0.005):
        self.volume = volume
        self.threshold = threshold
        self.last_audible = volume if volume > threshold else 0.5
        self.setter = setter
        self.set_muted = set_muted

    def apply(self, volume):
        applied = self.setter(volume)
        if applied is not None:
            self.volume = applied
            if applied > self.threshold:
                self.last_audible = applied
            self.set_muted(applied <= self.threshold)
        return applied

    def mute(self, muted):
        if muted:
            if self.volume > self.threshold:
                self.last_audible = self.volume
            self.set_muted(True)
            return self.volume
        return self.apply(self.last_audible)
