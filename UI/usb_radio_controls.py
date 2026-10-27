"""One compact six-row native receiver picker, shared across USB decoders."""
import math
from usb_radios import choices


def receiver_rows(workspace,cache,devices,leases,owner,selection,page=0,action='assign',unique=True,blocked=(),top=200,include_auto=True,left=24,right=1256,page_size=6,row_height=56,row_gap=4):
    items=choices(devices,leases,owner,selection,unique,blocked)
    if not include_auto:items=items[1:]
    last=max(0,math.ceil(len(items)/page_size)-1);page=max(0,min(page,last))
    for i,row in enumerate(items[page*page_size:page*page_size+page_size]):
        y=top+i*(row_height+row_gap)
        workspace.decoder_button(cache,(left,y,right,y+row_height),row['name'],(action,row['id']),row['detail'],row['selected'],enabled=row['enabled'],font_size=21,uppercase=False)
    return page,last
