'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const bands=require('../UI/spectrum_bands'),data=require('../UI/spectrum_allocations.json');
const at=(region,mhz)=>bands.describe(bands.lookup(data,region,mhz*1e6),mhz*1e6);
const has=(info,text)=>info.services.some(s=>s.name.toLowerCase().includes(text.toLowerCase()));
test('official snapshots cover the whole survey range, including exact end point',()=>{
 for(const region of ['eu','us']){
  let covered=25e6;
  for(const row of data[region]){assert.ok(row.low<row.high);if(row.low<=covered&&row.high>covered)covered=row.high;}
  assert.ok(covered>1700e6,region+' has a gap or omits the right endpoint');
  assert.ok(bands.lookup(data,region,1700e6).length);
 }
 assert.match(data.sources.us.version,/2026-08-11/);assert.ok(data.eu.length>100);assert.ok(data.us.length>300);
});
test('European and US band edges are half-open and preserve regional differences',()=>{
 assert.ok(has(at('eu',145.9),'amateur'));assert.equal(has(at('eu',146),'amateur'),false);
 assert.ok(has(at('us',146),'amateur'));assert.equal(has(at('us',148),'amateur'),false);
 assert.equal(has(at('eu',137),'aeronautical mobile (R)'),false);
 assert.ok(has(at('eu',137),'meteorological-satellite'));
});
test('915 MHz includes US amateur allocation by footnote as well as ISM rule categories',()=>{
 const result=at('us',915);
 assert.ok(has(result,'radiolocation'));assert.ok(has(result,'amateur'));
 assert.equal(result.services.find(s=>/amateur/i.test(s.name)).priority,'secondary');
 assert.ok(result.references.includes('US275'));assert.ok(result.applications.includes('ISM Equipment (18)'));
 assert.match(data.footnotes.us.US275,/secondary basis to the amateur service/);
});
test('European applications respect their narrower subbands inside a broad allocation',()=>{
 const result=at('eu',868.3);
 assert.ok(result.applications.includes('Non-specific SRDs'));
 assert.equal(result.applications.includes('GSM'),false);assert.equal(result.applications.includes('RFID'),false);
 assert.ok(at('eu',867.5).applications.includes('RFID'));assert.ok(at('eu',885).applications.includes('GSM'));
 assert.ok(at('eu',433.92).applications.includes('Non-specific SRDs'));
});
test('aviation, satellite and FM allocations remain available without receiver samples',()=>{
 for(const region of ['eu','us']){
  assert.ok(has(at(region,1090),'aeronautical radionavigation'));
  assert.ok(has(at(region,1575.42),'radionavigation-satellite'));
  assert.ok(has(at(region,101.3),'broadcasting'));
  for(const value of [NaN,Infinity,'101300000'])assert.deepEqual(bands.lookup(data,region,value),[]);
 }
 assert.deepEqual(bands.lookup(data,'unknown',100e6),[]);assert.deepEqual(bands.lookup(data,'eu',1e6),[]);
});
