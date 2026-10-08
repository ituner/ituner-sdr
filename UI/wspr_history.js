/* Durable history and opt-in reporting; receiver transport controls stay shared. */
class WSPRHistoryUI {
 constructor(refresh){
  this.sources=[];this.rows=[];this.offset=0;this.total=0;this.token='';this.revision=0;this.busy=false;this.refresh=refresh;
  document.getElementById('history-filter').innerHTML=`<label>Receiver <select id="history-source"><option value="">All receivers</option></select></label><label>Band <select id="history-band"><option value="">All bands</option></select></label><label>Period <select id="history-scope"><option value="24h">Last 24 hours</option><option value="today">Today (UTC)</option><option value="session">Latest session</option><option value="all">All history</option><option value="range">Date range (UTC)</option></select></label><span id="history-dates" hidden><label>From <input type="date" id="history-from"></label><label>Through <input type="date" id="history-to"></label></span><a id="history-csv" href="/api/wspr/history.csv">Export CSV</a><button id="report-open">WSPRnet uploads</button>`;
  document.getElementById('history-paging').innerHTML='<button id="history-prev">Previous</button> <span id="history-count"></span> <button id="history-next">Next</button>';
  for(const id of ['history-source','history-band','history-scope','history-from','history-to'])document.getElementById(id).onchange=()=>{
   if(id==='history-source'){this.bands();const p=this.profile();if(p)document.getElementById('history-scope').value=p.is_local?'24h':'session'}
   document.getElementById('history-dates').hidden=document.getElementById('history-scope').value!=='range';this.offset=0;this.revision++;this.load();
  };
  document.getElementById('history-prev').onclick=()=>{this.offset=Math.max(0,this.offset-50);this.revision++;this.load()};
  document.getElementById('history-next').onclick=()=>{if(this.offset+50<this.total)this.offset+=50;this.revision++;this.load()};
  document.getElementById('report-open').onclick=()=>this.openReporting();
  document.getElementById('report-close').onclick=()=>document.getElementById('report-dialog').close();
  document.getElementById('report-source').onchange=()=>this.fillReporting();
  document.getElementById('report-form').onsubmit=e=>{e.preventDefault();this.saveReporting()};
 }
 profile(){return this.sources.find(r=>r.source===document.getElementById('history-source').value)}
 updateSources(sources){
  this.sources=sources;const s=document.getElementById('history-source'),chosen=s.value;
  s.replaceChildren(new Option('All receivers',''));for(const p of sources)s.add(new Option(p.name,p.source));s.value=sources.some(p=>p.source===chosen)?chosen:'';this.bands();
 }
 bands(){const s=document.getElementById('history-band'),chosen=s.value,p=this.profile();s.replaceChildren(new Option('All bands',''));const bands=[...new Set((p?[p]:this.sources).flatMap(r=>r.bands))].sort((a,b)=>Number(b)-Number(a));for(const b of bands)s.add(new Option(b+' m',b));s.value=bands.includes(chosen)?chosen:''}
 params(){
  const q=new URLSearchParams();for(const k of ['source','band','scope']){const v=document.getElementById('history-'+k).value;if(v)q.set(k,v)}
  if(q.get('scope')==='range')for(const [id,k,extra] of [['history-from','since',0],['history-to','until',86400]]){const value=document.getElementById(id).value;if(value)q.set(k,Date.parse(value+'T00:00:00Z')/1000+extra)}
  return q;
 }
 async load(){
  const revision=this.revision;
  try{
   const q=this.params();document.getElementById('history-csv').href='/api/wspr/history.csv?'+q;
   q.set('offset',this.offset);q.set('limit',50);
   const response=await fetch('/api/wspr/history?'+q,{cache:'no-store'});if(!response.ok)throw Error('History is unavailable');const data=await response.json();if(revision!==this.revision)return;
   this.total=data.total;this.rows=data.spots;const tbody=document.getElementById('spots');tbody.replaceChildren();
   for(const s of this.rows){const tr=document.createElement('tr');const values=[new Date(s.cycle_start*1000).toISOString().replace('T',' ').slice(0,16),s.callsign,s.grid,s.snr_db,Number(s.frequency_mhz).toFixed(6),s.power_dbm,s.drift_hz,(s.session_receiver||s.source)+' / '+s.band+' m'];for(const v of values){const td=document.createElement('td');td.textContent=v??'—';tr.append(td)}tbody.append(tr)}
   document.getElementById('empty').hidden=this.rows.length>0;document.getElementById('empty').textContent=data.importing?'Importing saved logs…':'No spots in this view. Try All history or another receiver.';
   document.getElementById('history-count').textContent=data.total+' saved spots · page '+(Math.floor(this.offset/50)+1);
   document.getElementById('history-prev').disabled=this.offset===0;document.getElementById('history-next').disabled=this.offset+50>=data.total;
   if(data.error)document.getElementById('notice').textContent=data.error;
  }catch(e){document.getElementById('notice').textContent=e.message}
 }
 async refreshProfiles(){const r=await fetch('/api/wspr/reporting',{cache:'no-store'});if(!r.ok)return;const d=await r.json();this.token=d.control_token;this.updateSources(d.sources)}
 async openReporting(){await this.refreshProfiles();const select=document.getElementById('report-source');select.replaceChildren();for(const p of this.sources)select.add(new Option(p.name,p.source));const chosen=document.getElementById('history-source').value;if(chosen)select.value=chosen;this.fillReporting();document.getElementById('report-dialog').showModal()}
 fillReporting(){const p=this.sources.find(s=>s.source===document.getElementById('report-source').value);if(!p)return;document.getElementById('report-call').value=p.call;document.getElementById('report-grid').value=p.grid;document.getElementById('report-enabled').checked=!!p.enabled;document.getElementById('report-confirmed').checked=!!p.confirmed;document.getElementById('report-status').textContent=(Object.entries(p.uploads).map(([k,v])=>k+': '+v).join(' · ')||'No uploads')+(p.last_error?' · '+p.last_error:'');document.getElementById('report-error').textContent=''}
 async saveReporting(){
  const button=document.getElementById('report-save');button.disabled=true;
  try{const body={source:document.getElementById('report-source').value,call:document.getElementById('report-call').value,grid:document.getElementById('report-grid').value,enabled:document.getElementById('report-enabled').checked,confirmed:document.getElementById('report-confirmed').checked};const r=await fetch('/api/wspr/reporting',{method:'POST',headers:{'Content-Type':'application/json','X-SDR-Control':this.token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not save');document.getElementById('report-error').textContent='Saved. '+(body.enabled?'New spots will be uploaded.':'Uploading is off.');await this.refreshProfiles()}catch(e){document.getElementById('report-error').textContent=e.message}finally{button.disabled=false}
 }
}
