'use strict';
// Native RTL433-UI cards and plots, with the shared iTuner receiver controls.
(()=>{
  const section=document.createElement('section');section.id='ituner-receiver';
  section.innerHTML='<div class="ituner-radio-row"><label>Primary USB <select id="ituner-device" aria-label="USB receiver"><option value="auto">Auto · available dongle</option></select></label><button id="ituner-start">▶ Start sensors</button><button id="ituner-stop">■ Stop sensors</button><label class="pool-option"><input type="checkbox" id="ituner-expand" checked> Use free dongles</label><a id="ituner-observatory">Decoders ↗</a><a id="ituner-airspace">Airspace ↗</a><a id="ituner-survey">Spectrum Survey ↗</a><a id="ituner-weather">Weather ↗</a></div><div id="ituner-state" role="status">Connecting to the CM5 receiver…</div><div id="ituner-pool" aria-label="Sensor receivers"></div>';
  document.querySelector('header').after(section);
  const style=document.createElement('style');style.textContent=`
  #ituner-receiver{padding:10px 20px;border-bottom:1px solid var(--border);background:var(--surface);flex-shrink:0}
  .ituner-radio-row{display:flex;align-items:center;flex-wrap:wrap;gap:12px}.ituner-radio-row label{display:flex;gap:8px;align-items:center}
  .ituner-radio-row select{max-width:min(430px,75vw)}
  .ituner-radio-row button,.ituner-radio-row select,.intelligent-scan button{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;min-height:40px}
  .ituner-radio-row button:disabled{opacity:.4}.ituner-radio-row a{color:var(--accent);text-decoration:none}
  #ituner-state{margin-top:6px;color:var(--text-dim);font-size:12px}
  .intelligent-scan{padding:10px 14px;border-bottom:1px solid var(--border);background:var(--surface)}
  .intelligent-scan summary{cursor:pointer;display:flex;justify-content:space-between;gap:12px;color:var(--text);font-weight:600;min-height:26px}
  #ituner-scan-badge{color:var(--green);font:11px var(--mono)}.scan-description{color:var(--text-dim);font-size:11px;margin:5px 0 8px}
  .scan-live{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
  #ituner-scan-state{font-size:12px;color:var(--accent-hover)}.scan-table-wrap{overflow:auto;max-height:185px}
  .intelligent-scan table{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}
  .intelligent-scan th{text-align:right;color:var(--text-dim);font-weight:400;position:sticky;top:0;background:var(--surface)}
  .intelligent-scan td{text-align:right;border-top:1px solid var(--border);padding:5px 6px;white-space:nowrap}
  .intelligent-scan th:first-child,.intelligent-scan td:first-child{text-align:left}.scan-current{color:var(--green);background:rgba(34,197,94,.06)}
  #ituner-pool{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}.receiver-chip{display:flex;gap:10px;align-items:center;border:1px solid var(--border);border-radius:5px;padding:5px 9px;background:var(--surface-2);font-size:11px}.receiver-chip strong{color:var(--green);font-family:var(--mono)}.receiver-chip small{color:var(--text-dim)}.pool-option{font-size:12px}.pool-option input{accent-color:var(--green)}
  .scan-band-button{padding:2px 6px!important;min-height:28px!important;color:inherit!important;cursor:pointer}
  #btn-scan.active{color:var(--green);border-color:var(--green)}
  @media(max-width:700px){#ituner-receiver{padding:8px 12px}.ituner-radio-row{gap:8px}.intelligent-scan summary{font-size:12px}}
  `;document.head.append(style);
  const $=id=>document.getElementById(id);
  $('ituner-observatory').href=`http://${location.hostname}:8092/#ism`;
  $('ituner-airspace').href=`http://${location.hostname}:8090/`;
  $('ituner-weather').href=`http://${location.hostname}:8094/`;
  $('ituner-survey').href=`http://${location.hostname}:8092/spectrum`;
  const panel=$('scan-results');panel.style.display='';panel.innerHTML='<details class="intelligent-scan" id="ituner-scan-details"><summary><span>Intelligent Scan</span><span id="ituner-scan-badge">READY</span></summary><p class="scan-description">Parallel USB receivers · six popular frequencies · 60–180 s per visit. Learns from decoded packets, revisits productive bands and keeps exploring. Up to six free dongles join automatically. Runs with this tab closed.</p><div class="scan-live"><span id="ituner-scan-state" role="status"></span><button id="ituner-scan-hold">Hold frequency</button></div><div class="scan-table-wrap"><table><thead><tr><th>MHz / hold</th><th>Packets</th><th>Devices</th><th>Receiver</th><th>Listened</th><th>pkt/min</th><th>Last RX</th></tr></thead><tbody id="ituner-scan-bands"></tbody></table></div></details>';
  let enabled=false,busy=false,scanEnabled=false,first=true,pending=false;
  const mhz=hz=>String(Number((hz/1e6).toFixed(3)));
  const age=ts=>!ts?'—':timeAgo(ts*1000);
  async function call(url,body){if(pending)return;pending=true;try{const r=await fetch(API_BASE+url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});const value=await r.json();if(!r.ok)throw Error(value.error||'Receiver request failed');await refresh();}finally{pending=false;}}
  async function refresh(){if(busy)return;busy=true;try{
    const r=await fetch(API_BASE+'/api/ituner/receiver');if(!r.ok)throw Error('Receiver offline');const s=await r.json();
    enabled=s.settings.enabled===true;const select=$('ituner-device');
    if(document.activeElement!==select){const choices=[{id:'auto',label:'Auto · available dongle'},...s.devices.filter(d=>d.persistent)];select.replaceChildren(...choices.map(d=>{const o=document.createElement('option');o.value=d.id;o.textContent=d.label;return o;}));select.value=(s.primary_settings||s.settings).selection||'auto';}
    $('ituner-start').disabled=enabled;$('ituner-stop').disabled=!enabled;
    const frequency=Number(s.settings.frequency)/1e6;
    $('ituner-state').textContent=(Number.isFinite(frequency)?frequency.toFixed(3)+' MHz · ':'')+(s.assigned?.label||s.error||'Select a receiver and press Start sensors.');
    if(Number.isFinite(frequency)){state.frequency=frequency+'M';updateFreqButtons(state.frequency);}
    if(document.activeElement!==$('ituner-expand'))$('ituner-expand').checked=s.pool?.autoExpand!==false;
    const lanes=s.receivers||[],visits=s.scan?.receivers||[];
    $('ituner-pool').replaceChildren(...lanes.map(r=>{
      const chip=document.createElement('div');chip.className='receiver-chip';
      const name=document.createElement('span');name.textContent=r.assigned?.serial||r.settings.selection||r.id;
      const freq=document.createElement('strong');freq.textContent=mhz(r.receiving_frequency||r.settings.frequency)+' MHz';
      const detail=document.createElement('small'),v=visits.find(v=>v.id===r.id);detail.textContent=r.status+(v?' · '+v.remaining+'s':'');
      chip.append(name,freq,detail);return chip;
    }));
    if(lanes.length>1)$('ituner-state').textContent=lanes.length+' sensor receivers · simultaneous frequencies · '+(s.pool?.warning||'Other decoders keep their assigned dongles.');
    const scan=s.scan;if(scan){
      scanEnabled=scan.enabled;
      if(first&&scanEnabled)$('ituner-scan-details').open=true;first=false;
      $('btn-scan').textContent=scanEnabled?'◉ Intelligent Scan ON':'▶ Intelligent Scan';$('btn-scan').classList.toggle('active',scanEnabled);
      $('ituner-scan-badge').textContent=scanEnabled?'SCANNING · ROUND '+scan.round:'HOLD / MANUAL';
      $('ituner-scan-hold').disabled=!scanEnabled;
      $('ituner-scan-state').textContent=scanEnabled&&scan.current?`${mhz(scan.current.frequency)} MHz · ${scan.reason} · ${scan.current.remaining}s listening left`:scan.reason;
      $('ituner-scan-bands').replaceChildren(...scan.bands.map(b=>{
        const tr=document.createElement('tr');tr.className=scanEnabled&&visits.some(v=>v.frequency===b.frequency)?'scan-current':'';
        const td=document.createElement('td'),button=document.createElement('button');button.className='scan-band-button';button.textContent=mhz(b.frequency);button.title='Hold '+mhz(b.frequency)+' MHz';button.onclick=()=>call('/api/frequency',{frequency:b.frequency}).catch(showError);td.append(button);tr.append(td);
        for(const value of [b.packets,b.devices.length,visits.filter(v=>v.frequency===b.frequency).map(v=>lanes.find(r=>r.id===v.id)?.assigned?.serial||v.id).join(', ')||'—',Math.floor(b.seconds/60)+'m '+Math.floor(b.seconds%60)+'s',b.packetsPerMinute.toFixed(1),age(b.lastSeen)]){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}return tr;
      }));
    }
  }catch(e){showError(e);}finally{busy=false;}}
  function showError(e){$('ituner-state').textContent=e.message;}
  $('ituner-start').onclick=()=>call('/api/rtl433/start').catch(showError);
  $('ituner-stop').onclick=()=>call('/api/rtl433/stop').catch(showError);
  $('ituner-expand').onchange=()=>call('/api/ituner/receiver',{autoExpand:$('ituner-expand').checked}).catch(showError);
  $('ituner-device').onchange=()=>call('/api/ituner/receiver',{selection:$('ituner-device').value}).catch(showError);
  $('btn-scan').onclick=()=>{$('ituner-scan-details').open=true;call('/api/ituner/scan/'+(scanEnabled?'stop':'start')).catch(showError);};
  $('ituner-scan-hold').onclick=()=>call('/api/ituner/scan/stop').catch(showError);
  const hint=document.createElement('p');hint.textContent='Shared iTuner / SoapySDR receiver. Starting sensors hands off an occupied dongle. Supported receiver configuration: frequency, gain and ppm. Primary USB chooses the main receiver; Intelligent Scan adds only free dongles with unique serials. Hold freezes all active receiver frequencies.';
  document.getElementById('cfg-rtl433-conf').before(hint);
  refresh();setInterval(refresh,2000);
})();
