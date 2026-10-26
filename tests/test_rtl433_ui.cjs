'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const http=require('node:http'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createAdapter,frequency,parseConfig}=require('../integrations/rtl433-ui/broker-adapter.cjs');
async function hub(t,options={}){
  const calls=[],now=Date.now()/1000;
  const s={control_token:'only-the-backend-knows-this',devices:[{id:'serial:789',persistent:true,label:'RTL-SDR'}],leases:{'serial:789':'adsb'},sessions:{ism:{enabled:false,status:'STOPPED',messages:0,events:[],output:[],settings:{selection:'auto',frequency:433920000,gain:38.6,ppm:0,enabled:false},assigned:null}}};
  if(options.multi)s.sensor_receivers={ism:s.sessions.ism,...Object.fromEntries([2,3,4,5,6].map(i=>['ism-'+i,structuredClone(s.sessions.ism)]))};
  const server=http.createServer(async(req,res)=>{
    res.setHeader('Content-Type','application/json');
    if(req.method==='GET'){res.end(JSON.stringify(s));return;}
    if(req.headers['x-vhf-token']!==s.control_token){res.writeHead(403);res.end('{"error":"Bad token"}');return;}
    let body='';for await(const chunk of req)body+=chunk;
    const request=JSON.parse(body);calls.push(request);
    const ism=s.sensor_receivers?.[request.mode]||s.sessions.ism;
    if(request.action==='configure'){Object.assign(ism.settings,Object.fromEntries(Object.entries(request).filter(([key])=>!['mode','action'].includes(key))));ism.receiving_frequency=ism.settings.frequency;}
    if(request.action==='start'){
      const choices=s.devices.filter(d=>d.persistent&&(ism.settings.selection==='auto'||d.id===ism.settings.selection));
      const device=choices.find(d=>!s.leases[d.id]||s.leases[d.id]===request.mode)||choices[0];
      if(!device||(request.mode!=='ism'&&s.leases[device.id]&&s.leases[device.id]!==request.mode)){res.writeHead(400);res.end('{"error":"Receiver busy"}');return;}
      ism.enabled=ism.settings.enabled=true;ism.status='LISTENING';ism.assigned=device;ism.receiving_frequency=ism.settings.frequency;s.leases[device.id]=request.mode;
    }
    if(request.action==='stop'){ism.enabled=ism.settings.enabled=false;ism.status='STOPPED';ism.assigned=null;s.leases=Object.fromEntries(Object.entries(s.leases).filter(([,owner])=>owner!==request.mode));}
    res.end('{"ok":true}');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rtl433-ui-test-'));
  const config={base:`http://127.0.0.1:${server.address().port}`,interval:false,configFile:path.join(dir,'receiver.conf'),...options};
  const adapter=createAdapter(config);
  t.after(async()=>{await adapter.close();await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});});
  return {adapter,s,calls,now,config,dir};
}
test('viewing the UI never claims USB; explicit Start and Stop use the broker',async t=>{
  const {adapter,s,calls}=await hub(t);await adapter.poll();
  assert.equal(calls.length,0);assert.equal(adapter.getStatus().status,'stopped');assert.match(adapter.getStatus().error,/ADS[B-]*/);
  assert.equal('control_token' in adapter.getReceiver(),false);
  await adapter.start();assert.equal(s.leases['serial:789'],'ism');assert.equal(adapter.getStatus().status,'running');
  await adapter.stop();await adapter.poll();assert.equal(s.sessions.ism.enabled,false);
  assert.deepEqual(calls.map(c=>[c.mode,c.action]),[['ism','start'],['ism','stop']]);
});
test('external handoff stops the UI receiver without an automatic takeover',async t=>{
  const {adapter,s,calls}=await hub(t);await adapter.start();
  s.sessions.ism.enabled=false;s.sessions.ism.settings.enabled=false;s.leases={'serial:789':'adsb'};
  await adapter.poll();await adapter.poll();assert.equal(adapter.getStatus().status,'stopped');assert.equal(calls.length,1);
});
test('frequencies and receiver assignment are applied through the shared hub',async t=>{
  const {adapter,s,calls}=await hub(t);await adapter.setFrequency('868.3M');
  assert.equal(s.sessions.ism.settings.frequency,868300000);assert.equal(s.sessions.ism.enabled,false);
  await adapter.start();await adapter.configure({selection:'serial:789',gain:40.2});
  assert.equal(s.sessions.ism.settings.gain,40.2);assert.equal(s.sessions.ism.settings.selection,'serial:789');
  assert.deepEqual(calls.slice(-2).map(c=>c.action),['configure','start']);
});
test('raw sensor events arrive once, retain their real time, and exclude old replay',async t=>{
  const {adapter,s,now}=await hub(t);const output=[];adapter.on('data',row=>output.push(row));
  s.sessions.ism.enabled=true;s.sessions.ism.status='LISTENING';s.sessions.ism.messages=2;
  s.sessions.ism.events=[{time:now-200,id:'old',count:1,fields:{model:'Old'}},{time:now,id:'sensor',count:1,fields:{model:'Weather',temperature_C:19.5}}];
  await adapter.poll();await adapter.poll();assert.equal(output.length,1);assert.equal(output[0].temperature_C,19.5);assert.equal(output[0].time,now);
  s.sessions.ism.events.push({time:now+1,id:'sensor',count:2,fields:{model:'Weather',temperature_C:19.6}});
  await adapter.poll();assert.equal(output.length,2);
});
test('uploaded config cannot invoke extra processes or bypass managed dongles',async t=>{
  const {adapter,s,calls}=await hub(t);
  assert.throws(()=>adapter.writeConfig('output exec:/bin/sh'),/Supported settings/);
  assert.throws(()=>adapter.writeConfig('device 0'),/Supported settings/);
  assert.throws(()=>adapter.setFrequency('1M'),/30/);assert.equal(calls.length,0);
  await adapter.writeConfig('# weather\nfrequency 433.92M\ngain 38.6\nppm 2\n');
  assert.equal(s.sessions.ism.settings.ppm,2);assert.equal(s.sessions.ism.enabled,false);
  assert.match(adapter.readConfig(),/frequency 433920000/);
});
test('frequency and config formats are bounded',()=>{
  assert.equal(frequency('433.92M'),433920000);assert.equal(frequency(868300000),868300000);
  for(const value of ['1G; rm -rf','NaN','433.9.2M',Infinity,'1800M'])assert.throws(()=>frequency(value));
  assert.deepEqual(parseConfig('frequency 868.3M # Europe\ngain 40.2'),{frequency:868300000,gain:40.2});
  assert.throws(()=>parseConfig('gain 80'));assert.throws(()=>parseConfig('ppm -151'));
});
test('server scan reaches 915 without a browser and manual tuning holds it',async t=>{
  let clock=Date.now();const {adapter,s,calls}=await hub(t,{now:()=>clock});
  await adapter.startScan();await adapter.poll();assert.equal(adapter.getReceiver().scan.enabled,true);
  for(const target of [868300000,915000000]){
    for(let i=0;i<60;i++){clock+=1000;await adapter.poll();}
    // Retunes are serialized on the receiver queue, not tied to a page timer.
    for(let i=0;i<20&&s.sessions.ism.settings.frequency!==target;i++)await new Promise(r=>setTimeout(r,5));
    assert.equal(s.sessions.ism.settings.frequency,target);await adapter.poll();
  }
  assert.ok(calls.some(c=>c.frequency===915000000));
  await adapter.setFrequency('915M');assert.equal(adapter.getReceiver().scan.enabled,false);assert.equal(s.sessions.ism.enabled,true);
});
test('external decoder handoff cancels scan permanently and cannot retake the receiver',async t=>{
  const {adapter,s,calls}=await hub(t);await adapter.startScan();
  s.sessions.ism.enabled=false;s.sessions.ism.assigned=null;s.leases={'serial:789':'adsb'};
  const before=calls.length;await adapter.poll();await adapter.poll();
  assert.equal(adapter.getReceiver().scan.enabled,false);assert.equal(calls.length,before);
  assert.match(adapter.getReceiver().scan.reason,/handed/);
});
test('server restart resumes an enabled scan but never starts a stopped receiver',async t=>{
  const {adapter,s,calls,config}=await hub(t);await adapter.startScan();adapter.close();
  const resumed=createAdapter(config);t.after(()=>resumed.close());await resumed.poll();
  assert.equal(resumed.getReceiver().scan.enabled,true);
  // First poll may queue a tune, but must not queue Start.
  await new Promise(r=>setTimeout(r,20));const starts=calls.filter(c=>c.action==='start').length;
  s.sessions.ism.enabled=false;await resumed.poll();resumed.close();
  const stopped=createAdapter(config);t.after(()=>stopped.close());await stopped.poll();
  assert.equal(stopped.getReceiver().scan.enabled,false);assert.equal(calls.filter(c=>c.action==='start').length,starts);stopped.close();
});
test('deduplicated real packets are attributed to their actual scan frequency',async t=>{
  let clock=Date.now();const {adapter,s}=await hub(t,{now:()=>clock});await adapter.startScan();
  clock+=1000;s.sessions.ism.events=[{time:clock/1000,id:'Weather:7',count:1,frequency:433920000,fields:{model:'Weather',id:7}}];
  await adapter.poll();await adapter.poll();
  const band=adapter.getReceiver().scan.bands[0];assert.equal(band.packets,1);assert.equal(band.devices.length,1);
  await adapter.stopScan();assert.equal(s.sessions.ism.enabled,true);assert.equal(adapter.getReceiver().scan.enabled,false);
});
const device=(id)=>({id:'serial:'+id,serial:id,persistent:true,label:'RTL '+id});
async function until(adapter,predicate){for(let i=0;i<80;i++){await adapter.poll();if(predicate())return;await new Promise(r=>setTimeout(r,10));}assert.fail('Receiver pool did not settle');}
test('parallel scan claims only free dongles and hotplug adds a different frequency',async t=>{
  const {adapter,s,calls}=await hub(t,{multi:true});s.devices=[device('789'),device('222'),device('333')];s.leases={'serial:333':'adsb'};
  await adapter.startScan();await until(adapter,()=>adapter.getReceiver().receivers.length===2);
  assert.equal(s.leases['serial:333'],'adsb');assert.equal(s.leases['serial:789'],'ism');assert.equal(s.leases['serial:222'],'ism-2');
  assert.equal(new Set(adapter.getReceiver().scan.receivers.map(r=>r.frequency)).size,2);
  s.devices.push(device('444'));await until(adapter,()=>adapter.getReceiver().receivers.length===3);
  const scan=adapter.getReceiver().scan;assert.equal(new Set(scan.receivers.map(r=>r.frequency)).size,3);assert.ok(scan.receivers.some(r=>r.frequency===915000000));
  assert.ok(calls.filter(c=>c.action==='start').every(c=>c.mode.startsWith('ism')));assert.equal(s.leases['serial:333'],'adsb');
});
test('unplug shrinks the pool; primary handoff leaves other sensor receivers running',async t=>{
  const {adapter,s}=await hub(t,{multi:true});s.devices=[device('789'),device('222'),device('444')];s.leases={};await adapter.startScan();
  await until(adapter,()=>adapter.getReceiver().receivers.length===3);
  s.devices=s.devices.filter(d=>d.serial!=='444');await until(adapter,()=>adapter.getReceiver().receivers.length===2);
  s.sessions.ism.enabled=false;s.sessions.ism.assigned=null;s.leases['serial:789']='adsb';
  await until(adapter,()=>adapter.getReceiver().scan.receivers.length===1);
  const r=adapter.getReceiver();assert.equal(r.scan.enabled,true);assert.equal(r.status,'running');assert.equal(r.settings.enabled,true);assert.equal(r.assigned.serial,'222');assert.equal(s.leases['serial:789'],'adsb');
  await adapter.stop();assert.equal(adapter.getReceiver().receivers.length,0);assert.equal(adapter.getReceiver().scan.enabled,false);assert.equal(s.leases['serial:789'],'adsb');
});
test('pool opt-out and duplicate serial descriptors prevent automatic claims',async t=>{
  const {adapter,s,calls}=await hub(t,{multi:true});s.devices=[device('789'),device('222'),{...device('dupe'),persistent:false}];s.leases={};
  await adapter.configure({autoExpand:false});assert.equal(calls.length,0);await adapter.startScan();
  assert.equal(adapter.getReceiver().receivers.length,1);
  await adapter.configure({autoExpand:true});await until(adapter,()=>adapter.getReceiver().receivers.length===2);
  assert.equal(s.leases['serial:dupe'],undefined);assert.equal(adapter.getReceiver().pool.maxReceivers,6);
});
test('events retain receiver and serial provenance without cross-receiver deduplication',async t=>{
  let clock=Date.now();const {adapter,s}=await hub(t,{multi:true,now:()=>clock});s.devices=[device('789'),device('222')];s.leases={};await adapter.startScan();await until(adapter,()=>adapter.getReceiver().receivers.length===2);
  const output=[];adapter.on('data',row=>output.push(row));clock+=1000;
  for(const [id,r] of Object.entries(s.sensor_receivers))if(r.enabled){r.events=[{time:clock/1000,id:'weather',count:1,frequency:r.settings.frequency,serial:r.assigned.serial,fields:{model:'Weather'}}];}
  await adapter.poll();await adapter.poll();assert.equal(output.length,2);assert.deepEqual(new Set(output.map(r=>r.rx_serial)),new Set(['789','222']));
  assert.equal(adapter.getReceiver().scan.bands.reduce((n,b)=>n+b.packets,0),2);
});

test('every listening band tunes immediately without starting or changing the assigned USB',async t=>{
  const {adapter,s,calls}=await hub(t);await adapter.poll();
  const selection=s.sessions.ism.settings.selection;
  const bands=adapter.getReceiver().bands;assert.ok(bands.length>6);
  assert.match(bands.find(b=>b.frequency===433920000).name,/US.*EU/);
  for(const band of bands){
    await adapter.setFrequency(band.frequency);
    assert.equal(s.sessions.ism.settings.frequency,band.frequency);
    assert.equal(s.sessions.ism.settings.selection,selection);
    assert.equal(s.sessions.ism.enabled,false);
  }
  assert.ok(calls.every(c=>c.action==='configure'));
});
