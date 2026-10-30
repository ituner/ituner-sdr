import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const load=async path=>import('data:text/javascript;base64,'+Buffer.from(await readFile(new URL(path,import.meta.url),'utf8')).toString('base64'));
const {mountCoverage,newCoveragePoints,spaceHeightScale,spaceFrame,skyArc,coverageObservation,nearestCoverageHit}=await load('../UI/adsb_coverage.js');
const sampleData={base:1000,meta:{reference_height_m:100},aircraft:[{hex:'abc123',label:'TEST'}],points:[[10,0,3000,4000,1100,5000,-22,1,'FLIGHT']]};
const sample=coverageObservation(sampleData,0);assert.equal(sample.time,1010);assert.equal(sample.label,'FLIGHT');assert.equal(sample.horizontal,5);assert.equal(sample.altitude,5000);assert.equal(sample.gnss,true);
const trail={kind:'trail',depth:0,path:[{x:0,y:0},{x:100,y:0}],segment:{a:{id:0},b:{id:1}}};
assert.equal(nearestCoverageHit([trail],40,3).point.id,0);assert.equal(nearestCoverageHit([trail],70,3).point.id,1);assert.equal(nearestCoverageHit([trail],40,30),null);
const dot={kind:'point',x:41,y:0,depth:1,point:{id:2}};assert.equal(nearestCoverageHit([trail,dot],40,3).point.id,2);
const arc=skyArc([0,.98480775,.17364818],[0,-.98480775,.17364818]);assert.ok(arc.length>2);for(const p of arc)assert.ok(Math.abs(Math.hypot(...p)-1)<1e-6);assert.ok(Math.max(...arc.map(p=>p[2]))>.9);
assert.equal(spaceHeightScale(100000,14000,true),5);assert.equal(spaceHeightScale(100000,14000,false),1);
for(const [width,height] of [[340,360],[920,558],[1232,460]])for(const yaw of [0,95,210])for(const tilt of [8,25,55,90]){
  const points=[[-.8,0,.5],[.8,.2,.7]],f=spaceFrame(points,.7,yaw,tilt,width,height),a=yaw*Math.PI/180,t=tilt*Math.PI/180;
  for(const v of points){const x=f.cx+(v[0]*Math.cos(a)-v[1]*Math.sin(a))*f.scale,y=f.cy+(-(v[0]*Math.sin(a)+v[1]*Math.cos(a))*Math.sin(t)-v[2]*Math.cos(t))*f.scale;
    assert.ok(x>=30&&x<=width-30);assert.ok(y>=60&&y<=height-60);
  }
}
const {TrafficView,CoverageWindow,COVERAGE_WINDOWS}=await load('../UI/adsb_view.js');
const window=new CoverageWindow();assert.equal(window.seconds,3600);
assert.equal(window.since(10000),6360);assert.equal(window.since(10019),6360);assert.equal(window.since(10020),6420);
for(const [seconds,label] of COVERAGE_WINDOWS){window.select(seconds,10000000);assert.equal(window.label,label);assert.equal(window.since(10000000),seconds===60?9999940:seconds?9999960-seconds:0);}
assert.throws(()=>window.select(1));
assert.deepEqual(COVERAGE_WINDOWS.map(([seconds])=>seconds),[60,300,1800,3600,21600,86400,604800,0]);
window.select(60,1000.25);assert.equal(window.since(1000.25),940);window.reset(1000.25);assert.equal(window.since(1059),1000.25);assert.equal(window.since(1061),1000.25);assert.equal(window.since(1120),1060);
window.reset(1123.5);assert.equal(window.since(1123.5),1123.5);
window.select(300,1130);assert.equal(window.since(1130),780);assert.equal(window.startedAt,null);
for(const [seconds] of COVERAGE_WINDOWS){window.select(seconds);window.reset(10000000.25);assert.equal(window.seconds,seconds);assert.equal(window.since(10000001),10000000.25);window.select(seconds);assert.equal(window.startedAt,null);assert.ok(window.since(10000001)<10000000.25);}
const controls=await readFile(new URL('../UI/adsb_controls.js',import.meta.url),'utf8');
assert.match(controls,/domeWindow.reset\(viewNow\(\)\)/);assert.doesNotMatch(controls,/reloadCoverage\(value===60\)/);
const html=await readFile(new URL('../UI/adsb_map.html',import.meta.url),'utf8');assert.match(html,/<\/details><button id="dome-reset"/);
const independent=new TrafficView(100);independent.startFresh(1000);independent.mode='history';
assert.equal(new CoverageWindow().seconds,3600);

