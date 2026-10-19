/* Survey workflow tools. All measurements and RF changes use the shared backend. */
(function(root){'use strict';
 const $=id=>document.getElementById(id),finite=Number.isFinite;
 let app=null,state=null,insights=null,active='survey',fetching=false,fetchAt=0,fetchKey='',seq=0,busy=false,selected=null,serverConfig='',activityGeometry=null,activityStamp='',difference=null,differenceKey='',comparing=false,signalPage=0;
 const palette=[[8,18,29],[25,78,145],[32,170,168],[196,225,116],[255,240,188]];
 const mhz=f=>(f/1e6).toFixed(6),clock=t=>t?new Date(t*1000).toLocaleTimeString():'—';
 function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
 function button(text,fn){const el=node('button',text);el.onclick=fn;return el;}
 function feedback(text){$('warning').textContent=text;}
 async function action(name,values={}){if(busy)return;busy=true;feedback(name==='investigate'?'Opening live investigation…':name==='return'?'Restoring previous survey…':'Applying…');try{const result=await app.command(name,values);fetchAt=0;await app.poll();feedback(name==='report'?'Report saved. Open it from the list below.':'');return result;}catch(e){feedback(e.message);}finally{busy=false;}}
 function choose(frequency){selected=frequency;$('investigate-frequency').value=mhz(frequency);$('watch-frequency').value=mhz(frequency);$('investigate-start').hidden=false;document.querySelector('.mission-bar').hidden=false;$('mission-description').textContent='Selected '+mhz(selected)+' MHz';app.select(frequency);}
 function investigate(frequency){if(!finite(frequency)||frequency<25e6||frequency>1700e6){feedback('Choose a frequency within 25–1700 MHz.');return;}choose(frequency);action('investigate',{frequency}).then(result=>{if(result)workspace('survey');});}
 function workspace(value){active=value;const back=$('scanner-back'),parent=['activity','compare','watch','reports'].includes(value)?'tools':value==='survey'?null:'survey';back.textContent=parent==='tools'?'← Back to tools':parent==='survey'?'← Back to scan':'← Back to decoders';back.href=parent?'#'+parent:'/';back.onclick=parent?e=>{e.preventDefault();workspace(parent);}:null;document.body.dataset.workspace=value;for(const el of document.querySelectorAll('[data-workspace]'))if(el.tagName==='BUTTON')el.classList.toggle('active',el.dataset.workspace===value||el.dataset.workspace==='tools'&&!['survey','signals'].includes(value));for(const key of ['survey','signals','tools','activity','compare','watch','reports'])$(key+'-view').hidden=key!==value;activityStamp='';refresh(true);app.draw();}
 function selectedFrequency(){return Number($('investigate-frequency').value)*1e6;}
 function update(value){
  state=value;const s=state.settings,purpose=s.purpose||'survey',config=JSON.stringify([s.low,s.high,s.bin,s.gain,s.ppm,s.selection,s.repeat,s.auto_gain,purpose,s.focus]);
  if(config!==serverConfig){serverConfig=config;app.fillSettings(s);fetchAt=0;}
  $('mission-mode').textContent=purpose==='investigate'?'LIVE INVESTIGATION':purpose==='watch'?'FREQUENCY WATCHLIST':'BROAD SURVEY';
  document.querySelector('.mission-bar').hidden=!finite(selected)&&!state.can_return&&purpose!=='investigate';
  $('mission-description').textContent=finite(selected)?'Selected '+mhz(selected)+' MHz':purpose==='investigate'?'Fixed tuning · ~5 averaged frames/s · '+mhz(s.focus)+' MHz target':purpose==='watch'?'Revisiting saved frequencies; other ranges are not surveyed.':'Discover → select a signal → investigate its band.';
  $('return-survey').hidden=!state.can_return;$('return-survey').textContent='← Return to '+(state.return_to==='watch'?'watchlist':'survey');
  $('scan-settings-summary').textContent=mhz(s.low)+'–'+mhz(s.high)+' MHz · '+s.bin/1000+' kHz bins · '+(s.repeat?'Repeating':'One sweep');$('start').hidden=state.enabled;$('stop').hidden=!state.enabled;
  $('investigate-start').hidden=!finite(selected);
  $('watch-start').textContent=purpose==='watch'?'Restart watch mode':'Start watch mode';
  for(const id of ['investigate-start','return-survey','watch-start'])$(id).disabled=busy;
  renderWatches();renderReports();renderComparison();refresh(false);
 }
 async function refresh(force){
  if(!state||fetching||!['signals','activity','watch'].includes(active))return;const scope=active==='signals'&&state.can_return?'survey':'current',range=app.getView(),params=new URLSearchParams({columns:'512',scope,detail:active==='activity'?($('activity-mode').value==='persistence'?'persistence':'timeline'):'signals'});
  if(scope==='current'&&range){params.set('low',range[0]);params.set('high',range[1]);}
  const key=params.toString();if(!force&&key===fetchKey&&Date.now()-fetchAt<4000)return;if(key!==fetchKey){insights=null;activityStamp='';const canvas=$('activity-plot');canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);$('activity-description').textContent='Loading matching measurements…';}fetching=true;fetchKey=key;const serial=++seq;
  try{const response=await fetch('/api/spectrum/insights?'+params,{signal:AbortSignal.timeout(20000)});if(!response.ok)throw Error('Analysis unavailable; retrying.');const data=await response.json();if(serial!==seq||key!==fetchKey)return;insights=data;fetchAt=Date.now();activityStamp='';renderSignals();renderWatches();draw();}
  catch(e){$('discovery-method').textContent=e.message;fetchAt=Date.now()-3000;}
  finally{fetching=false;}
 }
 function renderSignals(){
  if(!insights)return;$('signal-count').textContent=insights.signals.length;
  $('discovery-method').textContent=(state.can_return&&active==='signals'?'Original survey results retained · ':'')+insights.visits+' completed visits · +'+insights.threshold+' dB above estimated local floor. Widths are estimates at the acquired bin resolution.';
  const sort=$('signal-sort').value,rows=[...insights.signals].sort((a,b)=>(b[sort]??-1)-(a[sort]??-1));
  const pages=Math.max(1,Math.ceil(rows.length/20));signalPage=Math.min(signalPage,pages-1);$('signal-page').textContent='Page '+(signalPage+1)+' / '+pages+' · '+rows.length+' signals';$('signal-prev').disabled=signalPage===0;$('signal-next').disabled=signalPage===pages-1;
  $('signal-rows').replaceChildren(...rows.slice(signalPage*20,(signalPage+1)*20).map(signal=>{
   const tr=node('tr');if(selected===signal.frequency)tr.className='selected';
   const frequency=node('td',mhz(signal.frequency)+' MHz');frequency.append(node('small','First '+clock(signal.first)));tr.append(frequency,node('td',(signal.width/1000).toFixed(1)+' kHz'),node('td','+'+signal.excess.toFixed(1)+' dB'),node('td',signal.active_visits+' / '+signal.visits+' · '+(signal.activity??0).toFixed(1)+'%'),node('td',clock(signal.last)));
   const controls=node('td');controls.append(button('Investigate',()=>investigate(signal.frequency)),button('+ Watch',()=>{choose(signal.frequency);action('watch_add',{frequency:signal.frequency,bandwidth:Math.max(2500,Math.min(1e6,signal.width))});}));tr.append(controls);tr.onclick=()=>choose(signal.frequency);return tr;
  }));
  if(!rows.length){const tr=node('tr'),td=node('td','No signals above the detection threshold in completed visits yet.');td.colSpan=6;tr.append(td);$('signal-rows').append(tr);}
 }
 function renderWatches(){
  const watches=state?.watchlist||[];
  $('watch-rows').replaceChildren(...watches.map(w=>{
   const tr=node('tr'),name=node('td',mhz(w.frequency)+' MHz');name.append(node('small',w.label+' · '+w.bandwidth/1000+' kHz'));
   const m=w.measurement,status=w.stale?'Not recently sampled':m?.present?'Detected':'Quiet on valid visits';
   tr.append(name,node('td',status+' · '+clock(m?.time)),node('td',m?m.level.toFixed(1)+' dBFS/Hz · +'+m.excess.toFixed(1)+' dB'+(m.resolution?' · '+(m.resolution/1000).toFixed(1)+' kHz resolution':''):'—'));
   const controls=node('td');controls.append(button('Investigate',()=>investigate(w.frequency)),button('Remove',()=>action('watch_remove',{id:w.id})));tr.append(controls);return tr;
  }));
  if(!watches.length){const tr=node('tr'),td=node('td','Select a discovered signal or add a frequency above.');td.colSpan=4;tr.append(td);$('watch-rows').append(tr);}
  $('watch-events').replaceChildren(...(insights?.events||[]).map(e=>node('div',clock(e.time)+' · '+e.label+' · '+e.kind.toUpperCase()+' · '+e.detail)));
 }
 function renderReports(){
  $('report-list').replaceChildren(...(state?.reports||[]).map(report=>{
   const card=node('article',undefined,'report-card');card.append(node('strong',report.label),node('p',new Date(report.time*1000).toLocaleString()));
   for(const [name,file] of [['Open / print report','index.html'],['CSV','signals.csv'],['JSON','report.json'],['Waterfall PNG','waterfall.png']]){const link=node('a',name);link.href='/spectrum/reports/'+report.id+'/'+file;link.target='_blank';link.rel='noopener';card.append(link);}return card;
  }));
  if(!state?.reports?.length)$('report-list').append(node('p','Your exported reports will appear here.'));
 }
 function renderComparison(){
  const reference=app?.getBaseline(),signature=JSON.stringify((state?.saved||[]).map(s=>[s.id,s.label]));if($('compare-baseline').dataset.signature!==signature){$('compare-baseline').replaceChildren(new Option('Choose a saved baseline',''),...(state?.saved||[]).map(s=>new Option(s.label,s.id)));$('compare-baseline').dataset.signature=signature;}$('compare-baseline').value=$('baseline').value;
  const canvas=$('difference-plot'),width=canvas.clientWidth,height=canvas.clientHeight;if(!width||active!=='compare')return;
  canvas.width=width;canvas.height=height;const c=canvas.getContext('2d');c.fillStyle='#0a1622';c.fillRect(0,0,width,height);
  if(!reference||!app.compatible()){$('comparison-summary').textContent=reference?'Settings differ: overlay and differences are hidden. Match receiver, range, actual gain, bins and PPM.':'Choose a saved reference above.';return;}
  const key=reference.id+':'+state.last_complete_finished;
  if(key!==differenceKey&&!comparing){comparing=true;differenceKey=key;difference=null;fetch('/api/spectrum/compare?id='+encodeURIComponent(reference.id)).then(r=>{if(!r.ok)throw Error('Comparison unavailable');return r.json();}).then(value=>{if(differenceKey===key)difference=value;}).catch(e=>{difference={matched:false,reason:e.message};}).finally(()=>{comparing=false;renderComparison();});}
  if(!difference?.matched){$('comparison-summary').textContent=difference?.reason||'Waiting for a completed sweep B at matching settings…';return;}
  const d=state.data,s=d.settings,range=app.getView()||[s.low,s.high],delta=difference.delta,valid=delta.filter(finite).sort((a,b)=>a-b),extent=Math.max(5,...valid.map(v=>Math.abs(v))),left=58,w=width-78,top=25,h=height-65;
  $('comparison-summary').textContent=valid.length?'Latest complete B − saved A · median '+valid[Math.floor(valid.length/2)].toFixed(1)+' dB · range '+valid[0].toFixed(1)+' to '+valid.at(-1).toFixed(1)+' dB · '+valid.length.toLocaleString()+' matched valid bins':'No comparable valid bins.';
  c.font='11px monospace';c.fillStyle='#9cb4c7';for(const value of [-extent,0,extent]){const yy=top+(extent-value)/(extent*2)*h;c.strokeStyle=value===0?'#65899b':'#263b4d';c.beginPath();c.moveTo(left,yy);c.lineTo(left+w,yy);c.stroke();c.fillText(value.toFixed(0)+' dB',4,yy+4);}
  c.strokeStyle='#70e2c0';c.beginPath();let pen=false;delta.forEach((v,i)=>{const frequency=s.low+(i+.5)*s.bin;if(frequency<range[0]||frequency>range[1])return;if(!finite(v)){pen=false;return;}const x=left+(frequency-range[0])/(range[1]-range[0])*w,y=top+(extent-v)/(2*extent)*h;if(pen)c.lineTo(x,y);else c.moveTo(x,y);pen=true;});c.stroke();c.fillText(mhz(range[0])+' – '+mhz(range[1])+' MHz',left,height-12);
 }
 function rgb(value){const t=Math.max(0,Math.min(1,value))*4,i=Math.min(3,Math.floor(t)),f=t-i;return palette[i].map((v,k)=>Math.round(v+(palette[i+1][k]-v)*f));}
 function draw(){
  renderComparison();if(active!=='activity'||!insights)return;const canvas=$('activity-plot'),width=canvas.clientWidth;if(!width)return;
  const mode=$('activity-mode').value,rows=mode==='persistence'?[...insights.persistence].reverse():[...insights.timeline].reverse();
  const stamp=[mode,width,insights.key,insights.visits,insights.finished,insights.low,insights.high].join(':');if(stamp===activityStamp)return;activityStamp=stamp;
  const left=84,top=36,w=Math.max(1,width-left-20),rh=mode==='persistence'?8:Math.max(3,Math.min(20,350/Math.max(1,rows.length))),height=Math.max(370,top+rows.length*rh+24);
  canvas.style.height=height+'px';canvas.width=width;canvas.height=height;const c=canvas.getContext('2d');c.fillStyle='#101923';c.fillRect(0,0,width,height);c.font='10px monospace';c.fillStyle='#a1b9ca';
  const name=mode==='persistence'?'Spectrum persistence':mode==='activity'?'Activity heatmap':mode==='mean'?'24-hour history · mean power':'24-hour history · peak power';$('activity-title').textContent=name;
  $('activity-description').textContent=mode==='persistence'?insights.persistence_visits+' recent detailed sweeps · colour = frequency of measured level':insights.visits+' visits retained across 24-hour minute summaries · scroll for older intervals';
  $('activity-legend').textContent=mode==='activity'?'Colour = 0–100% detected visits at the strongest bin in each screen column. Grey = no valid measurement. These are sampled fractions, not continuous airtime. Rows show recorded intervals; gaps are not quiet.':mode==='persistence'?'Vertical axis = relative dBFS/Hz. Colour = fraction of recent detailed sweeps at that level (square-root colour scale). Unsampled / clipped cells do not create readings.':'Colour = −130 to −60 dBFS/Hz. Minute buckets retain mean and peak separately. Every row shows its actual capture interval; wide sweeps are sequential.';
  for(let i=0;i<=5;i++)c.fillText(((insights.low+(insights.high-insights.low)*i/5)/1e6).toFixed(2),Math.min(width-68,left+w*i/5-18),20);
  const cells=rows[0]?.length||insights.columns||512;
  if(rows.length){
   const image=c.createImageData(cells,rows.length);rows.forEach((row,y)=>{
    const values=mode==='persistence'?row:mode==='activity'?row.activity:Uint8Array.from(atob(mode==='mean'?row.mean:row.values),v=>v.charCodeAt(0));
    for(let x=0;x<cells;x++){const value=values[x];let color;
     if(mode==='persistence')color=rgb(Math.sqrt(value/Math.max(1,insights.persistence_visits)));
     else if(mode==='activity')color=finite(value)?rgb(value/100):[31,39,47];
     else color=value===0?[31,39,47]:value===1?[232,148,72]:rgb((value-202+130)/70);
     const p=(y*cells+x)*4;image.data[p]=color[0];image.data[p+1]=color[1];image.data[p+2]=color[2];image.data[p+3]=255;
    }
   });const bitmap=document.createElement('canvas');bitmap.width=cells;bitmap.height=rows.length;bitmap.getContext('2d').putImageData(image,0,0);c.imageSmoothingEnabled=false;c.drawImage(bitmap,left,top,w,rows.length*rh);
   rows.forEach((row,i)=>{if(i%Math.max(1,Math.ceil(40/rh)))return;c.fillStyle='#a1b9ca';c.fillText(mode==='persistence'?(insights.persistence_low+(rows.length-1-i)*insights.persistence_step)+' dB':new Date(row.finished*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',hour12:false}),4,top+i*rh+10);});
  }else c.fillText('Completed measurements will build this view.',left,140);
  activityGeometry={left,w,top,rh,rows,mode,cells};
 }
 function init(context){
  app=context;document.body.dataset.chart='spectrum';
  const dialog=$('scan-setup');dialog.append(document.querySelector('.receiver-details'));
  const commandBar=document.createElement('div');commandBar.className='workspace-bar';const tabs=document.querySelector('.survey-workflow');tabs.before(commandBar);commandBar.append(tabs,document.querySelector('.scan-toolbar'));
  $('open-setup').onclick=()=>dialog.showModal();$('close-setup').onclick=()=>dialog.close();
  $('settings').addEventListener('invalid',()=>{if(!dialog.open)dialog.showModal();},true);
  dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
  const compareOptions=document.querySelector('.comparison-options');$('compare-view').append(compareOptions);
  const manual=document.querySelector('.manual-tuning');$('manual-tune-slot').append(manual);const manualButton=$('investigate-start').cloneNode(true);manualButton.id='manual-investigate';manualButton.hidden=false;$('manual-tune-slot').append(manualButton);manualButton.onclick=()=>investigate(selectedFrequency());
  const extra=document.querySelector('.bottom');$('tools-view').append(extra);
  for(const b of document.querySelectorAll('button[data-chart]'))b.onclick=()=>{document.body.dataset.chart=b.dataset.chart;for(const other of document.querySelectorAll('button[data-chart]'))other.setAttribute('aria-pressed',String(other===b));app.draw();};
  app.onStarted=()=>dialog.close();
  for(const el of document.querySelectorAll('button[data-workspace]'))el.onclick=()=>workspace(el.dataset.workspace);
  $('investigate-start').onclick=()=>investigate(selectedFrequency());$('return-survey').onclick=()=>action('return').then(result=>{if(result)workspace('survey');});
  $('signal-sort').onchange=()=>{signalPage=0;renderSignals();};$('signal-prev').onclick=()=>{signalPage=Math.max(0,signalPage-1);renderSignals();};$('signal-next').onclick=()=>{signalPage++;renderSignals();};$('activity-mode').onchange=()=>{activityStamp='';fetchKey='';refresh(true);draw();};
  $('activity-zoom-in').onclick=()=>{app.zoom(.5,selected??undefined);refresh(true);};$('activity-zoom-out').onclick=()=>{app.zoom(2,selected??undefined);refresh(true);};$('activity-full').onclick=()=>{$('reset-zoom').click();refresh(true);};
  $('compare-save').onclick=()=>$('save').click();$('compare-baseline').onchange=()=>{$('baseline').value=$('compare-baseline').value;$('baseline').dispatchEvent(new Event('change'));};
  $('watch-add').onsubmit=e=>{e.preventDefault();action('watch_add',{frequency:Number($('watch-frequency').value)*1e6,label:$('watch-label').value,bandwidth:Number($('watch-width').value)*1000});};
  $('watch-start').onclick=()=>action('watch_start').then(result=>{if(result)workspace('watch');});$('report-create').onclick=()=>action('report',{label:$('report-label').value,notes:$('report-notes').value,baseline_id:$('baseline').value});
  $('activity-plot').onpointerdown=e=>{
   if(!activityGeometry||!insights)return;const g=activityGeometry,box=e.currentTarget.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(e.clientX-box.left-g.left)/g.w)),row=g.rows[Math.floor((e.clientY-box.top-g.top)/g.rh)],frequency=insights.low+fraction*(insights.high-insights.low);choose(frequency);
   $('activity-readout').textContent=mhz(frequency)+' MHz'+(row&&g.mode!=='persistence'?' · '+clock(row.started)+' – '+clock(row.finished)+' · '+row.visits+' visits':'');
  };
  new ResizeObserver(()=>{activityStamp='';draw();}).observe($('activity-plot').parentElement);
  document.body.dataset.workspace='survey';
 }
 root.SurveyTools={init,update,draw,select:choose,started:()=>app?.onStarted?.()};
})(window);
