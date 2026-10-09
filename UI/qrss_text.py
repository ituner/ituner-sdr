"""Separate capture completion, acquisition and incomplete Morse display."""
def track_text(row):
    text=row.get('tentative_text','').strip()
    pending=row.get('partial_morse','')
    if pending:text+=(('  |  ' if text else '')+'Unfinished Morse: '+pending)
    return text


def presentation(item):
    row=dict(item)
    row['tracks']=[dict(t,display_text=track_text(t)) for t in item.get('tracks',[])]
    live=item.get('kind')=='receiving'
    if item.get('mode')=='VISUAL' or item.get('text_status')=='visual_only':
        message='Visual-only capture · automatic text decoding is disabled'
    elif not item.get('tracks') and item.get('mode')=='AUTO':
        message=('Searching for consistent Morse timing' if live else
                 'Capture saved · no Morse timing lock; inspect the visible traces')
    else:
        message=('Waiting for a complete Morse character' if live else
                 'Capture saved · no complete Morse characters recognized')
    row['empty_text_message']=message
    row['text_message']=track_text(item) or message
    acquisition=item.get('acquisition',{})
    row['reception_detail']=acquisition.get('detail','') if live else (
        'Saved image · partial text is shown when available; no CRC check' if item.get('tracks') or item.get('tentative_text') else message)
    return row
