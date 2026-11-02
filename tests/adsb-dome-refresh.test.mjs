import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const load=async path=>{
  let source=await readFile(new URL(path,import.meta.url),'utf8');
  if(source.includes("'./adsb_view.js'")){const view='data:text/javascript;base64,'+Buffer.from(await readFile(new URL('../UI/adsb_view.js',import.meta.url),'utf8')).toString('base64');source=source.replace("'./adsb_view.js'",JSON.stringify(view));}
  return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
};
const {mountCoverage,newCoveragePoints,spaceHeightScale,spaceFrame,skyArc,coverageObservation,latestCoverageObservation,nearestCoverageHit,signalColour,overviewIndices,refinementIndices,dotRadius,detailBudget,skyOverview,mergeCoverage,domeZoom,PREVIEW_POINTS,PREVIEW_SEGMENTS}=await load('../UI/adsb_coverage.js');
assert.equal(signalColour(-45),'rgb(38,89,255)');assert.equal(signalColour(-5),'rgb(255,46,26)');assert.equal(signalColour(null),'#91aac1');
assert.equal(signalColour(-100),signalColour(-45));assert.equal(signalColour(1),signalColour(-5));
for(const count of [0,1,10,20000]){
  const ids=overviewIndices(count,PREVIEW_POINTS);assert.ok(ids.length<=PREVIEW_POINTS);assert.equal(new Set(ids).size,ids.length);
  if(count){assert.equal(ids[0],0);assert.equal(ids.at(-1),count-1);}assert.ok(ids.every(i=>i>=0&&i<count));
}
assert.equal(overviewIndices(20000,PREVIEW_SEGMENTS).length,PREVIEW_SEGMENTS);
assert.equal(dotRadius(20000)*2,1);assert.ok(dotRadius(20000,true)>dotRadius(20000));
assert.equal(detailBudget(100000,3000,true),1800,'Holding a drag never restores full detail');
assert.deepEqual([0,500,1400].map(idle=>detailBudget(100000,idle)),[8000,30000,100000]);
for(const n of [0,1,17,40000]){const ids=refinementIndices(n);assert.equal(new Set(ids).size,n);assert.deepEqual(refinementIndices(n,1800),ids.slice(0,1800));}
assert.deepEqual([0,500,1400,2600].map(idle=>detailBudget(172500,idle)),[8000,30000,100000,172500]);
const sky=skyOverview([{az:8,el:4,count:2,level:-20},{az:12,el:6,count:1,level:-10}]);assert.equal(sky.length,1);assert.equal(sky[0].count,3);assert.ok(Math.abs(sky[0].level+50/3)<1e-9);
assert.equal(detailBudget(75,0),75);assert.equal(detailBudget(0,1500),0);
assert.equal(domeZoom(1.75),1.75);assert.equal(domeZoom(2),2);assert.equal(domeZoom(4),4);assert.equal(domeZoom(5),4);assert.equal(domeZoom(.1),.5);assert.equal(domeZoom(undefined),1);
const sampleData={base:1000,meta:{reference_height_m:100},aircraft:[{hex:'abc123',label:'TEST'}],points:[[10,0,3000,4000,1100,5000,-22,1,'FLIGHT']]};
const sample=coverageObservation(sampleData,0);assert.equal(sample.time,1010);assert.equal(sample.label,'FLIGHT');assert.equal(sample.horizontal,5);assert.equal(sample.altitude,5000);assert.equal(sample.gnss,true);
const newerPosition={...sampleData,points:[...sampleData.points,[1020,0,4000,5000,1200,6000,-20,1,'FLIGHT']]};
const followed=latestCoverageObservation(newerPosition,{...sample,context:'Recorded reception'});
assert.equal(followed.time,2020);assert.equal(followed.altitude,6000);
assert.equal(latestCoverageObservation(sampleData,followed),followed,'An older snapshot cannot restore the tapped point');
assert.equal(latestCoverageObservation({...sampleData,points:[]},followed),followed);
const trail={kind:'trail',depth:0,path:[{x:0,y:0},{x:100,y:0}],segment:{a:{id:0},b:{id:1}}};
assert.equal(nearestCoverageHit([trail],40,3).point.id,0);assert.equal(nearestCoverageHit([trail],70,3).point.id,1);assert.equal(nearestCoverageHit([trail],40,30),null);
const dot={kind:'point',x:41,y:0,depth:1,point:{id:2}};assert.equal(nearestCoverageHit([trail,dot],40,3).point.id,2);
const arc=skyArc([0,.98480775,.17364818],[0,-.98480775,.17364818]);assert.ok(arc.length>2);for(const p of arc)assert.ok(Math.abs(Math.hypot(...p)-1)<1e-6);assert.ok(Math.max(...arc.map(p=>p[2]))>.9);
assert.equal(spaceHeightScale(100000,14000,true),5);assert.equal(spaceHeightScale(100000,14000,false),1);
for(const [width,height] of [[340,360],[920,558],[1232,460]])for(const yaw of [0,95,210])for(const tilt of [8,25,55,90]){
  const points=[[-.8,0,.5],[.8,.2,.7]],f=spaceFrame(points,.7,yaw,tilt,width,height),a=yaw*Math.PI/180,t=tilt*Math.PI/180;
  for(const v of points){const x=f.cx+(v[0]*Math.cos(a)-v[1]*Math.sin(a))*f.scale,y=f.cy+(-(v[0]*Math.sin(a)+v[1]*Math.cos(a))*Math.sin(t)-v[2]*Math.cos(t))*f.scale;
    assert.ok(x>=24&&x<=width-24);assert.ok(y>=32&&y<=height-32);
  }
}
const {TrafficView,CoverageWindow,COVERAGE_WINDOWS,domeContact,domeAltitude,receptionAge}=await load('../UI/adsb_view.js');
for(const [seconds,label] of [[0,'0 s ago'],[3.9,'3 s ago'],[65,'1 min 5 s ago'],[3670,'1 h 1 min ago'],[90000,'1 d 1 h ago']])assert.equal(receptionAge(seconds),label);
assert.equal(receptionAge(NaN),'Unknown');
const report={hex:'abc123',last_seen_at:100,alt_geom:10000};
let contact=domeContact([report],'abc123',102);assert.equal(contact.live,true);assert.match(domeAltitude(contact),/10,000/);
contact=domeContact([{...report,last_seen_at:104,alt_geom:10500}],'abc123',105,contact);assert.match(domeAltitude(contact),/10,500/);
contact=domeContact([report],'abc123',110,contact);assert.equal(contact.alt_geom,10500);
contact=domeContact([],'abc123',120,contact);assert.equal(contact.live,false);assert.equal(contact.seen,16);
assert.equal(domeContact([],'other',120,contact),null);
assert.equal(domeContact([{hex:'abc123',seen:0}],'abc123',120),null);
assert.equal(domeContact([{...report,last_seen_at:500}],'abc123',120),null);
assert.match(domeAltitude({alt_geom:null,alt_baro:9500}),/BARO/);assert.equal(domeAltitude({alt_baro:'ground'}),'On ground');
assert.equal(domeAltitude({alt_geom:NaN}),null);
let fromPosition=domeContact([{hex:followed.hex,last_seen_at:followed.time,alt_geom:followed.altitude}],followed.hex,2021);
assert.equal(receptionAge(fromPosition.seen),'1 s ago');
fromPosition=domeContact([{hex:'other',last_seen_at:2023}],followed.hex,2025,fromPosition);
assert.equal(receptionAge(fromPosition.seen),'5 s ago','Another aircraft cannot reset the selected reception clock');
fromPosition=domeContact([{hex:followed.hex,last_seen_at:2026,alt_geom:6500}],followed.hex,2027,fromPosition);
assert.equal(receptionAge(fromPosition.seen),'1 s ago');assert.match(domeAltitude(fromPosition),/6,500/);
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

