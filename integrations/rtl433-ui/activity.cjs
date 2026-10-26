'use strict';
// Read-only normalization of real outputs. No radio control or RF-energy inference.
const {createHash}=require('node:crypto');
const MODES={ism:['rtl_433','messages','#78df9a'],ais:['AIS','messages','#63dcca'],aprs:['APRS','packets','#efbd75'],sonde:['Radiosonde','frames','#f69ca6'],cubesat:['CubeSat','frames','#88cff5'],meteor:['Meteor','frames','#b9a5f7'],
  'adsb-1090':['ADS-B 1090','frames','#ffca73'],'adsb-978':['ADS-B 978','frames','#eaa158'],wspr:['WSPR','spots','#72e9eb'],cw:['CW','characters','#66b6ff'],sstv:['SSTV','images','#ed9cff'],hell:['Hell OCR','text guesses','#c5a1ff'],qrss:['QRSS','text updates','#a4c9ff']};
const MAX_FREQUENCY=1500e6,RETENTION=1920;
const number=x=>typeof x==='number'&&Number.isFinite(x);
const stamp=x=>number(x)?x:typeof x==='string'?Date.parse(x)/1000:NaN;
const label=x=>String(x??'').slice(0,160);
class DecoderActivity{
 constructor({now=Date.now,fetcher=fetch,vhf='http://127.0.0.1:8092',adsb='http://127.0.0.1:8090',hf='http://127.0.0.1:8073',interval=1000}={}){
  this.now=now;this.fetcher=fetcher;this.started=now()/1000;this.stats=Object.fromEntries(Object.entries(MODES).map(([id,[name,unit,color]])=>[id,{id,name,unit,color,successful:0,tentative:0,lastSeen:0}]));
  this.sources=new Map();this.receivers=new Map();this.counters=new Map();this.seen=new Map();this.cells=new Map();this.versions=new Map();this.ready=new Set();this.busy=null;this.closed=false;
  this.feeds=[['vhf',vhf+'/api/state'],['adsb',adsb+'/api/state'],...['wspr','cw','sstv','hell','qrss'].map(m=>[m,hf+'/api/'+m])];this.attempted=new Map();
  this.timer=interval===false?null:setInterval(()=>this.poll(),interval);this.timer?.unref();
 }
 registerDecoder({id,name,unit,color='#88cff5'}){
  if(!/^[a-z0-9-]{1,40}$/.test(id)||!name||!unit||!/^#[a-f0-9]{6}$/i.test(color))throw Error('Invalid decoder registration');
  if(!this.stats[id])this.stats[id]={id,name:label(name),unit:label(unit),color,successful:0,tentative:0,lastSeen:0};
 }
 // Stable adapter contract: producers publish; browser views subscribe to snapshots.
 publish({decoder,receiver,frequency=null,timestamp,count=1,quality='successful',eventId,description=''}){
  if(!this.stats[decoder]||!this.validTime(timestamp)||!Number.isSafeInteger(count)||count<=0||!['successful','tentative'].includes(quality))return false;
  if(frequency!==null&&(!number(frequency)||frequency<0))return false;
  if(eventId&&!this.unique('published:'+decoder+':'+String(eventId),timestamp))return false;
  const tentative=quality==='tentative';this.count(decoder,count,timestamp,tentative);
  this.point(decoder,frequency,timestamp,count,receiver,description,tentative);return true;
 }
 validTime(t){return number(t)&&t>=this.now()/1000-RETENTION&&t<=this.now()/1000+2;}
 count(mode,n,time,tentative=false){if(!this.stats[mode]||!Number.isSafeInteger(n)||n<=0)return;this.stats[mode][tentative?'tentative':'successful']+=n;this.stats[mode].lastSeen=Math.max(this.stats[mode].lastSeen,time||0);}
 point(mode,frequency,time,count,receiver,description,tentative=false){
  if(!this.stats[mode]||!number(frequency)||frequency<0||frequency>MAX_FREQUENCY||!this.validTime(time)||count<=0)return;
  const bin=Math.floor(time),key=JSON.stringify([mode,frequency,bin,receiver,tentative]);
  const old=this.cells.get(key);this.cells.set(key,{mode,frequency,time:bin,lastSeen:time,count:(old?.count||0)+count,receiver:label(receiver),description:label(description),tentative});
 }
 unique(key,time){if(key.length>256)key=createHash('sha256').update(key).digest('hex');if(this.seen.has(key))return false;this.seen.set(key,time);return true;}
 counter(key,value,enabled){
  if(!enabled||!number(value)||value<0){this.counters.delete(key);return null;}
  const old=this.counters.get(key);this.counters.set(key,value);return old===undefined?null:Math.max(0,value>=old?value-old:value);
 }
 receiver(source,id,mode,frequency,status,enabled,name){this.receivers.set(source+':'+id,{source,id,mode,frequency:number(frequency)?frequency:null,status:label(status),enabled:!!enabled,name:label(name||id)});}
 vhf(s){
  const sessions={...s.sessions,...s.sensor_receivers};
  for(const [id,d] of Object.entries(sessions)){
   const mode=id.startsWith('ism')?'ism':id;if(!this.stats[mode])continue;
   const frequency=d.receiving_frequency,enabled=d.enabled===true;
   this.receiver('vhf',id,mode,frequency,d.status,enabled,d.assigned?.serial||id);
   const delta=this.counter('vhf:'+id,d.messages,enabled);
   const rows=Array.isArray(d.events)?d.events:[];let placed=0;
   for(const row of rows){
    const fresh=this.unique(JSON.stringify(['vhf',id,row.time,row.id,row.count]),row.time);
    if(!enabled||delta===null||!delta||!fresh||!this.validTime(row.time))continue;
    const actual=number(row.frequency)?row.frequency:frequency;
    // A pending retune has no receiving_frequency; never relabel old packets.
    if(mode==='ism'&&!number(row.frequency))continue;
    this.point(mode,actual,row.time,1,d.assigned?.serial||id,row.label||row.fields?.model||mode);placed++;
   }
   if(delta>0){
    this.publish({decoder:mode,receiver:id,timestamp:this.now()/1000,count:delta});
    // SatDump frame counters have no per-frame event list. Mark their observed interval.
    if(mode==='meteor'&&placed===0)this.point(mode,frequency,this.now()/1000,delta,id,'Frames observed since previous poll');
   }
  }
 }
 adsb(s){
  const bands=Array.isArray(s.bands)?s.bands:[{id:'1090',frequency_mhz:1090,enabled:s.enabled,messages:s.messages,last_message_at:s.last_message_at,status:s.status,assigned:s.assigned}];
  for(const d of bands){
   const mode='adsb-'+d.id;if(!this.stats[mode])continue;
   const frequency=d.frequency_mhz*1e6,enabled=d.enabled===true;
   this.receiver('adsb',d.id,mode,frequency,d.status,enabled,d.assigned?.serial||d.id);
   const delta=this.counter('adsb:'+d.id,d.messages,enabled),time=d.last_message_at;
   if(delta>0&&this.validTime(time)){this.publish({decoder:mode,receiver:d.assigned?.serial||d.id,frequency,timestamp:time,count:delta,description:'Frames observed since previous poll'});}
  }
 }
 hf(mode,s){
  const decoders=new Map();
  for(const d of s.decoders||[]){
   const enabled=d.running===true&&d.paused!==true;decoders.set(d.id,{...d,enabled});
   this.receiver(mode,d.id,mode,d.freq_khz*1000,d.status,enabled,d.name);
  }
  const initial=!this.ready.has(mode);
  const emit=(d,key,time,frequency,description,tentative=false,count=1)=>{
   if(!this.unique(mode+':'+key,time)||initial||!d?.enabled||!this.validTime(time))return;
   this.publish({decoder:mode,receiver:d.name||d.id,frequency,timestamp:time,count,description,quality:tentative?'tentative':'successful'});
  };
  if(mode==='wspr')for(const d of decoders.values())for(const row of d.spots||[]){
   const time=stamp(row.cycle_start||row.cycle_start_utc),frequency=row.frequency_mhz*1e6;
   if(Math.abs(frequency-d.freq_khz*1000)>10000)continue;
   emit(d,JSON.stringify([d.id,row.history_id||[time,frequency,row.callsign]]),time,frequency,'Receive cycle · '+label(row.callsign));
  }
  if(mode==='cw')for(const row of s.history||[]){
   const d=decoders.get(row.session_id),time=stamp(row.end_utc),key=mode+':'+row.id,text=typeof row.text==='string'?row.text:'',previous=this.versions.get(key);
   this.versions.set(key,{text,time});
   if(!initial&&d?.enabled&&this.validTime(time)&&previous?.text!==text){
    const added=previous&&text.startsWith(previous.text)?text.slice(previous.text.length):text;
    const count=added.replace(/\s/g,'').length;if(count){this.publish({decoder:mode,receiver:d.name,frequency:row.rf_hz,timestamp:time,count,description:'Tentative CW text',quality:'tentative'});}
   }
  }
  if(['sstv','hell','qrss'].includes(mode))for(const row of s.images||[]){
   const d=decoders.get(row.session_id),time=number(row.updated_ns)?row.updated_ns/1e9:stamp(row.capture_utc);
   const frequency=number(row.rf_hz)?row.rf_hz:row.freq_khz*1000;
   if(mode==='sstv'){
    if(!row.has_image||row.error||!['full','partial'].includes(row.kind))continue;
    emit(d,row.id+':'+row.kind,time,frequency,row.mode+' '+row.kind+' image',row.kind!=='full');
   }else if(mode==='hell'){
    if(row.ocr_status==='possible_text'&&String(row.ocr_text||'').trim())emit(d,row.id+':'+row.ocr_text,time,frequency,'Tentative Hell OCR',true);
   }else if(row.text_status!=='visual_only'&&String(row.tentative_text||'').trim()){
    const key='qrss:'+row.id,previous=this.versions.get(key);this.versions.set(key,{text:row.tentative_text,time});
    if(previous?.text!==row.tentative_text)emit(d,row.id+':'+row.tentative_text,time,frequency,'Tentative QRSS text',true);
   }
  }
  this.ready.add(mode);
 }
 prune(){
  const cutoff=this.now()/1000-RETENTION;
  for(const [key,c] of this.cells)if(c.lastSeen<cutoff)this.cells.delete(key);
  for(const [key,t] of this.seen)if(!number(t)||t<cutoff)this.seen.delete(key);
  for(const [key,v] of this.versions)if(v.time<cutoff)this.versions.delete(key);
  for(const [map,max] of [[this.cells,4096],[this.seen,16384],[this.versions,4096]])while(map.size>max)map.delete(map.keys().next().value);
 }
 async poll(){
  if(this.closed)return;if(this.busy)return this.busy;
  this.busy=(async()=>{
   await Promise.allSettled(this.feeds.map(async([id,url])=>{
    // Fast counter feeds follow the one-second waterfall; HF snapshots stay at 5 s.
    const current=this.now(),previous=this.attempted.get(id);if(!['vhf','adsb'].includes(id)&&current>=previous&&current-previous<5000)return;
    this.attempted.set(id,current);
    try{
     const response=await this.fetcher(url,{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error('Unavailable');
     const text=await response.text();if(text.length>4*1024*1024)throw Error('Snapshot too large');
     const data=JSON.parse(text);if(!data||typeof data!=='object'||Array.isArray(data))throw Error('Invalid snapshot');
     for(const [key,r] of this.receivers)if(r.source===id)this.receivers.delete(key);
     if(id==='vhf')this.vhf(data);else if(id==='adsb')this.adsb(data);else this.hf(id,data);
     this.sources.set(id,{id,online:true,updated:this.now()/1000});
    }catch{
     this.sources.set(id,{id,online:false,updated:this.now()/1000});
     for(const [key,r] of this.receivers)if(r.source===id)this.receivers.set(key,{...r,enabled:false,status:'UNAVAILABLE'});
     for(const key of this.counters.keys())if(key.startsWith(id+':'))this.counters.delete(key);
    }
   }));this.prune();
  })().finally(()=>{this.busy=null;});return this.busy;
 }
 snapshot(){this.prune();return {version:1,now:this.now()/1000,started:this.started,retention:RETENTION,width:1024,pixel:8,maximum:MAX_FREQUENCY,
  sources:[...this.sources.values()],receivers:[...this.receivers.values()],decoders:Object.values(this.stats).map(s=>({...s})),events:[...this.cells.values()].map(c=>({...c}))};}
 close(){this.closed=true;clearInterval(this.timer);}
}
function allowActivityOrigin(origin,host){try{const a=new URL(origin),b=new URL('http://'+host);return ['http:','https:'].includes(a.protocol)&&a.hostname===b.hostname&&['8092','8093'].includes(a.port);}catch{return false;}}
module.exports={DecoderActivity,MODES,MAX_FREQUENCY,RETENTION,allowActivityOrigin};
