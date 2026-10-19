'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {IntelligentScanner,BANDS}=require('../integrations/rtl433-ui/scanner.cjs');
function clock(saved){let time=1000000;return {scanner:new IntelligentScanner({now:()=>time,saved}),advance:(s=1)=>time+=s*1000,now:()=>time/1000};}
function finish(c,packets=0){
  const s=c.scanner;s.tick(true);
  for(let i=0;i<packets;i++)s.observe({time:c.now(),frequency:s.current.frequency,id:'weather:'+i,fields:{model:'Weather'}});
  while(!s.tick(true))c.advance();
  return s.next();
}
test('initial survey includes 915 and every popular frequency before any extra visit',()=>{
  const c=clock(),s=c.scanner;s.start();const visited=[];
  for(let i=0;i<BANDS.length;i++){visited.push(s.current.frequency);finish(c,i===0?10:0);}
  assert.deepEqual(visited,BANDS);assert.ok(visited.includes(915000000));
  assert.equal(s.current.frequency,433920000);assert.equal(s.current.kind,'Productive revisit');assert.ok(s.current.dwell>60&&s.current.dwell<=180);
});
test('productive revisit cannot starve quieter bands and stale activity loses priority',()=>{
  const c=clock(),s=c.scanner;s.start();
  for(let i=0;i<BANDS.length;i++)finish(c,i===0?20:0);
  const visits=[];
  for(let i=0;i<40;i++){visits.push(s.current.frequency);finish(c);}
  for(const frequency of BANDS){const indices=visits.map((f,i)=>f===frequency?i:-1).filter(i=>i>=0);assert.ok(indices.length>=4);for(let i=1;i<indices.length;i++)assert.ok(indices[i]-indices[i-1]<=9);}
  assert.equal(s.score(s.bands[0]),0);assert.equal(s.current.dwell,60);
});
test('USB settling, downtime and wrong-band packets do not inflate scan results',()=>{
  const c=clock(),s=c.scanner;s.start();c.advance(120);s.tick(false);assert.equal(s.current.listened,0);
  s.observe({time:c.now(),frequency:433920000,id:'x',fields:{model:'Weather'}});assert.equal(s.bands[0].packets,0);
  s.tick(true);s.observe({time:c.now()-1,frequency:433920000,id:'old',fields:{model:'Weather'}});
  s.observe({time:c.now(),frequency:915000000,id:'wrong',fields:{model:'Weather'}});
  s.observe({time:c.now(),frequency:433920000,id:'real',fields:{model:'Weather'}});
  assert.equal(s.bands[0].packets,1);assert.deepEqual(s.bands[0].devices,['real']);
  c.advance(500);s.tick(true);assert.equal(s.current.listened,5);
  s.tick(false);c.advance(10);s.tick(true);assert.equal(s.current.listened,5);
});
test('saved enabled state and learned totals survive restart without counting offline time',()=>{
  const c=clock(),s=c.scanner;s.start();finish(c,2);const saved=s.snapshot(),r=clock(saved).scanner;
  assert.equal(r.enabled,true);assert.equal(r.bands[0].packets,2);assert.equal(r.current,null);
  r.next();r.tick(true);assert.equal(r.current.listened,0);
  r.stop('Manual hold');assert.equal(r.snapshot().enabled,false);assert.equal(r.snapshot().reason,'Manual hold');
});
test('six receivers cover six different frequencies continuously without collisions',()=>{
 const c=clock(),s=c.scanner,ids=['ism','ism-2','ism-3','ism-4','ism-5','ism-6'];s.start(ids);
 for(let visit=0;visit<8;visit++){
  assert.equal(new Set(s.snapshot().receivers.map(r=>r.frequency)).size,6);
  const before=new Map([...s.slots].map(([id,r])=>[id,r.frequency]));
  for(const id of ids){s.tick(true,id);c.advance(1);s.tick(true,id);s.next(id);assert.equal(s.slots.get(id).frequency,before.get(id));}
 }
 s.reconcile(ids.slice(0,2));assert.equal(s.slots.size,2);
 const visited=new Set();for(let i=0;i<18;i++){for(const id of ids.slice(0,2)){visited.add(s.slots.get(id).frequency);s.next(id);}assert.equal(new Set(s.snapshot().receivers.map(r=>r.frequency)).size,2);}
 assert.equal(visited.size,6);
});
