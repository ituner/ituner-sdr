const usbRadiosLink=document.getElementById('usb-radios');if(usbRadiosLink){const url=new URL('/usb-radios',location.href);url.port='8092';usbRadiosLink.href=url.href;}
const form=document.getElementById('station-form'),notice=document.getElementById('notice');let token='',dirty=false,busy=false;
const numeric=new Set(['latitude','longitude','elevation_m','antenna_height_m','ellipsoid_height_m','gps_height_offset_m']);
function render(data){const p=data.position,g=data.gps;token=data.control_token;
 document.getElementById('source').textContent=p?(p.source==='gps'?'GPS'+(p.stale?' · STALE / LAST KNOWN':' · AUTOMATIC'):'MANUAL ANTENNA LOCATION'):'LOCATION NOT SET';
 document.getElementById('position').textContent=p?`${p.lat.toFixed(6)}°, ${p.lon.toFixed(6)}°`:'Set coordinates or connect a GPS receiver';
 document.getElementById('locator').textContent=data.grid?`Grid ${data.grid} · antenna elevation ${p.altitude_msl_m==null?'unknown':p.altitude_msl_m.toFixed(1)+' m above sea level'} · WGS84 height ${p.ellipsoid_height_m==null?'unknown':p.ellipsoid_height_m.toFixed(1)+' m'}`:'';
 document.getElementById('gps-state').textContent=g.status;
 document.getElementById('gps-detail').textContent=[g.mode>=2?g.mode+'D fix':'No position fix',g.fix_age_s==null?'':`Last fix ${Math.floor(g.fix_age_s)}s ago`,g.accuracy_m==null?'':`±${g.accuracy_m.toFixed(1)} m`,g.satellites==null?'':`${g.used??'—'}/${g.satellites} satellites used`].filter(Boolean).join(' · ');
 document.getElementById('gps-devices').textContent=g.devices.length?g.devices.map(d=>d.path+(d.driver?' · '+d.driver:'')).join('\n'):'No GPS receiver detected. The saved location remains available.';
 if(!dirty)for(const [key,value] of Object.entries(data.config)){const input=form.elements.namedItem(key);if(!input)continue;if(input.type==='checkbox')input.checked=value;else input.value=value??'';}
}
async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/station');const data=await r.json();if(!r.ok)throw Error(data.error);render(data);}catch(e){notice.className='error';notice.textContent='Station connection: '+e.message+' · retrying';}finally{busy=false;}}
form.addEventListener('input',()=>dirty=true);
form.onsubmit=async e=>{e.preventDefault();const values={};for(const input of form.elements){if(!input.name)continue;values[input.name]=input.type==='checkbox'?input.checked:numeric.has(input.name)?input.value===''?null:Number(input.value):input.value;}
 const save=document.getElementById('save');save.disabled=true;notice.textContent='Saving…';notice.className='';try{const r=await fetch('/api/station',{method:'POST',headers:{'Content-Type':'application/json','X-Station-Token':token},body:JSON.stringify(values)}),data=await r.json();if(!r.ok)throw Error(data.error);dirty=false;render(data);notice.textContent='Saved. All local SDR applications now use this profile.';}catch(e){notice.className='error';notice.textContent=e.message;}finally{save.disabled=false;}};
refresh();setInterval(refresh,2000);
