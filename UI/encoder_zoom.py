"""Apply physical zoom only to a workspace's visible, zoomable content."""


def zoom_factor(steps):
    """One clockwise detent increases magnification by ten percent."""
    return 1.10 ** max(-100, min(100, int(steps)))


class ContinuousHomeZoom:
    """Fractional viewport span without pretending SDR protocol levels are fractional."""
    def __init__(self):
        self.context = None
        self.target_span = None

    def span(self, source, level, native_span):
        if self.context != (source, level):
            self.context = None
            self.target_span = None
        return native_span if self.target_span is None else self.target_span

    def step(self, source, level, current_span, steps, minimum, maximum, span_at):
        target = max(span_at(maximum), min(span_at(minimum), current_span / zoom_factor(steps)))
        # Request only integer protocol levels. Keep a source at least as wide
        # as the viewport; the renderer performs the remaining fine cropping.
        source_level = minimum
        for candidate in range(minimum, maximum + 1):
            if span_at(candidate) + 1e-12 >= target:
                source_level = candidate
        self.context = (source, source_level)
        self.target_span = target
        return source_level, target


def zoom_workspace(workspace, kind, steps):
    """Return feedback after a supported action, or None without changing state."""
    steps = max(-100, min(100, int(steps)))
    if not steps:
        return None
    factor = zoom_factor(steps)
    if kind == "scan":
        if workspace is None or not workspace.open or workspace.page != "history" or workspace.keyboard:
            return None
        left, _top, right, _bottom = workspace.plot_box()
        workspace.zoom_at(factor, (left + right) / 2)
        return f"SCAN HISTORY  {workspace.zoom:.2f}×"
    if kind == "adsb":
        if any(getattr(getattr(workspace, name, None), "open", False)
               for name in ("dongles", "radio_info")):
            return None
        screen = workspace.current_screen()
        if screen == "coverage":
            view = workspace.coverage_view
            if view.window_open:
                return None
            view.zoom = max(.5, min(4, view.zoom * factor))
            view.wake.set()
            return f"COVERAGE  {view.zoom:.1%}"
        if screen != "map":
            return None
        workspace.zoom(factor)
        return f"ADS-B MAP  {workspace.scale:.2f}×"
    if kind == "vhf":
        if workspace.dongles.open:
            return None
        if workspace.mode == "spectrum":
            view = workspace.spectrum
            if (view.overlay or view.screen not in ("survey", "activity", "compare")
                    or not view.view):
                return None
            config = view.state.get("data", {}).get("settings", view.state.get("settings", {}))
            if not config:
                return None
            view.zoom(1 / factor)
            return f"SPECTRUM  {(view.view[1] - view.view[0]) / 1e6:g} MHz"
        if workspace.view != "map" or workspace.overlay:
            return None
        workspace.map.zoom(factor)
        return f"{workspace.mode.upper()} MAP  {workspace.map.scale:.2f}×"
    return None
