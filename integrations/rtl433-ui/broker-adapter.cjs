'use strict';
const {EventEmitter}=require('node:events');
const fs=require('node:fs');
const path=require('node:path');
const {IntelligentScanner,PROFILES}=require('./scanner.cjs');

function frequency(value){
  if(typeof value==='number'&&Number.isFinite(value)&&value>=30e6&&value<=1700e6)return Math.round(value);
  const match=String(value).trim().match(/^(\d+(?:\.\d+)?)\s*([kmg]?)$/i);
  if(!match)throw Error('Enter a frequency such as 433.92M or 868.3M.');
  const hz=Number(match[1])*({k:1e3,m:1e6,g:1e9}[match[2].toLowerCase()]||1);
  if(!Number.isFinite(hz)||hz<30e6||hz>1700e6)throw Error('Frequency must be 30–1700 MHz.');
  return Math.round(hz);
}
function parseConfig(text){
  if(typeof text!=='string'||text.length>8192)throw Error('Receiver configuration is limited to 8 KiB.');
  const values={};
  for(const raw of text.split('\n')){
    const line=raw.split('#')[0].trim();if(!line)continue;
    const match=line.match(/^(frequency|gain|ppm)\s+(\S+)$/);
    if(!match)throw Error('Supported settings: frequency, gain, ppm. Select the dongle above; other rtl_433 settings remain managed by iTuner.');
    if(match[1]==='frequency')values.frequency=frequency(match[2]);
    else{
      const v=Number(match[2]),gain=match[1]==='gain';
      if(!Number.isFinite(v)||(gain?(v<0||v>49.6):(v< -150||v>150)))throw Error(gain?'Gain must be 0–49.6 dB.':'PPM must be −150 to 150.');
      values[match[1]]=v;
    }
  }
  return values;
}
function createAdapter(options={}){
  const emitter=new EventEmitter();
  const base=options.base||process.env.ITUNER_VHF_URL||'http://127.0.0.1:8092';
  const configFile=options.configFile||process.env.RTL433_CONFIG||'/var/lib/ituner-rtl433-ui/receiver.conf';
  const fetcher=options.fetch||fetch,now=options.now||Date.now;
  const scanFile=options.scanFile||path.join(path.dirname(configFile),'intelligent-scan.json');
  const scanLog=path.join(path.dirname(scanFile),'intelligent-scan.jsonl');
  let saved={};try{saved=JSON.parse(fs.readFileSync(scanFile,'utf8'))||{};}catch{}
  const scanner=new IntelligentScanner({now,saved});let autoExpand=saved.autoExpand!==false,lastSave=0,poolPending=false,syncing=false,poolWarning='';
  let cached=null,status='starting',error='',busy=false,closed=false,queue=Promise.resolve();
  const seen=new Set(),diagnostics=new Map();const attachedAt=now()/1000;
  const sessions=s=>s?.sensor_receivers||{ism:s?.sessions.ism};
  const active=s=>Object.entries(sessions(s)).filter(([,v])=>v?.enabled);
  const main=s=>active(s)[0]?.[1]||s?.sessions.ism;
  function saveScan(event){
    const snapshot={...scanner.snapshot(),autoExpand};
    fs.mkdirSync(path.dirname(scanFile),{recursive:true});
    fs.writeFileSync(scanFile+'.tmp',JSON.stringify(snapshot),{mode:0o600});fs.renameSync(scanFile+'.tmp',scanFile);lastSave=now();
    if(event){
      try{if(fs.statSync(scanLog).size>1024*1024)fs.renameSync(scanLog,scanLog+'.1');}catch{}
      fs.appendFileSync(scanLog,JSON.stringify({time:now()/1000,event,...snapshot})+'\n',{mode:0o600});
    }
  }
  function holdScan(reason){if(scanner.enabled){scanner.stop(reason);saveScan('hold');}}
  function setStatus(value,detail=''){
    if(value===status&&detail===error)return;
    status=value;error=detail;emitter.emit('status',{status,error});
  }
  async function request(url,init){
    const res=await fetcher(base+url,{...init,signal:AbortSignal.timeout(5000)});
    const body=await res.json();if(!res.ok)throw Error(body.error||'Receiver request failed.');return body;
  }
  async function state(){const s=await request('/api/state');if(!s.sessions?.ism)throw Error('iTuner sensor decoder is unavailable.');cached=s;return s;}
  async function control(action,values={},mode='ism'){
    const s=await state();
    return request('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-VHF-Token':s.control_token},body:JSON.stringify({mode,action,...values})});
  }
  function run(operation){
    const result=queue.catch(()=>{}).then(operation);queue=result;
    result.catch(e=>{setStatus('error',e.message);console.error('[iTuner] '+e.message);});
    return result;
  }
  function freeDevices(s){
    const used=new Set(active(s).map(([,r])=>r.assigned?.id||r.target||r.settings.selection));
    let free=s.devices.filter(d=>d.persistent&&!s.leases?.[d.id]&&!used.has(d.id));
    if(s.sessions.ism.enabled&&!s.sessions.ism.assigned&&s.sessions.ism.settings.selection==='auto'&&!s.devices.some(d=>d.id===s.sessions.ism.target))free=free.slice(1);
    return free;
  }
  function needsPool(s){
    if([...scanner.slots].some(([id,c])=>sessions(s)[id]?.settings.frequency!==c.frequency))return true;
    if(active(s).some(([id,r])=>id!=='ism'&&(!s.devices.some(d=>d.persistent&&d.id===r.settings.selection)||(s.leases?.[r.settings.selection]&&s.leases[r.settings.selection]!==id))))return true;
    return autoExpand&&scanner.slots.size<6&&freeDevices(s).length>0&&Object.entries(sessions(s)).some(([id,r])=>id!=='ism'&&!r.enabled);
  }
  async function syncPool(){
    if(closed||!scanner.enabled||syncing)return;syncing=true;
    try{
    let s=await state();
    // Auxiliary receivers are bound to one serial and never hand off other decoders.
    for(const [id,receiver] of active(s))if(id!=='ism'){
      const selection=receiver.settings.selection,owner=s.leases?.[selection];
      if(!s.devices.some(d=>d.persistent&&d.id===selection)||(owner&&owner!==id))await control('stop',{},id);
    }
    s=await state();
    if(!active(s).length){holdScan('Receiver stopped or handed to another decoder');return;}
    scanner.reconcile(active(s).map(([id])=>id));
    if(autoExpand){
      const free=freeDevices(s);
      for(const [id,receiver] of Object.entries(sessions(s))){
        if(id==='ism'||receiver.enabled||!free.length||scanner.slots.size>=6)continue;
        const device=free.shift();scanner.reconcile([...scanner.slots.keys(),id]);
        try{
          const defaults=s.sessions.ism.settings;
          await control('configure',{selection:device.id,frequency:scanner.slots.get(id).frequency,gain:defaults.gain,ppm:defaults.ppm},id);
          // Python enforces no-handoff for auxiliaries, including allocation races.
          await control('start',{},id);poolWarning='';saveScan('receiver-added');
        }catch(e){scanner.reconcile([...scanner.slots.keys()].filter(key=>key!==id));poolWarning=e.message;console.error('[iTuner pool] '+e.message);}
      }
    }
    s=await state();scanner.reconcile(active(s).map(([id])=>id));
    for(const [id,c] of scanner.slots){
      if(closed||!scanner.enabled)break;
      const receiver=sessions(s)[id];
      if(receiver?.enabled&&receiver.settings.frequency!==c.frequency){await control('configure',{frequency:c.frequency},id);saveScan('tune');}
    }
    }finally{syncing=false;}
  }
  function schedulePool(){if(poolPending||closed||!scanner.enabled)return;poolPending=true;run(syncPool).finally(()=>poolPending=false).catch(()=>{});}
  async function poll(){
    if(busy||closed||syncing)return;busy=true;
    try{
      const s=await state(),receivers=active(s);
      if(scanner.enabled&&!receivers.length)holdScan('Receiver stopped or handed to another decoder');
      if(scanner.enabled){
        scanner.reconcile(receivers.map(([id])=>id));
        for(const [id,receiver] of receivers){
          const c=scanner.slots.get(id);if(!c)continue;
          if(c.readyAt!==null&&receiver.settings.frequency!==c.frequency){holdScan('Frequency changed from another interface');break;}
          scanner.tick(receiver.assigned&&['LISTENING','RECEIVING'].includes(receiver.status)&&receiver.receiving_frequency===c.frequency,id);
        }
      }
      const running=receivers.some(([,r])=>r.assigned&&['LISTENING','RECEIVING'].includes(r.status));
      const owner=Object.values(s.leases||{}).find(o=>!Object.hasOwn(sessions(s),o));
      const detail=receivers.length>1?receivers.length+' sensor receivers active':main(s)?.detail||'';
      setStatus(!receivers.length?'stopped':running?'running':receivers.every(([,r])=>r.status==='ERROR')?'error':'starting',!receivers.length?(owner?'Receiver currently used by '+owner.toUpperCase()+'. Press Start sensors to switch.':'Sensor receiver stopped.'):detail);
      for(const [id,receiver] of Object.entries(sessions(s))){
        const output=receiver.output?.at(-1);
        if(output){const key=output.time+'|'+output.text;if(key!==diagnostics.get(id)){diagnostics.set(id,key);console.log('[iTuner '+id+'] '+output.text);}}
        for(const row of receiver.events||[]){
          const key=id+'|'+row.time+'|'+row.id+'|'+row.count;
          if(seen.has(key))continue;seen.add(key);
          if(row.time<attachedAt-15||!receiver.enabled||!row.fields?.model)continue;
          scanner.observe(row,id);
          emitter.emit('data',{...row.fields,time:row.time,...(row.frequency?{rx_frequency:row.frequency}:{}),rx_receiver:id,...(row.serial?{rx_serial:row.serial}:{})});
        }
      }
      if(scanner.enabled){
        for(const [id,c] of scanner.slots)if(c.listened>=c.dwell)scanner.next(id);
        if(needsPool(s))schedulePool();if(now()-lastSave>=30000)saveScan();
      }
      if(seen.size>4096){const latest=[...seen].slice(-512);seen.clear();latest.forEach(k=>seen.add(k));}
    }catch(e){setStatus('error',e.message);}finally{busy=false;}
  }
  const adapter={
    start:()=>run(async()=>{await control('start');await poll();}),
    stop:()=>run(async()=>{holdScan('Sensor receivers stopped');const s=await state();for(const [id] of active(s).reverse())await control('stop',{},id);await poll();}),
    restart:()=>run(async()=>{const s=await state();for(const [id] of active(s)){await control('stop',{},id);await control('start',{},id);}await poll();}),
    setFrequency:value=>{const hz=frequency(value);return run(async()=>{holdScan('Manual frequency selected');const s=await state();await control('configure',{frequency:hz},active(s)[0]?.[0]||'ism');await poll();});},
    configure:values=>run(async()=>{
      const allowed={};if(values.selection!==undefined)allowed.selection=String(values.selection);
      if(values.frequency!==undefined)allowed.frequency=frequency(values.frequency);
      for(const key of ['gain','ppm'])if(values[key]!==undefined){const n=Number(values[key]);Object.assign(allowed,parseConfig(key+' '+n));}
      if(values.autoExpand!==undefined){if(typeof values.autoExpand!=='boolean')throw Error('Automatic expansion must be enabled or disabled.');autoExpand=values.autoExpand;saveScan('allocation-policy');}
      if(Object.keys(allowed).length){
        const s=await state();if(allowed.frequency!==undefined)holdScan('Manual frequency selected');await control('configure',allowed);
        if(s.sessions.ism.enabled&&allowed.selection!==undefined)await control('start');
      }
      await poll();
    }),
    readConfig:()=>{const s=main(cached)?.settings;return s?`# iTuner / SoapySDR managed receiver\nfrequency ${s.frequency}\ngain ${s.gain}\nppm ${s.ppm}\n`:'';},
    writeConfig:text=>{const values=parseConfig(text);return run(async()=>{if(values.frequency!==undefined)holdScan('Manual frequency configured');const s=await state();await control('configure',values,active(s)[0]?.[0]||'ism');fs.mkdirSync(path.dirname(configFile),{recursive:true});fs.writeFileSync(configFile,text,{mode:0o600});await poll();});},
    startScan:()=>run(async()=>{
      const s=await state(),ids=active(s).map(([id])=>id);scanner.start(ids.length?ids:['ism']);
      try{
        if(!ids.length){await control('configure',{frequency:scanner.current.frequency});await control('start');}
        await syncPool();await poll();saveScan('start');
      }catch(e){holdScan('Scan could not start: '+e.message);throw e;}
    }),
    stopScan:()=>run(async()=>{holdScan('Holding current frequencies');await poll();}),
    getFrequency:()=>main(cached)?.settings.frequency||null,
    getStatus:()=>({status,error}),
    getReceiver:()=>({status,error,bands:PROFILES,settings:{...main(cached)?.settings,enabled:active(cached).length>0},primary_settings:cached?.sessions.ism?.settings||{},assigned:main(cached)?.assigned||null,
      receivers:Object.entries(sessions(cached)).filter(([,r])=>r?.enabled||r?.assigned).map(([id,r])=>({id,enabled:r.enabled,status:r.status,settings:r.settings,assigned:r.assigned,receiving_frequency:r.receiving_frequency})),
      pool:{autoExpand,maxReceivers:6,warning:poolWarning},devices:cached?.devices||[],leases:cached?.leases||{},scan:scanner.snapshot()}),
    on:emitter.on.bind(emitter),poll,
    close:()=>{if(closed)return queue.catch(()=>{});closed=true;clearInterval(timer);saveScan();return queue.catch(()=>{});},
  };
  const timer=options.interval===false?null:setInterval(poll,options.interval||1000);
  timer?.unref();if(options.interval!==false)setTimeout(poll,0).unref();
  return adapter;
}
module.exports={createAdapter,frequency,parseConfig};
