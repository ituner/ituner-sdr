export function bandReadings(state,now){
  const labels={RECEIVING:'Receiving',LISTENING:'Listening',STARTING:'Starting',STOPPED:'Stopped','PAUSED FOR COMPARISON':'Comparing 1090', 'NOT INSTALLED':'Not installed','WAITING FOR SECOND DONGLE':'USB disconnected','WAITING FOR DONGLE':'USB disconnected','WAITING FOR USB':'USB disconnected','DONGLE BUSY':'USB busy','UNIQUE ID REQUIRED':'Rename USB',ERROR:'Receiver error',RETRYING:'Reconnecting',OFFLINE:'Offline'};
  return [['1090','1090 ES'],['978','978 UAT']].map(([id,name])=>{
    const b=state.bands?.find(b=>b.id===id)||{status:id==='1090'?state.status:'NOT INSTALLED',messages:id==='1090'?state.messages:0};
    const status=state.status==='OFFLINE'?'OFFLINE':b.status||'STOPPED',age=Number.isFinite(b.last_message_at)?Math.max(0,Math.floor(now-b.last_message_at)):null;
    const ago=age===null?'never':age<2?'now':age<60?age+'s ago':age<3600?Math.floor(age/60)+'m ago':Math.floor(age/3600)+'h ago';
    const packets=b.messages||0,live=status==='OFFLINE'?0:b.aircraft_count||0,tone=status==='RECEIVING'?'good':['LISTENING','STARTING'].includes(status)?'quiet':['STOPPED','NOT INSTALLED'].includes(status)?'muted':'warning';
    return {id,name,status:labels[status]||status,tone,packets,live,details:packets.toLocaleString('en-US')+(packets===1?' packet · ':' packets · ')+live+' live · heard '+ago};
  });
}
