"""Presentation-only pacing for streaming speech captions."""
import time


class CaptionReveal:
    def __init__(self):
        self.context = None
        self.streams = {}

    def reset_for(self, context):
        if context != self.context:
            self.context = context
            self.streams.clear()

    def reveal(self, text, channel='main', now=None):
        now = time.monotonic() if now is None else now
        words = str(text).split()
        old, visible, last, interval = self.streams.get(channel, ([], 0, now, 0.12))
        if words != old:
            # A rolling caption history drops completed phrases from its front.
            # Preserve progress through the suffix that is still on screen.
            shift = next((i for i in range(len(old))
                          if old[i:] == words[:len(old) - i]), None)
            if shift is not None:
                visible = max(0, visible - shift)
            else:
                # Recognizers revise partial hypotheses. Keep the stable prefix
                # and reveal the corrected ending without replaying old words.
                common = 0
                for a, b in zip(old, words):
                    if a != b:
                        break
                    common += 1
                visible = min(visible, common)
            if not old or visible >= len(old):
                last = now
            if visible == 0 and words:
                visible = 1
                last = now
            interval = min(0.12, 1.0 / max(1, len(words) - visible))
        pending = len(words) - visible
        if pending > 0:
            # Normal speech: ~8 words/s. Larger batches catch up in about a
            # second, without timers, sleeps or work on the audio thread.
            steps = max(0, int((now - last) / interval))
            if steps:
                visible = min(len(words), visible + steps)
                last += steps * interval
        else:
            last = now
        self.streams[channel] = (words, visible, last, interval)
        return ' '.join(words[:visible])
