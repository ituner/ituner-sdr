/* Offline frequency allocation lookup. Kept pure for boundary/coverage checks. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.SpectrumBands=factory();})(typeof window==='object'?window:this,function(){
 'use strict';
 function lookup(data,region,frequency){
  if(!Number.isFinite(frequency)||!Array.isArray(data?.[region]))return [];
  // Half-open intervals: a boundary belongs to the new band. Keep all overlapping
  // federal/non-federal entries instead of hiding shared or secondary services.
  return data[region].filter(row=>frequency>=row.low&&frequency<row.high);
 }
 function range(low,high){return (low/1e6).toFixed(6).replace(/\.?0+$/,'')+'–'+(high/1e6).toFixed(6).replace(/\.?0+$/,'')+' MHz';}
 function describe(rows,frequency){
  const services=new Map(),applications=new Set(),references=new Set();
  for(const row of rows){
   for(const service of row.services){
    const key=service.name.toLowerCase();let item=services.get(key);
    if(!item){item={name:service.name,primary:false,secondary:false,audiences:new Set()};services.set(key,item);}
    item[service.priority]=true;if(row.audience)item.audiences.add(row.audience);
    for(const note of service.references||[])references.add(note);
   }
   for(const app of row.applications||[])if(!app.ranges?.length||app.ranges.some(([low,high])=>frequency>=low&&frequency<high))applications.add(app.name);
   for(const note of row.references||[])references.add(note);
  }
  return {services:[...services.values()].map(s=>({name:s.name,priority:s.primary&&s.secondary?'primary / secondary by user class':s.primary?'primary':'secondary',audiences:[...s.audiences]})),applications:[...applications],references:[...references].sort(),ranges:[...new Set(rows.map(r=>range(r.low,r.high)))]};
 }
 return {lookup,describe,range};
});
