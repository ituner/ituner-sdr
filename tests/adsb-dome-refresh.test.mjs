import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const load=async path=>import('data:text/javascript;base64,'+Buffer.from(await readFile(new URL(path,import.meta.url),'utf8')).toString('base64'));
const {mountCoverage,newCoveragePoints}=await load('../UI/adsb_coverage.js');
const {TrafficView}=await load('../UI/adsb_view.js');

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
}finally{globalThis.fetch=originalFetch;globalThis.setInterval=originalInterval;}
console.log('PASS: stable Live dome scope, new-sample identity, and no empty loading-frame replacement');
