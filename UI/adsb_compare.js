export function relativePackets(a,b){return a>0?((b/a-1)*100):null;}
export function comparisonHistory(data){
  const roster=data.current?.receivers?.map(r=>r.id)||data.receivers?.map(r=>r.id),selected=data.selections;
  return (data.history||[]).filter(w=>!data.graph_reset_at||w.start>=data.graph_reset_at).filter(w=>roster?.length?w.receivers.length===roster.length&&w.receivers.every((r,i)=>r.id===roster[i]):selected?.length?w.receivers.length===selected.length+1&&w.receivers.slice(1).every((r,i)=>r.id===selected[i]):!data.selection||data.selection==='auto'||w.receivers.length===2&&w.receivers[1].id===data.selection);
}
export function completedWindows(data){return comparisonHistory(data).filter(w=>w.complete&&w.valid);}
export function packetRates(series,count,interval=5,averageSeconds=30){
  const rates=[];let recent=[];
  for(const point of series){
    if(!Number.isFinite(point.elapsed)||point.packets?.length!==count||!point.packets.every(Number.isFinite)){recent=[];continue;}
    if(recent.length&&point.elapsed<=recent.at(-1).elapsed)continue;
    if(recent.length&&point.packets.some((v,i)=>v<recent.at(-1).packets[i]))recent=[];
    recent.push(point);const cutoff=point.elapsed-Math.max(interval,averageSeconds);
    while(recent.length>1&&recent[1].elapsed<=cutoff)recent.shift();
    let start=recent[0].elapsed,baseline=recent[0].packets;
    if(recent.length>1&&start<cutoff){const fraction=(cutoff-start)/(recent[1].elapsed-start);baseline=baseline.map((v,i)=>v+(recent[1].packets[i]-v)*fraction);start=cutoff;}
    const duration=point.elapsed-start;
    if(duration>=interval)rates.push({elapsed:point.elapsed,rates:point.packets.map((v,i)=>(v-baseline[i])/duration)});
  }
  return rates;
}
export function rateGraphMax(rates){
  const peak=Math.max(0,...rates.flatMap(s=>s.rates));if(peak<=0)return 1;
  const target=Math.max(.1,peak*1.2),unit=10**Math.floor(Math.log10(target));
  return [1,1.5,2,2.5,3,4,5,6,8,10].map(step=>step*unit).find(value=>value>=target);
}
export function rateTickDigits(maximum){return Math.max(0,1-Math.floor(Math.log10(maximum/4)));}
export function livePaths(series,count){
  const rates=packetRates(series,count),max=rateGraphMax(rates);
  return {max,rates,paths:Array.from({length:count},(_,i)=>rates.map(s=>`${60+s.elapsed/300*920},${220-s.rates[i]/max*190}`).join(' '))};
}

export function graphSpan(value){return [300,1800,3600,43200,86400].includes(Number(value))?Number(value):300;}
export function graphRangeLabel(seconds){return seconds>=3600?`${seconds/3600} ${seconds===3600?'hour':'hours'}`:`${seconds/60} minutes`;}
export function rateTimeline(data,seconds=300){
  seconds=graphSpan(seconds);const now=data.now,roster=(data.current?.receivers||data.receivers||[]).map(r=>r.id);
  let points=(data.rate_history||[]).filter(p=>p.time>(data.graph_reset_at||0));
  if(!roster.length||roster.length!==data.rate_history_ids?.length||roster.some((id,i)=>id!==data.rate_history_ids[i]))points=[];
  const segments=[];let segment=[],previous=null;
  for(const point of points){
    if(point.time<now-seconds)continue;if(point.time>now)break;
    if(point.rates===null||previous!==null&&point.time-previous.time>Math.max(8,1.5*(point.period||2),1.5*(previous.period||2))){if(segment.length)segments.push(segment);segment=[];}
    if(point.rates!==null)segment.push({elapsed:point.time-(now-seconds),rates:point.rates});
    previous=point;
  }
  if(segment.length)segments.push(segment);
  const latest=points.at(-1);
  return {seconds,segments,max:rateGraphMax(segments.flat()),rates:latest&&now-latest.time>=0&&now-latest.time<=8&&latest.rates!==null?latest.rates:[],available_seconds:points.length?Math.min(seconds,Math.max(0,now-points[0].time)):0};
}
export function timelinePaths(frame,count){
  return frame.segments.flatMap(segment=>Array.from({length:count},(_,index)=>({index,points:segment.map(s=>`${60+s.elapsed/frame.seconds*920},${220-s.rates[index]/frame.max*190}`).join(' ')})));
}

