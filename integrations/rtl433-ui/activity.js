/* Shared, read-only decoder waterfall. Used by RTL433-UI and Spectrum Survey. */
(function(root){'use strict';
 const WIDTH=1024,HEIGHT=256,PIXEL=8,MAX=1500e6,MIN_SPAN=1e6,FULL={low:0,high:MAX};
 const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
 function createTimeline({monotonic=()=>performance.now(),wall=Date.now}={}){
  let value=null,last=0,target=0;
  function read(){
   const t=monotonic()/1000;if(value===null)return wall()/1000;
   const elapsed=Math.max(0,t-last),expected=value+elapsed;
   // Network jitter can adjust speed by at most 2%; it can never step the clock.
   value=expected+clamp(t+target-expected,-elapsed*.02,elapsed*.02);last=t;return value;
  }
  function sync(serverTime,roundTripMs=0){
   if(!Number.isFinite(serverTime))return;
   const t=monotonic()/1000,estimate=serverTime+Math.max(0,roundTripMs)/2000;
   if(value===null){value=estimate;last=t;}else read();
   target=estimate-t;
  }
  return {read,sync};
 }
 function timelineTicks(rows,seconds){return rows.filter(row=>Math.round(row.time/seconds)%8===0);}
 function zoomRange(view,factor,anchor=(view.low+view.high)/2){
  const span=view.high-view.low,width=clamp(span*factor,MIN_SPAN,MAX),ratio=clamp((anchor-view.low)/span,0,1);
  const low=clamp(anchor-ratio*width,0,MAX-width);return {low,high:low+width};
 }
 function panRange(view,fraction){const span=view.high-view.low,low=clamp(view.low+span*fraction,0,MAX-span);return {low,high:low+span};}
 function gestureRange(view,start,current,width){
  const span=view.high-view.low;
  if(start.length===1)return panRange(view,(start[0].x-current[0].x)/width);
  const distance=points=>Math.hypot(points[1].x-points[0].x,points[1].y-points[0].y);
  const nextSpan=clamp(span*Math.max(1,distance(start))/Math.max(1,distance(current)),MIN_SPAN,MAX);
  const anchor=view.low+(start[0].x+start[1].x)/2/width*span;
  const low=clamp(anchor-(current[0].x+current[1].x)/2/width*nextSpan,0,MAX-nextSpan);
  return {low,high:low+nextSpan};
 }
 function messageWidth(count){return clamp(4+Math.round(4*Math.log2(Number.isFinite(count)&&count>1?count:1)),4,24);}
 function marker(frequency,view=FULL,width=4){return clamp(Math.round((frequency-view.low)/(view.high-view.low)*WIDTH-width/2),0,WIDTH-width);}
 function waterfallLayout(events,now,seconds,view=FULL){
  const current=Math.floor(now/seconds),phase=now/seconds-current,rows=Array.from({length:HEIGHT/PIXEL},(_,age)=>({time:(current-age)*seconds,y:(age+phase)*PIXEL,height:PIXEL,count:0})),groups=new Map();
  for(const e of events){
   const age=current-Math.floor(e.time/seconds);
   if(!Number.isFinite(e.frequency)||e.frequency<view.low||e.frequency>view.high||e.lastSeen>now+2||!Number.isInteger(age)||age<0||age>=rows.length)continue;
   if(!groups.has(age))groups.set(age,new Map());
   const group=groups.get(age),key=JSON.stringify([e.mode,e.frequency,e.receiver,!!e.tentative]),count=Number.isFinite(e.count)&&e.count>0?e.count:1,previous=group.get(key);
   group.set(key,{...e,count:(previous?.count||0)+count,lastSeen:Math.max(previous?.lastSeen??-Infinity,e.lastSeen)});rows[age].count+=count;
  }
  const points=[];
  for(const [age,group] of groups){
   for(const event of group.values()){const width=messageWidth(event.count);points.push({...event,x:marker(event.frequency,view,width),y:rows[age].y,height:PIXEL,width});}
  }
  return {points,rows,duration:rows.length*seconds};
 }
 function visible(events,now,seconds,view=FULL){return waterfallLayout(events,now,seconds,view).points;}
 function decoderStates(data,view=FULL){
  return data.decoders.map(d=>{
   const receivers=data.receivers.filter(r=>r.mode===d.id),active=receivers.filter(r=>r.enabled);
   const source=d.id.startsWith('adsb-')?'adsb':['wspr','cw','sstv','hell','qrss'].includes(d.id)?d.id:'vhf';
   const offline=data.sources.some(s=>s.id===source&&!s.online);
   return {...d,receivers,active,source,enabled:active.length>0,
    state:offline?'FEED OFFLINE':active.length?[...new Set(active.map(r=>r.status))].join(', '):'STOPPED',
    inSpan:active.some(r=>Number.isFinite(r.frequency)&&r.frequency>=view.low&&r.frequency<=view.high)};
  });
 }
 function ticks(view){
  const raw=(view.high-view.low)/8,power=10**Math.floor(Math.log10(raw)),step=[1,2,5,10].map(n=>n*power).find(n=>n>=raw),values=[view.low];
  for(let f=Math.ceil(view.low/step)*step;f<view.high;f+=step)if(f-view.low>step*.65&&view.high-f>step*.65)values.push(f);
  values.push(view.high);return values;
 }
 if(typeof module==='object'&&module.exports){module.exports={createTimeline,timelineTicks,marker,messageWidth,visible,waterfallLayout,decoderStates,zoomRange,panRange,gestureRange,ticks,WIDTH,HEIGHT,PIXEL,MAX,MIN_SPAN};return;}
 const script=document.currentScript,base=new URL(script.src).origin;
 for(const mount of document.querySelectorAll('[data-decoder-activity]')){
  if(mount.dataset.mounted)continue;mount.dataset.mounted='true';
  mount.innerHTML='<div class="da-heading"><div><h2>Decoder activity · mini SDR</h2><p>0–1.5 GHz · real decoded outputs from all receivers</p></div><label>Waterfall speed <select aria-label="Decoder waterfall speed"><option value="1" selected>1 s / row · live</option><option value="10">10 s / row</option><option value="30">30 s / row · slow</option><option value="60">60 s / row</option></select></label></div><div class="da-legend"></div><div class="da-chart"><canvas class="da-spectrum" width="1024" height="64" role="img" aria-label="Decoded output activity by frequency, from zero to 1500 MHz"></canvas><canvas class="da-waterfall" width="1024" height="256" tabindex="0" role="img" aria-label="Decoded activity waterfall. Rows stay eight pixels high. Marks are four to twenty-four pixels wide based on decoded outputs in each selected time interval. Newest activity is at the top."></canvas></div><div class="da-density"></div><div class="da-readout" role="status">Waiting for the central decoder feed…</div><p class="da-note">Marks show decoded activity, not measured RF power. Rows stay 8 pixels high and scroll continuously. Mark width shows output count per interval: 4 px for one, up to 24 px for 32 or more. Blank space means no observed decode. Drag or swipe to pan; pinch with two fingers or scroll to zoom. Tap a frequency to focus button zoom. Full range resets the view. ADS-B is at 978 / 1090 MHz. Outlined or dashed marks are tentative text or partial images.</p><details class="da-counts"><summary>Central decoder counts <span></span></summary><p>Observed outputs since this feed started. Each decoder keeps its own unit; tentative outputs and scanner energy detections are excluded from successful totals.</p><div class="da-table-wrap"><table><thead><tr><th>Decoder</th><th>Receiver / state</th><th>Successful</th><th>Tentative</th><th>Unit</th></tr></thead><tbody></tbody></table></div></details>';
  const $=s=>mount.querySelector(s),spectrum=$('.da-spectrum'),waterfall=$('.da-waterfall'),ctx=waterfall.getContext('2d'),top=spectrum.getContext('2d');
  const navigation=document.createElement('div');navigation.className='da-navigation';navigation.setAttribute('role','group');navigation.setAttribute('aria-label','Waterfall frequency zoom');
  navigation.innerHTML='<button type="button" data-view="left" aria-label="Pan to lower frequencies">←</button><button type="button" data-view="out" aria-label="Zoom out">− Zoom out</button><button type="button" data-view="in" aria-label="Zoom in">+ Zoom in</button><button type="button" data-view="right" aria-label="Pan to higher frequencies">→</button><button type="button" data-view="reset">Full range</button><output aria-live="polite"></output>';
  mount.insertBefore(navigation,$('.da-chart'));
  const health=document.createElement('div');health.className='da-status';mount.insertBefore(health,$('.da-legend'));
  let data=null,seconds=1,points=[],pending=false,online=false,view={...FULL},focus=null,layoutCache=null,uiDirty=true,lastUiSecond=-1,topDirty=true,topSecond=-1;
  const timeline=createTimeline(),now=timeline.read,formatter=new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',second:'2-digit'}),labels=new Map(),legendItems=new Map();
  const clock=t=>{const key=Math.floor(t);if(!labels.has(key)){labels.set(key,formatter.format(new Date(key*1000)));if(labels.size>128)labels.delete(labels.keys().next().value);}return labels.get(key);},fmt=f=>f<1e6?(f/1000).toFixed(3)+' kHz':(f/1e6).toFixed(3)+' MHz';
  const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
  function resizeCanvases(){
   const scale=Math.max(1,devicePixelRatio||1);
   for(const [canvas,context,height] of [[waterfall,ctx,HEIGHT],[spectrum,top,64]]){canvas.width=Math.round(WIDTH*scale);canvas.height=Math.round(height*scale);canvas.style.aspectRatio=WIDTH+' / '+height;context.setTransform(canvas.width/WIDTH,0,0,canvas.height/height,0,0);}
   topDirty=true;
  }
  resizeCanvases();
  addEventListener('resize',()=>{resizeCanvases();draw();});
  const color=e=>data?.decoders.find(d=>d.id===e.mode)?.color||'#88cff5';
  function updateStatus(time,layout){
   text($('.da-density'),`${seconds} s / row · 8 px high, marks 4–24 px wide · ${layout.duration<60?layout.duration+' s':Number((layout.duration/60).toFixed(1))+' min'} shown · live clock ${clock(time)}`);
   if(!data)return;
   const states=decoderStates(data,view),enabled=states.filter(d=>d.enabled),receiving=enabled.filter(d=>d.inSpan&&d.active.some(r=>['RECEIVING','LISTENING','DECODING','RUNNING'].includes(r.status)));
   const outside=data.events.some(e=>e.lastSeen>=time-layout.duration&&(e.frequency<view.low||e.frequency>view.high));
   text(health,points.length?'Live decoded output in this span. Decoder labels below show current state.':outside?'Decoded output is outside this frequency span. Use Full range to see it.':!enabled.length?'All decoders are stopped or unavailable. Open a decoder below to start reception.':receiving.length?'Listening in this span; no decoded output in the current time window.':enabled.some(d=>d.inSpan)?'Enabled decoders are waiting or retrying; no decoded output to plot.':'No enabled decoder is listening in this span. Use Full range or open a decoder below.');
   health.dataset.live=points.length?'true':'false';
  }
  function drawTop(time){
   top.fillStyle='#0c1723';top.fillRect(0,0,WIDTH,64);top.font='11px system-ui';top.fillStyle='#a6bdcd';
   for(const f of ticks(view)){const x=(f-view.low)/(view.high-view.low)*WIDTH;top.textAlign=f===view.low?'left':f===view.high?'right':'center';top.fillText(String(Number((f/1e6).toFixed(3)))+(f===view.high?' MHz':''),x,14);}
   if(!data)return;
   // Height is decoded-output density during the most recent minute, never RSSI.
   const bins=new Map();for(const e of data.events)if(e.lastSeen>time-60&&e.frequency>=view.low&&e.frequency<=view.high){const x=Math.min(127,Math.floor((e.frequency-view.low)/(view.high-view.low)*128));const key=x+':'+e.mode;const b=bins.get(key)||{x,mode:e.mode,count:0};b.count+=e.count;bins.set(key,b);}
   const maximum=Math.max(1,...[...bins.values()].map(b=>Math.log1p(b.count)));
   for(const b of bins.values()){top.fillStyle=color(b);top.fillRect(b.x*8,60-Math.max(2,Math.log1p(b.count)/maximum*34),8,Math.max(2,Math.log1p(b.count)/maximum*34));}
  }
  function draw(){
   const time=now(),second=Math.floor(time),bucket=Math.floor(time/seconds);
   if(!layoutCache||layoutCache.bucket!==bucket)layoutCache={bucket,time,layout:waterfallLayout(data?.events||[],time,seconds,view)};
   const offset=(time-layoutCache.time)/seconds*PIXEL,layout={...layoutCache.layout,
    rows:layoutCache.layout.rows.map(row=>({...row,y:row.y+offset})),
    points:layoutCache.layout.points.map(point=>({...point,y:point.y+offset})).filter(point=>point.y<HEIGHT)};
   points=layout.points;
   if(uiDirty||lastUiSecond!==second){updateStatus(time,layout);lastUiSecond=second;uiDirty=false;}
   if(topDirty||topSecond!==second){drawTop(time);topSecond=second;topDirty=false;}
   ctx.fillStyle='#07101b';ctx.fillRect(0,0,WIDTH,HEIGHT);ctx.strokeStyle='#193044';
   for(const f of ticks(view)){const x=(f-view.low)/(view.high-view.low)*WIDTH;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,HEIGHT);ctx.stroke();}
   if(!data)return;
   ctx.font='10px system-ui';ctx.textAlign='right';
   // Absolute tick times travel with their rows, instead of resetting every second.
   for(const row of timelineTicks(layout.rows,seconds))if(row.y<HEIGHT-11){ctx.fillStyle='#07101bd9';ctx.fillRect(WIDTH-78,row.y,78,11);ctx.fillStyle='#a3b8ca';ctx.fillText(clock(row.time),WIDTH-3,row.y+9);}
   for(const e of points){ctx.strokeStyle=ctx.fillStyle=color(e);if(!e.tentative)ctx.fillRect(e.x,e.y,e.width,e.height);else if(e.width>=3)ctx.strokeRect(e.x+.5,e.y+.5,e.width-1,e.height-1);else for(let dy=0;dy<e.height;dy+=3)ctx.fillRect(e.x,e.y+dy,e.width,2);}
   if(!points.length){ctx.fillStyle='#829cb2';ctx.font='13px system-ui';ctx.textAlign='center';ctx.fillText('No decoded output in this time window · see decoder states above',WIDTH/2,HEIGHT/2);}
  }
  function renderLegend(){
   for(const d of decoderStates(data,view)){
    let item=legendItems.get(d.id);if(!item){item=document.createElement('a');legendItems.set(d.id,item);$('.da-legend').append(item);}
    const url=new URL(base);url.port=d.source==='adsb'?'8090':d.source==='vhf'?'8092':'8073';url.pathname=d.source==='vhf'?'/':'/'+(d.source==='adsb'?'':d.id);if(d.source==='vhf')url.hash=d.id;
    if(item.href!==url.href)item.href=url.href;
    text(item,d.name+' · '+d.state+(d.enabled?' · '+d.successful.toLocaleString()+' '+d.unit:'')+(d.enabled&&!d.inSpan?' · outside span':''));
    item.title='Open '+d.name+' controls';item.dataset.enabled=String(d.enabled);item.style.setProperty('--decoder-color',d.color);
   }
  }
  function renderCounts(){
   const tbody=$('tbody');tbody.replaceChildren();
   for(const d of data.decoders){const tr=document.createElement('tr'),receivers=data.receivers.filter(r=>r.mode===d.id);for(const value of [d.name,receivers.map(r=>r.name+' · '+r.status).join('; ')||'Not running',d.successful.toLocaleString(),d.tentative.toLocaleString(),d.unit]){const td=document.createElement('td');td.textContent=value;tr.append(td);}tbody.append(tr);}
  }
  $('.da-counts').addEventListener('toggle',()=>{if(data&&$('.da-counts').open)renderCounts();});
  function render(){
   renderLegend();if($('.da-counts').open)renderCounts();
   text($('.da-counts summary span'),'· '+data.decoders.reduce((n,d)=>n+d.successful,0).toLocaleString()+' successful outputs');
   const missing=data.sources.filter(s=>!s.online).map(s=>s.id);
   text($('.da-readout'),(missing.length?'Unavailable feeds: '+missing.join(', ')+' · ':'')+'Counts since '+clock(data.started)+' · newest at top · point to a mark for details');
   draw();
  }
  async function poll(){if(pending||document.hidden)return;pending=true;const requestedAt=performance.now();try{const r=await fetch(base+'/api/ituner/activity',{signal:AbortSignal.timeout(4000)});if(!r.ok)throw Error();const value=await r.json();if(value.version!==1||!Number.isFinite(value.now)||!Array.isArray(value.events))throw Error();timeline.sync(value.now,performance.now()-requestedAt);data=value;layoutCache=null;uiDirty=topDirty=true;online=true;render();}catch{online=false;$('.da-readout').textContent='Central decoder feed unavailable. Existing marks continue aging; no new activity is assumed.';}finally{pending=false;}}
  $('select').onchange=e=>{seconds=Number(e.target.value);layoutCache=null;uiDirty=topDirty=true;if(data)render();};
  function updateView(){
   const span=view.high-view.low;
   navigation.querySelector('output').textContent=`${Number((view.low/1e6).toFixed(3))}–${Number((view.high/1e6).toFixed(3))} MHz · ${Number((MAX/span).toFixed(1))}×`+(focus===null?'':` · focus ${fmt(focus)}`);
   for(const name of ['out','reset'])navigation.querySelector(`[data-view="${name}"]`).disabled=span>=MAX;
   navigation.querySelector('[data-view="in"]').disabled=span<=MIN_SPAN;
   navigation.querySelector('[data-view="left"]').disabled=view.low<=0;
   navigation.querySelector('[data-view="right"]').disabled=view.high>=MAX;
   spectrum.setAttribute('aria-label',`Decoded output activity by frequency, ${fmt(view.low)} to ${fmt(view.high)}`);layoutCache=null;uiDirty=topDirty=true;if(data)renderLegend();draw();
  }
  function navigate(action){
   if(action==='reset'){view={...FULL};focus=null;}
   else if(action==='left'||action==='right'){view=panRange(view,action==='left'?-.4:.4);focus=null;}
   else view=zoomRange(view,action==='in'?.5:2,focus??undefined);
   updateView();
  }
  navigation.onclick=e=>{const action=e.target.closest('[data-view]')?.dataset.view;if(action)navigate(action);};
  const frequencyAt=event=>{const box=waterfall.getBoundingClientRect();return view.low+clamp((event.clientX-box.left)/box.width,0,1)*(view.high-view.low);};
  const chart=$('.da-chart'),pointers=new Map();let gesture=null,moved=false;
  chart.addEventListener('wheel',event=>{if(!event.deltaY||pointers.size)return;event.preventDefault();const anchor=frequencyAt(event),delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?HEIGHT:1);view=zoomRange(view,Math.exp(clamp(delta,-100,100)*.006),anchor);focus=null;updateView();},{passive:false});
  waterfall.addEventListener('keydown',event=>{const action={'+':'in','=':'in','-':'out',ArrowLeft:'left',ArrowRight:'right',Home:'reset'}[event.key];if(action){event.preventDefault();navigate(action);}});
  function inspect(event){if(!data)return;const box=waterfall.getBoundingClientRect(),x=(event.clientX-box.left)*WIDTH/box.width,y=(event.clientY-box.top)*HEIGHT/box.height;const hits=points.filter(p=>Math.abs(p.x+p.width/2-x)<=Math.max(4,p.width/2)&&y>=p.y&&y<p.y+p.height);$('.da-readout').textContent=hits.length?hits.slice(0,6).map(e=>`${data.decoders.find(d=>d.id===e.mode)?.name||e.mode} · ${fmt(e.frequency)} · ${e.count} output${e.count===1?'':'s'} · ${clock(e.lastSeen)} · ${e.receiver}${e.tentative?' · tentative':''}`).join(' | '):fmt(view.low+x/WIDTH*(view.high-view.low))+' · no decoded output in this time cell';}
  const position=event=>{const box=chart.getBoundingClientRect();return {x:event.clientX-box.left,y:event.clientY-box.top};};
  const beginGesture=()=>{gesture={view:{...view},points:[...pointers.values()],width:chart.getBoundingClientRect().width};};
  chart.addEventListener('pointerdown',event=>{
   if(event.button!==0||pointers.size>=2)return;
   event.preventDefault();if(!pointers.size)moved=false;else moved=true;
   pointers.set(event.pointerId,position(event));chart.setPointerCapture(event.pointerId);beginGesture();chart.classList.add('da-dragging');
  });
  chart.addEventListener('pointermove',event=>{
   if(!pointers.has(event.pointerId)){if(!pointers.size&&event.target===waterfall)inspect(event);return;}
   event.preventDefault();pointers.set(event.pointerId,position(event));const current=[...pointers.values()];
   if(!moved)moved=current.some((p,i)=>Math.hypot(p.x-gesture.points[i].x,p.y-gesture.points[i].y)>6);
   if(moved){view=gestureRange(gesture.view,gesture.points,current,gesture.width);focus=null;updateView();}
  });
  function finishGesture(event){
   if(!pointers.has(event.pointerId))return;
   const tap=event.type==='pointerup'&&!moved&&pointers.size===1;
   pointers.delete(event.pointerId);if(chart.hasPointerCapture(event.pointerId))chart.releasePointerCapture(event.pointerId);
   if(pointers.size){moved=true;beginGesture();}else{gesture=null;chart.classList.remove('da-dragging');}
   if(tap){focus=frequencyAt(event);updateView();if(event.target===waterfall||event.clientY>=waterfall.getBoundingClientRect().top)inspect(event);}
  }
  for(const name of ['pointerup','pointercancel','lostpointercapture'])chart.addEventListener(name,finishGesture);
  waterfall.addEventListener('pointerleave',()=>{if(!pointers.size&&data&&online)render();});
  updateView();
  let running=false,pollTimer=null,frame=null;
  function animate(){if(!running)return;draw();frame=requestAnimationFrame(animate);}
  function start(){if(running||document.hidden)return;running=true;poll();pollTimer=setInterval(poll,1000);frame=requestAnimationFrame(animate);}
  function stop(){running=false;clearInterval(pollTimer);cancelAnimationFrame(frame);pollTimer=frame=null;}
  addEventListener('pagehide',stop);addEventListener('pageshow',()=>{if(!document.hidden)start();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else start();});start();
 }
 const style=document.createElement('style');style.textContent=`
 [data-decoder-activity]{box-sizing:border-box;display:block;width:1060px;max-width:100%;padding:16px;margin:16px auto;border:1px solid #2a4053;border-radius:8px;background:#0d1825;color:#dce8f2;font:12px/1.5 system-ui,sans-serif}
 .da-navigation{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:8px 0}.da-navigation button{min-height:36px;padding:6px 10px;border:1px solid #345069;border-radius:5px;background:#132637;color:#e1edf8;cursor:pointer;font:inherit}.da-navigation button:disabled{opacity:.4;cursor:default}.da-navigation button:focus-visible{outline:2px solid #78df9a;outline-offset:2px}.da-navigation output{color:#a6bdcd;font-variant-numeric:tabular-nums;margin-left:6px}
 [data-decoder-activity] *{box-sizing:border-box}.da-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}.da-heading h2{font-size:17px;margin:0}.da-heading p{margin:3px 0 10px;color:#91a9bd}.da-heading label{font-size:11px;color:#a6bdcd}.da-heading select{display:block;min-height:38px;background:#132637;border:1px solid #345069;border-radius:5px;color:#e1edf8;padding:7px;margin-top:3px}.da-chart{width:1026px;max-width:100%;overflow:hidden;border:1px solid #223e53;border-radius:4px;background:#07101b}.da-chart canvas{width:100%;height:auto;display:block;image-rendering:auto;touch-action:none;user-select:none;cursor:grab}.da-chart.da-dragging canvas{cursor:grabbing}.da-spectrum{border-bottom:1px solid #294154}.da-density{padding-top:7px;color:#8fa6ba;font-size:11px;font-variant-numeric:tabular-nums}.da-readout{min-height:36px;padding-top:8px;color:#b7d1e4;overflow-wrap:anywhere}.da-note,.da-counts p{color:#8fa6ba;font-size:11px;margin:4px 0 10px}.da-legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:7px 0 10px;color:#a6bdcd}.da-status{margin:5px 0 9px;padding:8px 10px;border:1px solid #66502b;border-radius:5px;color:#efcb8b;background:#262114}.da-status[data-live="true"]{border-color:#285344;background:#10271f;color:#99dfbd}.da-legend a{font-variant-numeric:tabular-nums;padding:5px 8px;border:1px solid #29465b;border-radius:5px;background:#102334;color:#d2e4ef;text-decoration:none}.da-legend a[data-enabled="false"]{color:#92a7ba;background:#101b27;border-color:#26394a}.da-legend a:hover,.da-legend a:focus-visible{border-color:#78df9a;outline:1px solid #78df9a}.da-legend a:before{content:'';display:inline-block;background:var(--decoder-color);width:8px;height:8px;margin-right:6px}.da-counts summary{cursor:pointer;color:#c6dce9;font-size:12px}.da-counts summary span{color:#8fa6ba;font-size:11px}.da-table-wrap{max-height:240px;overflow:auto}.da-counts table{border-collapse:collapse;width:100%;font-size:11px}.da-counts th,.da-counts td{padding:6px 9px;border-bottom:1px solid #21384a;text-align:left}.da-counts th{color:#8fa6ba}.da-counts td:nth-child(3),.da-counts td:nth-child(4){font-variant-numeric:tabular-nums;text-align:right}
 `;document.head.append(style);
})(typeof globalThis==='object'?globalThis:this);
