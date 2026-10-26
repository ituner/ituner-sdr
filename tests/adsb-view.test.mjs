import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import test from 'node:test';
const source=await readFile(new URL('../UI/adsb_view.js',import.meta.url),'utf8');
const {TrafficView,aged,freshness}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const plane=(hex='a',heard=100,position=100)=>({hex,last_seen_at:heard,...(position===null?{}:{lat:44,lon:26,position_time:position})});
test('aircraft icons switch independently without removing saved aircraft or affecting Live',()=>{
 const v=new TrafficView(100),tracks={old:[{time:90,lat:44,lon:26}]};v.mode='history';
 assert.equal(v.iconsVisible(false),true);v.historyIcons=false;assert.equal(v.iconsVisible(true),false);
 assert.equal(v.historyLabels,false);assert.equal(v.historyTrails,false);
 assert.deepEqual(v.aircraft([],tracks,110,true).map(p=>p.hex),['old']);
 v.mode='live';assert.equal(v.iconsVisible(true),true);
 v.mode='history';assert.equal(v.iconsVisible(true),false);
});
test('history names default off independently of Live labels and trail visibility',()=>{
 const v=new TrafficView(100);assert.equal(v.labelsVisible(true),true);assert.equal(v.labelsVisible(false),false);
 v.mode='history';assert.equal(v.labelsVisible(true),false);
 v.historyLabels=true;assert.equal(v.labelsVisible(false),true);assert.equal(v.historyTrails,false);
 v.mode='live';assert.equal(v.labelsVisible(false),false);
 v.mode='history';assert.equal(v.labelsVisible(false),true);
});
test('history hides trail lines and dots by default while retaining selectable aircraft',()=>{
 const v=new TrafficView(100),tracks={old:[{time:90,lat:44,lon:26}]};v.mode='history';
 assert.equal(v.trailVisible('old',[],110,tracks.old),false);
 assert.deepEqual(v.aircraft([],tracks,110,true).map(p=>p.hex),['old']);
 v.historyTrails=true;assert.equal(v.trailVisible('old',[],110,tracks.old),true);
 v.mode='live';assert.equal(v.trailVisible('a',[plane('a',110,110)],110),true);
 v.mode='history';assert.equal(v.trailVisible('old',[],110),true);
 assert.equal(tracks.old[0].time,90);
});
test('live ages RF contact independently from a stale aircraft position',()=>{
  const v=new TrafficView(100),planes=[plane(),plane('speed',110,80),plane('gone',90)];v.ingest(planes,110);
  assert.deepEqual(v.counts(planes,110),{live:2,positions:1,new:0});
  assert.deepEqual(v.aircraft(planes,{},110,true).map(p=>p.hex),['a']);
  assert.match(freshness(aged(planes[1],110)),/Position old · 30s ago/);
  assert.deepEqual(v.aircraft(planes,{},125),[]);
});
test('session clips old positions even when new speed messages arrive',()=>{
  const v=new TrafficView(100);v.mode='session';const p=plane('a',110,99),tracks={a:[{time:99,lat:44,lon:26}]};
  v.ingest([p],110);assert.equal(v.aircraft([p],tracks,110).length,1);assert.deepEqual(v.aircraft([p],tracks,110,true),[]);
  p.position_time=111;assert.equal(v.aircraft([p],tracks,111,true).length,1);
});
test('arrival baseline, highlight expiry and reset do not alter saved history',()=>{
  const v=new TrafficView(100),tracks={old:[{time:90,lat:44,lon:26}]};v.ingest([plane()],100);v.ingest([plane('new',102)],102);
  assert.equal(v.counts([],102).new,1);assert.ok(v.arrival('new',103));assert.ok(!v.arrival('new',114));
  v.reset(110);v.mode='session';v.ingest([plane('new',102)],110);
  assert.equal(v.counts([],110).new,0);assert.deepEqual(v.aircraft([],tracks,110,true),[]);
  v.mode='history';assert.equal(v.aircraft([],tracks,110,true).length,1);assert.equal(tracks.old[0].time,90);
});
test('shared globe keeps VHF behavior and applies ADS-B windows only when opted in',async()=>{
  const src=await readFile(new URL('../UI/adsb_globe.js',import.meta.url),'utf8');
  const {ADSBGlobe}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
  const globe=Object.create(ADSBGlobe.prototype);globe.planes=[];globe.historicalMarkers=true;globe.trailSeconds=300;
  globe.traces=new Map([['old',{points:[{time:50,lat:44,lon:26}]}]]);
  assert.equal(globe.mapAircraft(100).length,1);
  globe.trafficView=new TrafficView(100);globe.trafficNow=()=>100;
  assert.deepEqual(globe.mapAircraft(),[]);globe.trafficView.mode='history';assert.equal(globe.mapAircraft().length,1);
});
