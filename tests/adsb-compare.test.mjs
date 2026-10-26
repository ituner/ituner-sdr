import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../UI/adsb_compare.js',import.meta.url),'utf8');
const {comparisonHistory,completedWindows,livePaths,packetRates,rateGraphMax,rateTickDigits,rateTimeline,timelinePaths,graphSpan,comparisonControl}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const old={receivers:[{id:'5.6'},{id:'nesdr'}],complete:true,valid:true};
const fresh={receivers:[{id:'5.6'},{id:'v4'}],complete:true,valid:true};
const partial={...fresh,complete:false,valid:false};
let data={selection:'v4',history:[old,fresh,partial],current:null};
assert.deepEqual(comparisonHistory(data),[fresh,partial]);assert.deepEqual(completedWindows(data),[fresh]);
data.current={receivers:old.receivers};assert.deepEqual(completedWindows(data),[old]);
console.log('PASS: swapped dongles retain separate results; incomplete windows are excluded');

const triple={receivers:[...fresh.receivers,{id:'flightaware'}],complete:true,valid:true};
assert.deepEqual(comparisonHistory({current:triple,history:[fresh,triple]}),[triple]);
assert.deepEqual(comparisonHistory({selections:['v4','flightaware'],history:[fresh,triple]}),[triple]);
const samples=[{elapsed:0,packets:[100,200,300]},{elapsed:2,packets:[150,220,300]},
 {elapsed:5,packets:[200,250,300]},{elapsed:7,packets:[210,290,320]},{elapsed:10,packets:[225,350,350]}];
assert.deepEqual(packetRates(samples,3)[0],{elapsed:5,rates:[20,10,0]});
assert.deepEqual(packetRates(samples,3).at(-1),{elapsed:10,rates:[12.5,15,5]});
assert.deepEqual(packetRates([{elapsed:0,packets:[100]},{elapsed:7,packets:[170]},
 {elapsed:8,packets:[0]},{elapsed:13,packets:[25]}],1),[{elapsed:7,rates:[10]},{elapsed:13,rates:[5]}]);
const graph=livePaths(samples,3);
assert.equal(graph.max,25);assert.equal(graph.paths.length,3);
assert.ok(graph.paths.every(p=>!p.includes('NaN')));
assert.deepEqual(livePaths([],3).rates,[]);
console.log('PASS: differential graph shows actual interval rates, zero traffic, falling rates and safe counter resets');

let total=0;const burst=[{elapsed:0,packets:[0,0,0]}];
for(let second=1;second<=90;second++){total+=second===16?200:second<=60?20:0;burst.push({elapsed:second,packets:[total,2*total,total/2]});}
const smooth=new Map(packetRates(burst,3).map(r=>[r.elapsed,r.rates]));
assert.deepEqual(smooth.get(5),[20,40,10]);assert.deepEqual(smooth.get(16),[31.25,62.5,15.625]);
assert.deepEqual(smooth.get(60),[20,40,10]);assert.deepEqual(smooth.get(75),[10,20,5]);assert.deepEqual(smooth.get(90),[0,0,0]);
const uneven=[{elapsed:0,packets:[0]},{elapsed:10,packets:[100]},{elapsed:25,packets:[400]},{elapsed:35,packets:[400]}];
assert.equal(packetRates(uneven,1).at(-1).rates[0],350/30);
assert.equal(rateGraphMax([{rates:[40]}]),50);assert.equal(rateGraphMax([{rates:[41]}]),50);assert.equal(rateGraphMax([{rates:[60]}]),80);
for(const peak of [.02,.4,2,6,60,6000]){
 const maximum=rateGraphMax([{rates:[peak/2,peak]}]);
 assert.ok(maximum>=peak*1.2&&maximum<=Math.max(.1,peak*2));
 assert.notEqual(Number((maximum/4).toFixed(rateTickDigits(maximum))),0);
}
assert.equal(rateGraphMax([]),1);assert.equal(rateGraphMax([{rates:[0,0]}]),1);
const autoView={now:4000,receivers:[{id:'a'},{id:'b'}],rate_history_ids:['a','b'],rate_history:[{time:1000,rates:[100,200]},{time:3998,rates:[1,2]},{time:4000,rates:[2,3]}]};
assert.equal(rateTimeline(autoView,300).max,4);assert.equal(rateTimeline(autoView,3600).max,250);
assert.equal(rateTimeline({...autoView,graph_reset_at:3990},86400).max,4);
console.log('PASS: auto scale fits low and high visible rates, excludes off-screen peaks and rescales after Reset');
console.log('PASS: rolling 30-second smoothing suppresses bursts, preserves ratios, reaches zero and handles irregular samples');