const ram={cache_key:'site',base:1000,meta:{window_since:1000,last_position:1040},aircraft:[{hex:'a'},{hex:'b'}],points:[[0,0],[20,0],[40,1]],segments:[[0,1]]};
const tail={delta:true,after:1020,cache_key:'site',base:1020,meta:{window_since:1010,first_position:1020,last_position:1050},aircraft:[{hex:'b'},{hex:'a'}],points:[[0,1],[15,1],[20,0],[30,0]],breaks:[1045]};
const merged=mergeCoverage(ram,tail);assert.deepEqual(merged.points.map(p=>[merged.base+p[0],merged.aircraft[p[1]].hex]),[[1020,'a'],[1035,'a'],[1040,'b'],[1050,'b']]);assert.equal(merged.segments,undefined);assert.deepEqual(merged.breaks,[1045]);assert.throws(()=>mergeCoverage(ram,{...tail,cache_key:'moved'}));

const originalFetch=globalThis.fetch,originalInterval=globalThis.setInterval;
try{
  globalThis.setInterval=()=>0;
  let response=first,createCount=0;const replacements=[],summary={textContent:''};
  globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify(response)});
  const root={hidden:false,dataset:{},querySelector:()=>summary};
  const reload=mountCoverage(root,()=>700,(_root,data)=>{createCount++;replacements.push(data);return data=>replacements.push(data);});
  await reload();assert.equal(createCount,1);assert.equal(replacements.length,1);
  response={status:'LOADING',meta:{},points:[],aircraft:[],cells:[]};
  await reload();assert.equal(replacements.length,1);assert.match(summary.textContent,/Updating/);
  response=next;root.dataset.moving='true';await reload();assert.equal(replacements.length,1,'Do not rebuild history during a drag');root.dataset.moving='false';await reload();assert.equal(replacements.length,2);assert.equal(createCount,1);
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