const v=new TrafficView(1000),start=v.coverageSince(1001);
assert.equal(start,700);
for(const now of [1010,1800,10000])assert.equal(v.coverageSince(now),start);
v.startFresh(1801);assert.equal(v.coverageSince(9999),1801);

const first={status:'READY',base:100,meta:{last_position:105},aircraft:[{hex:'a'},{hex:'b'}],points:[[5,0]]};
const next={status:'READY',base:105,meta:{last_position:108},aircraft:[{hex:'b'},{hex:'a'}],points:[[0,1],[3,0],[-90,1]]};
assert.deepEqual([...newCoveragePoints(first,next)],['108.000:b']);
assert.equal(newCoveragePoints(first,{...next,meta:{...next.meta,reference:{lat:1,lon:2}}}).size,0);

const originalFetch=globalThis.fetch,originalInterval=globalThis.setInterval;
try{
  globalThis.setInterval=()=>0;
  let response=first,createCount=0;const replacements=[],summary={textContent:''};
  globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify(response)});
  const root={hidden:false,querySelector:()=>summary};
  const reload=mountCoverage(root,()=>700,(_root,data)=>{createCount++;replacements.push(data);return data=>replacements.push(data);});
  await reload();assert.equal(createCount,1);assert.equal(replacements.length,1);
  response={status:'LOADING',meta:{},points:[],aircraft:[],cells:[]};
  await reload();assert.equal(replacements.length,1);assert.match(summary.textContent,/Updating/);
  response=next;await reload();assert.equal(replacements.length,2);assert.equal(createCount,1);
  root.hidden=true;response=first;await reload();assert.equal(replacements.length,2);
  // Fresh clears synchronously even while a previous history request is pending.
  root.hidden=false;let since=700,release;const resetViews=[];
  const freshReload=mountCoverage(root,()=>since,(_root,data)=>{resetViews.push(data);return data=>resetViews.push(data);});
  response={...first,receiver_enabled:true,receiver_status:'RECEIVING'};await freshReload();
  globalThis.fetch=()=>new Promise(resolve=>{release=()=>resolve({ok:true,text:async()=>JSON.stringify(first)});});
  const oldRequest=freshReload();since=1000.25;await freshReload(true);
  assert.equal(resetViews.at(-1).status,'EMPTY');assert.equal(resetViews.at(-1).points.length,0);
  assert.equal(resetViews.at(-1).meta.window_since,since);assert.equal(resetViews.at(-1).meta.retained_positions,0);
  assert.equal(resetViews.at(-1).meta.max_altitude_ft,null);
  assert.equal(resetViews.at(-1).receiver_enabled,true);assert.equal(resetViews.at(-1).receiver_status,'RECEIVING');
  release();await oldRequest;assert.equal(resetViews.at(-1).status,'EMPTY','Late history cannot undo reset');
  since=1060;response=next;globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify(response)});
  await freshReload();assert.deepEqual(resetViews.at(-1),next,'Reception continues after the first minute');
}finally{globalThis.fetch=originalFetch;globalThis.setInterval=originalInterval;}
console.log('PASS: stable Live dome scope, new-sample identity, and no empty loading-frame replacement');
