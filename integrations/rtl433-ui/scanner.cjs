'use strict';
// Shared activity model; independent receiver visits never duplicate a frequency.
const BANDS=[433920000,868300000,915000000,315000000,345000000,868950000];
class IntelligentScanner {
  constructor({now=Date.now,saved={}}={}){
    this.now=now;this.enabled=saved.enabled===true;this.reason=this.enabled?'Resuming scan':'Ready to explore';
    this.cursor=0;this.explorations=0;this.bonus=false;this.slots=new Map();
    this.bands=BANDS.map(frequency=>{
      const old=Array.isArray(saved.bands)?saved.bands.find(b=>b.frequency===frequency)||{}:{};
      const number=key=>Number.isFinite(old[key])&&old[key]>=0?old[key]:0;
      return {frequency,packets:number('packets'),seconds:number('seconds'),visits:number('visits'),lastSeen:number('lastSeen'),
        devices:Array.isArray(old.devices)?old.devices.filter(x=>typeof x==='string').slice(-256):[],recent:[]};
    });
  }
  get current(){return this.slots.get('ism')||this.slots.values().next().value||null;}
  start(ids=['ism']){this.enabled=true;this.reason='Surveying all frequencies';this.cursor=0;this.explorations=0;this.bonus=false;this.slots.clear();this.reconcile(ids);return this.current?.frequency;}
  stop(reason='Holding current frequencies'){this.enabled=false;this.reason=reason;this.slots.clear();}
  score(b){const r=b.recent;const seconds=r.reduce((n,v)=>n+v.seconds,0);return seconds?r.reduce((n,v)=>n+v.packets,0)/seconds:0;}
  finish(id){const c=this.slots.get(id);if(c){const b=this.bands.find(b=>b.frequency===c.frequency);if(c.listened>0){b.recent.push({packets:c.packets,seconds:c.listened});b.recent=b.recent.slice(-3);}}}
  reconcile(ids){
    if(!this.enabled)return;
    const keep=new Set(ids.slice(0,BANDS.length));
    for(const id of this.slots.keys())if(!keep.has(id)){this.finish(id);this.slots.delete(id);}
    for(const id of keep)if(!this.slots.has(id))this.next(id);
  }
  next(id='ism'){
    if(!this.enabled)return null;this.finish(id);
    const occupied=new Set([...this.slots].filter(([key])=>key!==id).map(([,c])=>c.frequency));
    const choices=this.bands.filter(b=>!occupied.has(b.frequency));if(!choices.length)return null;
    const best=[...choices].sort((a,b)=>this.score(b)-this.score(a))[0];
    const bonus=this.explorations>=BANDS.length&&this.explorations%3===0&&!this.bonus&&this.score(best)>0;
    let b;if(bonus){b=best;this.bonus=true;}else{
      for(let i=0;i<BANDS.length;i++){const candidate=this.bands[this.cursor];this.cursor=(this.cursor+1)%BANDS.length;if(!occupied.has(candidate.frequency)){b=candidate;break;}}
      this.explorations++;this.bonus=false;
    }
    const dwell=60+Math.min(120,Math.round(this.score(b)*600));
    b.visits++;this.slots.set(id,{frequency:b.frequency,dwell,listened:0,packets:0,readyAt:null,lastTick:null,kind:bonus?'Productive revisit':'Survey'});
    return b.frequency;
  }
  tick(ready,id='ism'){
    const c=this.slots.get(id);if(!this.enabled||!c)return false;const time=this.now();
    if(ready){
      if(c.readyAt===null)c.readyAt=time/1000;
      const elapsed=c.lastTick===null?0:Math.min(5,Math.max(0,(time-c.lastTick)/1000));
      c.listened+=elapsed;this.bands.find(b=>b.frequency===c.frequency).seconds+=elapsed;c.lastTick=time;this.reason=c.kind;
    }else{c.lastTick=null;this.reason='Waiting for receiver to tune';}
    return c.listened>=c.dwell;
  }
  observe(row,id='ism'){
    const c=this.slots.get(id);if(!this.enabled||!c||c.readyAt===null||row.time<c.readyAt||row.frequency!==c.frequency||!row.fields?.model)return;
    const b=this.bands.find(b=>b.frequency===c.frequency);b.packets++;c.packets++;b.lastSeen=row.time;
    if(!b.devices.includes(row.id)){b.devices.push(row.id);b.devices=b.devices.slice(-256);}
  }
  snapshot(){
    const visit=c=>{if(!c)return null;const {lastTick,...rest}=c;return {...rest,remaining:Math.max(0,Math.ceil(c.dwell-c.listened))};};
    return {enabled:this.enabled,reason:this.reason,round:Math.floor(Math.max(0,this.explorations-1)/BANDS.length)+1,
      current:visit(this.current),receivers:[...this.slots].map(([id,c])=>({id,...visit(c)})),
      bands:this.bands.map(b=>({...b,devices:[...b.devices],recent:b.recent.map(v=>({...v})),packetsPerMinute:b.seconds?b.packets*60/b.seconds:0}))};
  }
}
module.exports={IntelligentScanner,BANDS};
