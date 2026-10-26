import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.open=false;this.hidden=false;this.textContent='';}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}setAttribute(k,v){this[k]=v;}addEventListener(k,fn){this.listeners[k]=fn;}showModal(){this.open=true;}close(){this.open=false;}focus(){}
}
const body=new Element('body'),intervals=new Map(),saved=new Map();let tick=0,next=0,posts=[];
const document={body,hidden:false,activeElement:new Element('button'),createElement:tag=>new Element(tag),getElementById:id=>body.children.find(e=>e.id===id),addEventListener(){}};
const row={id:'serial:11',name:'Roof antenna',serial:'10000011',port:'3-1',conflict:false};
let notice={id:'boot:1',kind:'ready',title:'1 SDR receiver detected',message:'Ready',receivers:[row]};
const sandbox={document,Date:{now:()=>tick},sessionStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},setInterval(fn){const id=++next;intervals.set(id,fn);return id;},clearInterval(id){intervals.delete(id);},fetch:async(_url,options)=>{
 if(options?.method==='POST'){posts.push(JSON.parse(options.body));notice={...notice,id:'boot:4',kind:'working',title:'Assigning a new ID'};return {ok:true};}
 return {ok:true,json:async()=>({available:true,notice,control_token:'token'})};
}};
vm.runInNewContext(fs.readFileSync(new URL('../UI/dongle-notice.js',import.meta.url),'utf8'),sandbox);
const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();
const dialog=document.getElementById('usb-detection-notice');assert.equal(dialog.open,true);assert.equal(posts.length,0);
async function advance(ms){tick+=ms;for(const fn of [...intervals.values()])fn();await settle();}
await advance(9999);assert.equal(dialog.open,true);
await advance(1);assert.equal(dialog.open,false,'Ready closes at ten seconds');
await advance(5000);assert.equal(dialog.open,false,'Periodic refresh cannot reopen the same dismissed notice');
notice={id:'boot:2',kind:'conflict',title:'Assign a new ID?',message:'Shared ID',target:'port:3-1',can_assign:true,receivers:[{...row,id:'port:3-1',conflict:true,state:'conflict',can_assign:true}]};
await advance(1500);assert.equal(dialog.open,true);await advance(60000);assert.equal(dialog.open,true,'Conflict remains until an explicit choice');
const actions=dialog.children.at(-1),[cancel,yes]=actions.children;
cancel.onclick();assert.equal(dialog.open,false);assert.equal(posts.length,0,'Cancel never programs USB');
notice={...notice,id:'boot:3'};await advance(1500);assert.equal(dialog.open,true);await yes.onclick();await settle();
assert.equal(posts.length,1);assert.deepEqual(posts[0],{action:'assign_id',event:'boot:3',target:'port:3-1'});
assert.equal(dialog.open,true);// Queued/writing rows cannot submit a second write; another receiver remains selectable.
notice={...notice,id:'boot:5',receivers:[{...row,id:'port:3-1',state:'working',can_assign:false},{...row,id:'port:3-2',port:'3-2',state:'conflict',conflict:true,can_assign:true}]};await advance(1500);
const list=dialog.children[2];assert.equal(list.children.length,2);
list.children[1].children.at(-1).onclick();await yes.onclick();await settle();
assert.equal(posts.length,2);assert.equal(posts[1].target,'port:3-2');
notice={...notice,id:'boot:6',receivers:[{...row,id:'port:3-1',state:'reconnect',new_serial:'10000014',can_assign:false},{...row,id:'port:3-2',state:'queued',can_assign:false}]};await advance(1500);
assert.equal(yes.hidden,true,'Pending receivers cannot submit another write');
console.log('PASS: startup notice, exact timeout, sticky conflict, Cancel and deliberate Yes');
