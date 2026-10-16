// Browser counterpart of globe_gpu.py: same sphere axes, orthographic camera,
// Blue Marble imagery, country rings and globe_tiles.py HD tile selection/cache.
const RAD = Math.PI / 180;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const TRAIL_RETENTION = 86400;
export function startupNoticeVisible(state,now=Date.now()/1000){return Boolean(state?.enabled&&Number.isFinite(state.started_at)&&now-state.started_at>=0&&now-state.started_at<5);}
export function receptionSummary(state,now=Date.now()/1000){
  const age=stamp=>{if(!Number.isFinite(stamp))return 'none';const seconds=Math.max(0,Math.floor(now-stamp));return seconds<1?'now':seconds<60?seconds+'s ago':seconds<3600?Math.floor(seconds/60)+'m ago':Math.floor(seconds/3600)+'h ago';};
  return 'Last message: '+age(state.last_message_at)+' · Last position: '+age(state.last_position_at);
}
export function compactTrail(points, now=Date.now()/1000) {
  const valid=points.filter(p=>Number.isFinite(p.time)&&p.time>=now-TRAIL_RETENTION&&p.time<=now&&Number.isFinite(p.lat)&&Math.abs(p.lat)<=90&&Number.isFinite(p.lon)&&Math.abs(p.lon)<=180);
  const result=[];
  for(let i=0;i<valid.length;i++){
    const p=valid[i],previous=valid[i-1],next=valid[i+1];
    if(!result.length||p.time>=now-1800||p.time-result.at(-1).time>=60||!next||(previous&&p.time-previous.time>120)||(next&&next.time-p.time>120))result.push(p);
  }
  return result.slice(-2048);
}
export class ADSBGlobe {
  constructor(host, onSelect, onError, storageKey='ituner-adsb-globe') {
    this.storageKey=storageKey;
    this.host=host; this.onSelect=onSelect; this.onError=onError;
    this.yaw=25*RAD; this.pitch=45*RAD; this.scale=5; this.radiusFactor=.92; this.dragGain=1;
    this.style='both'; this.following=false; this.labels=true; this.rings=false; this.trailSeconds=900; this.site=null; this.planes=[]; this.selected=null; this.centered=false;
    this.tiles=new Map(); this.traces=new Map(); this.wanted=[]; this.pending=new Set();
    this.canvas=document.createElement('canvas'); this.canvas.setAttribute('aria-label','GLOBE satellite map');
    this.overlay=document.createElement('canvas'); this.overlay.setAttribute('aria-hidden','true');
    host.prepend(this.canvas,this.overlay); this.ctx=this.overlay.getContext('2d');
    this.gl=this.canvas.getContext('webgl',{alpha:false,antialias:true});
    if(!this.gl) {onError('This browser cannot open the GPU globe. Logs and receiver controls are still available.');return;}
    this.initGL(); this.base=this.mesh([-180,-90,180,90],120,60);
    this.loadTexture('/globe/earth.jpg').then(t=>{this.earth=t;this.render();}).catch(()=>onError('Could not load GLOBE satellite imagery.'));
    fetch('/globe/countries.json').then(r=>{if(!r.ok)throw Error();return r.json();}).then(c=>{this.countries=c;this.borders=this.borderMesh(c);this.render();}).catch(()=>onError('Country outlines are unavailable.'));
    try { const s=JSON.parse(localStorage.getItem(this.storageKey));
      if(s && [s.yaw,s.pitch,s.scale].every(Number.isFinite)) {this.yaw=s.yaw;this.pitch=clamp(s.pitch,-82*RAD,82*RAD);this.scale=clamp(s.scale,.55,120);this.centered=true;}
    } catch {}
    this.bind(); this.observer=new ResizeObserver(()=>{this.resize();this.requestTiles();});this.observer.observe(host);
    this.resize(); this.requestTiles();
  }
  initGL() {
    const gl=this.gl;
    const vs=`attribute vec3 aPosition;attribute vec2 aUV;uniform vec3 uRight,uUp,uDepth,uSun;uniform vec2 uViewport;uniform float uRadius;varying vec2 vUV;varying float vDepth,vLight;void main(){vUV=aUV;vDepth=dot(aPosition,uDepth);vLight=dot(aPosition,uSun);gl_Position=vec4(dot(aPosition,uRight)*uRadius*2.0/uViewport.x,dot(aPosition,uUp)*uRadius*2.0/uViewport.y,0.0,1.0);}`;
    const fs=`precision mediump float;varying vec2 vUV;varying float vDepth,vLight;uniform sampler2D uTexture;uniform bool uImage;uniform vec4 uColor;void main(){if(vDepth<0.0)discard;if(!uImage){gl_FragColor=uColor;return;}float light=clamp((vLight+0.16)/0.34,0.0,1.0);light=light*light*(3.0-2.0*light);float twilight=exp(-pow((vLight-0.025)/0.115,2.0));vec3 shade=vec3(0.16+0.84*light+0.15*twilight,0.22+0.78*light+0.06*twilight,0.41+0.59*light);gl_FragColor=vec4(texture2D(uTexture,vUV).rgb*shade,1.0);}`;
    const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
    this.program=gl.createProgram();gl.attachShader(this.program,shader(gl.VERTEX_SHADER,vs));gl.attachShader(this.program,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(this.program);
    if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error('Could not link globe renderer');
    gl.useProgram(this.program); this.uniform={};
    for(const name of ['Right','Up','Depth','Sun','Viewport','Radius','Texture','Image','Color'])this.uniform[name]=gl.getUniformLocation(this.program,'u'+name);
    this.position=gl.getAttribLocation(this.program,'aPosition');this.uv=gl.getAttribLocation(this.program,'aUV');
    gl.enableVertexAttribArray(this.position);gl.enableVertexAttribArray(this.uv);
  }
  vertex(lon,lat,u=0,v=0) {const la=lat*RAD,lo=lon*RAD,c=Math.cos(la);return[c*Math.sin(lo),Math.sin(la),c*Math.cos(lo),u,v];}
  buffer(vertices,mode) {const gl=this.gl,b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);return{buffer:b,count:vertices.length/5,mode};}
  mesh(bounds,cols=12,rows=12) {
    const [w,s,e,n]=bounds,vertices=[];
    for(let row=0;row<rows;row++)for(let col=0;col<cols;col++) {
      const p=(x,y)=>this.vertex(w+(e-w)*x/cols,n+(s-n)*y/rows,x/cols,y/rows);
      const a=p(col,row),b=p(col+1,row),c=p(col+1,row+1),d=p(col,row+1);
      vertices.push(...a,...b,...c,...a,...c,...d);
    }
    return this.buffer(vertices,this.gl.TRIANGLES);
  }
  borderMesh(countries) {
    const vertices=[];
    for(const country of countries)for(const ring of country.rings)for(let i=1;i<ring.length;i++)
      vertices.push(...this.vertex(ring[i-1][1],ring[i-1][0]),...this.vertex(ring[i][1],ring[i][0]));
    return this.buffer(vertices,this.gl.LINES);
  }
  loadTexture(url) {
    return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>{
      const gl=this.gl,texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,image);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);resolve(texture);
    };image.onerror=reject;image.src=url;});
  }
  radius(){return Math.min(this.width,this.height)*this.radiusFactor*this.scale;}
  project(p) {
    const lat=p.lat*RAD,delta=p.lon*RAD-this.yaw,sl=Math.sin(lat),cl=Math.cos(lat),sp=Math.sin(this.pitch),cp=Math.cos(this.pitch);
    const depth=sp*sl+cp*cl*Math.cos(delta);if(depth<0)return null;
    return[this.width/2+cl*Math.sin(delta)*this.radius(),this.height/2-(cp*sl-sp*cl*Math.cos(delta))*this.radius()];
  }
  resize(){const rect=this.host.getBoundingClientRect();this.width=Math.max(1,rect.width);this.height=Math.max(1,rect.height);const dpr=Math.min(devicePixelRatio||1,2);for(const c of [this.canvas,this.overlay]){c.width=Math.round(this.width*dpr);c.height=Math.round(this.height*dpr);}this.ctx.setTransform(dpr,0,0,dpr,0,0);this.render();}
  save(){try{localStorage.setItem(this.storageKey,JSON.stringify({yaw:this.yaw,pitch:this.pitch,scale:this.scale}));}catch{}}
  bind() {
    const points=new Map(); let origin=null,moved=false;
    const reset=()=>{const a=[...points.values()];origin={yaw:this.yaw,pitch:this.pitch,scale:this.scale,points:a};moved=false;};
    this.overlay.addEventListener('pointerdown',e=>{this.overlay.setPointerCapture(e.pointerId);points.set(e.pointerId,[e.clientX,e.clientY]);reset();});
    this.overlay.addEventListener('pointermove',e=>{if(!points.has(e.pointerId))return;points.set(e.pointerId,[e.clientX,e.clientY]);const a=[...points.values()];
      if(a.length===1&&origin.points.length===1){const dx=a[0][0]-origin.points[0][0],dy=a[0][1]-origin.points[0][1];if(Math.hypot(dx,dy)>5){moved=true;if(this.following){this.following=false;this.onFollowChange?.(false);}}this.yaw=((origin.yaw-this.dragGain*dx/this.radius()+Math.PI*3)%(Math.PI*2))-Math.PI;this.pitch=clamp(origin.pitch+this.dragGain*dy/this.radius(),-82*RAD,82*RAD);}
      else if(a.length===2&&origin.points.length===2){const distance=p=>Math.hypot(p[0][0]-p[1][0],p[0][1]-p[1][1]);this.scale=clamp(origin.scale*distance(a)/Math.max(1,distance(origin.points)),.55,120);moved=true;}
      this.render();
    });
    const end=e=>{if(!points.has(e.pointerId))return;const tap=points.size===1&&!moved;points.delete(e.pointerId);if(tap){const r=this.overlay.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const near=this.planes.filter(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15).map(p=>({p,point:this.project(p)})).filter(v=>v.point).map(v=>({p:v.p,d:Math.hypot(v.point[0]-x,v.point[1]-y)})).sort((a,b)=>a.d-b.d);if(near[0]?.d<32){this.selected=near[0].p.hex;this.onSelect(near[0].p);this.render();}}
      reset();this.save();this.requestTiles();};
    this.overlay.addEventListener('pointerup',end);this.overlay.addEventListener('pointercancel',e=>{points.delete(e.pointerId);reset();});
    this.overlay.addEventListener('wheel',e=>{e.preventDefault();this.zoom(Math.exp(-e.deltaY*.0015));},{passive:false});
  }
  zoom(factor){this.scale=clamp(this.scale*factor,.55,120);this.save();this.render();clearTimeout(this.tileTimer);this.tileTimer=setTimeout(()=>this.requestTiles(),150);}
  center(){const p=this.planes.find(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15);this.yaw=(p?.lon??25)*RAD;this.pitch=(p?.lat??45)*RAD;this.centered=Boolean(p);this.save();this.render();this.requestTiles();}
  setStyle(value){this.style=value;this.render();}
  locate(plane){if(!plane||!Number.isFinite(plane.lat)||!Number.isFinite(plane.lon))return;this.yaw=plane.lon*RAD;this.pitch=clamp(plane.lat*RAD,-82*RAD,82*RAD);this.centered=true;this.save();this.render();this.requestTiles();}
  followSelected(enabled){const plane=this.planes.find(p=>p.hex===this.selected&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15);if(enabled&&!plane)return;this.following=enabled;if(enabled)this.locate(plane);this.onFollowChange?.(enabled);}
  fitTraffic(){this.following=false;this.onFollowChange?.(false);const planes=this.planes.filter(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15);if(!planes.length){this.locate(this.site||{lat:45,lon:25});return;}
    this.yaw=Math.atan2(planes.reduce((v,p)=>v+Math.sin(p.lon*RAD),0),planes.reduce((v,p)=>v+Math.cos(p.lon*RAD),0));this.pitch=clamp(planes.reduce((v,p)=>v+p.lat,0)/planes.length*RAD,-82*RAD,82*RAD);
    let x=.02,y=.02;for(const p of planes){const lat=p.lat*RAD,delta=p.lon*RAD-this.yaw;x=Math.max(x,Math.abs(Math.cos(lat)*Math.sin(delta)));y=Math.max(y,Math.abs(Math.cos(this.pitch)*Math.sin(lat)-Math.sin(this.pitch)*Math.cos(lat)*Math.cos(delta)));}
    this.scale=clamp(Math.min(this.width*.38/(Math.min(this.width,this.height)*this.radiusFactor*x),this.height*.38/(Math.min(this.width,this.height)*this.radiusFactor*y)),.55,35);this.centered=true;this.save();this.render();this.requestTiles();}
  setTracks(tracks){this.traces.clear();for(const [key,rows] of Object.entries(tracks)){if(!Array.isArray(rows))continue;const points=compactTrail(rows);if(points.length)this.traces.set(key,{at:points.at(-1).time*1000,points});}this.render();}
  update(state){this.site=state.receiver_position||null;this.planes=state.aircraft||[];const now=Date.now();for(const [key,trace] of this.traces){trace.points=compactTrail(trace.points,now/1000);if(!trace.points.length)this.traces.delete(key);}
    for(const p of this.planes){if(!Number.isFinite(p.lat)||!Number.isFinite(p.lon)||p.seen_pos>=15)continue;let trace=this.traces.get(p.hex)||{at:0,points:[]};const positionTime=p.position_time??now/1000-(p.seen_pos||0);if(now-trace.at>=4500&&positionTime>(trace.points.at(-1)?.time||0)){trace.points.push({lat:p.lat,lon:p.lon,time:positionTime});trace.points=compactTrail(trace.points,now/1000);trace.at=now;this.traces.set(p.hex,trace);}}
    const target=this.planes.find(p=>p.hex===this.selected&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15);
    if(this.following&&target){this.yaw=target.lon*RAD;this.pitch=clamp(target.lat*RAD,-82*RAD,82*RAD);}
    if(!this.centered&&this.planes.some(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.seen_pos<15))this.center();
    if(this.selected){const plane=this.planes.find(p=>p.hex===this.selected);this.onSelect(plane||null);}
    this.render();this.requestTiles();
  }
  async requestTiles(){if(!this.gl||!this.width||this.tileBusy)return;this.tileBusy=true;try{
    const query=new URLSearchParams({yaw:this.yaw/RAD,pitch:this.pitch/RAD,scale:this.scale,width:Math.min(4096,this.width),height:Math.min(4096,this.height)});
    const r=await fetch('/api/globe/view?'+query);if(!r.ok)return;const data=await r.json();this.radiusFactor=data.radius_factor;this.dragGain=data.drag_gain;this.wanted=data.tiles.map(t=>t.id);
    for(const tile of data.tiles){if(this.tiles.has(tile.id)||this.pending.has(tile.id))continue;this.pending.add(tile.id);this.loadTexture(tile.url).then(texture=>{this.tiles.set(tile.id,{texture,mesh:this.mesh(tile.bounds)});this.pending.delete(tile.id);this.prune();this.render();}).catch(()=>this.pending.delete(tile.id));}
  }catch{}finally{this.tileBusy=false;}}
  prune(){for(const [key,tile] of this.tiles){if(this.tiles.size<=32)break;if(this.wanted.includes(key))continue;this.gl.deleteTexture(tile.texture);this.gl.deleteBuffer(tile.mesh.buffer);this.tiles.delete(key);}}
  draw(mesh,texture,color){if(!mesh)return;const gl=this.gl;gl.uniform1i(this.uniform.Image,texture?1:0);gl.uniform4fv(this.uniform.Color,color||[1,1,1,1]);if(texture)gl.bindTexture(gl.TEXTURE_2D,texture);gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);gl.vertexAttribPointer(this.position,3,gl.FLOAT,false,20,0);gl.vertexAttribPointer(this.uv,2,gl.FLOAT,false,20,12);gl.drawArrays(mesh.mode,0,mesh.count);}
  drawTrail(points,cutoff){const ctx=this.ctx;ctx.beginPath();let previous=null;for(const point of points){if(point.time<cutoff){previous=null;continue;}const q=this.project(point);if(!q){previous=null;continue;}if(previous&&point.time-previous.time<=120)ctx.lineTo(...q);else ctx.moveTo(...q);previous=point;}ctx.stroke();}
  render(){if(!this.gl||!this.width)return;const gl=this.gl;gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(.025,.06,.085,1);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(this.program);
    const sy=Math.sin(this.yaw),cy=Math.cos(this.yaw),sp=Math.sin(this.pitch),cp=Math.cos(this.pitch);
    gl.uniform3fv(this.uniform.Right,[cy,0,-sy]);gl.uniform3fv(this.uniform.Up,[-sp*sy,cp,-sp*cy]);gl.uniform3fv(this.uniform.Depth,[cp*sy,sp,cp*cy]);
    const now=new Date(),utc=(now.getUTCHours()+now.getUTCMinutes()/60)/24;const day=(now-Date.UTC(now.getUTCFullYear(),0,0))/86400000;const sunLon=(.5-utc)*2*Math.PI,sunLat=23.44*RAD*Math.sin(2*Math.PI*(day-80)/365.25);
    gl.uniform3fv(this.uniform.Sun,[Math.cos(sunLat)*Math.sin(sunLon),Math.sin(sunLat),Math.cos(sunLat)*Math.cos(sunLon)]);gl.uniform2fv(this.uniform.Viewport,[this.width,this.height]);gl.uniform1f(this.uniform.Radius,this.radius());gl.uniform1i(this.uniform.Texture,0);
    this.draw(this.base,this.style!=='borders'?this.earth:null,[.055,.15,.18,1]);
    if(this.style!=='borders')for(const key of this.wanted){const tile=this.tiles.get(key);if(tile)this.draw(tile.mesh,tile.texture);}
    if(this.style!=='satellite')this.draw(this.borders,null,[.62,.75,.71,1]);
    const ctx=this.ctx;ctx.clearRect(0,0,this.width,this.height);ctx.font='12px system-ui';ctx.lineJoin='round';
    const scaleLabel=document.querySelector('#scale-bar b'),scaleLine=document.querySelector('#scale-bar span');
    if(scaleLabel&&scaleLine){const maxDistance=Math.asin(Math.min(.95,110/this.radius()))*3440.065;const distances=[1,2,5,10,20,50,100,200,500,1000,2000];const distance=distances.filter(n=>n<=maxDistance).pop()||1;scaleLabel.textContent=distance+' NM';scaleLine.style.width=(Math.sin(distance/3440.065)*this.radius())+'px';}
    const viewStatus=document.querySelector('#view-status');if(viewStatus)viewStatus.textContent='NORTH UP · '+(this.style==='borders'?'BORDERS':'GLOBE')+' · '+this.scale.toFixed(1)+'×';
    if(this.rings&&this.site){ctx.strokeStyle='#7eacc199';ctx.lineWidth=1;ctx.setLineDash([4,5]);for(const distance of [50,100,200]){const angular=distance/3440.065,lat=this.site.lat*RAD,lon=this.site.lon*RAD;ctx.beginPath();let previous=false;for(let angle=0;angle<=360;angle+=3){const bearing=angle*RAD,la=Math.asin(Math.sin(lat)*Math.cos(angular)+Math.cos(lat)*Math.sin(angular)*Math.cos(bearing));const lo=lon+Math.atan2(Math.sin(bearing)*Math.sin(angular)*Math.cos(lat),Math.cos(angular)-Math.sin(lat)*Math.sin(la));const q=this.project({lat:la/RAD,lon:lo/RAD});if(!q){previous=false;continue;}previous?ctx.lineTo(...q):ctx.moveTo(...q);previous=true;}ctx.stroke();}ctx.setLineDash([]);const site=this.project(this.site);if(site){ctx.strokeStyle='#d2dce5';ctx.strokeRect(site[0]-4,site[1]-4,8,8);ctx.fillStyle='#cbd8e4';ctx.fillText('RX SITE',site[0]+10,site[1]+4);}}
    const trailCutoff=Date.now()/1000-this.trailSeconds;
    if(this.trailSeconds>0)for(const [key,trace] of this.traces){ctx.strokeStyle=key===this.selected?'#ffd267':'#65e3d260';ctx.lineWidth=key===this.selected?1.6:1;this.drawTrail(trace.points,trailCutoff);}
    for(const plane of this.planes){if(!Number.isFinite(plane.lat)||!Number.isFinite(plane.lon)||plane.seen_pos>=15)continue;const p=this.project(plane);if(!p||p[0]<-20||p[0]>this.width+20||p[1]<-20||p[1]>this.height+20)continue;const selected=plane.hex===this.selected,color=selected?'#ffd267':Number(plane.alt_baro)>20000?'#78b8ff':'#65e3d2';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.6;
      ctx.save();ctx.translate(...p);ctx.rotate((plane.track||0)*RAD);ctx.beginPath();if(plane.kind==='ship'){ctx.moveTo(0,-12);ctx.lineTo(6,-3);ctx.lineTo(6,9);ctx.lineTo(-6,9);ctx.lineTo(-6,-3);ctx.closePath();}else if(plane.kind==='station'){ctx.arc(0,0,5,0,Math.PI*2);ctx.moveTo(-9,0);ctx.lineTo(9,0);ctx.moveTo(0,-9);ctx.lineTo(0,9);}else if(plane.kind==='balloon'){ctx.arc(0,-3,7,0,Math.PI*2);ctx.moveTo(0,4);ctx.lineTo(0,12);}else{ctx.moveTo(0,-11);ctx.lineTo(0,10);ctx.moveTo(-10,3);ctx.lineTo(0,-4);ctx.lineTo(10,3);ctx.moveTo(-5,9);ctx.lineTo(0,6);ctx.lineTo(5,9);}ctx.stroke();ctx.restore();
      if(!this.labels&&!selected)continue;ctx.strokeStyle='#07131d';ctx.lineWidth=3;const label=(plane.flight||plane.hex).trim();ctx.strokeText(label,p[0]+14,p[1]-10);ctx.fillText(label,p[0]+14,p[1]-10);
    }
  }
}
