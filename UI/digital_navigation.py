"""One Back action that returns to the preceding digital decoder view."""
from decoder_style import full_width_back_box


def install_navigation(workspace):
    if getattr(workspace, 'navigation_installed', False):
        return
    workspace.navigation_installed = True
    original_draw, original_tap = workspace.draw, workspace.tap
    original_show = getattr(workspace, 'show', None)
    history = []
    route_fields = ('decoders_open', 'history_open', 'enlarged', 'filter_id', 'page')
    route_actions = {'decoders', 'gallery', 'history', 'live', 'filter', 'image', 'select_rx', 'create'}

    def route():
        return {key: getattr(workspace, key) for key in route_fields if hasattr(workspace, key)}

    def modal_owns_navigation():
        return (getattr(getattr(workspace, 'log_search_view', None), 'open', False)
                or getattr(workspace, 'field', None) is not None
                or getattr(workspace, 'reporting', None) is not None
                or getattr(workspace, 'add_open', False))

    def back():
        if getattr(workspace, 'delete_armed', None):
            workspace.delete_armed = None
        elif history:
            for key, value in history.pop().items():
                setattr(workspace, key, value)
        elif getattr(workspace, 'enlarged', None):
            workspace.enlarged = None
        elif getattr(workspace, 'history_open', False):
            workspace.history_open = False
        elif getattr(workspace, 'decoders_open', False):
            workspace.decoders_open = False
        else:
            workspace.open = False

    def draw(cache, *args):
        original_draw(cache, *args)
        # Forms already have Cancel; shared keyboards own the complete canvas.
        if modal_owns_navigation():
            return
        back_box = full_width_back_box()
        drawn = {box for box, _ in getattr(workspace, 'actions', ())}
        if back_box not in drawn:
            workspace.button(cache, back_box, 'BACK', ('nav_back', None))

    def tap(x, y, *args):
        if not modal_owns_navigation() and workspace.ui.contains(full_width_back_box(), x, y):
            back()
            return
        action = next((a for box, a in reversed(getattr(workspace, 'actions', ()))
                       if workspace.ui.contains(box, x, y)), None)
        before = route()
        result = original_tap(x, y, *args)
        if action and action[0] in route_actions and before != route():
            history.append(before)
        return result

    def show(*args, **kwargs):
        history.clear()
        return original_show(*args, **kwargs)

    workspace.draw, workspace.tap = draw, tap
    if original_show is not None:
        workspace.show = show
