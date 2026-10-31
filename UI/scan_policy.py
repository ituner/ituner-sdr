"""Bounded scan-resolution trials with compulsory reference sweeps.

This is a conservative feedback policy, not a claim of optimal detection:
unknown weak signals can still first appear during a later narrow audit.
Every accepted pass covers the entire allocation; timeouts are never absence.
"""
import math
import time


def window_count(bandwidth_hz, zoom, low, high):
    span = bandwidth_hz/(2**zoom*1000)
    width = min(bandwidth_hz/1000, high+8)-max(0, low-8)
    return max(1, math.ceil(max(0, width-span)/(span-16))+1) if span > 16 else 0


def coverage_windows(bandwidth_hz, zoom, low, high):
    """The same overlapping RF grid for references, trials and follow-ups."""
    span = bandwidth_hz/(2**zoom*1000)
    low,high = max(0,low-8),min(bandwidth_hz/1000,high+8)
    count = window_count(bandwidth_hz,zoom,low+8,high-8)
    if not count or high<=low:
        return []
    first = low+min(high-low,span)/2
    last = high-min(high-low,span)/2
    return [first+(last-first)*i/max(1,count-1) for i in range(count)]


class ScanPolicy:
    MAX_WIDE_PASSES = 3
    FAILURE_COOLDOWN = 3
    MAX_WIDE_BIN_HZ = 250
    MIN_PROMINENCE = 18
    WATCH_SECONDS = 2*60*60

    def __init__(self):
        self.profiles = {}

    def plan(self, key, bandwidth_hz, zoom_cap, low, high):
        narrow = min(8, int(zoom_cap))
        profile = self.profiles.get(key)
        wide = min(narrow, max(7, math.ceil(math.log2(
            bandwidth_hz/(1024*self.MAX_WIDE_BIN_HZ)))))
        if (not profile or profile['cooldown'] or profile.get('unspecified')
                or profile['wide_passes'] >= self.MAX_WIDE_PASSES
                or window_count(bandwidth_hz, wide, low, high) + len(self.refinement_windows(
                    key,profile.get('candidates',()),
                    [freq for freq,hits in profile.get('lines',{}).items() if hits<2],
                    bandwidth_hz,zoom_cap)) >=
                   window_count(bandwidth_hz, narrow, low, high)):
            return narrow
        return wide

    @classmethod
    def restricted(cls, candidates):
        frequencies = sorted(c.tuning_khz for c in candidates)
        return (any(c.prominence < cls.MIN_PROMINENCE for c in candidates)
                or any(b-a < 8 for a, b in zip(frequencies, frequencies[1:])))

    def finish(self, key, zoom, zoom_cap, candidates, complete, uncertain=False, now=None):
        """Return True only when a wider pass must be repeated narrowly now."""
        profile = self.profiles.get(key)
        narrow = min(8, int(zoom_cap))
        if not complete:
            if profile:
                profile['cooldown'] = self.FAILURE_COOLDOWN
            return False
        if zoom < narrow:
            missing = profile is None or any(
                not any(abs(freq-c.tuning_khz) < .75 for c in candidates)
                for freq in profile.get('watch',profile['reference']))
            lines = () if isinstance(uncertain,bool) else uncertain
            pending = uncertain is True or any(not self.known_line(profile,freq) for freq in lines)
            unexpected = missing or uncertain is True or any(
                not any(abs(freq-old)<.75 for old in profile.get('lines',{})) for freq in lines)
            if missing or pending or self.restricted(candidates):
                if profile:
                    profile['unexpected'] = unexpected
                    if unexpected:
                        profile['cooldown'] = self.FAILURE_COOLDOWN
                return True
            profile['wide_passes'] += 1
            # New detections also become evidence that the next wide sweep
            # must preserve. A later miss triggers a full narrow recheck.
            profile['reference'] = tuple(c.tuning_khz for c in candidates)
            profile['candidates'] = tuple(candidates)
            profile['watch'] = self.watch_counts(profile,candidates,now=now)
        else:
            self.profiles[key] = dict(reference=tuple(c.tuning_khz for c in candidates),
                restricted=uncertain or self.restricted(candidates), wide_passes=0,
                candidates=tuple(candidates),unspecified=uncertain is True,
                lines=self.line_counts(profile,uncertain,replace=True),
                watch=self.watch_counts(profile,candidates,now=now),
                cooldown=max(0, profile['cooldown']-1) if profile else 0)
        return False

    @staticmethod
    def known_line(profile,freq):
        return bool(profile) and any(abs(freq-old)<.75 and hits>=2
                                    for old,hits in profile.get('lines',{}).items())

    @staticmethod
    def line_counts(profile,observed,replace=False):
        previous = profile.get('lines',{}) if profile else {}
        result = {} if replace else dict(previous)
        if isinstance(observed,bool):
            return result
        seen = []
        for freq in observed:
            if any(abs(freq-other)<.75 for other in seen):
                continue
            seen.append(freq)
            hits = max((hits for old,hits in previous.items() if abs(freq-old)<.75),default=0)
            for old in list(result):
                if abs(freq-old)<.75:
                    del result[old]
            result[freq] = min(3,hits+1)
        return result

    @classmethod
    def watch_counts(cls,profile,candidates,now=None):
        """Remember fading stations without counting an absent one as present."""
        now = time.monotonic() if now is None else now
        previous = profile.get('watch',{}) if profile else {}
        result = {freq:stamp for freq,stamp in previous.items()
                  if 0<=now-stamp<cls.WATCH_SECONDS
                  and not any(abs(freq-c.tuning_khz)<.75 for c in candidates)}
        for candidate in candidates:
            result[candidate.tuning_khz] = now
        return result

    def order_windows(self, key, windows, span, previous_center=None):
        """Visit productive views first; nearest view wins ties. Omit none."""
        profile = self.profiles.get(key,{})
        reference = profile.get('reference') or profile.get('watch',())
        remaining, result = list(windows), []
        while remaining:
            def priority(center):
                hits = sum(abs(freq-center) <= span/2-8 for freq in reference)
                return (-hits, abs(center-previous_center) if previous_center is not None else center)
            center = min(remaining,key=priority)
            result.append(center)
            remaining.remove(center)
            previous_center = center
        return result

    def refinement_windows(self, key, candidates, uncertain, bandwidth_hz, zoom_cap):
        """Minimum subset of reference-grid views covering suspect carriers.

        Reusing the reference grid avoids introducing a new FFT alignment
        when checking a marginal carrier. Among views covering the leftmost
        suspect, the furthest-right view cannot require more later views.
        The preceding wider sweep has already covered the rest of the band.
        """
        targets = self.refinement_targets(key,candidates,uncertain)
        return self.cover_targets(key,targets,bandwidth_hz,min(8,int(zoom_cap)))

    def refinement_targets(self,key,candidates,uncertain):
        profile = self.profiles.get(key,{})
        reference = profile.get('watch',profile.get('reference',()))
        targets = [freq for freq in reference
                   if not any(abs(freq-c.tuning_khz)<.75 for c in candidates)]
        targets += [freq for freq in uncertain
                    if not self.known_line(self.profiles.get(key),freq)
                    and not any(abs(freq-c.tuning_khz)<.75 for c in candidates)]
        targets += [c.tuning_khz for c in candidates if c.prominence<self.MIN_PROMINENCE]
        frequencies = sorted(c.tuning_khz for c in candidates)
        for a,b in zip(frequencies,frequencies[1:]):
            if b-a<8:
                targets.extend((a,b))
        return targets

    @staticmethod
    def cover_targets(key,targets,bandwidth_hz,zoom):
        usable = bandwidth_hz/(2**zoom*1000)-16
        grid = coverage_windows(bandwidth_hz,zoom,*key[1:3])
        targets = sorted(set(targets))
        windows = []
        while targets:
            first = targets[0]
            choices = [center for center in grid if abs(center-first)<=usable/2+1e-8]
            if not choices:
                return grid  # uncertain geometry requires full reference coverage
            center = max(choices)
            windows.append(center)
            targets = [freq for freq in targets if freq>center+usable/2+1e-8]
        return windows

    def refinement_plan(self,key,candidates,uncertain,bandwidth_hz,zoom_cap):
        windows = self.refinement_windows(key,candidates,uncertain,bandwidth_hz,zoom_cap)
        zoom = min(8,int(zoom_cap))
        if not windows:
            return windows,zoom
        targets = self.refinement_targets(key,candidates,uncertain)
        # Spend the same view budget on better frequency resolution when the
        # suspect group fits. No extra view command is needed to gain detail.
        for finer in range(min(10,int(zoom_cap)),zoom,-1):
            if bandwidth_hz/(2**finer*1000)<20:
                continue
            fine_windows = self.cover_targets(key,targets,bandwidth_hz,finer)
            if fine_windows and len(fine_windows)<=len(windows):
                return fine_windows,finer
        return windows,zoom

    def finish_refinement(self, key, candidates, complete, uncertain=False, now=None):
        profile = self.profiles.get(key)
        if profile is None:
            return
        unexpected = profile.pop('unexpected',True)
        if unexpected or not complete:
            profile['cooldown'] = self.FAILURE_COOLDOWN
            profile['wide_passes'] = self.MAX_WIDE_PASSES
        else:
            profile['wide_passes'] += 1
        if complete:
            profile['reference'] = tuple(c.tuning_khz for c in candidates)
            profile['restricted'] = uncertain or self.restricted(candidates)
            profile['candidates'] = tuple(candidates)
            profile['watch'] = self.watch_counts(profile,candidates,now=now)
            profile['lines'] = self.line_counts(profile,uncertain)
            profile['unspecified'] = uncertain is True

    def rank_bands(self, receiver_context, bands, bandwidth_hz, zoom_cap, hints=None, origin=None):
        """A cycle remains exhaustive, even when all prior observations were empty."""
        hints = hints or {}
        labels = [band[2] for band in bands]
        def priority(band):
            low, high, label = band
            distance = abs(labels.index(label)-labels.index(origin)) if origin in labels else 0
            hint = hints.get(label,0)/(1+.2*distance)
            key = (receiver_context,low,high,bandwidth_hz,int(zoom_cap))
            profile = self.profiles.get(key)
            if profile:
                zoom = self.plan(key,bandwidth_hz,zoom_cap,low,high)
                cost = window_count(bandwidth_hz,zoom,low,high)
                if zoom<min(8,int(zoom_cap)):
                    cost += len(self.refinement_windows(key,profile.get('candidates',()),
                        [freq for freq,hits in profile.get('lines',{}).items() if hits<2],bandwidth_hz,zoom_cap))
                yield_per_view = len(profile['reference'])/max(1,cost)
                return (not bool(profile['reference']),-yield_per_view,-hint,distance,low)
            return (hints.get(label,0)<6,0,-hint,distance,low)
        return sorted(bands,key=priority)
