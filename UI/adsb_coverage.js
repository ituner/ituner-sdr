// Shared real-history reception view. No external aircraft feeds.
export function mountCoverage(root){
  let update=null,busy=false,last='';
  async function reload(){
    if(root.hidden||busy)return;busy=true;
    try{const r=await fetch('/api/coverage');if(!r.ok)throw Error('Coverage unavailable');const body=await r.text(),data=JSON.parse(body);
      if(data.error)throw Error(data.error);
      if(data.status==='LOADING'){root.querySelector('[data-summary]').textContent='Loading retained reception history…';return;}
      if(body!==last){if(update)update(data);else update=setup(root,data,reload);last=body;}
    }catch(e){root.querySelector('[data-summary]').textContent='Coverage: '+e.message+' · retrying';}finally{busy=false;}
  }
  setInterval(reload,5000);return reload;
}
function setup(root,initial,reload){

    const $=name=>root.querySelector('[data-'+name+']'),canvas=root.querySelector('canvas'),c=canvas.getContext('2d');
    let data=initial,meta=data.meta;const rad=Math.PI/180;
    const fmtTime=t=>new Date(t*1000).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
    let state={view:'cells',aircraft:'all',colour:'visits',yaw:0,tilt:65,height:0,gaps:false},points=[],cells=[],segments=[],allCells=[],hits=[],drag=null,pinned=false,width=0,height=0,scale=1,cx=0,cy=0,colours={},frame=0;
    const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),median=a=>{const v=a.filter(Number.isFinite).sort((x,y)=>x-y);if(!v.length)return null;return v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2;};
    try{state={...state,...JSON.parse(localStorage.getItem("adsb-coverage-view")||"{}")};}catch{}
    state.height=meta.reference_height_m||0;
    state.yaw=clamp(Number(state.yaw)||0,0,360);state.tilt=clamp(Number(state.tilt)||65,8,90);state.height=clamp(Number(state.height)||0,-500,9000);
    if(!['cells','trails','space'].includes(state.view))state.view='cells';if(!['visits','signal'].includes(state.colour))state.colour='visits';
    function metadata(){
      $('receiver-state').textContent=' · '+(data.receiver_enabled?'ADS-B '+data.receiver_status:'ADS-B paused')+' · HISTORY';
      const selected=state.aircraft;$('aircraft').replaceChildren(new Option('All positioned aircraft','all'));
      for(const a of data.aircraft)$('aircraft').append(new Option(a.label+(a.label===a.hex?'':' · '+a.hex.toUpperCase()),a.hex));
      state.aircraft=selected==='all'||data.aircraft.some(a=>a.hex===selected)?selected:'all';
      $('summary').textContent=meta.retained_positions+' positions · '+meta.positioned_aircraft+' aircraft'+(meta.first_position?' · '+fmtTime(meta.first_position)+' – '+fmtTime(meta.last_position):'')+(meta.excluded_other_sites?' · '+meta.excluded_other_sites+' positions from other sites excluded':'');
      $('reference').textContent=meta.reference?'Site '+meta.reference.lat.toFixed(5)+'°, '+meta.reference.lon.toFixed(5)+'° · '+(meta.reference_height_known?'antenna ellipsoid height set':'height unknown; 0 m assumed'):'Set antenna latitude / longitude in Receiver to build the dome.';
      $('method').textContent='Blue = directly received positions; grey = unobserved, not confirmed obstruction. Retains up to 90 days / 250,000 positions. Coverage includes reception within 100 m of the current antenna site; other sites remain stored separately. All cells and statistics use complete retained history; dots are thinned above 20,000. GNSS altitude preferred (above WGS84 ellipsoid); open circles use approximate barometric altitude. RSSI is readsb aircraft average, not calibrated gain. Cells: 4° azimuth × 2° elevation. Trails join observations ≤15 s apart; intervening reception is unknown. ADS-B may have been paused during this interval. Radius is furthest horizontal position; diameter = twice that radius, not continuous circular coverage.';
      const r=meta.horizontal_range_max_km||0,alt=meta.max_altitude_ft;
      $('readouts').replaceChildren(...[['RX RADIUS',r.toFixed(2)+' km'],['DIAMETER · 2 × R',(2*r).toFixed(2)+' km'],['MAX SLANT RANGE',(meta.slant_range_max_km||0).toFixed(2)+' km'],['HIGHEST RECEIVED',alt==null?'—':alt.toLocaleString()+' ft / '+(alt*.0003048).toFixed(2)+' km']].map(([label,value])=>{const item=document.createElement('div'),small=document.createElement('small'),b=document.createElement('b');small.textContent=label;b.textContent=value;item.append(small,b);return item;}));
      if(document.activeElement!==$('height'))$('height').value=meta.reference_height_known?meta.reference_height_m:'';
    }
    function save(){try{localStorage.setItem("adsb-coverage-view",JSON.stringify(state));}catch{}}
    function sync(){for(const k of ['view','aircraft','colour','yaw','tilt'])$(k).value=state[k];$('gaps').checked=state.gaps;$('yaw-value').value=Math.round(state.yaw)+'°';$('tilt-value').value=Math.round(state.tilt)+'°';$('gap-legend').hidden=!state.gaps||state.view==='cells';$('colour-label').textContent=state.colour==='signal'?'Received · stronger signal is more opaque':'Received · brighter = more samples';}
    function vector(az,el,r=1){return [r*Math.sin(az*rad)*Math.cos(el*rad),r*Math.cos(az*rad)*Math.cos(el*rad),r*Math.sin(el*rad)];}
    function geometry(){
      points=data.points.filter(p=>state.aircraft==='all'||data.aircraft[p[1]].hex===state.aircraft).map((p,i)=>{
        const up=p[4]-state.height,horizontal=Math.hypot(p[2],p[3]),az=(Math.atan2(p[2],p[3])/rad+360)%360,el=Math.atan2(up,horizontal)/rad;
        return {id:i,time:data.base+p[0],aircraft:{...data.aircraft[p[1]],label:p[8]||data.aircraft[p[1]].label},east:p[2],north:p[3],up,alt:p[5],rssi:p[6],gnss:!!p[7],az,el,distance:horizontal,sky:vector(az,el)};
      });
      const buckets=new Map();for(const p of points){if(p.el<0||p.el>90)continue;const az=Math.floor(p.az/4)*4,el=Math.min(88,Math.floor(p.el/2)*2),key=az+':'+el;if(!buckets.has(key))buckets.set(key,{key,az,el,points:[]});buckets.get(key).points.push(p);}
      cells=[...buckets.values()];for(const cell of cells){cell.level=median(cell.points.map(p=>p.rssi));cell.aircraft=new Set(cell.points.map(p=>p.aircraft.hex)).size;cell.center=vector(cell.az+2,cell.el+1);}
      if(state.aircraft==='all'&&data.cells)for(const [az,el,count,level,aircraft,maxDistance] of data.cells){const key=az+':'+el,cell=buckets.get(key)||{key,az,el,points:[]};Object.assign(cell,{count,level,aircraft,maxDistance,center:vector(az+2,el+1)});buckets.set(key,cell);}cells=[...buckets.values()];
      allCells=[];for(let el=0;el<90;el+=2)for(let az=0;az<360;az+=4){const key=az+':'+el;allCells.push({az,el,center:vector(az+2,el+1),vertices:[vector(az+.22,el+.12),vector(az+3.78,el+.12),vector(az+3.78,el+1.88),vector(az+.22,el+1.88)],observed:buckets.get(key)});}
      segments=[];const tracks=new Map();for(const p of points){const last=tracks.get(p.aircraft.hex);if(last){const dt=p.time-last.time,moved=Math.hypot(p.east-last.east,p.north-last.north,p.up-last.up);if(dt>0&&dt<=120&&moved<=500+400*dt&&!data.breaks?.some(t=>last.time<t&&t<=p.time))segments.push({a:last,b:p,gap:dt>15,dt});}tracks.set(p.aircraft.hex,p);}
      pinned=false;$('detail').textContent=points.length+' retained positions · '+cells.length+' observed sky cells · '+new Set(points.map(p=>p.aircraft.hex)).size+' aircraft. Select a cell or dot.';
    }
    function project(v){const yaw=state.yaw*rad,tilt=state.tilt*rad,x=v[0]*Math.cos(yaw)-v[1]*Math.sin(yaw),y=v[0]*Math.sin(yaw)+v[1]*Math.cos(yaw);return {x:cx+x*scale,y:cy+(-y*Math.sin(tilt)-v[2]*Math.cos(tilt))*scale,depth:-y*Math.cos(tilt)+v[2]*Math.sin(tilt)};}
    function world(p){return state.view==='space'?[p.east/range,p.north/range,p.up/range]:p.sky;}
    const rangeFor=()=>Math.max(5000,Math.ceil(Math.max(meta.horizontal_range_max_km||0,(meta.max_altitude_ft||0)*.0003048)/5)*5000);let range=rangeFor();
    function path(vertices){c.beginPath();vertices.forEach((v,i)=>{const p=project(v);if(i)c.lineTo(p.x,p.y);else c.moveTo(p.x,p.y);});}
    function label(text,v,alpha=1){const p=project(v);c.globalAlpha=alpha;c.fillStyle=colours.text;c.textAlign='center';c.textBaseline='middle';c.fillText(text,clamp(p.x,30,width-30),clamp(p.y,14,height-14));}
    function intensity(level,count,maxCount){if(level==null)return .5;return state.colour==='signal'?.3+.7*clamp((level-meta.rssi_min)/(meta.rssi_max-meta.rssi_min||1),0,1):.55+.45*Math.log1p(count)/Math.log1p(maxCount);}
    function draw(){
      frame=0;width=canvas.clientWidth;if(!width)return;height=clamp(window.innerHeight-canvas.offsetTop-62,260,580);canvas.style.height=height+'px';const dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,width,height);
      colours={received:'#4c9dff',muted:'#98adbf',text:'#dcecff',gap:'#ffca78'};
      c.font=getComputedStyle($('summary')).font;const t=state.tilt*rad;scale=Math.min((width-88)/2,(height-84)/(1+Math.sin(t)));cx=width/2;cy=height/2+scale*(1-Math.sin(t))/2;hits=[];
      const ring=Array.from({length:121},(_,i)=>vector(i*3,0));path(ring);c.closePath();c.globalAlpha=.06;c.fillStyle=colours.muted;c.fill();
      if(state.view==='cells'){
        const maxCount=Math.max(1,...cells.map(cell=>cell.count||cell.points.length));
        for(const cell of allCells.map(cell=>({...cell,depth:project(cell.center).depth})).sort((a,b)=>a.depth-b.depth)){
          path(cell.vertices);c.closePath();c.fillStyle=cell.observed?colours.received:colours.muted;c.globalAlpha=cell.observed?intensity(cell.observed.level,cell.observed.count||cell.observed.points.length,maxCount):.045;c.fill();
          hits.push({...project(cell.center),kind:'cell',cell:cell.observed||cell});
        }
      }
      c.strokeStyle=colours.muted;c.lineWidth=1;c.globalAlpha=.24;
      const distanceRings=Array.from({length:Math.round(range/5000)},(_,i)=>(i+1)*5000/range);
      const rings=state.view==='space'?distanceRings:[0,15,30,45,60,75];
      for(const r of rings){const v=Array.from({length:121},(_,i)=>vector(i*3,state.view==='space'?0:r,state.view==='space'?r:1));path(v);c.stroke();}
      if(state.view!=='space')for(let az=0;az<360;az+=30){path(Array.from({length:31},(_,i)=>vector(az,i*3)));c.stroke();}
      else for(let az=0;az<360;az+=45){path([[0,0,0],vector(az,0)]);c.stroke();}
      if(state.view!=='cells'){
        const geometryToDraw=segments.filter(s=>!s.gap||state.gaps).map(s=>({...s,depth:(project(world(s.a)).depth+project(world(s.b)).depth)/2})).sort((a,b)=>a.depth-b.depth);
        for(const s of geometryToDraw){path([world(s.a),world(s.b)]);c.strokeStyle=s.gap?colours.gap:colours.received;c.globalAlpha=s.gap?.65:.4;c.lineWidth=s.gap?1:1.5;c.setLineDash(s.gap?[4,5]:[]);c.stroke();if(s.gap){const a=project(world(s.a)),b=project(world(s.b));hits.push({x:(a.x+b.x)/2,y:(a.y+b.y)/2,depth:s.depth,kind:'gap',segment:s});}}
        c.setLineDash([]);
        for(const p of [...points].sort((a,b)=>project(world(a)).depth-project(world(b)).depth)){
          const q=project(world(p));if(p.el<0&&state.view!=='space')continue;c.globalAlpha=intensity(p.rssi,1,1);c.fillStyle=colours.received;c.strokeStyle=colours.received;c.lineWidth=1.5;c.beginPath();c.arc(q.x,q.y,state.aircraft==='all'?2.5:3.5,0,Math.PI*2);if(p.gnss)c.fill();else c.stroke();hits.push({...q,kind:'point',point:p});
        }
      }
      c.globalAlpha=.55;c.strokeStyle=colours.muted;c.lineWidth=1.2;path(ring);c.stroke();
      for(const [name,az] of [['N',0],['E',90],['S',180],['W',270]])label(name,vector(az,0,1.11));
      if(state.view==='space'){
        for(const r of (width<480?distanceRings.filter((_,i)=>i%2===1||i===distanceRings.length-1):distanceRings))label((r*range/1000).toFixed(0)+' km',vector(95,0,r),.8);
        c.strokeStyle=colours.muted;c.globalAlpha=.5;path([[0,0,0],[0,0,Math.max(...points.map(p=>p.up),1000)/range]]);c.stroke();
        if(state.tilt<82)label('Up · '+(Math.max(...points.map(p=>p.up),1000)/1000).toFixed(1)+' km',[0,0,Math.max(...points.map(p=>p.up),1000)/range+.08],.9);
      }else{
        for(const el of (width<480?[30]:[30,60]))label(el+'°',vector(90,el),.85);label(state.tilt>=82?'Zenith · receiver':'Zenith · 90°',[0,0,1.06],.9);
      }
      if(meta.max_altitude_ft!=null){const highest=project([0,0,state.view==='space'?Math.max(...points.map(p=>p.up),1000)/range:1.06]);c.globalAlpha=1;c.fillStyle='#b9d9ff';c.textAlign='center';c.font='600 15px system-ui';c.fillText('MAX ALT '+meta.max_altitude_ft.toLocaleString()+' ft · '+(meta.max_altitude_ft*.0003048).toFixed(2)+' km',cx,Math.max(45,highest.y-35));c.font='12px system-ui';c.fillText(meta.max_altitude_source+' · '+meta.max_altitude_aircraft+' · not necessarily overhead',cx,Math.max(63,highest.y-17));}
      c.globalAlpha=1;const origin=project([0,0,0]);c.fillStyle=colours.text;c.beginPath();c.arc(origin.x,origin.y,3,0,Math.PI*2);c.fill();if(state.view==='space'||state.tilt<82)label('Receiver',[0,0,-.08],.9);
      c.textAlign='left';c.textBaseline='top';c.fillStyle=colours.text;c.globalAlpha=.8;c.fillText(state.view==='space'?(width<480?'Distance / height · true scale':'Horizontal distance / altitude · no vertical exaggeration'):(width<480?'Dome · compass / elevation':'Azimuth / elevation · distance projected onto dome'),12,12);c.globalAlpha=1;
    }
    function schedule(){if(!frame)frame=requestAnimationFrame(draw);}
    function selectAt(x,y,pin=false){
      const candidates=hits.map(h=>({...h,d:Math.hypot(h.x-x,h.y-y)})).filter(h=>h.d<18).sort((a,b)=>a.d-b.d||b.depth-a.depth);const observed=candidates.find(h=>(h.kind!=='cell'||h.cell.points)&&h.d<9),near=observed||candidates[0];if(!near)return;
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
    for(const k of ['view','aircraft','colour'])$(k).addEventListener('change',()=>{state[k]=$(k).value;geometry();sync();schedule();save();});
    for(const k of ['yaw','tilt']){$(k).addEventListener('input',()=>{state[k]=Number($(k).value);sync();schedule();});$(k).addEventListener('change',save);}
    $('height').addEventListener('change',async()=>{try{const r=await fetch('/api/state'),auth=await r.json();const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':auth.control_token},body:JSON.stringify({action:'coverage_height',height_m:$('height').value===''?null:Number($('height').value)})});if(!response.ok)throw Error((await response.json()).error);reload();}catch(e){$('detail').textContent=e.message;}});
    $('gaps').addEventListener('change',()=>{state.gaps=$('gaps').checked;sync();schedule();save();});
    canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw:state.yaw,tilt:state.tilt,moved:false};pinned=false;canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{const b=canvas.getBoundingClientRect();if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){state.yaw=(drag.yaw+dx*.35+360)%360;state.tilt=clamp(drag.tilt+dy*.25,8,90);sync();schedule();}}else if(!pinned)selectAt(e.clientX-b.left,e.clientY-b.top);});
    canvas.addEventListener('pointerup',e=>{if(!drag)return;const moved=drag.moved;drag=null;if(moved)save();else{const b=canvas.getBoundingClientRect();selectAt(e.clientX-b.left,e.clientY-b.top,true);}canvas.releasePointerCapture(e.pointerId);});
    canvas.addEventListener('pointercancel',()=>{drag=null;});
    new ResizeObserver(schedule).observe(canvas.parentElement);
    metadata();geometry();sync();schedule();for(const control of root.querySelectorAll('select,input'))control.disabled=false;
    return next=>{data=next;meta=data.meta;state.height=meta.reference_height_m||0;range=rangeFor();metadata();geometry();sync();schedule();};
}