const roster=[{id:'a'},{id:'b'},{id:'c'}],points=[];
for(let time=400;time<=4000;time+=2)points.push({time,rates:time===3990?null:[10,20,5]});
const timeline={now:4000,current:{receivers:roster},rate_history_ids:['a','b','c'],rate_history:points};
for(const span of [300,1800,3600,43200,86400]){
 const frame=rateTimeline(timeline,span);assert.equal(frame.seconds,span);assert.deepEqual(frame.rates,[10,20,5]);assert.equal(frame.segments.length,2);
 assert.ok(frame.segments.flat().every(p=>p.elapsed>=0&&p.elapsed<=span));
 assert.equal(timelinePaths(frame,3).length,6);assert.ok(timelinePaths(frame,3).every(p=>!p.points.includes('NaN')));
}
assert.ok(rateTimeline(timeline,3600).segments[0].length>rateTimeline(timeline,300).segments[0].length);
assert.deepEqual(rateTimeline({...timeline,rate_history_ids:['other']},3600).segments,[]);
assert.deepEqual(rateTimeline({...timeline,now:4020},3600).rates,[]);
assert.equal(graphSpan('1800'),1800);assert.equal(graphSpan('3600'),3600);assert.equal(graphSpan('invalid'),300);
console.log('PASS: 5-minute / 30-minute / 1-hour rolling graphs preserve gaps, receiver identities and time bounds');

const resetView={...timeline,graph_reset_at:3992};
for(const span of [300,1800,3600,43200,86400]){
 const frame=rateTimeline(resetView,span);
 assert.ok(frame.segments.flat().every(p=>p.elapsed>=span-8));assert.equal(frame.segments.length,1);
}
assert.deepEqual(comparisonHistory({current:triple,graph_reset_at:100,history:[{...triple,start:50},{...triple,start:110}]}).map(w=>w.start),[110]);
console.log('PASS: graph reset hides old curves and completed bars across every time range');

assert.equal(graphSpan('43200'),43200);assert.equal(graphSpan('86400'),86400);
const daily=[];
for(let t=100000;t<=186400;t+=60)daily.push({time:t,period:60,samples:30,rates:t===143200?null:[10,20,5]});
const day={now:186400,receivers:roster,rate_history_ids:['a','b','c'],rate_history:daily};
assert.equal(rateTimeline(day,86400).segments.length,2);
assert.equal(rateTimeline(day,43200).segments.length,1);
assert.equal(rateTimeline(day,86400).available_seconds,86400);
assert.deepEqual(rateTimeline({...day,graph_reset_at:186350},86400).segments.flat().map(p=>p.elapsed),[86400]);
console.log('PASS: 12-hour / 24-hour views connect minute averages and preserve explicit outages and resets');

const response=(status,value)=>({status,ok:status===200,json:async()=>value});
let serviceToken='before-restart',accepted=[];
const service=async(path,options)=>{
 if(path==='/api/state'){assert.equal(options.cache,'no-store');return response(200,{control_token:serviceToken});}
 assert.equal(options.headers['X-ADSB-Token'],serviceToken);
 accepted.push(JSON.parse(options.body).action);return response(200,{ok:true});
};
await comparisonControl('comparison_reset',service);
serviceToken='after-restart';await comparisonControl('comparison_reset',service);
assert.deepEqual(accepted,['comparison_reset','comparison_reset']);
// A restart between the token fetch and POST can safely retry a rejected request.
let gets=0,posts=0;
await comparisonControl('comparison_reset',async(path,options)=>{
 if(path==='/api/state')return response(200,{control_token:'token-'+(++gets)});
 posts++;assert.equal(options.headers['X-ADSB-Token'],'token-'+posts);
 return posts===1?response(403,{error:'Control token required'}):response(200,{ok:true});
});
assert.equal(gets,2);assert.equal(posts,2);
let denied=0;
await assert.rejects(comparisonControl('comparison_reset',async path=>{
 if(path==='/api/state')return response(200,{control_token:'current'});
 denied++;return response(400,{error:'Receiver unavailable'});
}),/Receiver unavailable/);
assert.equal(denied,1);
console.log('PASS: Reset works across service token changes, retries only rejected authentication and preserves control errors');
