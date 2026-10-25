// Shared real-history reception view. No external aircraft feeds.
export const coverageScope=data=>JSON.stringify([data.meta?.window_since,data.meta?.reference?.lat,data.meta?.reference?.lon,data.meta?.reference_height_m]);
export const coveragePointKey=(data,p)=>((data.base+p[0]).toFixed(3))+':'+data.aircraft[p[1]].hex;
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
  const scale=Math.min(Math.max(1,width-72)/(maxX-minX),Math.max(1,height-140)/Math.max(.1,maxY-minY));
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
export function mountCoverage(root,getSince=()=>null,createView=setup){
  let update=null,busy=false,last='';
  async function reload(){
    if(root.hidden||busy)return;busy=true;
    const since=getSince();try{const r=await fetch('/api/coverage'+(since===null?'':'?since='+since));if(!r.ok)throw Error('Coverage unavailable');const body=await r.text(),data=JSON.parse(body);if(since!==getSince())return;
      if(data.error)throw Error(data.error);
      if(data.status==='LOADING'){root.querySelector('[data-summary]').textContent=update?'Updating reception window…':'Loading reception history…';return;}
      if(body!==last){if(update)update(data);else update=createView(root,data,reload);last=body;}
    }catch(e){root.querySelector('[data-summary]').textContent='Coverage: '+e.message+' · retrying';}finally{busy=false;}
  }
  setInterval(reload,5000);return reload;
}
function setup(root,initial,reload){

    const $=name=>root.querySelector('[data-'+name+']'),canvas=root.querySelector('canvas'),display=canvas.getContext('2d'),surface=document.createElement('canvas'),c=surface.getContext('2d');
    let data=initial,meta=data.meta;const rad=Math.PI/180;
    let sceneRevision=0,baseKey='',freshKeys=new Set(),pulseUntil=0,pulseTimer;
    const fmtTime=t=>new Date(t*1000).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
    let state={view:'cells',aircraft:'all',colour:'visits',yaw:0,tilt:65,height:0,gaps:false,spaceScale:'expanded'},points=[],cells=[],segments=[],allCells=[],hits=[],drag=null,pinned=false,width=0,height=0,scale=1,cx=0,cy=0,colours={},frame=0,cosYaw=1,sinYaw=0,cosTilt=1,sinTilt=0,scaffolds=[],unknownGrid=[];
    const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),median=a=>{const v=a.filter(Number.isFinite).sort((x,y)=>x-y);if(!v.length)return null;return v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2;};
    try{state={...state,...JSON.parse(localStorage.getItem("adsb-coverage-view")||"{}")};}catch{}
    state.height=meta.reference_height_m||0;
    state.yaw=clamp(Number(state.yaw)||0,0,360);state.tilt=clamp(Number(state.tilt)||65,8,90);state.height=clamp(Number(state.height)||0,-500,9000);
    if(!['cells','trails','space'].includes(state.view))state.view='cells';if(!['visits','signal'].includes(state.colour))state.colour='visits';
    if(!['expanded','true'].includes(state.spaceScale))state.spaceScale='expanded';
    function metadata(){
      $('receiver-state').textContent=' · '+(data.receiver_enabled?'ADS-B '+data.receiver_status:'ADS-B paused');
      const selected=state.aircraft,choices=[['All positioned aircraft','all'],...data.aircraft.map(a=>[a.label+(a.label===a.hex?'':' · '+a.hex.toUpperCase()),a.hex])],choiceKey=JSON.stringify(choices);
      if($('aircraft').dataset.choices!==choiceKey){$('aircraft').replaceChildren(...choices.map(([label,value])=>new Option(label,value)));$('aircraft').dataset.choices=choiceKey;}
      state.aircraft=selected==='all'||data.aircraft.some(a=>a.hex===selected)?selected:'all';
      $('summary').textContent=meta.retained_positions+' positions · '+meta.positioned_aircraft+' aircraft'+(meta.first_position?' · '+fmtTime(meta.first_position)+' – '+fmtTime(meta.last_position):'')+(meta.excluded_other_sites?' · '+meta.excluded_other_sites+' positions from other sites excluded':'');
      $('reference').textContent=meta.reference?'Site '+meta.reference.lat.toFixed(5)+'°, '+meta.reference.lon.toFixed(5)+'° · '+(meta.reference_height_known?'antenna ellipsoid height set':'height unknown; 0 m assumed'):'Set antenna latitude / longitude in Receiver to build the dome.';
      $('method').textContent='Blue = directly received positions; grey = unobserved, not confirmed obstruction. Retains up to 90 days / 250,000 positions. Coverage includes reception within 100 m of the current antenna site; other sites remain stored separately. The dome has its own rolling timespan, from five minutes to All recorded; a new page defaults to one hour. Live/History and Start fresh on the aircraft map do not change the dome. Window cutoffs advance once a minute. New samples glow briefly. All cells and statistics use the displayed observations; dots are thinned above 20,000. GNSS altitude preferred (above WGS84 ellipsoid); open circles use approximate barometric altitude. RSSI is readsb aircraft average, not calibrated gain. Cells: 4° azimuth × 2° elevation. Trails preserve continuous reception through display thinning; each original link is ≤15 s. Actual gaps remain disconnected. 3D height expansion is labelled with its factor; True scale uses equal horizontal and vertical units. Altitude readouts always retain their actual values. ADS-B may have been paused during this interval. Radius is furthest horizontal position; diameter = twice that radius, not continuous circular coverage.';
      const r=meta.horizontal_range_max_km||0,alt=meta.max_altitude_ft;
      const stats=[['HORIZONTAL RADIUS',r.toFixed(2)+' km'],['DIAMETER · 2 × R',(2*r).toFixed(2)+' km'],['MAX SLANT RANGE',(meta.slant_range_max_km||0).toFixed(2)+' km'],['HIGHEST RECEIVED',alt==null?'—':alt.toLocaleString()+' ft / '+(alt*.0003048).toFixed(2)+' km']];
      for(const [index,name] of ['readouts','range-readouts'].entries())$(name).replaceChildren(...stats.slice(index*2,index*2+2).map(([label,value])=>{const item=document.createElement('div'),term=document.createElement('dt'),description=document.createElement('dd');term.textContent=label;description.textContent=value;item.append(term,description);return item;}));
      if(document.activeElement!==$('height'))$('height').value=meta.reference_height_known?meta.reference_height_m:'';
    }
    function save(){try{localStorage.setItem("adsb-coverage-view",JSON.stringify(state));}catch{}}
    function sync(){$('space-scale-wrap').hidden=state.view!=='space';for(const k of ['view','aircraft','colour','yaw','tilt','spaceScale'])(k==='spaceScale'?$('space-scale'):$(k)).value=state[k];$('gaps').checked=state.gaps;$('yaw-value').value=Math.round(state.yaw)+'°';$('tilt-value').value=Math.round(state.tilt)+'°';$('gap-legend').hidden=!state.gaps||state.view==='cells';$('colour-label').textContent=state.colour==='signal'?'Received · stronger signal is more opaque':'Received · brighter = more samples';}
    function vector(az,el,r=1){return [r*Math.sin(az*rad)*Math.cos(el*rad),r*Math.cos(az*rad)*Math.cos(el*rad),r*Math.sin(el*rad)];}
    function geometry(resetSelection=false){
      sceneRevision++;
      points=data.points.map((p,i)=>{
        const up=p[4]-state.height,horizontal=Math.hypot(p[2],p[3]),az=(Math.atan2(p[2],p[3])/rad+360)%360,el=Math.atan2(up,horizontal)/rad;
        return {id:i,fresh:freshKeys.has(coveragePointKey(data,p)),time:data.base+p[0],aircraft:{...data.aircraft[p[1]],label:p[8]||data.aircraft[p[1]].label},east:p[2],north:p[3],up,alt:p[5],rssi:p[6],gnss:!!p[7],az,el,distance:horizontal,sky:vector(az,el)};
      }).filter(p=>state.aircraft==='all'||p.aircraft.hex===state.aircraft);
      range=rangeFor();axisHeight=Math.ceil(Math.max(1000,...points.map(p=>p.up))/1000)*1000;heightScale=state.view==='space'?spaceHeightScale(range,axisHeight,state.spaceScale==='expanded'):1;
      const buckets=new Map();for(const p of points){if(p.el<0||p.el>90)continue;const az=Math.floor(p.az/4)*4,el=Math.min(88,Math.floor(p.el/2)*2),key=az+':'+el;if(!buckets.has(key))buckets.set(key,{key,az,el,points:[]});buckets.get(key).points.push(p);}
      cells=[...buckets.values()];for(const cell of cells){cell.level=median(cell.points.map(p=>p.rssi));cell.aircraft=new Set(cell.points.map(p=>p.aircraft.hex)).size;cell.center=vector(cell.az+2,cell.el+1);}
      if(state.aircraft==='all'&&data.cells)for(const [az,el,count,level,aircraft,maxDistance] of data.cells){const key=az+':'+el,cell=buckets.get(key)||{key,az,el,points:[]};Object.assign(cell,{count,level,aircraft,maxDistance,center:vector(az+2,el+1)});buckets.set(key,cell);}cells=[...buckets.values()];
      allCells=[];for(let el=0;el<90;el+=2)for(let az=0;az<360;az+=4){const key=az+':'+el;allCells.push({az,el,center:vector(az+2,el+1),vertices:[vector(az+.22,el+.12),vector(az+3.78,el+.12),vector(az+3.78,el+1.88),vector(az+.22,el+1.88)],observed:buckets.get(key)});}
      segments=[];const tracks=new Map(),confirmed=Array.isArray(data.segments)?new Set(data.segments.map(pair=>pair.join(':'))):null;for(const p of points){const last=tracks.get(p.aircraft.hex);if(last){const dt=p.time-last.time,moved=Math.hypot(p.east-last.east,p.north-last.north,p.up-last.up),received=confirmed?confirmed.has(last.id+':'+p.id):dt>0&&dt<=15&&moved<=500+400*dt&&!data.breaks?.some(t=>last.time<t&&t<=p.time);if(received||(dt>0&&dt<=120&&moved<=500+400*dt&&!data.breaks?.some(t=>last.time<t&&t<=p.time)))segments.push({a:last,b:p,gap:!received,dt,skyPath:skyArc(last.sky,p.sky)});}tracks.set(p.aircraft.hex,p);}
      if(!unknownGrid.length)unknownGrid=[...Array.from({length:23},(_,i)=>Array.from({length:91},(_,j)=>vector(j*4,i*4))),...Array.from({length:45},(_,i)=>Array.from({length:24},(_,j)=>vector(i*8,Math.min(90,j*4))))];
      const groundRings=[],step=distanceStep(range,4);for(let d=step;d<range;d+=step)groundRings.push(d);groundRings.push(range);
      scaffolds=state.view==='space'?groundRings.map(d=>Array.from({length:121},(_,j)=>vector(j*3,0,d/range))):[...Array.from({length:6},(_,i)=>Array.from({length:121},(_,j)=>vector(j*3,i*15))),...Array.from({length:12},(_,i)=>Array.from({length:31},(_,j)=>vector(i*30,j*3)))];
      if(resetSelection)pinned=false;
      if(!pinned)$('detail').textContent=points.length+' retained positions · '+cells.length+' observed sky cells · '+new Set(points.map(p=>p.aircraft.hex)).size+' aircraft. Select a cell or dot.';
    }
    function project(v){const x=v[0]*cosYaw-v[1]*sinYaw,y=v[0]*sinYaw+v[1]*cosYaw;return {x:cx+x*scale,y:cy+(-y*sinTilt-v[2]*cosTilt)*scale,depth:-y*cosTilt+v[2]*sinTilt};}
    function world(p){return state.view==='space'?[p.east/range,p.north/range,p.up/range*heightScale]:p.sky;}
    const rangeFor=()=>Math.max(5000,Math.ceil((state.aircraft==='all'?Math.max(meta.horizontal_range_max_km||0,(meta.max_altitude_ft||0)*.0003048):Math.max(0,...points.map(p=>p.distance/1000)))/5)*5000);let range=rangeFor(),heightScale=1,axisHeight=1000;
    function path(vertices){c.beginPath();vertices.forEach((v,i)=>{const p=project(v);if(i)c.lineTo(p.x,p.y);else c.moveTo(p.x,p.y);});}
    function label(text,v,alpha=1){const p=project(v);c.globalAlpha=alpha;c.fillStyle=colours.text;c.textAlign='center';c.textBaseline='middle';c.fillText(text,clamp(p.x,30,width-30),clamp(p.y,14,height-14));}
    function intensity(level,count){return state.colour==='signal'?(level==null?.5:.3+.7*clamp((level+45)/45,0,1)):.55+.45*(1-Math.exp(-count/8));}
    function draw(){
      const started=performance.now();frame=0;width=canvas.clientWidth;height=canvas.clientHeight;if(!width||!height)return;const dpr=drag?.moved?1:Math.min(2,window.devicePixelRatio||1),pixelWidth=Math.round(width*dpr),pixelHeight=Math.round(height*dpr);const key=[width,height,dpr,sceneRevision,state.view,state.yaw,state.tilt,state.colour,state.gaps].join(':');
      if(key!==baseKey){baseKey=key;if(surface.width!==pixelWidth||surface.height!==pixelHeight){surface.width=pixelWidth;surface.height=pixelHeight;}c.setTransform(dpr,0,0,dpr,0,0);c.globalAlpha=1;c.fillStyle='#000';c.fillRect(0,0,width,height);cosYaw=Math.cos(state.yaw*rad);sinYaw=Math.sin(state.yaw*rad);cosTilt=Math.cos(state.tilt*rad);sinTilt=Math.sin(state.tilt*rad);
      colours={received:'#4c9dff',muted:'#98adbf',text:'#dcecff',gap:'#ffca78'};
      c.font=getComputedStyle($('summary')).font;const t=state.tilt*rad;scale=Math.min((width-64)/2,(height-88)/(1+Math.sin(t)));cx=width/2;cy=height/2+scale*(1-Math.sin(t))/2;if(state.view==='space')({scale,cx,cy}=spaceFrame(points.map(world),axisHeight/range*heightScale,state.yaw,state.tilt,width,height));hits=[];
      const ring=Array.from({length:121},(_,i)=>vector(i*3,0));path(ring);c.closePath();c.globalAlpha=.06;c.fillStyle=colours.muted;c.fill();
      if(state.view==='cells'){
        // A faint wire shell represents unknown sky; only received cells need filled polygons.
        c.beginPath();for(const line of unknownGrid){line.forEach((v,i)=>{const p=project(v);if(i)c.lineTo(p.x,p.y);else c.moveTo(p.x,p.y);});}c.strokeStyle=colours.muted;c.globalAlpha=.09;c.lineWidth=.5;c.stroke();
        const observed=allCells.filter(cell=>cell.observed).map(cell=>({cell,q:project(cell.center)})).sort((a,b)=>a.q.depth-b.q.depth);
        for(const {cell,q} of observed){path(cell.vertices);c.closePath();c.fillStyle=colours.received;c.globalAlpha=intensity(cell.observed.level,cell.observed.count||cell.observed.points.length);c.fill();hits.push({...q,kind:'cell',cell:cell.observed});}
      }
      c.strokeStyle=colours.muted;c.lineWidth=1;c.globalAlpha=.24;
      for(const vertices of scaffolds){path(vertices);c.stroke();}
      if(state.view==='space')for(let az=0;az<360;az+=45){path([[0,0,0],vector(az,0)]);c.stroke();}
      if(state.view!=='cells'){
        const geometryToDraw=segments.filter(s=>(!s.gap||state.gaps)&&(state.view==='space'||s.a.el>=0&&s.b.el>=0)).map(s=>({...s,depth:(project(world(s.a)).depth+project(world(s.b)).depth)/2})).sort((a,b)=>a.depth-b.depth);
        for(const s of geometryToDraw){path(state.view==='space'?[world(s.a),world(s.b)]:s.skyPath);c.strokeStyle=s.gap?colours.gap:colours.received;c.globalAlpha=s.gap?.65:.8;c.lineWidth=s.gap?1:2;c.setLineDash(s.gap?[4,5]:[]);c.stroke();if(s.gap){const a=project(world(s.a)),b=project(world(s.b));hits.push({x:(a.x+b.x)/2,y:(a.y+b.y)/2,depth:s.depth,kind:'gap',segment:s});}}
        c.setLineDash([]);
        for(const p of [...points].sort((a,b)=>project(world(a)).depth-project(world(b)).depth)){
          const q=project(world(p));if(p.el<0&&state.view!=='space')continue;c.globalAlpha=intensity(p.rssi,1);c.fillStyle=colours.received;c.strokeStyle=colours.received;c.lineWidth=1.5;c.beginPath();c.arc(q.x,q.y,state.aircraft==='all'?2.5:3.5,0,Math.PI*2);if(p.gnss)c.fill();else c.stroke();hits.push({...q,kind:'point',point:p});
        }
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
      if(meta.max_altitude_ft!=null){const highest=project([0,0,state.view==='space'?Math.max(...points.map(p=>p.up),1000)/range*heightScale:1.06]);c.globalAlpha=1;c.fillStyle='#b9d9ff';c.textAlign='center';c.font='600 15px system-ui';c.fillText('MAX ALT '+meta.max_altitude_ft.toLocaleString()+' ft · '+(meta.max_altitude_ft*.0003048).toFixed(2)+' km',cx,Math.max(45,highest.y-35));c.font='12px system-ui';c.fillText(meta.max_altitude_source+' · '+meta.max_altitude_aircraft+' · not necessarily overhead',cx,Math.max(63,highest.y-17));}
      c.globalAlpha=1;const origin=project([0,0,0]);c.fillStyle=colours.text;c.beginPath();c.arc(origin.x,origin.y,3,0,Math.PI*2);c.fill();if(state.view==='space'||state.tilt<82)label('Receiver',[0,0,-.08],.9);
      c.textAlign='left';c.textBaseline='top';c.fillStyle=colours.text;c.globalAlpha=.8;c.fillText(state.view==='space'?(heightScale>1?'HEIGHT EXPANDED ×'+heightScale+' · distances unchanged':'True scale · equal horizontal / vertical'):(width<480?'Dome · compass / elevation':'Azimuth / elevation · distance projected onto dome'),12,12);c.globalAlpha=1;}
      // Present only complete frames. Pulse frames reuse the finished base image.
      if(canvas.width!==pixelWidth||canvas.height!==pixelHeight){canvas.width=pixelWidth;canvas.height=pixelHeight;}
      display.setTransform(1,0,0,1,0,0);display.globalAlpha=1;display.drawImage(surface,0,0);display.setTransform(dpr,0,0,dpr,0,0);
      const pulse=clamp((pulseUntil-performance.now())/800,0,1);
      if(pulse>0){display.strokeStyle='#b1ffdb';display.globalAlpha=pulse;display.lineWidth=1.8;display.beginPath();
        for(const p of points.filter(p=>p.fresh).slice(-256)){if(p.el<0&&state.view!=='space')continue;const q=project(world(p));display.moveTo(q.x+7,q.y);display.arc(q.x,q.y,7,0,Math.PI*2);}display.stroke();display.globalAlpha=1;
        clearTimeout(pulseTimer);pulseTimer=setTimeout(schedule,100);
      }
      canvas.dataset.renderMs=(performance.now()-started).toFixed(2);canvas.dataset.sceneRevision=String(sceneRevision);canvas.dataset.positions=String(points.length);
    }
    function schedule(){if(!frame)frame=requestAnimationFrame(draw);}
    function selectAt(x,y,pin=false){
      const candidates=hits.map(h=>({...h,d:Math.hypot(h.x-x,h.y-y)})).filter(h=>h.d<18).sort((a,b)=>a.d-b.d||b.depth-a.depth);const observed=candidates.find(h=>(h.kind!=='cell'||h.cell.points)&&h.d<9),near=observed||candidates[0]||(state.view==='cells'?allCells.map(cell=>({...project(cell.center),kind:'cell',cell,d:0})).map(h=>({...h,d:Math.hypot(h.x-x,h.y-y)})).filter(h=>h.d<18).sort((a,b)=>a.d-b.d||b.depth-a.depth)[0]:null);if(!near)return;
      if(pin)pinned=true;let text='';
      if(near.kind==='point'){
        const p=near.point;text=p.aircraft.label+' · '+p.aircraft.hex.toUpperCase()+' · '+p.az.toFixed(1)+'° az / '+p.el.toFixed(1)+'° el · '+(p.distance/1000).toFixed(1)+' km horizontal · '+p.alt.toLocaleString()+' ft '+(p.gnss?'GNSS':'barometric ≈')+' · '+(p.rssi==null?'—':p.rssi.toFixed(1))+' dBFS · '+fmtTime(p.time)+' local';
      }else if(near.kind==='gap')text=near.segment.a.aircraft.label+' · '+near.segment.dt.toFixed(0)+' s between retained positions · dashed connector is inferred; no reception or obstruction is proven along it.';
      else{
        const cell=near.cell;text=cell.az+'–'+(cell.az+4)+'° az / '+cell.el+'–'+(cell.el+2)+'° elevation';
        if(cell.points){text+=' · '+(cell.count||cell.points.length)+' received positions · '+cell.aircraft+' aircraft · '+(cell.level==null?'—':cell.level.toFixed(1))+' dBFS · max '+((cell.maxDistance||Math.max(...cell.points.map(p=>p.distance)))/1000).toFixed(1)+' km horizontal';}
        else text+=' · no retained observations · obstruction status unknown';
      }
      $('detail').textContent=text;
    }
    for(const k of ['view','aircraft','colour'])$(k).addEventListener('change',()=>{if(k==='view'&&state.view!==$(k).value)state.tilt=$(k).value==='space'?25:55;state[k]=$(k).value;geometry(true);sync();schedule();save();});
    $('space-scale').addEventListener('change',()=>{state.spaceScale=$('space-scale').value;geometry();sync();schedule();save();});
    for(const k of ['yaw','tilt']){$(k).addEventListener('input',()=>{state[k]=Number($(k).value);sync();schedule();});$(k).addEventListener('change',save);}
    $('height').addEventListener('change',async()=>{try{const r=await fetch('/api/state'),auth=await r.json();const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':auth.control_token},body:JSON.stringify({action:'coverage_height',height_m:$('height').value===''?null:Number($('height').value)})});if(!response.ok)throw Error((await response.json()).error);reload();}catch(e){$('detail').textContent=e.message;}});
    $('gaps').addEventListener('change',()=>{state.gaps=$('gaps').checked;sync();schedule();save();});
    canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw:state.yaw,tilt:state.tilt,moved:false};pinned=false;canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{const b=canvas.getBoundingClientRect();if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){state.yaw=(drag.yaw+dx*.35+360)%360;state.tilt=clamp(drag.tilt+dy*.25,8,90);sync();schedule();}}else if(!pinned)selectAt(e.clientX-b.left,e.clientY-b.top);});
    canvas.addEventListener('pointerup',e=>{if(!drag)return;const moved=drag.moved;drag=null;if(moved){save();schedule();}else{const b=canvas.getBoundingClientRect();selectAt(e.clientX-b.left,e.clientY-b.top,true);}canvas.releasePointerCapture(e.pointerId);});
    canvas.addEventListener('pointercancel',()=>{drag=null;schedule();});
    new ResizeObserver(schedule).observe(canvas.parentElement);
    metadata();geometry();sync();schedule();for(const control of root.querySelectorAll('select,input'))control.disabled=false;
    return next=>{if(next.status==='LOADING')return;const resetSelection=coverageScope(data)!==coverageScope(next);freshKeys=newCoveragePoints(data,next);data=next;meta=data.meta;state.height=meta.reference_height_m||0;range=rangeFor();metadata();geometry(resetSelection);pulseUntil=freshKeys.size?performance.now()+800:0;sync();schedule();};
}
