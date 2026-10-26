'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {DecoderActivity,RETENTION,allowActivityOrigin}=require('../integrations/rtl433-ui/activity.cjs');
const {createTimeline,timelineTicks,marker,messageWidth,visible,waterfallLayout,decoderStates,zoomRange,panRange,gestureRange,ticks}=require('../integrations/rtl433-ui/activity.js');
function setup(){let time=1800000000000;const a=new DecoderActivity({now:()=>time,interval:false});return {a,now:()=>time/1000,advance:(seconds=5)=>time+=seconds*1000};}
const decoder=(extra={})=>({id:'hf-1',name:'Kiwi',running:true,paused:false,status:'RECEIVING',freq_khz:7038.6,...extra});
const session=(extra={})=>({enabled:true,status:'LISTENING',receiving_frequency:433920000,messages:50,events:[],assigned:{serial:'USB1'},...extra});
test('VHF and parallel sensors publish actual-frequency events once, with counter totals',()=>{
 const {a,now,advance}=setup(),s={sessions:{ism:session()},sensor_receivers:{'ism-2':session({receiving_frequency:915000000})}};
 a.vhf(s);assert.equal(a.snapshot().events.length,0);advance();
 s.sessions.ism.messages+=3;s.sessions.ism.events=[{time:now(),id:'weather',count:1,frequency:433920000,label:'Weather'}];
 s.sensor_receivers['ism-2'].messages++;s.sensor_receivers['ism-2'].events=[{time:now(),id:'weather',count:1,frequency:915000000}];
 a.vhf(s);a.vhf(s);assert.equal(a.stats.ism.successful,4);
 assert.deepEqual(new Set(a.snapshot().events.map(e=>e.frequency)),new Set([433920000,915000000]));
 // A retune in progress never attributes an old, untagged APRS event to new settings.
 s.sessions.aprs=session({receiving_frequency:null,messages:0});a.vhf(s);s.sessions.aprs.messages=1;s.sessions.aprs.events=[{time:now(),id:'call',count:1}];a.vhf(s);
 assert.equal(a.stats.aprs.successful,1);assert.ok(!a.snapshot().events.some(e=>e.mode==='aprs'));
 s.sessions.ism.enabled=false;s.sessions.ism.messages++;a.vhf(s);assert.equal(a.stats.ism.successful,4);
});
test('1090 and 978 count new decoded frames, not retained aircraft or cumulative boot totals',()=>{
 const {a,now,advance}=setup(),s={bands:[{id:'1090',frequency_mhz:1090,enabled:true,messages:900000,last_message_at:now(),status:'RECEIVING'},{id:'978',frequency_mhz:978,enabled:true,messages:500,last_message_at:now()}],aircraft:[{hex:'retained'}]};
 a.adsb(s);assert.equal(a.snapshot().events.length,0);advance();
 for(const b of s.bands){b.messages+=7;b.last_message_at=now();}a.adsb(s);a.adsb(s);
 assert.equal(a.stats['adsb-1090'].successful,7);assert.equal(a.stats['adsb-978'].successful,7);
 assert.deepEqual(a.snapshot().events.map(e=>e.frequency),[1090e6,978e6]);
 advance();s.bands[0].messages=2;s.bands[0].last_message_at=now();a.adsb(s);assert.equal(a.stats['adsb-1090'].successful,9);
 s.bands[0].enabled=false;s.bands[0].messages++;a.adsb(s);assert.equal(a.stats['adsb-1090'].successful,9);
});
test('WSPR only accepts new spots from an active receiver on the matching band',()=>{
 const {a,now,advance}=setup(),d=decoder({spots:[{history_id:'old',cycle_start:now(),frequency_mhz:7.0401,callsign:'OLD'}]});
 a.hf('wspr',{decoders:[d]});assert.equal(a.stats.wspr.successful,0);advance();
 d.spots.push({history_id:'new',cycle_start:now()-120,frequency_mhz:7.0402,callsign:'CALL'});
 d.spots.push({history_id:'wrong-band',cycle_start:now(),frequency_mhz:14.0971});
 d.spots.push({history_id:'stale',cycle_start:now()-RETENTION-1,frequency_mhz:7.0401});
 a.hf('wspr',{decoders:[d]});a.hf('wspr',{decoders:[d]});assert.equal(a.stats.wspr.successful,1);
 assert.equal(a.snapshot().events[0].frequency,7040200);
 d.paused=true;d.spots.push({history_id:'paused',cycle_start:now(),frequency_mhz:7.0401});a.hf('wspr',{decoders:[d]});assert.equal(a.stats.wspr.successful,1);
 d.paused=false;a.hf('wspr',{decoders:[d]});assert.equal(a.stats.wspr.successful,1);
});
test('CW characters, Hell OCR guesses and QRSS text remain tentative; noise produces no marks',()=>{
 const {a,now,advance}=setup(),d=decoder(),row={id:'cw-line',session_id:d.id,end_utc:new Date(now()*1000).toISOString(),rf_hz:7026000,text:'CQ'};
 a.hf('cw',{decoders:[d],history:[row]});a.hf('hell',{decoders:[d],images:[]});a.hf('qrss',{decoders:[d],images:[]});advance();
 row.text='CQ TEST';row.end_utc=new Date(now()*1000).toISOString();a.hf('cw',{decoders:[d],history:[row]});a.hf('cw',{decoders:[d],history:[row]});
 assert.equal(a.stats.cw.tentative,4);assert.equal(a.stats.cw.successful,0);
 const image={id:'raster',session_id:d.id,rf_hz:7040000,updated_ns:now()*1e9,ocr_status:'no_text',ocr_text:'',tentative_text:''};
 a.hf('hell',{decoders:[d],images:[image]});a.hf('qrss',{decoders:[d],images:[image]});assert.equal(a.stats.hell.tentative,0);assert.equal(a.stats.qrss.tentative,0);
 image.ocr_status='possible_text';image.ocr_text='CQ';image.tentative_text='TEST';
 for(let i=0;i<2;i++){a.hf('hell',{decoders:[d],images:[image]});a.hf('qrss',{decoders:[d],images:[image]});}
 assert.equal(a.stats.hell.tentative,1);assert.equal(a.stats.qrss.tentative,1);assert.ok(a.snapshot().events.every(e=>e.tentative));
});
test('SSTV counts complete images separately from partial images, once per capture stage',()=>{
 const {a,now}=setup(),d=decoder();a.hf('sstv',{decoders:[d],images:[]});
 const image={id:'picture',session_id:d.id,has_image:true,kind:'partial',mode:'Scottie 1',freq_khz:14230,updated_ns:now()*1e9};
 a.hf('sstv',{decoders:[d],images:[image]});a.hf('sstv',{decoders:[d],images:[image]});assert.equal(a.stats.sstv.tentative,1);assert.equal(a.stats.sstv.successful,0);
 image.kind='full';a.hf('sstv',{decoders:[d],images:[image]});a.hf('sstv',{decoders:[d],images:[image]});assert.equal(a.stats.sstv.successful,1);
});
test('adapter registration and publish contract reject invalid, stale and duplicate reports',()=>{
 const {a,now}=setup();a.registerDecoder({id:'package-decoder',name:'Packaged decoder',unit:'frames'});
 const event={decoder:'package-decoder',receiver:'USB2',frequency:433e6,timestamp:now(),eventId:'frame-1'};
 assert.equal(a.publish(event),true);assert.equal(a.publish(event),false);
 for(const extra of [{decoder:'unregistered'},{timestamp:now()+60},{timestamp:now()-RETENTION-1},{frequency:NaN},{count:-3},{quality:'signal-detected'}])assert.equal(a.publish({...event,eventId:undefined,...extra}),false);
 assert.equal(a.stats['package-decoder'].successful,1);
 // Counts outside the 0–1.5 GHz view are still valid, but cannot invent in-range pixels.
 assert.equal(a.publish({...event,eventId:'frame-2',frequency:2400e6}),true);assert.equal(a.snapshot().events.length,1);
 assert.equal(a.publish({...event,eventId:'frame-3',frequency:1500e6}),true);
 assert.equal(a.snapshot().maximum,1500e6);assert.equal(a.snapshot().events.length,2);
 const snapshot=a.snapshot();snapshot.decoders[0].successful=999;assert.notEqual(a.stats.ism.successful,999);
});
test('time retention and storage remain bounded, including idle time and clock correction',()=>{
 const {a,now,advance}=setup();
 for(let i=0;i<4200;i++)a.publish({decoder:'ism',timestamp:now(),frequency:300e6+i,receiver:'test',eventId:'p'+i});
 assert.equal(a.snapshot().events.length,4096);advance(RETENTION+1);assert.equal(a.snapshot().events.length,0);assert.equal(a.stats.ism.successful,4200);
});
test('waterfall defaults to four-pixel marks and preserves both frequency endpoints',()=>{
 assert.equal(marker(0),0);assert.equal(marker(1500e6),1020);assert.equal(marker(1090e6),742);
 const events=[0,7e6,433.92e6,978e6,1090e6,1500e6,1600e6].map(frequency=>({frequency,time:1000,lastSeen:1001}));
 const points=visible(events,1010,30);assert.equal(points.length,6);assert.ok(points.every(e=>e.y>0&&e.y<8&&e.width===4&&e.x>=0&&e.x<=1020));assert.equal(visible(events,2000,30).length,0);
});
test('one-second events stay in separate cells and age by actual seconds',()=>{
 const {a,now,advance}=setup();
 a.publish({decoder:'ism',timestamp:now(),frequency:433.92e6,receiver:'USB1'});advance(1);
 a.publish({decoder:'ism',timestamp:now(),frequency:433.92e6,receiver:'USB1'});
 const events=a.snapshot().events;assert.equal(events.length,2);assert.equal(events[1].time-events[0].time,1);
 assert.deepEqual(visible(events,now(),1).map(p=>p.y),[8,0]);
 assert.deepEqual(visible(events,now()+1,1).map(p=>p.y),[16,8]);
});
test('message intensity grows marks from four to twenty-four pixels without changing scroll geometry',()=>{
 for(const [count,width] of [[1,4],[2,8],[4,12],[8,16],[16,20],[32,24],[10000,24]]){
  assert.equal(messageWidth(count),width);
  const layout=waterfallLayout([{frequency:1090e6,time:1000,lastSeen:1000,count}],1000.5,1);
  assert.equal(layout.points[0].width,width);assert.equal(layout.points[0].height,8);assert.equal(layout.points[0].y,4);assert.equal(layout.duration,32);
 }
 assert.equal(messageWidth(0),4);assert.equal(messageWidth(NaN),4);
 const edges=waterfallLayout([0,1500e6].map(frequency=>({frequency,time:1000,lastSeen:1000,count:100})),1000,1);
 assert.deepEqual(edges.points.map(p=>p.x),[0,1000]);assert.ok(edges.points.every(p=>p.x+p.width<=1024));
});
test('intensity counts combine the selected interval separately per receiver, decoder, frequency and quality',()=>{
 const base={mode:'adsb-1090',receiver:'USB1',frequency:1090e6,time:1011,lastSeen:1011,count:1};
 const events=[base,{...base,time:1019,lastSeen:1019,count:3},{...base,receiver:'USB2',count:2},{...base,mode:'package-decoder'},{...base,tentative:true},{...base,frequency:978e6}];
 const layout=waterfallLayout(events,1020,10);assert.equal(layout.points.length,5);
 const combined=layout.points.find(p=>p.mode===base.mode&&p.receiver===base.receiver&&p.frequency===base.frequency&&!p.tentative);
 assert.equal(combined.count,4);assert.equal(combined.width,12);assert.equal(combined.lastSeen,1019);assert.equal(layout.rows[1].count,9);
 assert.equal(waterfallLayout(events,1020,1).points.length,6);assert.equal(base.count,1);
});
test('waterfall scrolls eight pixels per second smoothly, across boundaries and during counter updates',()=>{
 const event={frequency:1090e6,time:999,lastSeen:999,count:100};
 const y=now=>waterfallLayout([event],now,1).points[0].y;
 assert.equal(y(1000.25),10);assert.equal(y(1000.5),12);assert.equal(y(1001.25)-y(1000.25),8);
 assert.ok(Math.abs(y(1001.01)-y(1000.99)-.16)<1e-8);
 assert.equal(waterfallLayout([{...event,count:10000}],1000.5,1).points[0].y,y(1000.5));
 assert.equal(waterfallLayout([],1000.5,1).rows.length,32);
});
test('timeline clock never steps or reverses when snapshots arrive with changing network delay',()=>{
 let ms=0;const timeline=createTimeline({monotonic:()=>ms,wall:()=>1000000});timeline.sync(1000,0);
 assert.equal(timeline.read(),1000);ms=1000;assert.equal(timeline.read(),1001);
 for(const sample of [1000.6,1002.4,999,1005]){
  const before=timeline.read();timeline.sync(sample,300);assert.equal(timeline.read(),before);
  for(let i=0;i<60;i++){const old=timeline.read();ms+=1000/60;const next=timeline.read();assert.ok(next-old>=.98/60-1e-9&&next-old<=1.02/60+1e-9);}
 }
 const before=timeline.read();timeline.sync(NaN);assert.equal(timeline.read(),before);
});
test('timestamp labels keep their absolute times and scroll through second boundaries',()=>{
 const first=timelineTicks(waterfallLayout([],1000.9,1).rows,1),next=timelineTicks(waterfallLayout([],1001.1,1).rows,1);
 const tick=first.find(row=>row.time===1000),moved=next.find(row=>row.time===1000);
 assert.ok(tick&&moved);assert.ok(Math.abs(moved.y-tick.y-1.6)<1e-8);
 assert.ok(first.every(row=>row.time%8===0));
 const slow=timelineTicks(waterfallLayout([],1001.1,10).rows,10);assert.ok(slow.every(row=>row.time%80===0));
});
test('frequency zoom keeps the pointer anchored, pans within bounds and clips off-screen marks',()=>{
 const full={low:0,high:1500e6},view=zoomRange(full,.5,1090e6);
 assert.equal(marker(1090e6,view),marker(1090e6,full));
 assert.equal(view.high-view.low,750e6);
 const points=visible([7e6,978e6,1090e6,1500e6].map(frequency=>({frequency,time:1000,lastSeen:1001})),1010,30,view);
 assert.deepEqual(points.map(p=>p.frequency),[978e6,1090e6]);
 assert.deepEqual(zoomRange(view,4),full);
 const narrow=zoomRange(full,.00001,0);assert.deepEqual(narrow,{low:0,high:1e6});
 assert.deepEqual(panRange(narrow,-1),narrow);
 assert.deepEqual(panRange(narrow,2000),{low:1499e6,high:1500e6});
 for(const range of [full,view,narrow]){const scale=ticks(range);assert.equal(scale[0],range.low);assert.equal(scale.at(-1),range.high);assert.ok(scale.every((f,i)=>i===0||f>scale[i-1]));}
});
test('mouse and one-finger swipes pan in the drag direction and stop at band edges',()=>{
 const view={low:375e6,high:1125e6},start=[{x:500,y:100}];
 assert.deepEqual(gestureRange(view,start,[{x:700,y:100}],1000),{low:225e6,high:975e6});
 assert.deepEqual(gestureRange(view,start,[{x:-500,y:100}],1000),{low:750e6,high:1500e6});
 assert.deepEqual(gestureRange(view,start,[{x:500,y:500}],1000),view);
});
test('two-finger pinch preserves the frequency under the midpoint, supports pan, and stays bounded',()=>{
 const view={low:375e6,high:1125e6},start=[{x:400,y:100},{x:600,y:100}];
 const pinch=gestureRange(view,start,[{x:300,y:100},{x:700,y:100}],1000);
 assert.deepEqual(pinch,{low:562.5e6,high:937.5e6});
 assert.deepEqual(gestureRange(view,start,[{x:400,y:100},{x:800,y:100}],1000),{low:525e6,high:900e6});
 assert.deepEqual(gestureRange(view,start,[{x:499,y:100},{x:501,y:100}],1000),{low:0,high:1500e6});
 const minimum=gestureRange({low:749e6,high:751e6},start,[{x:0,y:100},{x:1000,y:100}],1000);
 assert.equal(minimum.high-minimum.low,1e6);
 // Lifting one finger rebases the remaining pointer without jumping the view.
 assert.deepEqual(gestureRange(pinch,[{x:300,y:100}],[{x:300,y:100}],1000),pinch);
});
test('read-only polling isolates unavailable feeds and shares a single in-flight poll',async()=>{
 const {a,now}=setup();let requests=0;
 a.fetcher=async(url,init)=>{requests++;assert.equal(init.method,undefined);if(url.includes(':8073'))throw Error('offline');return {ok:true,text:async()=>JSON.stringify(url.includes(':8092')?{sessions:{ism:session()}}:{bands:[]})};};
 await Promise.all([a.poll(),a.poll()]);assert.equal(requests,7);assert.equal(a.snapshot().sources.filter(s=>s.online).length,2);assert.equal(a.snapshot().events.length,0);
 const serialized=JSON.stringify(a.snapshot());assert.ok(!serialized.includes('control_token'));
 a.close();await a.poll();assert.equal(requests,7);
});
test('decoder status keeps zero-output and stopped decoders visible and distinguishes offline feeds and zoom',()=>{
 const data={decoders:[{id:'ism',name:'rtl_433',successful:0},{id:'adsb-1090',name:'ADS-B 1090',successful:0},{id:'wspr',name:'WSPR',successful:0}],
  sources:[{id:'vhf',online:true},{id:'adsb',online:true},{id:'wspr',online:false}],
  receivers:[{mode:'ism',enabled:true,status:'LISTENING',frequency:433.92e6},{mode:'adsb-1090',enabled:false,status:'STOPPED',frequency:1090e6}]};
 let states=decoderStates(data);assert.equal(states.length,3);assert.equal(states[0].state,'LISTENING');assert.equal(states[1].state,'STOPPED');assert.equal(states[2].state,'FEED OFFLINE');
 data.receivers[1].enabled=true;data.receivers[1].status='RECEIVING';
 states=decoderStates(data,{low:1000e6,high:1200e6});assert.equal(states[1].state,'RECEIVING');assert.equal(states[1].inSpan,true);assert.equal(states[0].inSpan,false);
});
test('one-second live counter polls keep slower HF feeds at five seconds',async()=>{
 const {a,advance}=setup(),calls=[];
 a.fetcher=async url=>{calls.push(url);return {ok:true,text:async()=>JSON.stringify({bands:[],sessions:{},decoders:[]})};};
 await a.poll();assert.equal(calls.length,7);advance(1);await a.poll();assert.equal(calls.length,9);
 assert.ok(calls.slice(7).every(url=>url.includes(':8090')||url.includes(':8092')));
 advance(4);await a.poll();assert.equal(calls.length,16);a.close();
});
test('scanner sharing permits only the same host and known web-app ports',()=>{
 assert.equal(allowActivityOrigin('http://cm5.local:8092','cm5.local:8093'),true);
 assert.equal(allowActivityOrigin('http://evil.local:8092','cm5.local:8093'),false);
 assert.equal(allowActivityOrigin('http://cm5.local:9999','cm5.local:8093'),false);
 assert.equal(allowActivityOrigin(undefined,'cm5.local:8093'),false);
});
