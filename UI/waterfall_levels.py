"""Automatic display contrast shared by native waterfall views."""


class AutoWaterfallLevels:
    """Adapt display contrast to the current RF window with bounded smoothing."""

    def __init__(self):
        self.floor = self.ceiling = None

    def levels_for(self, samples):
        if not samples:
            return (0, 28) if self.floor is None else (self.floor, self.ceiling)
        ordered = sorted(samples)
        floor = max(0, ordered[len(ordered)//5]-5)
        ceiling = min(255, max(ordered[min(len(ordered)-1, int(len(ordered)*.98))]+4,
                               floor+28))
        floor = min(floor, ceiling-28)
        if self.floor is None:
            self.floor, self.ceiling = floor, ceiling
        else:
            self.floor = .82*self.floor+.18*floor
            self.ceiling = .82*self.ceiling+.18*ceiling
        return self.floor, self.ceiling

