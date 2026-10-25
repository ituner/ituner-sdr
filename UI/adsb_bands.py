"""Small, passive per-band readouts shared with the browser contract."""


def band_readings(state,now):
    bands={b['id']:b for b in state.get('bands',[])};rows=[]
    labels={'RECEIVING':'Receiving','LISTENING':'Listening','STARTING':'Starting','STOPPED':'Stopped',
            'PAUSED FOR COMPARISON':'Comparing 1090', 'NOT INSTALLED':'Not installed','WAITING FOR SECOND DONGLE':'USB disconnected',
            'WAITING FOR DONGLE':'USB disconnected','WAITING FOR USB':'USB disconnected',
            'DONGLE BUSY':'USB busy','UNIQUE ID REQUIRED':'Rename USB','ERROR':'Receiver error','RETRYING':'Reconnecting','OFFLINE':'Offline'}
    for key,name in (('1090','1090 ES'),('978','978 UAT')):
        b=bands.get(key,dict(id=key,name=name,status=state.get('status','STOPPED') if key=='1090' else 'NOT INSTALLED',messages=state.get('messages',0) if key=='1090' else 0))
        status='OFFLINE' if state.get('status')=='OFFLINE' else b.get('status','STOPPED')
        heard=b.get('last_message_at');age=max(0,int(now-heard)) if isinstance(heard,(int,float)) else None
        ago='never' if age is None else 'now' if age<2 else f'{age}s ago' if age<60 else f'{age//60}m ago' if age<3600 else f'{age//3600}h ago'
        packets=b.get('messages',0);live=0 if status=='OFFLINE' else b.get('aircraft_count',0)
        tone='good' if status=='RECEIVING' else 'quiet' if status in ('LISTENING','STARTING') else 'muted' if status in ('STOPPED','NOT INSTALLED') else 'warning'
        rows.append(dict(id=key,name=name,status=labels.get(status,status),tone=tone,
                         details=f"{packets:,} {'packet' if packets==1 else 'packets'} · {live} live · heard {ago}",packets=packets,live=live))
    return rows