export async function comparisonControl(action,request=fetch){
  // Open pages survive service restarts; control tokens do not.
  for(let attempt=0;attempt<2;attempt++){
    const state=await request('/api/state',{cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!state.ok)throw Error('Receiver service unavailable');
    const token=(await state.json()).control_token;
    const response=await request('/api/control',{method:'POST',signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json','X-ADSB-Token':token},body:JSON.stringify({action})});
    if(response.status===403&&attempt===0)continue;
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Control failed');
    return result;
  }
}

function mount(){
  const $=id=>document.getElementById(id),colours=['#65e3d2','#ad9bff','#ffbf69','#f98ba9'];let busy=false,pending=false,controlError='',data=null,span=300;
  try{span=graphSpan(localStorage.getItem('ituner-compare-range'));}catch{}
  $('compare-range').value=String(span);
  const fmt=(v,d=0)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:d}):'—';
  const name=r=>r?.label?.split(' · USB ')[0]||r?.label||'Receiver';
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function svg(tag,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
  function render(){if(!data)return;const w=data.current,elapsed=w?.duration||0,receivers=w?.receivers||data.receivers||[],count=receivers.length||2,lines=rateTimeline(data,span),currentRates=lines.rates;
    $('compare-status').textContent={RUNNING:`${count} receivers · comparison running`,'WARMING UP':'Warming up receivers',STOPPED:'Comparison stopped'}[data.status]||data.status;
    $('compare-detail').textContent=data.detail||'Receivers listen simultaneously. A result is saved every five minutes.';
    $('compare-reset').disabled=pending;$('compare-start').disabled=data.enabled||pending;$('compare-stop').disabled=!data.enabled||pending;
    $('compare-reset').textContent=data.graph_reset_at&&data.now-data.graph_reset_at<8?'Graphs reset ✓':'Reset graphs';
    $('compare-progress-label').textContent=w?'Current five-minute window':'Waiting for every receiver';$('compare-progress').value=elapsed;
    const left=Math.max(0,Math.ceil(300-elapsed));$('compare-countdown').textContent=w?`${Math.floor(left/60)}:${String(left%60).padStart(2,'0')} remaining`:'—';
    const cards=$('compare-receivers');cards.replaceChildren();
    for(let i=0;i<count;i++){const r=w?.receivers[i],identity=receivers[i],letter=String.fromCharCode(65+i),card=el('article',undefined,'compare-card');card.style.setProperty('--receiver-colour',colours[i%colours.length]);card.append(el('span','RECEIVER '+letter,'eyebrow'),el('h2',name(identity)),el('p',identity?.id?.replace('serial:','Serial ')||'Awaiting assignment','receiver-serial'));
      card.append(el('div',fmt(r?.packets),'packet-count'),el('div',r?'VALID PACKETS · CURRENT WINDOW':identity?.status||'WAITING','packet-caption'));
      const dl=el('dl');for(const [label,value] of [['PACKETS / SEC · SMOOTHED',fmt(currentRates[i],1)],['AIRCRAFT',r?fmt(r.aircraft.length):'—'],['POSITIONED',r?fmt(r.positioned_aircraft.length):'—'],['POSITION UPDATES',fmt(r?.positions)],['MAX RANGE · KM',fmt(r?.max_range_km,1)],['TUNER GAIN · dB',fmt(r?.gain,1)]]){const box=el('div');box.append(el('dt',label),el('dd',value));dl.append(box);}card.append(dl,el('p',`Signal ${fmt(r?.signal,1)} dBFS · noise ${fmt(r?.noise,1)} dBFS · dropped samples ${fmt(r?.samples_dropped)}`));cards.append(card);}
    const legend=$('compare-legend');legend.replaceChildren();receivers.forEach((r,i)=>{const item=el('span',`${String.fromCharCode(65+i)} · ${name(r)} · ${fmt(currentRates[i],1)} packets/s`);item.style.setProperty('--receiver-colour',colours[i%colours.length]);legend.append(item);});
    const graph=$('compare-live-graph');graph.replaceChildren();
    for(let i=0;i<5;i++){const y=220-i*47.5;graph.append(svg('line',{x1:60,x2:980,y1:y,y2:y,stroke:'#253847'}),svg('text',{x:50,y:y+4,'text-anchor':'end',fill:'#9cb8c8','font-size':13},fmt(lines.max*i/4,rateTickDigits(lines.max))));}
    for(const second of [0,1,2,3,4,5].map(i=>i*span/5))graph.append(svg('text',{x:60+second/span*920,y:245,'text-anchor':'middle',fill:'#9cb8c8','font-size':13},second===span?'Now':span>=43200?`−${Number(((span-second)/3600).toFixed(1))}h`:`−${(span-second)/60}m`));
    timelinePaths(lines,count).forEach(({points,index:i})=>{if(points)graph.append(svg('polyline',{points,fill:'none',stroke:colours[i%colours.length],'stroke-width':3,'vector-effect':'non-scaling-stroke','stroke-linejoin':'round','stroke-linecap':'round'}));});
    $('compare-live-graph').setAttribute('aria-label',`Smoothed packet reception rates over the last ${graphRangeLabel(span)}`);
    $('compare-live-caption').textContent=`Auto scale · 30-second rolling average · last ${graphRangeLabel(span)} · gaps indicate interruptions.${span>3600?' Older than one hour: one-minute averages.':''}${lines.available_seconds<span-5?` Collecting history: ${Math.floor(lines.available_seconds/60)} min available.`:''}`;
    const completed=completedWindows(data),last=completed.at(-1);if(last){const a=last.receivers[0];$('compare-verdict').textContent='Latest completed: '+last.receivers.map((r,i)=>{const pct=relativePackets(a.packets,r.packets);return `${String.fromCharCode(65+i)} ${fmt(r.packets)} packets${i&&pct!==null?` (${pct>=0?'+':''}${pct.toFixed(1)}% vs A)`:''}`;}).join(' · ')+'.';}else $('compare-verdict').textContent='The first complete result for this receiver group appears after five minutes of uninterrupted reception.';
    const chart=$('compare-chart');chart.replaceChildren();const plotted=completed.slice(-12),max=Math.max(1,...plotted.flatMap(w=>w.receivers.map(r=>r.packets)));
    for(const window of plotted){const group=el('div',undefined,'compare-bar-group'),stamp=new Date(window.start*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});window.receivers.forEach((r,i)=>{const bar=el('i');bar.style.height=(r.packets/max*130)+'px';bar.style.background=colours[i%colours.length];bar.title=`${stamp} · ${name(r)}: ${r.packets} packets`;group.append(bar);});group.append(el('span',stamp));chart.append(group);}
    const head=$('compare-columns');head.replaceChildren();['Window',...Array.from({length:count},(_,i)=>'Receiver '+String.fromCharCode(65+i)),'Status'].forEach(t=>head.append(el('th',t)));
    const body=$('compare-history');body.replaceChildren();for(const window of comparisonHistory(data).reverse().slice(0,24)){const row=el('tr');for(const value of [new Date(window.start*1000).toLocaleString(),...window.receivers.map(r=>fmt(r.packets)),window.valid&&window.complete?'Complete':window.reason||'Partial'])row.append(el('td',value));body.append(row);}
  }
  async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/comparison',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error('Comparison service unavailable');data=await r.json();$('compare-connection').textContent='● CONNECTED';$('compare-error').textContent=controlError;render();}catch(e){$('compare-connection').textContent='OFFLINE';$('compare-error').textContent=e.message;}finally{busy=false;}}
  async function control(action){if(pending)return;pending=true;render();try{await comparisonControl(action);controlError='';$('compare-error').textContent='';await refresh();}catch(e){controlError=e.message;$('compare-error').textContent=controlError;}finally{pending=false;render();}}
  $('compare-range').onchange=()=>{span=graphSpan($('compare-range').value);try{localStorage.setItem('ituner-compare-range',String(span));}catch{}render();};
  $('compare-reset').onclick=()=>control('comparison_reset');
  $('compare-start').onclick=()=>control('comparison_start');$('compare-stop').onclick=()=>control('comparison_stop');refresh();setInterval(refresh,2000);setInterval(()=>$('compare-clock').textContent=new Date().toISOString().slice(11,19)+' UTC',1000);
}
if(typeof document!=='undefined')mount();
