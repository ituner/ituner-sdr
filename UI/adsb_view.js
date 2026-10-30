// Display windows only: capture and coverage are independent of these controls.
const RETENTION=86400, LIVE_WINDOWS=[15,30,60,120,300], finite=Number.isFinite;
export const COVERAGE_WINDOWS=[[60,'1 min'],[300,'5 min'],[1800,'30 min'],[3600,'1 hour'],[21600,'6 hours'],[86400,'24 hours'],[604800,'7 days'],[0,'All recorded']];
export class CoverageWindow{
  constructor(){this.seconds=3600;this.startedAt=null;this.revision=0;}
  select(seconds,now=Date.now()/1000){if(!COVERAGE_WINDOWS.some(([value])=>value===seconds))throw Error('Invalid dome timespan');this.seconds=seconds;this.startedAt=null;this.revision++;}
  reset(now=Date.now()/1000){this.startedAt=now;this.revision++;}
  get label(){return COVERAGE_WINDOWS.find(([value])=>value===this.seconds)[1];}
  since(now){const bucket=this.seconds===60?10:60,cutoff=this.seconds?Math.max(0,Math.floor(now/bucket)*bucket-this.seconds):0;return Math.max(this.startedAt??0,cutoff);}
}
export function domeContact(planes,key,now,previous=null){
  let latest=null;
  for(const raw of [...planes,previous]){if(!raw||raw.hex!==key)continue;const stamp=finite(raw.last_seen_at)?raw.last_seen_at:null;if(stamp===null||stamp>now+5)continue;if(!latest||stamp>latest.last_seen_at)latest={...raw,last_seen_at:stamp};}
  if(latest){latest.seen=Math.max(0,now-latest.last_seen_at);latest.live=latest.seen<15;}return latest;
}
export function domeAltitude(contact){if(!contact)return null;if(finite(contact.alt_geom))return Math.round(contact.alt_geom).toLocaleString()+' ft GNSS';if(finite(contact.alt_baro))return Math.round(contact.alt_baro).toLocaleString()+' ft BARO≈';return contact.alt_baro==='ground'?'On ground':null;}
export function receptionAge(value){if(!finite(value))return 'Unknown';const s=Math.max(0,Math.floor(value));return s<60?s+' s ago':s<3600?Math.floor(s/60)+' min '+s%60+' s ago':s<86400?Math.floor(s/3600)+' h '+Math.floor(s%3600/60)+' min ago':Math.floor(s/86400)+' d '+Math.floor(s%86400/3600)+' h ago';}
export function aged(raw,now){const p={...raw};p.last_seen_at=finite(p.last_seen_at)?p.last_seen_at:now-(p.seen??100);if(!('position_time' in p))p.position_time=finite(p.seen_pos)?now-p.seen_pos:null;p.seen=Math.max(0,now-p.last_seen_at);p.seen_pos=finite(p.position_time)?Math.max(0,now-p.position_time):1e9;return p;}
export function positioned(p){return Boolean(p&&finite(p.lat)&&Math.abs(p.lat)<=90&&finite(p.lon)&&Math.abs(p.lon)<=180&&p.seen_pos<15);}
const age=seconds=>{seconds=Math.max(0,Math.floor(seconds));return seconds<60?seconds+'s ago':seconds<3600?Math.floor(seconds/60)+'m ago':Math.floor(seconds/3600)+'h ago';};
export function freshness(p){return (p.contact_known===false?'Recorded '+age(p.seen_pos):(p.seen<15?'Contact ':'Last heard ')+age(p.seen))+' · '+(finite(p.position_time)?(positioned(p)?'Position ':'Position old · ')+age(p.seen_pos):'No position');}
export class TrafficView{
  constructor(now=Date.now()/1000){this.mode='live';this.liveSeconds=15;this.liveArmed=false;this.trailSeconds=300;this.historyTrails=false;this.historyLabels=false;this.historyIcons=true;this.backdrop=false;this.freshAt=null;this.reset(now);}
  reset(now){this.openedAt=now;this.coverageLiveSince=null;this.records=new Map();this.positions=new Map();this.initialized=false;}
  startFresh(now){this.reset(now);this.coverageLiveSince=now;this.freshAt=now;this.backdrop=false;this.mode='live';this.liveArmed=false;this.trailSeconds=300;this.coverageSeconds=300;}
  pressLive(){if(this.mode!=='live'||!this.liveArmed){this.mode='live';this.liveArmed=true;return false;}this.liveSeconds=LIVE_WINDOWS[(LIVE_WINDOWS.indexOf(this.liveSeconds)+1)%LIVE_WINDOWS.length];return true;}
  get liveLabel(){return this.liveSeconds<60?this.liveSeconds+' s':this.liveSeconds/60+' min';}
  coverageSince(now){const span=this.coverageSeconds??this.trailSeconds??300;if(this.mode==='history'&&span>=90*86400)return 0;if(this.mode!=='history'){this.coverageLiveSince??=Math.max(0,Math.floor(now/10)*10-(span||300));const cutoff=this.mode==='session'?this.openedAt:this.coverageLiveSince;return this.freshAt===null?cutoff:Math.max(cutoff,this.freshAt);}return Math.floor(now/10)*10-(span||300);}
  ingest(planes,now){for(const raw of planes){if(!raw.hex)continue;const p=aged(raw,now);if(positioned(p)&&(this.freshAt===null||p.position_time>=this.freshAt)){const old=this.positions.get(p.hex);if(!old||p.position_time>=old.position_time)this.positions.set(p.hex,p);}if(p.seen>=15||(this.freshAt!==null&&p.last_seen_at<this.freshAt))continue;const previous=this.records.get(p.hex);if(previous&&p.last_seen_at<=previous.plane.last_seen_at)continue;this.records.set(p.hex,{plane:p,new:previous?previous.new:this.initialized&&p.last_seen_at>=this.openedAt,arrived:previous?.arrived??now});}this.initialized=true;for(const [key,p] of this.positions)if(p.position_time<=now-300)this.positions.delete(key);if(this.positions.size>4096)this.positions=new Map([...this.positions].sort((a,b)=>a[1].position_time-b[1].position_time).slice(-4096));for(const [key,v] of this.records)if(v.plane.last_seen_at<now-RETENTION)this.records.delete(key);if(this.records.size>4096)this.records=new Map([...this.records].sort((a,b)=>a[1].plane.last_seen_at-b[1].plane.last_seen_at).slice(-4096));}
  live(planes,now){return planes.map(p=>aged(p,now)).filter(p=>p.seen<15&&(this.mode==='history'||this.freshAt===null||p.last_seen_at>=this.freshAt));}
  cutoff(now){const cutoff=this.mode==='session'?Math.max(this.openedAt,now-RETENTION):now-this.trailSeconds;return this.mode!=='history'&&this.freshAt!==null?Math.max(cutoff,this.freshAt):cutoff;}
  endpoints(tracks,now){const rows=[];for(const [hex,points] of Object.entries(tracks)){const p=points.at(-1);if(!p||![p.time,p.lat,p.lon].every(finite)||p.time<this.cutoff(now)||p.time>now||Math.abs(p.lat)>90||Math.abs(p.lon)>180)continue;rows.push(aged({hex,lat:p.lat,lon:p.lon,flight:p.flight,alt_baro:p.alt,track:p.track,gs:p.gs,baro_rate:p.baro_rate,band:p.band||'1090',last_seen_at:p.time,position_time:p.time,last_position_at:p.time,historical:true,contact_known:false},now));}return rows;}
  aircraft(planes,tracks,now,mapOnly=false){const live=this.live(planes,now);if(this.mode==='live'){const rows=this.livePositions(planes,tracks,now);return mapOnly?[...rows.values()]:[...new Map([...live.map(p=>[p.hex,p]),...rows]).values()];}const rows=new Map((this.mode==='session'||this.trailSeconds?this.endpoints(tracks,now):[]).map(p=>[p.hex,p]));if(!mapOnly&&this.mode==='session')for(const [key,v] of this.records)if(v.plane.last_seen_at>=this.cutoff(now))rows.set(key,aged(v.plane,now));for(const p of live){if(this.mode==='session'&&p.last_seen_at<this.cutoff(now))continue;if(mapOnly&&(!positioned(p)||(this.mode==='session'&&(p.position_time??0)<this.cutoff(now))))continue;rows.set(p.hex,p);}return [...rows.values()];}
  livePositions(planes,tracks,now,onlyKey=null){
    const live=this.live(planes,now),contacts=new Map(live.map(p=>[p.hex,p])),rows=new Map(),cache=onlyKey?(this.positions.has(onlyKey)?[this.positions.get(onlyKey)]:[]):[...this.positions.values()];
    const candidates=[...(this.liveSeconds>15?[...cache,...this.endpoints(tracks,now)]:[]),...live];
    for(const raw of candidates){let p=aged(raw,now);if(!finite(p.position_time)||!positioned({...p,seen_pos:0})||now-p.position_time<0||p.seen_pos>=this.liveSeconds||(this.freshAt!==null&&p.position_time<this.freshAt))continue;
      const previous=rows.get(p.hex);if(previous&&previous.position_time>p.position_time)continue;
      const contact=contacts.get(p.hex);if(contact)p={...p,...contact,lat:p.lat,lon:p.lon,position_time:p.position_time,seen_pos:p.seen_pos,contact_known:true};
      p.historical=!positioned(p)||!contact;rows.set(p.hex,p);
    }return rows;
  }
  counts(planes,now,tracks={}){const live=this.live(planes,now);return {live:live.length,positions:this.mode==='live'?this.livePositions(planes,tracks,now).size:live.filter(positioned).length,new:[...this.records.values()].filter(v=>v.new).length};}
  arrival(key,now){const v=this.records.get(key);return Boolean(v?.new&&now-v.arrived>=0&&now-v.arrived<12);}
  trailVisible(key,planes,now,trace=null){if(this.mode==='history')return this.historyTrails;return this.mode!=='live'||this.livePositions(planes.filter(p=>p.hex===key),trace?{[key]:trace}:{},now,key).has(key);}
  labelsVisible(liveLabels=true){return this.mode==='history'?this.historyLabels:liveLabels;}
  iconsVisible(liveIcons=true){return this.mode==='history'?this.historyIcons:liveIcons;}
  get label(){return {live:'Live',session:'Since opened',history:'History'}[this.mode];}
}
