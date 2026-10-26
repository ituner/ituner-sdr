'use strict';
const express=require('express');
const receiver=require('./rtl433proc');
const {DecoderActivity,allowActivityOrigin}=require('./activity.cjs');
const activity=new DecoderActivity();
activity.poll();
process.on('exit',()=>activity.close());
module.exports=function install(app){
  app.use('/api',(req,res,next)=>{
    const origin=req.headers.origin;
    if(!['GET','HEAD','OPTIONS'].includes(req.method)&&origin){
      try{if(new URL(origin).host!==req.headers.host)return res.status(403).json({error:'Open this dashboard directly before changing receiver settings.'});}
      catch{return res.status(403).json({error:'Invalid request origin.'});}
    }
    next();
  });
  const json=express.json({limit:'8kb'});
  const action=fn=>async(req,res)=>{try{await fn(req);res.json({ok:true});}catch(e){res.status(400).json({error:e.message});}};
  app.get('/api/ituner/activity',async(req,res)=>{
    if(allowActivityOrigin(req.headers.origin,req.headers.host)){res.setHeader('Access-Control-Allow-Origin',req.headers.origin);res.setHeader('Vary','Origin');}
    res.setHeader('Cache-Control','no-store');res.json(activity.snapshot());
  });
  app.get('/api/ituner/receiver',(_req,res)=>res.json(receiver.getReceiver()));
  app.post('/api/ituner/receiver',json,action(req=>receiver.configure(req.body||{})));
  app.post('/api/ituner/scan/start',action(()=>receiver.startScan()));
  app.post('/api/ituner/scan/stop',action(()=>receiver.stopScan()));
  app.get('/api/rtl433/status',(_req,res)=>res.json(receiver.getStatus()));
  app.get('/api/rtl433/config',(_req,res)=>res.type('text/plain').send(receiver.readConfig()));
  app.post('/api/rtl433/config',express.text({type:'*/*',limit:'8kb'}),action(req=>receiver.writeConfig(req.body)));
  app.post('/api/frequency',json,action(req=>receiver.setFrequency(req.body?.frequency)));
  for(const name of ['start','stop','restart'])app.post('/api/rtl433/'+name,action(()=>receiver[name]()));
};

// Retain real device timestamps across UI restarts; raw observations remain in
// the existing iTuner JSONL log. This display checkpoint never starts a radio.
const fs=require('node:fs'),path=require('node:path'),store=require('./store');
const devicesFile=process.env.DEVICES_FILE||'/var/lib/ituner-rtl433-ui/devices.json';
try{
  const saved=JSON.parse(fs.readFileSync(devicesFile,'utf8'));
  if(Array.isArray(saved))for(const dev of saved.slice(-512)){
    if(typeof dev.model!=='string'||typeof dev.id!=='string'||!dev.fields||!Number.isFinite(dev.lastSeen))continue;
    const restored=store.updateDevice({model:dev.model,id:dev.id});
    Object.assign(restored,dev);
  }
}catch{}
function saveDevices(){
  try{
    const devices=store.getDevices().sort((a,b)=>b.lastSeen-a.lastSeen);
    for(const dev of devices.slice(512))store.forgetDevice(dev.model,dev.id);
    fs.mkdirSync(path.dirname(devicesFile),{recursive:true});
    fs.writeFileSync(devicesFile+'.tmp',JSON.stringify(devices.slice(0,512)),{mode:0o600});fs.renameSync(devicesFile+'.tmp',devicesFile);
  }catch(e){console.error('[iTuner] Device checkpoint: '+e.message);}
}
setInterval(saveDevices,30000).unref();process.on('exit',()=>{saveDevices();receiver.close();});
process.on('SIGTERM',()=>process.exit(0));
