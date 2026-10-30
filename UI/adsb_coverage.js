// Shared real-history reception view. No external aircraft feeds.
import {domeContact,domeAltitude,receptionAge} from './adsb_view.js';
export const PREVIEW_POINTS=1800,PREVIEW_SEGMENTS=2200;
const SIGNAL_STOPS=[[.15,.35,1],[.05,.8,1],[.2,.85,.45],[1,.85,.15],[1,.18,.1]];
export function signalColour(level){
  if(!Number.isFinite(level))return '#91aac1';
  const value=Math.max(0,Math.min(1,(level+45)/40))*4,index=Math.min(3,Math.floor(value)),fraction=value-index;
  return 'rgb('+SIGNAL_STOPS[index].map((a,i)=>Math.round(255*(a+(SIGNAL_STOPS[index+1][i]-a)*fraction))).join(',')+')';
}
export function overviewIndices(count,limit){
  const size=Math.min(count,limit);return Array.from({length:size},(_,i)=>size===1?0:Math.floor(i*(count-1)/(size-1)));
}
export function refinementIndices(count,limit=count){
  const size=Math.min(count,limit);if(size<2)return Array.from({length:size},(_,i)=>i);
  const ids=[0,count-1],intervals=[[0,count-1]];let head=0;
  while(ids.length<size){const [lo,hi]=intervals[head++],mid=Math.floor((lo+hi)/2);if(lo<mid&&mid<hi){ids.push(mid);intervals.push([lo,mid],[mid,hi]);}}
  return ids;
}
export const dotRadius=(count,moving=false)=>moving?1.2:count<1500?2.7:count<6000?1.8:.5;
export const detailBudget=(count,idle,moving=false)=>Math.min(count,moving?PREVIEW_POINTS:idle<450?8000:idle<1300?30000:idle<2500?100000:count);
export const domeZoom=value=>Math.max(.5,Math.min(4,Number(value)||1));
export function skyOverview(cells){
  const buckets=new Map();
  for(const cell of cells){const az=Math.floor(cell.az/8)*8,el=Math.floor(cell.el/4)*4,key=az+':'+el;let target=buckets.get(key);if(!target){target={az,el,count:0,sum:0,levels:0};buckets.set(key,target);}const count=cell.count||cell.points?.length||0;target.count+=count;if(Number.isFinite(cell.level)){target.sum+=cell.level*count;target.levels+=count;}}
  return [...buckets.values()].map(cell=>({...cell,level:cell.levels?cell.sum/cell.levels:null}));
}
const signalBucket=level=>Number.isFinite(level)?Math.round(Math.max(0,Math.min(1,(level+45)/40))*15):16;
export const coverageScope=data=>JSON.stringify([data.meta?.window_since,data.meta?.reference?.lat,data.meta?.reference?.lon,data.meta?.reference_height_m]);
export const coveragePointKey=(data,p)=>((data.base+p[0]).toFixed(3))+':'+data.aircraft[p[1]].hex;
export function coverageObservation(data,index){
  const p=data.points[index],a=data.aircraft[p[1]],up=p[4]-(data.meta?.reference_height_m||0),horizontal=Math.hypot(p[2],p[3]);
  return {hex:a.hex,label:p[8]||a.label,time:data.base+p[0],altitude:p[5],gnss:!!p[7],rssi:p[6],east:p[2],north:p[3],up,horizontal:horizontal/1000,slant:Math.hypot(horizontal,up)/1000,azimuth:(Math.atan2(p[2],p[3])*180/Math.PI+360)%360,elevation:Math.atan2(up,horizontal)*180/Math.PI};
}
export function latestCoverageObservation(data,selected){
  if(!selected)return null;
  for(let i=data.points.length-1;i>=0;i--){const p=data.points[i];if(data.aircraft[p[1]].hex===selected.hex)return data.base+p[0]>selected.time?{...coverageObservation(data,i),context:selected.context}:selected;}
  return selected;
}
export function nearestCoverageHit(hits,x,y,radius=22){
  let nearest=null,nearestDot=null;
  for(const hit of hits){let d=Math.hypot(hit.x-x,hit.y-y),point=hit.point;
    if(hit.path){d=Infinity;for(let i=1;i<hit.path.length;i++){const a=hit.path[i-1],b=hit.path[i],vx=b.x-a.x,vy=b.y-a.y,t=Math.max(0,Math.min(1,((x-a.x)*vx+(y-a.y)*vy)/(vx*vx+vy*vy||1))),distance=Math.hypot(a.x+t*vx-x,a.y+t*vy-y);if(distance<d){d=distance;point=(i-1+t)/(hit.path.length-1)<.5?hit.segment.a:hit.segment.b;}}}
    if(d<radius){const candidate={...hit,d,point},closer=other=>!other||d<other.d||(d===other.d&&hit.depth>other.depth);if(closer(nearest))nearest=candidate;if(hit.kind==='point'&&d<8&&closer(nearestDot))nearestDot=candidate;}
  }
  return nearestDot||nearest;
}
export function newCoveragePoints(previous,data){
  if(!previous||coverageScope(previous)!==coverageScope(data))return new Set();
  const old=new Set(previous.points.map(p=>coveragePointKey(previous,p))),latest=Math.max(previous.meta.last_position||0,data.meta.last_position||0);
  return new Set(data.points.filter(p=>data.base+p[0]>=latest-15&&!old.has(coveragePointKey(data,p))).map(p=>coveragePointKey(data,p)));
}
export const spaceHeightScale=(radius,highest,expanded)=>expanded?Math.max(1,Math.min(12,Math.floor(.7*radius/Math.max(1000,highest)*2)/2)):1;
export function skyArc(a,b){
  const angle=Math.acos(Math.max(-1,Math.min(1,a.reduce((sum,v,i)=>sum+v*b[i],0)))),steps=Math.max(1,Math.ceil(angle*180/Math.PI/3));
  return Array.from({length:steps+1},(_,i)=>{const t=i/steps,sine=Math.sin(angle),u=Math.abs(sine)>1e-7?Math.sin((1-t)*angle)/sine:1-t,w=Math.abs(sine)>1e-7?Math.sin(t*angle)/sine:t,v=a.map((x,j)=>u*x+w*b[j]),length=Math.hypot(...v);return length>1e-8?v.map(x=>x/length):[0,0,1];});
}
export function spaceFrame(points,highest,yaw,tilt,width,height){
  const a=yaw*Math.PI/180,t=tilt*Math.PI/180,sa=Math.sin(a),ca=Math.cos(a),st=Math.sin(t),ct=Math.cos(t);
  let minX=-1.1,maxX=1.1,minY=Math.min(-1.1*st,-highest*ct),maxY=1.1*st;
  for(const v of points){const x=v[0]*ca-v[1]*sa,y=-(v[0]*sa+v[1]*ca)*st-v[2]*ct;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
  const scale=Math.min(Math.max(1,width-56)/(maxX-minX),Math.max(1,height-72)/Math.max(.1,maxY-minY));
  return {scale,cx:width/2-(minX+maxX)*scale/2,cy:height/2-(minY+maxY)*scale/2};
}
function distanceStep(radius,divisions){
  const target=radius/Math.max(1,divisions),unit=10**Math.floor(Math.log10(target));
  return [1,2,2.5,5,10].find(n=>n*unit>=target)*unit;
}
function distanceTicks(radius,pixels){
  const step=distanceStep(radius,Math.max(1,Math.min(4,Math.floor(pixels/72)))),ticks=[];
  for(let d=step;d<radius;d+=step)ticks.push(d);
  if(ticks.length&&(radius-ticks.at(-1))/radius*pixels<72)ticks.pop();
  return [...ticks,radius];
}
export function emptyCoverage(data,since){
  const meta=Object.fromEntries(Object.entries(data?.meta||{}).filter(([key])=>['reference','reference_height_m','reference_height_known','retention_days','storage_limit'].includes(key)));
  Object.assign(meta,{window_since:since,retained_positions:0,positioned_aircraft:0,horizontal_range_max_km:0,slant_range_max_km:0,max_altitude_ft:null});
  return {status:'EMPTY',meta,base:0,points:[],cells:[],aircraft:[],breaks:[],receiver_enabled:data?.receiver_enabled,receiver_status:data?.receiver_status};
}
export function mergeCoverage(previous,next){
  if(!next.delta)return next;
  if(!previous||previous.cache_key!==next.cache_key)throw Error('History reference changed');
  const base=previous.base||0,indexes=new Map(next.aircraft.map((a,i)=>[a.hex,i])),cutoff=Math.max(next.meta.window_since||0,next.meta.first_position||0),points=[];
  for(const p of previous.points){const time=base+p[0],index=indexes.get(previous.aircraft[p[1]].hex);if(time<cutoff||time>=next.after||index===undefined)continue;points.push(index===p[1]?p:[p[0],index,...p.slice(2)]);}
  for(const p of next.points)points.push([next.base+p[0]-base,...p.slice(1)]);
  const merged={...next,base,points};delete merged.delta;delete merged.after;delete merged.segments;return merged;
}
export function mountCoverage(root,getSince=()=>null,createView=setup,getLive=()=>[]){
  let update=null,busy=false,last='',current=null,lastFetch=0,lastSince=null;
  async function reload(reset=false){
    if(root.hidden)return;
    if(reset===true){current=emptyCoverage(current,getSince());if(update)update(current);else update=createView(root,current,reload,getLive);last='';}
    if(busy||root.dataset.moving==='true')return;busy=true;
    const since=getSince();try{if(current?.meta?.sampled&&since===lastSince&&performance.now()-lastFetch<30000)return;const query=new URLSearchParams();if(since!==null)query.set('since',since);if(current?.cache_key&&Number.isFinite(current.meta?.last_position)&&!current.meta.sampled&&(since??0)>=(current.meta.window_since||0)){query.set('after',current.meta.last_position-30);query.set('cache_key',current.cache_key);}const r=await fetch('/api/coverage'+(query.size?'?'+query:''));if(!r.ok)throw Error('Coverage unavailable');const body=await r.text();if(root.dataset.moving==='true')return;let data=JSON.parse(body);if(since!==getSince())return;
      if(data.error)throw Error(data.error);
      if(data.status==='LOADING'){root.querySelector('[data-summary]').textContent=update?'Updating reception window…':'Loading reception history…';return;}
      data=mergeCoverage(current,data);lastFetch=performance.now();lastSince=since;
      if(body!==last){if(update)update(data);else update=createView(root,data,reload,getLive);last=body;current=data;}
    }catch(e){root.querySelector('[data-summary]').textContent='Coverage: '+e.message+' · retrying';}finally{busy=false;}
  }
  setInterval(reload,5000);return reload;
}
function setup(root,initial,reload,getLive){

    const $=name=>root.querySelector('[data-'+name+']'),canvas=root.querySelector('canvas'),display=canvas.getContext('2d'),surface=document.createElement('canvas'),c=surface.getContext('2d');
    const bleedCanvas=document.createElement('canvas'),bleedDisplay=bleedCanvas.getContext('2d');bleedCanvas.className='dome-bleed';bleedCanvas.setAttribute('aria-hidden','true');bleedCanvas.hidden=true;canvas.parentElement.append(bleedCanvas);
    let data=initial,meta=data.meta;const rad=Math.PI/180;
    let sceneRevision=0,baseKey='',freshKeys=new Set(),pulseUntil=0,pulseTimer,motionUntil=performance.now(),motionTimer,detailTimer;
    let selectedObservation=null,detailsHex=null,details=null,detailsGeneration=0,latestContact=null;
    let groundInfo=null,groundImage=null,groundVersion='',groundDesired='',groundBusy=false,groundTimer,lastGroundRequest=0;
    const fmtTime=t=>new Date(t*1000).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
    let state={view:'cells',aircraft:'all',colour:'visits',yaw:0,tilt:65,height:0,spaceScale:'expanded',groundMap:false,zoom:1},points=[],pointOrder=[],cells=[],allCells=[],previewCells=[],fitVertices=[],hits=[],drag=null,pinned=false,width=0,height=0,scale=1,cx=0,cy=0,colours={},frame=0,cosYaw=1,sinYaw=0,cosTilt=1,sinTilt=0,scaffolds=[],unknownGrid=[];
    const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),median=a=>{const v=a.filter(Number.isFinite).sort((x,y)=>x-y);if(!v.length)return null;return v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2;};
    try{state={...state,...JSON.parse(localStorage.getItem("adsb-coverage-view")||"{}")};}catch{}
    state.height=meta.reference_height_m||0;
    state.yaw=clamp(Number(state.yaw)||0,0,360);state.tilt=clamp(Number(state.tilt)||65,8,90);state.height=clamp(Number(state.height)||0,-500,9000);
    state.zoom=domeZoom(state.zoom);
    if(!['cells','space'].includes(state.view))state.view='cells';if(!['visits','signal'].includes(state.colour))state.colour='visits';
    if(!['expanded','true'].includes(state.spaceScale))state.spaceScale='expanded';
    function metadata(){
      $('receiver-state').textContent=' · '+(data.receiver_enabled===undefined?'Receiver status loading…':data.receiver_enabled?'ADS-B '+data.receiver_status:'ADS-B paused');
      const selected=state.aircraft,choices=[['All positioned aircraft','all'],...data.aircraft.map(a=>[a.label+(a.label===a.hex?'':' · '+a.hex.toUpperCase()),a.hex])],choiceKey=JSON.stringify(choices);
      if($('aircraft').dataset.choices!==choiceKey){$('aircraft').replaceChildren(...choices.map(([label,value])=>new Option(label,value)));$('aircraft').dataset.choices=choiceKey;}
      state.aircraft=selected==='all'||data.aircraft.some(a=>a.hex===selected)?selected:'all';
      $('summary').textContent=meta.retained_positions+' positions · '+meta.positioned_aircraft+' aircraft'+(meta.first_position?' · '+fmtTime(meta.first_position)+' – '+fmtTime(meta.last_position):'')+(meta.excluded_other_sites?' · '+meta.excluded_other_sites+' positions from other sites excluded':'');
      $('reference').textContent=meta.reference?'Site '+meta.reference.lat.toFixed(5)+'°, '+meta.reference.lon.toFixed(5)+'° · '+(meta.reference_height_known?'antenna ellipsoid height set':'height unknown; 0 m assumed'):'Set antenna latitude / longitude in Receiver to build the dome.';
      $('method').textContent='Blue = directly received positions; grey = unobserved, not confirmed obstruction. Keeps all receptions for seven days; older history is retained up to 90 days within a 250,000-position target. Coverage includes reception within 100 m of the current antenna site; other sites remain stored separately. Choose 1 min · fresh to clear the displayed dome and statistics and receive from now; selecting it again restarts the view. It then rolls without periodic clearing. Longer periods show recorded history; All recorded uses all retained data. A new page defaults to one hour. Live/History and Start fresh on the aircraft map do not change the dome. One-minute cutoffs advance in 10-second steps; other rolling cutoffs advance once a minute. New samples glow briefly. Rotation uses a reduced preview until release, then builds an 8,000, 30,000, 100,000 and complete saved-position cloud over about three seconds. Saved observations and statistics are unchanged. Sky Cells uses a fast 8° × 4° moving overview and 4° × 2° reception cells at rest. The current selected set is held in RAM. Up to 250,000 representative display positions are used for larger histories; the complete seven-day archive stays on disk. Rotating never re-reads the database or downloads history. Zoom ranges from 50% to 400%, with a faint extension behind the side readouts above 100%. GNSS altitude preferred (above WGS84 ellipsoid); open circles use approximate barometric altitude. Signal colours use a fixed blue-to-red −45 to −5 dBFS scale on both dots and trails; they show received strength, not distance. RSSI is readsb aircraft average, not calibrated gain. Cells: 8° azimuth × 4° elevation while moving; 4° × 2° at rest. 3D Distance draws individual received positions without connecting lines. 3D height expansion is labelled with its factor; True scale uses equal horizontal and vertical units. Altitude readouts always retain their actual values. ADS-B may have been paused during this interval. Radius is furthest horizontal position; diameter = twice that radius, not continuous circular coverage.';
      const r=meta.horizontal_range_max_km||0,alt=meta.max_altitude_ft;
      const stats=[['HORIZONTAL RADIUS',r.toFixed(2)+' km'],['DIAMETER · 2 × R',(2*r).toFixed(2)+' km'],['MAX SLANT RANGE',(meta.slant_range_max_km||0).toFixed(2)+' km'],['HIGHEST RECEIVED',alt==null?'—':alt.toLocaleString()+' ft / '+(alt*.0003048).toFixed(2)+' km']];
      for(const [index,name] of ['readouts','range-readouts'].entries())$(name).replaceChildren(...stats.slice(index*2,index*2+2).map(([label,value])=>{const item=document.createElement('div'),term=document.createElement('dt'),description=document.createElement('dd');term.textContent=label;description.textContent=value;item.append(term,description);return item;}));
      const quality=document.createElement('small');quality.dataset.detailCount='';$('range-readouts').lastElementChild.append(quality);
      if(document.activeElement!==$('height'))$('height').value=meta.reference_height_known?meta.reference_height_m:'';
    }
    function save(){try{localStorage.setItem("adsb-coverage-view",JSON.stringify(state));}catch{}}
    function identityCard(){
      if(!selectedObservation)return;
      const info=details||{},photo=info.photo,link=$('selected-photo-link'),img=$('selected-photo');
      $('selected-maker').textContent=info.manufacturer||((info.status==='loading'||!details)?'Looking up aircraft…':'Aircraft');
      $('selected-model').textContent=info.model||info.icao_type||(!details||info.status==='loading'?'':'Model unavailable');
      $('selected-model').title=[info.manufacturer,info.model,info.icao_type,info.source].filter(Boolean).join(' · ');
      $('selected-registration').textContent=[info.registration,info.icao_type].filter(Boolean).join(' · ');
      link.hidden=!photo;if(photo){link.href=photo.link;link.title=photo.credit;const src=info.photo_cached?'/api/aircraft/photo?hex='+detailsHex:photo.url;if(img.getAttribute('src')!==src){img.alt='Aircraft '+(info.registration||detailsHex.toUpperCase());img.onerror=()=>{link.hidden=true;};img.src=src;}}
      else {img.removeAttribute('src');link.removeAttribute('href');}
    }
    function aircraftIdentity(hex){
      if(detailsHex===hex)return;detailsHex=hex;details=null;const generation=++detailsGeneration;
      async function load(attempt=0){
        try{const response=await fetch('/api/aircraft?hex='+encodeURIComponent(hex));if(!response.ok)throw Error();const info=await response.json();if(generation!==detailsGeneration||selectedObservation?.hex!==hex)return;details=info;identityCard();if(info.status==='loading'&&attempt<20)setTimeout(()=>load(attempt+1),800);}
        catch{if(generation!==detailsGeneration||selectedObservation?.hex!==hex)return;details={status:'unavailable'};identityCard();}
      }
      load();
    }
    function aircraftCard(){
      const card=$('aircraft-card'),p=selectedObservation;card.hidden=!p;if(!p){detailsHex=null;detailsGeneration++;latestContact=null;return;}aircraftIdentity(p.hex);identityCard();
      $('selected-name').textContent=p.label;$('selected-icao').textContent='ICAO '+p.hex.toUpperCase()+(p.context.includes('cell')?' · latest cell sample':'');
      const positionReport={hex:p.hex,last_seen_at:p.time,...(p.gnss?{alt_geom:p.altitude}:{alt_baro:p.altitude})};
      latestContact=domeContact([...getLive(),positionReport],p.hex,Date.now()/1000,latestContact);
      const live=latestContact,altitude=domeAltitude(live);
      $('selected-time').textContent=live?receptionAge(live.seen):'Age unavailable';
      $('selected-time').title='Latest positioned report: '+new Date(p.time*1000).toLocaleString();
      const fields=[['Altitude',altitude?.replace(/ ft .*/,' ft')||p.altitude.toLocaleString()+' ft '+(p.gnss?'GNSS':'BARO ≈')],['RSSI',p.rssi==null?'—':p.rssi.toFixed(1)+' dBFS'],['Horiz.',p.horizontal.toFixed(2)+' km'],['Slant',p.slant.toFixed(2)+' km'],['Az',p.azimuth.toFixed(1)+'°'],['El',p.elevation.toFixed(1)+'°']];
      $('selected-fields').replaceChildren(...fields.map(([label,value])=>{const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;if(label==='Altitude')dd.title=altitude||(p.gnss?'GNSS altitude':'Barometric altitude');row.append(dt,dd);return row;}));
      const fmt=v=>Number.isFinite(v)?Math.round(v).toLocaleString():'—';
      $('selected-live').textContent=live?fmt(live.gs)+' kt · '+fmt(live.track)+'°'+(live.squawk?' · SQ '+live.squawk:'')+' · '+(live.live?'Live':'Last report'):'Latest received position';
      $('filter-aircraft').textContent=state.aircraft===p.hex?'Show all aircraft':'Only this aircraft';
    }
    $('close-aircraft').onclick=()=>{selectedObservation=null;pinned=false;aircraftCard();schedule();};
    $('filter-aircraft').onclick=()=>{if(!selectedObservation)return;state.aircraft=state.aircraft===selectedObservation.hex?'all':selectedObservation.hex;geometry();sync();schedule();aircraftCard();save();};
    root.addEventListener('keydown',e=>{if(e.key==='Escape'&&selectedObservation){e.stopPropagation();$('close-aircraft').click();}});
    async function requestGround(){
      clearTimeout(groundTimer);
      const enabled=state.view==='space'&&state.groundMap&&!root.hidden,site=meta.reference;
      $('ground-status').hidden=!enabled;
      if(!enabled||!site){groundDesired='';if(enabled)$('ground-status').textContent='Set the receiver site to align the ground map.';return;}
      const desired=[site.lat,site.lon,range].join(':');
      if(groundBusy||desired===groundDesired&&performance.now()-lastGroundRequest<2000){groundTimer=setTimeout(requestGround,2200);return;}
      groundDesired=desired;groundBusy=true;lastGroundRequest=performance.now();
      try{
        const response=await fetch('/api/coverage/ground?'+new URLSearchParams({lat:site.lat,lon:site.lon,radius:range}));if(!response.ok)throw Error();const info=await response.json();
        if(groundDesired!==desired||!state.groundMap||state.view!=='space')return;
        $('ground-status').textContent=info.status==='READY'?info.attribution+' · flat ground reference · aircraft heights in 3D':'Loading satellite ground map…';
        const version=info.key+':'+info.revision;
        if(info.status==='READY'&&version!==groundVersion){const image=new Image();image.onload=()=>{if(groundDesired!==desired||!state.groundMap)return;groundInfo=info;groundImage=image;groundVersion=version;baseKey='';schedule();};image.onerror=()=>{$('ground-status').textContent='Ground imagery unavailable · retrying';};image.src='/api/coverage/ground.png?'+new URLSearchParams({key:info.key,revision:info.revision});}
      }catch{$('ground-status').textContent='Ground map unavailable · retrying';}
      finally{groundBusy=false;if(state.groundMap&&state.view==='space'&&!root.hidden)groundTimer=setTimeout(requestGround,2500);}
    }
    function groundBase(){
      if(state.view!=='space'||!state.groundMap||!groundImage||!meta.reference||groundInfo.reference.lat!==Number(meta.reference.lat.toFixed(5))||groundInfo.reference.lon!==Number(meta.reference.lon.toFixed(5)))return;
      const r=groundInfo.radius/range,q=project([-r,r,0]),a=project([r,r,0]),b=project([-r,-r,0]);
      c.save();path(Array.from({length:121},(_,i)=>vector(i*3,0)));c.closePath();c.clip();c.globalAlpha=.72;
      c.transform((a.x-q.x)/groundImage.width,(a.y-q.y)/groundImage.width,(b.x-q.x)/groundImage.height,(b.y-q.y)/groundImage.height,q.x,q.y);c.drawImage(groundImage,0,0);c.restore();
    }
    function sync(){$('space-scale-wrap').hidden=state.view!=='space';$('ground-map').textContent='Map '+(state.groundMap?'on':'off');$('ground-map').setAttribute('aria-pressed',String(state.groundMap));requestGround();for(const k of ['view','aircraft','colour','yaw','tilt','spaceScale'])(k==='spaceScale'?$('space-scale'):$(k)).value=state[k];$('yaw-value').value=Math.round(state.yaw)+'°';$('tilt-value').value=Math.round(state.tilt)+'°';$('zoom').value=Math.round(state.zoom*100);$('zoom-value').value=Math.round(state.zoom*100)+'%';$('colour-label').textContent=state.colour==='signal'?'Weak −45 dBFS · blue → cyan → green → yellow → red · −5 dBFS strong':'Received · brighter = more samples';$('colour-label').classList.toggle('signal-scale',state.colour==='signal');}
    function vector(az,el,r=1){return [r*Math.sin(az*rad)*Math.cos(el*rad),r*Math.cos(az*rad)*Math.cos(el*rad),r*Math.sin(el*rad)];}
    function geometry(resetSelection=false){
      sceneRevision++;
      points=data.points.map((p,i)=>{
        const up=p[4]-state.height,horizontal=Math.hypot(p[2],p[3]),az=(Math.atan2(p[2],p[3])/rad+360)%360,el=Math.atan2(up,horizontal)/rad;
        return {id:i,fresh:freshKeys.has(coveragePointKey(data,p)),time:data.base+p[0],aircraft:{...data.aircraft[p[1]],label:p[8]||data.aircraft[p[1]].label},east:p[2],north:p[3],up,alt:p[5],rssi:p[6],gnss:!!p[7],az,el,distance:horizontal,sky:vector(az,el)};
      }).filter(p=>state.aircraft==='all'||p.aircraft.hex===state.aircraft);
      range=rangeFor();axisHeight=Math.ceil(points.reduce((value,p)=>Math.max(value,p.up),1000)/1000)*1000;heightScale=state.view==='space'?spaceHeightScale(range,axisHeight,state.spaceScale==='expanded'):1;
      for(const p of points)p.world=state.view==='space'?[p.east/range,p.north/range,p.up/range*heightScale]:p.sky;
      pointOrder=refinementIndices(points.length);
      const side=$('range-readouts'),highest=side.children[1];
      if(highest){let note=highest.querySelector('[data-altitude-note]');if(!note){note=document.createElement('small');note.dataset.altitudeNote='';highest.append(note);}note.textContent=[meta.max_altitude_source,meta.max_altitude_aircraft].filter(Boolean).join(' · ');}
      let scaleNote=side.querySelector('[data-scale-note]');if(!scaleNote){scaleNote=document.createElement('small');scaleNote.dataset.scaleNote='';(highest||side).append(scaleNote);}scaleNote.hidden=state.view!=='space';scaleNote.textContent=heightScale>1?'Height expanded ×'+heightScale:'True scale · 1:1';scaleNote.title='Distance and altitude readouts retain actual values.';
      const buckets=new Map();for(const p of points){if(p.el<0||p.el>90)continue;const az=Math.floor(p.az/4)*4,el=Math.min(88,Math.floor(p.el/2)*2),key=az+':'+el;if(!buckets.has(key))buckets.set(key,{key,az,el,points:[]});buckets.get(key).points.push(p);}
      cells=[...buckets.values()];for(const cell of cells){cell.level=median(cell.points.map(p=>p.rssi));cell.aircraft=new Set(cell.points.map(p=>p.aircraft.hex)).size;cell.center=vector(cell.az+2,cell.el+1);}
      if(state.aircraft==='all'&&data.cells)for(const [az,el,count,level,aircraft,maxDistance] of data.cells){const key=az+':'+el,cell=buckets.get(key)||{key,az,el,points:[]};Object.assign(cell,{count,level,aircraft,maxDistance,center:vector(az+2,el+1)});buckets.set(key,cell);}cells=[...buckets.values()];
      allCells=[];for(let el=0;el<90;el+=2)for(let az=0;az<360;az+=4){const key=az+':'+el;allCells.push({az,el,center:vector(az+2,el+1),vertices:[vector(az+.22,el+.12),vector(az+3.78,el+.12),vector(az+3.78,el+1.88),vector(az+.22,el+1.88)],observed:buckets.get(key)});}
      previewCells=skyOverview(cells).map(cell=>({observed:cell,center:vector(cell.az+4,Math.min(90,cell.el+2)),vertices:[vector(cell.az+.44,cell.el+.24),vector(cell.az+7.56,cell.el+.24),vector(cell.az+7.56,Math.min(90,cell.el+4)-.24),vector(cell.az+.44,Math.min(90,cell.el+4)-.24)]}));
      fitVertices=state.view==='space'&&state.aircraft==='all'&&data.hull?.length?data.hull.map(v=>[v[0]/range,v[1]/range,(v[2]-state.height)/range*heightScale]):points.map(world);
      if(!unknownGrid.length)unknownGrid=[...Array.from({length:23},(_,i)=>Array.from({length:91},(_,j)=>vector(j*4,i*4))),...Array.from({length:45},(_,i)=>Array.from({length:24},(_,j)=>vector(i*8,Math.min(90,j*4))))];
      const groundRings=[],step=distanceStep(range,4);for(let d=step;d<range;d+=step)groundRings.push(d);groundRings.push(range);
      scaffolds=state.view==='space'?groundRings.map(d=>Array.from({length:121},(_,j)=>vector(j*3,0,d/range))):[...Array.from({length:6},(_,i)=>Array.from({length:121},(_,j)=>vector(j*3,i*15))),...Array.from({length:12},(_,i)=>Array.from({length:31},(_,j)=>vector(i*30,j*3)))];
      if(resetSelection)pinned=false;
      if(!pinned)$('detail').textContent=points.length+' retained positions · '+cells.length+' observed sky cells · '+new Set(points.map(p=>p.aircraft.hex)).size+' aircraft. Select a cell or dot.';
    }
    function project(v){const x=v[0]*cosYaw-v[1]*sinYaw,y=v[0]*sinYaw+v[1]*cosYaw;return {x:cx+x*scale,y:cy+(-y*sinTilt-v[2]*cosTilt)*scale,depth:-y*cosTilt+v[2]*sinTilt};}
    function world(p){return p.world;}
    const rangeFor=()=>Math.max(5000,Math.ceil((state.aircraft==='all'?Math.max(meta.horizontal_range_max_km||0,(meta.max_altitude_ft||0)*.0003048):points.reduce((value,p)=>Math.max(value,p.distance/1000),0))/5)*5000);let range=rangeFor(),heightScale=1,axisHeight=1000;
    function path(vertices){c.beginPath();vertices.forEach((v,i)=>{const p=project(v);if(i)c.lineTo(p.x,p.y);else c.moveTo(p.x,p.y);});}
    function label(text,v,alpha=1){const p=project(v);c.globalAlpha=alpha;c.fillStyle=colours.text;c.textAlign='center';c.textBaseline='middle';c.fillText(text,clamp(p.x,30,width-30),clamp(p.y,14,height-14));}
    function intensity(level,count){return state.colour==='signal'?(level==null?.5:.3+.7*clamp((level+45)/45,0,1)):.55+.45*(1-Math.exp(-count/8));}
    function draw(){
      const started=performance.now();frame=0;width=canvas.clientWidth;height=canvas.clientHeight;if(!width||!height)return;const moving=!!drag||started<motionUntil,budget=detailBudget(points.length,started-motionUntil,moving),dpr=moving?1:Math.min(2,window.devicePixelRatio||1),pixelWidth=Math.round(width*dpr),pixelHeight=Math.round(height*dpr),bleed=state.zoom>1,stage=canvas.parentElement,bleedWidth=bleed?stage.clientWidth:width,bleedTop=bleed?48:0,surfaceHeight=pixelHeight+Math.round(bleedTop*dpr),offset=bleed?canvas.getBoundingClientRect().left-stage.getBoundingClientRect().left:0;const key=[width,height,bleedWidth,offset,dpr,moving,budget,state.zoom,sceneRevision,state.view,state.yaw,state.tilt,state.colour,state.groundMap,groundVersion,selectedObservation?.time,selectedObservation?.hex].join(':');
      const repaint=key!==baseKey;if(repaint){baseKey=key;if(surface.width!==Math.round(bleedWidth*dpr)||surface.height!==surfaceHeight){surface.width=Math.round(bleedWidth*dpr);surface.height=surfaceHeight;}c.setTransform(dpr,0,0,dpr,offset*dpr,bleedTop*dpr);c.globalAlpha=1;c.fillStyle='#000';c.fillRect(-offset,-bleedTop,bleedWidth,height+bleedTop);cosYaw=Math.cos(state.yaw*rad);sinYaw=Math.sin(state.yaw*rad);cosTilt=Math.cos(state.tilt*rad);sinTilt=Math.sin(state.tilt*rad);
      colours={received:'#4c9dff',muted:'#98adbf',text:'#dcecff',gap:'#ffca78'};
      c.font=getComputedStyle($('summary')).font;const t=state.tilt*rad;scale=Math.min((width-64)/2,(height-88)/(1+Math.sin(t)));cx=width/2;cy=height/2+scale*(1-Math.sin(t))/2;if(state.view==='space')({scale,cx,cy}=spaceFrame(fitVertices,axisHeight/range*heightScale,state.yaw,state.tilt,width,height));scale*=state.zoom;cx=width/2+(cx-width/2)*state.zoom;cy=height/2+(cy-height/2)*state.zoom;if(!moving)hits=[];
      const ring=Array.from({length:121},(_,i)=>vector(i*3,0));path(ring);c.closePath();c.globalAlpha=.06;c.fillStyle=colours.muted;c.fill();groundBase();
      if(state.view==='cells'){
        // A faint wire shell represents unknown sky; only received cells need filled polygons.
        c.beginPath();for(const line of unknownGrid){line.forEach((v,i)=>{const p=project(v);if(i)c.lineTo(p.x,p.y);else c.moveTo(p.x,p.y);});}c.strokeStyle=colours.muted;c.globalAlpha=.09;c.lineWidth=.5;c.stroke();
        const observed=(moving?previewCells:allCells.filter(cell=>cell.observed)).map(cell=>({cell,q:project(cell.center)})).sort((a,b)=>a.q.depth-b.q.depth);
        for(const {cell,q} of observed){path(cell.vertices);c.closePath();c.fillStyle=state.colour==='signal'?signalColour(cell.observed.level):colours.received;c.globalAlpha=state.colour==='signal'?.9:intensity(cell.observed.level,cell.observed.count||cell.observed.points.length);c.fill();if(!moving)hits.push({...q,kind:'cell',cell:cell.observed});}
      }
      c.strokeStyle=colours.muted;c.lineWidth=1;c.globalAlpha=.24;
      for(const vertices of scaffolds){path(vertices);c.stroke();}
      if(state.view==='space')for(let az=0;az<360;az+=45){path([[0,0,0],vector(az,0)]);c.stroke();}
      if(state.view!=='cells'){
        const dots=new Map(),radius=dotRadius(points.length,moving);
        // Project once per sample, and batch by colour instead of one fill per dot.
        for(const index of pointOrder.slice(0,budget)){
          const p=points[index];if(p.el<0&&state.view!=='space')continue;const q=project(world(p)),bucket=state.colour==='signal'?signalBucket(p.rssi):0,key=bucket*2+(p.gnss?0:1);
          if(!dots.has(key))dots.set(key,[]);dots.get(key).push(q);if(!moving)hits.push({...q,kind:'point',point:p});
        }
        for(const [key,values] of [...dots].sort((a,b)=>a[0]-b[0])){
          const bucket=Math.floor(key/2);c.fillStyle=c.strokeStyle=state.colour==='signal'?signalColour(bucket===16?null:-45+bucket*40/15):colours.received;c.globalAlpha=.9;c.lineWidth=1;c.beginPath();
          for(const q of values){c.moveTo(q.x+radius,q.y);c.arc(q.x,q.y,radius,0,Math.PI*2);}if(key%2)c.stroke();else c.fill();
        }
      }
      if(state.view==='space'&&state.groundMap&&selectedObservation){
        const p=selectedObservation,foot=[p.east/range,p.north/range,0],top=[...foot.slice(0,2),p.up/range*heightScale];
        c.globalAlpha=.9;c.strokeStyle='#ffd675';c.lineWidth=1.4;c.setLineDash([3,4]);path([foot,top]);c.stroke();c.setLineDash([]);const q=project(foot);c.beginPath();c.arc(q.x,q.y,4,0,Math.PI*2);c.stroke();
      }
      c.globalAlpha=.55;c.strokeStyle=colours.muted;c.lineWidth=1.2;path(ring);c.stroke();
      for(const [name,az] of [['N',0],['E',90],['S',180],['W',270]])label(name,vector(az,0,1.11));
      if(state.view==='space'){
        // A single graduated radius on the ground plane. Its screen-right
        // orientation keeps labels separated at every rotation and tilt.
        c.globalAlpha=.85;c.strokeStyle=colours.muted;c.lineWidth=1.2;c.beginPath();c.moveTo(cx,cy);c.lineTo(cx+scale,cy);
        const ticks=distanceTicks(range,scale);
        for(const d of ticks){const x=cx+d/range*scale;c.moveTo(x,cy-4);c.lineTo(x,cy+5);}c.stroke();
        c.fillStyle=colours.text;c.textAlign='center';c.textBaseline='middle';c.font='13px system-ui';
        for(const d of ticks)c.fillText(String(d/1000),cx+d/range*scale,cy+19);
        c.font='12px system-ui';c.fillText('Ground range · km',cx+scale/2,cy+41);
        c.strokeStyle=colours.muted;c.globalAlpha=.65;path([[0,0,0],[0,0,axisHeight/range*heightScale]]);c.stroke();
        const top=project([0,0,axisHeight/range*heightScale]),axisPixels=Math.abs(top.y-cy);
        if(axisPixels>90){c.font='12px system-ui';for(const d of distanceTicks(axisHeight,axisPixels)){const q=project([0,0,d/range*heightScale]);c.fillText((d/1000)+' km',q.x+38,q.y);}}
      }else{
        for(const el of (width<480?[30]:[30,60]))label(el+'°',vector(90,el),.85);label(state.tilt>=82?'Zenith · receiver':'Zenith · 90°',[0,0,1.06],.9);
      }
      if(state.view!=='space'&&meta.max_altitude_ft!=null){const highest=project([0,0,1.06]);c.globalAlpha=1;c.fillStyle='#b9d9ff';c.textAlign='center';c.font='600 15px system-ui';c.fillText('MAX ALT '+meta.max_altitude_ft.toLocaleString()+' ft · '+(meta.max_altitude_ft*.0003048).toFixed(2)+' km',cx,Math.max(45,highest.y-35));c.font='12px system-ui';c.fillText(meta.max_altitude_source+' · '+meta.max_altitude_aircraft+' · not necessarily overhead',cx,Math.max(63,highest.y-17));}
      c.globalAlpha=1;const origin=project([0,0,0]);c.fillStyle=colours.text;c.beginPath();c.arc(origin.x,origin.y,3,0,Math.PI*2);c.fill();if(state.view==='space'||state.tilt<82)label('Receiver',[0,0,-.08],.9);
      if(state.view!=='space'){c.textAlign='left';c.textBaseline='top';c.fillStyle=colours.text;c.globalAlpha=.8;c.fillText(width<480?'Dome · compass / elevation':'Azimuth / elevation · distance projected onto dome',12,12);}c.globalAlpha=1;}
      // Present only complete frames. Pulse frames reuse the finished base image.
      if(canvas.width!==pixelWidth||canvas.height!==pixelHeight){canvas.width=pixelWidth;canvas.height=pixelHeight;}
      display.setTransform(1,0,0,1,0,0);display.globalAlpha=1;display.drawImage(surface,Math.round(offset*dpr),Math.round(bleedTop*dpr),pixelWidth,pixelHeight,0,0,pixelWidth,pixelHeight);display.setTransform(dpr,0,0,dpr,0,0);
      bleedCanvas.hidden=!bleed;if(bleed&&repaint){if(bleedCanvas.width!==surface.width||bleedCanvas.height!==surface.height){bleedCanvas.width=surface.width;bleedCanvas.height=surface.height;}bleedCanvas.style.height=(height+bleedTop)+'px';bleedCanvas.style.top=-bleedTop+'px';bleedDisplay.drawImage(surface,0,0);}
      const pulse=clamp((pulseUntil-performance.now())/800,0,1);
      if(pulse>0){display.strokeStyle='#b1ffdb';display.globalAlpha=pulse;display.lineWidth=1.8;display.beginPath();
        for(const p of points.filter(p=>p.fresh).slice(-256)){if(p.el<0&&state.view!=='space')continue;const q=project(world(p));display.moveTo(q.x+7,q.y);display.arc(q.x,q.y,7,0,Math.PI*2);}display.stroke();display.globalAlpha=1;
        clearTimeout(pulseTimer);pulseTimer=setTimeout(schedule,100);
      }
      root.dataset.moving=String(moving);canvas.dataset.drawnPositions=String(state.view==='cells'?0:budget);canvas.dataset.cellResolution=moving?'8x4':'4x2';canvas.dataset.renderDetail=state.view==='cells'?(moving?'preview':'detailed'):budget<points.length?'refining':meta.sampled?'representative':'detailed';if($('detail-count')){$('detail-count').hidden=false;$('detail-count').textContent=state.view==='cells'?(moving?'8° × 4° cells · preview':'4° × 2° reception cells'):budget.toLocaleString()+' / '+(meta.sampled?meta.retained_positions:points.length).toLocaleString()+' dots · '+(moving?'rotating':budget<points.length?'refining':meta.sampled?'representative':'detailed');}clearTimeout(detailTimer);if(!moving&&state.view!=='cells'&&budget<points.length){const deadline=motionUntil+(started-motionUntil<450?450:started-motionUntil<1300?1300:2500);detailTimer=setTimeout(schedule,Math.max(30,deadline-performance.now()+10));}canvas.dataset.renderMs=(performance.now()-started).toFixed(2);canvas.dataset.sceneRevision=String(sceneRevision);canvas.dataset.positions=String(points.length);canvas.dataset.quality=moving?'preview':'full';if(moving)canvas.dataset.previewMs=canvas.dataset.renderMs;
    }
    function schedule(){if(!frame)frame=requestAnimationFrame(draw);}
    function markMotion(){root.dataset.moving='true';motionUntil=performance.now()+160;clearTimeout(motionTimer);motionTimer=setTimeout(schedule,180);}
    function selectAt(x,y,pin=false){
      const near=nearestCoverageHit(hits,x,y)||(state.view==='cells'?allCells.map(cell=>({...project(cell.center),kind:'cell',cell,d:0})).map(h=>({...h,d:Math.hypot(h.x-x,h.y-y)})).filter(h=>h.d<18).sort((a,b)=>a.d-b.d||b.depth-a.depth)[0]:null);if(!near)return;
      if(pin)pinned=true;let text='';
      if(near.kind==='point'||near.kind==='trail'){
        const p=near.point;text=p.aircraft.label+' · '+p.aircraft.hex.toUpperCase()+' · '+p.az.toFixed(1)+'° az / '+p.el.toFixed(1)+'° el · '+(p.distance/1000).toFixed(1)+' km horizontal · '+p.alt.toLocaleString()+' ft '+(p.gnss?'GNSS':'barometric ≈')+' · '+(p.rssi==null?'—':p.rssi.toFixed(1))+' dBFS · '+fmtTime(p.time)+' local';
      }else if(near.kind==='gap')text=near.segment.a.aircraft.label+' · '+near.segment.dt.toFixed(0)+' s between retained positions · dashed connector is inferred; no reception or obstruction is proven along it.';
      else{
        const cell=near.cell;text=cell.az+'–'+(cell.az+(cell.azStep||4))+'° az / '+cell.el+'–'+(cell.el+(cell.elStep||2))+'° elevation';
        if(cell.points){text+=' · '+(cell.count||cell.points.length)+' received positions · '+cell.aircraft+' aircraft · '+(cell.level==null?'—':cell.level.toFixed(1))+' dBFS · max '+((cell.maxDistance||cell.points.reduce((value,p)=>Math.max(value,p.distance),0))/1000).toFixed(1)+' km horizontal';}
        else text+=' · no retained observations · obstruction status unknown';
      }
      $('detail').textContent=text;
      if(pin){const p=near.point||(near.kind==='cell'?near.cell.points?.reduce((latest,p)=>!latest||p.time>latest.time?p:latest,null):null);if(p){selectedObservation={...coverageObservation(data,p.id),context:near.kind==='cell'?'Latest retained sample in sky cell':'Recorded reception'};aircraftCard();schedule();$('close-aircraft').focus({preventScroll:true});}}
    }
    for(const k of ['view','aircraft','colour'])$(k).addEventListener('change',()=>{if(k==='view'&&state.view!==$(k).value)state.tilt=$(k).value==='space'?25:55;state[k]=$(k).value;geometry(true);sync();schedule();save();});
    $('ground-map').addEventListener('click',()=>{state.groundMap=!state.groundMap;if(state.groundMap&&state.view!=='space'){state.view='space';state.tilt=25;geometry(true);}sync();schedule();save();});
    $('space-scale').addEventListener('change',()=>{state.spaceScale=$('space-scale').value;geometry();sync();schedule();save();});
    for(const k of ['yaw','tilt','zoom']){$(k).addEventListener('input',()=>{state[k]=k==='zoom'?domeZoom(Number($(k).value)/100):Number($(k).value);markMotion();sync();schedule();});$(k).addEventListener('change',save);}
    $('height').addEventListener('change',async()=>{try{const r=await fetch('/api/state'),auth=await r.json();const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':auth.control_token},body:JSON.stringify({action:'coverage_height',height_m:$('height').value===''?null:Number($('height').value)})});if(!response.ok)throw Error((await response.json()).error);reload();}catch(e){$('detail').textContent=e.message;}});
    canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw:state.yaw,tilt:state.tilt,moved:false};pinned=false;markMotion();schedule();canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{const b=canvas.getBoundingClientRect();if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){markMotion();state.yaw=(drag.yaw+dx*.35+360)%360;state.tilt=clamp(drag.tilt+dy*.25,8,90);sync();schedule();}}else if(!pinned)selectAt(e.clientX-b.left,e.clientY-b.top);});
    canvas.addEventListener('pointerup',e=>{if(!drag)return;const moved=drag.moved;drag=null;motionUntil=performance.now();root.dataset.moving='false';if(moved){save();schedule();}else{const b=canvas.getBoundingClientRect();selectAt(e.clientX-b.left,e.clientY-b.top,true);}canvas.releasePointerCapture(e.pointerId);});
    canvas.addEventListener('pointercancel',()=>{drag=null;motionUntil=performance.now();root.dataset.moving='false';schedule();});
    canvas.addEventListener('wheel',e=>{e.preventDefault();state.zoom=domeZoom(state.zoom*(e.deltaY<0?1.1:1/1.1));markMotion();sync();schedule();save();},{passive:false});
    new ResizeObserver(schedule).observe(canvas.parentElement);
    metadata();geometry();sync();schedule();for(const control of root.querySelectorAll('select,input'))control.disabled=false;
    setInterval(()=>{if(!root.hidden&&selectedObservation)aircraftCard();},1000);
    return next=>{if(next.status==='LOADING')return;const resetSelection=coverageScope(data)!==coverageScope(next);freshKeys=newCoveragePoints(data,next);data=next;selectedObservation=latestCoverageObservation(data,selectedObservation);meta=data.meta;state.height=meta.reference_height_m||0;range=rangeFor();metadata();geometry(resetSelection);pulseUntil=freshKeys.size?performance.now()+800:0;sync();schedule();aircraftCard();};
}
