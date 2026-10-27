// Shared compact receiver choices. Never changes assignments until the decoder's own action.
(()=>{
 const managementURL=new URL('/usb-radios',document.currentScript?.src||location.href).href;
 const labels={adsb:'ADS-B · 1090 ES',uat:'ADS-B · 978 UAT',spectrum:'Spectrum Analyzer',ism:'rtl_433 sensors',ais:'AIS',aprs:'APRS',meteor:'Meteor-M',cubesat:'CubeSat',sonde:'Radiosonde','dongle-maintenance':'USB ID update'};
 const ownerName=o=>!o?'Available':o.startsWith('adsb-compare:')?'ADS-B comparison':/^ism[:-]/.test(o)?'rtl_433 sensors':labels[o]||o.replaceAll('_',' ').replaceAll('-',' ');
 const name=d=>d.nickname||d.product||(d.label||d.name||'RTL-SDR').split(' · USB ')[0];
 function fill(select,devices,{leases={},owner='',selection=select.value||'auto',unique=true,blocked=[],auto='Auto · available radio'}={}){
  if(document.activeElement===select)return;
  const rows=[{id:'auto',text:auto,disabled:false},...devices.map(d=>{
   let status=leases[d.id]===owner?'Selected':leases[d.id]?'In use · '+ownerName(leases[d.id]):'Available';
   if(unique&&!d.persistent)status=d.duplicate?'Assign a unique ID':'Identity needs checking';
   if(d.eeprom?.status==='verified'&&d.eeprom.serial&&d.eeprom.serial!==d.serial)status='Reconnect to load new ID';
   return {id:d.id,text:name(d)+' · '+(d.serial||'Unreadable ID')+' · '+status,disabled:(unique&&!d.persistent)||blocked.includes(d.id)};
  })];
  if(selection!=='auto'&&!rows.some(d=>d.id===selection))rows.push({id:selection,text:'Assigned radio · disconnected',disabled:false});
  const signature=JSON.stringify(rows);
  if(select.dataset.usbChoices!==signature){select.replaceChildren(...rows.map(d=>{const o=document.createElement('option');o.value=d.id;o.textContent=d.text;o.disabled=d.disabled;return o;}));select.dataset.usbChoices=signature;}
  select.value=selection;
  if(!select.dataset.usbManagement){
   const link=document.createElement('a');link.className='usb-radio-manage';link.textContent='USB-Radios ↗';link.href=managementURL;
   const target=select.closest('label')||select;target.after(link);select.dataset.usbManagement='1';
  }
 }
 window.USB_Radios={fill,name,ownerName};
})();
