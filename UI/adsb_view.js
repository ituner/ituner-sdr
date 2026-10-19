// Display windows only: capture and coverage are independent of these controls.
const RETENTION=86400, finite=Number.isFinite;
export function aged(raw,now){const p={...raw};p.last_seen_at=finite(p.last_seen_at)?p.last_seen_at:now-(p.seen??100);if(!('position_time' in p))p.position_time=finite(p.seen_pos)?now-p.seen_pos:null;p.seen=Math.max(0,now-p.last_seen_at);p.seen_pos=finite(p.position_time)?Math.max(0,now-p.position_time):1e9;return p;}
export function positioned(p){return Boolean(p&&finite(p.lat)&&Math.abs(p.lat)<=90&&finite(p.lon)&&Math.abs(p.lon)<=180&&p.seen_pos<15);}
const age=seconds=>{seconds=Math.max(0,Math.floor(seconds));return seconds<60?seconds+'s ago':seconds<3600?Math.floor(seconds/60)+'m ago':Math.floor(seconds/3600)+'h ago';};
export function freshness(p){return (p.contact_known===false?'Recorded '+age(p.seen_pos):(p.seen<15?'Contact ':'Last heard ')+age(p.seen))+' · '+(finite(p.position_time)?(positioned(p)?'Position ':'Position old · ')+age(p.seen_pos):'No position');}
export class TrafficView{
  constructor(now=Date.now()/1000){this.mode='live';this.trailSeconds=300;this.backdrop=false;this.reset(now);}
  reset(now){this.openedAt=now;this.records=new Map();this.initialized=false;}
  ingest(planes,now){for(const raw of planes){if(!raw.hex)continue;const p=aged(raw,now);if(p.seen>=15)continue;const previous=this.records.get(p.hex);if(previous&&p.last_seen_at<=previous.plane.last_seen_at)continue;this.records.set(p.hex,{plane:p,new:previous?previous.new:this.initialized&&p.last_seen_at>=this.openedAt,arrived:previous?.arrived??now});}this.initialized=true;for(const [key,v] of this.records)if(v.plane.last_seen_at<now-RETENTION)this.records.delete(key);if(this.records.size>4096)this.records=new Map([...this.records].sort((a,b)=>a[1].plane.last_seen_at-b[1].plane.last_seen_at).slice(-4096));}
  live(planes,now){return planes.map(p=>aged(p,now)).filter(p=>p.seen<15);}
  cutoff(now){return this.mode==='session'?Math.max(this.openedAt,now-RETENTION):now-this.trailSeconds;}
  endpoints(tracks,now){const rows=[];for(const [hex,points] of Object.entries(tracks)){const p=points.at(-1);if(!p||![p.time,p.lat,p.lon].every(finite)||p.time<this.cutoff(now)||p.time>now||Math.abs(p.lat)>90||Math.abs(p.lon)>180)continue;rows.push(aged({hex,lat:p.lat,lon:p.lon,flight:p.flight,alt_baro:p.alt,track:p.track,gs:p.gs,baro_rate:p.baro_rate,last_seen_at:p.time,position_time:p.time,last_position_at:p.time,historical:true,contact_known:false},now));}return rows;}
  aircraft(planes,tracks,now,mapOnly=false){const live=this.live(planes,now);if(this.mode==='live')return mapOnly?live.filter(positioned):live;const rows=new Map((this.mode==='session'||this.trailSeconds?this.endpoints(tracks,now):[]).map(p=>[p.hex,p]));if(!mapOnly&&this.mode==='session')for(const [key,v] of this.records)if(v.plane.last_seen_at>=this.cutoff(now))rows.set(key,aged(v.plane,now));for(const p of live){if(this.mode==='session'&&p.last_seen_at<this.cutoff(now))continue;if(mapOnly&&(!positioned(p)||(this.mode==='session'&&(p.position_time??0)<this.cutoff(now))))continue;rows.set(p.hex,p);}return [...rows.values()];}
  counts(planes,now){const live=this.live(planes,now);return {live:live.length,positions:live.filter(positioned).length,new:[...this.records.values()].filter(v=>v.new).length};}
  arrival(key,now){const v=this.records.get(key);return Boolean(v?.new&&now-v.arrived>=0&&now-v.arrived<12);}
  trailVisible(key,planes,now){return this.mode!=='live'||this.live(planes,now).some(p=>p.hex===key&&positioned(p));}
  get label(){return {live:'Live',session:'Since opened',history:'History'}[this.mode];}
}
