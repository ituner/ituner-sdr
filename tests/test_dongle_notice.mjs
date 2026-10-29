import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.open=false;this.hidden=false;this.textContent='';this.dataset={};}
 append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}setAttribute(k,v){this[k]=v;}addEventListener(k,fn){this.listeners[k]=fn;}showModal(){this.open=true;this.modal=true;}show(){this.open=true;this.modal=false;}close(){this.open=false;}focus(){}scrollIntoView(){this.scrolled=true;}
}
const body=new Element('body'),intervals=new Map(),saved=new Map();let tick=100000,next=0,posts=[],gets=0,hold=null,unblock;
const document={body,hidden:false,activeElement:new Element('button'),createElement:t=>new Element(t),getElementById:id=>body.children.find(e=>e.id===id),addEventListener(){}};
const row={id:'serial:11',name:'Roof antenna',serial:'10000011',port:'3-1',conflict:false};let notice=null;
const sandbox={document,AbortSignal,Date:{now:()=>tick},sessionStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},setInterval(fn){const id=++next;intervals.set(id,fn);return id;},clearInterval(id){intervals.delete(id);},fetch:async(_url,options)=>{
 if(options?.method==='POST'){const data=JSON.parse(options.body);posts.push(data);if(data.action==='dismiss'||data.action==='choose')notice=null;return {ok:true};}
 gets++;if(hold)await hold;return {ok:true,json:async()=>({available:true,notice,receivers:[row],control_token:'token',checked_at:tick/1000})};
}};
vm.runInNewContext(fs.readFileSync(new URL('../UI/dongle-notice.js',import.meta.url),'utf8'),sandbox);
const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();
const dialog=document.getElementById('usb-detection-notice');const [check,cancel,yes]=dialog.children.at(-1).children;
async function advance(ms){tick+=ms;for(const fn of [...intervals.values()])fn();await settle();}
assert.equal(dialog.open,false,'Known receivers at boot stay quiet');
notice={id:'new:1',kind:'discovery',title:'New receiver',message:'Review or Later',receivers:[row]};await advance(1500);
assert.equal(dialog.modal,true);assert.equal(cancel.textContent,'Later');assert.equal(yes.textContent,'Review receivers');assert.equal(yes.hidden,false);
cancel.onclick();await settle();assert.equal(dialog.open,false);await advance(1500);assert.equal(dialog.open,false);
notice={id:'new:2',kind:'arrival',title:'USB receiver detected',message:'Choose later',receivers:[row]};await advance(1500);
assert.equal(dialog.open,true);assert.equal(dialog.modal,false,'Arrival never blocks the page');
await advance(14999);assert.equal(dialog.open,true);await advance(1);assert.equal(dialog.open,false);
notice={id:'new:3',kind:'select',title:'Choose receiver',message:'Start',receivers:[{...row,can_choose:true,state:'ready'}]};await advance(1500);
assert.equal(dialog.modal,true);assert.equal(yes.hidden,true);
const list=dialog.children[2];list.children[0].children.at(-1).onclick();assert.equal(yes.hidden,false);assert.equal(yes.textContent,'Use receiver');
await yes.onclick();await settle();assert.deepEqual(posts.at(-1),{action:'choose',event:'new:3',target:row.id});assert.equal(dialog.open,false);
notice={id:'new:4',kind:'conflict',title:'Receiver ID conflicts',message:'Choose Yes',target:'port:3-1',receivers:[{...row,id:'port:3-1',conflict:true,state:'conflict',can_assign:true}]};await advance(1500);
await advance(60000);assert.equal(dialog.open,true,'Explicit conflict stays open');assert.equal(yes.textContent,'Yes, assign a new ID');
await yes.onclick();assert.deepEqual(posts.at(-1),{action:'assign_id',event:'new:4',target:'port:3-1'});
await check.onclick();assert.deepEqual(posts.at(-1),{action:'refresh'});
assert.equal(posts.filter(p=>p.action==='assign_id').length,1,'Only Yes may write an ID');
hold=new Promise(resolve=>{unblock=resolve;});const requests=gets;await advance(1500);await advance(6000);assert.equal(gets,requests+1);
unblock();hold=null;await settle();await advance(1500);assert.equal(gets,requests+2);
console.log('PASS: quiet boot, first discovery/Later, passive arrival timeout, start picker, explicit write and serialized polling');

notice={id:'new:5',kind:'arrival',title:'Duplicate ID found',message:'Shares ID',duplicate_warning:true,timeout_seconds:180,target:'port:3-2',receivers:[{...row,id:'port:3-2',conflict:true}]};await advance(1500);
assert.equal(dialog.modal,true);assert.equal(cancel.textContent,'Later');assert.equal(yes.textContent,'Fix now');assert.equal(yes.hidden,false);
await yes.onclick();assert.equal(posts.at(-1).action,'review');assert.equal(posts.filter(p=>p.action==='assign_id').length,1,'Fix now opens review without programming');
console.log('PASS: duplicate arrival offers Fix now/Later without writing EEPROM');

await advance(179999);assert.equal(dialog.open,true);await advance(1);assert.equal(dialog.open,false,'Unattended Later prompt dismisses after three minutes');assert.equal(posts.filter(p=>p.action==='assign_id').length,1);
