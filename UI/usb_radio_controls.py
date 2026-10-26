"""One compact six-row native receiver picker, shared across USB decoders."""
import math
from usb_radios import choices


def receiver_rows(workspace,cache,devices,leases,owner,selection,page=0,action='assign',unique=True,blocked=(),top=200,include_auto=True,left=24,right=1256):
    items=choices(devices,leases,owner,selection,unique,blocked)
    if not include_auto:items=items[1:]
    last=max(0,math.ceil(len(items)/6)-1);page=max(0,min(page,last))
    for i,row in enumerate(items[page*6:page*6+6]):
        y=top+i*60
        workspace.decoder_button(cache,(left,y,right,y+56),row['name'],(action,row['id']),row['detail'],row['selected'],enabled=row['enabled'],font_size=21,uppercase=False)
    return page,last
