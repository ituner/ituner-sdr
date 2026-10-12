"""Consistent Back/Home navigation for touchscreen decoder workspaces."""

def install_navigation(workspace):
    if getattr(workspace,'navigation_installed',False):return
    workspace.navigation_installed=True
    original_draw,original_tap=workspace.draw,workspace.tap
    back_box=(1034,728,1270,792);home_box=(1034,8,1270,72)
    def back():
        if getattr(workspace,'field',None) is not None:workspace.field=None
        elif getattr(workspace,'reporting',None) is not None:workspace.reporting=None
        elif workspace.add_open:workspace.add_open=False;workspace.edit_id=None
        elif workspace.delete_armed:workspace.delete_armed=None
        elif workspace.enlarged:workspace.enlarged=None
        elif getattr(workspace,'history_open',False):workspace.history_open=False;workspace.decoders_open=True
        elif not workspace.decoders_open:
            workspace.decoders_open=True;workspace.filter_id=None
        else:workspace.open=False
    def draw(cache,*args):
        original_draw(cache,*args)
        if getattr(getattr(workspace,'log_search_view',None),'open',False):return
        drawn={box for box,_ in getattr(workspace,'actions',())}
        if back_box not in drawn:workspace.button(cache,back_box,'BACK',('nav_back',None))
        if home_box not in drawn:workspace.button(cache,home_box,'HOME',('nav_home',None))
    def tap(x,y,*args):
        if getattr(getattr(workspace,'log_search_view',None),'open',False):return original_tap(x,y,*args)
        if workspace.ui.contains(home_box,x,y):workspace.open=False;return
        if workspace.ui.contains(back_box,x,y):back();return
        return original_tap(x,y,*args)
    workspace.draw,workspace.tap=draw,tap
