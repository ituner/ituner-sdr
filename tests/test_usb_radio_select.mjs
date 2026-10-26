import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
class E{constructor(){this.dataset={};this.children=[];this.value='auto';this.afterItems=[];}replaceChildren(...n){this.children=n;}closest(){return this;}after(n){this.afterItems.push(n);}}
const document={activeElement:null,currentScript:{src:'http://cm5.local:8092/usb-radio-select.js'},createElement:()=>new E()};const window={};
vm.runInNewContext(fs.readFileSync(new URL('../UI/usb-radio-select.js',import.meta.url),'utf8'),{document,window,URL,location:{href:'http://cm5.local:8093/'}});
const select=new E(),devices=[{id:'serial:12',serial:'10000012',nickname:'Roof antenna',label:'Long noisy USB 2 device name',persistent:true},{id:'port:3-1',serial:'00000001',product:'Blog V4L',persistent:false,duplicate:true}];
window.USB_Radios.fill(select,devices,{leases:{'serial:12':'uat'},owner:'ism',selection:'serial:missing'});
assert.equal(select.children.length,4);assert.match(select.children[1].textContent,/Roof antenna.*10000012.*978 UAT/);assert.equal(select.children[2].disabled,true);assert.equal(select.value,'serial:missing');assert.equal(select.afterItems[0].href,'http://cm5.local:8092/usb-radios');
const before=select.children;window.USB_Radios.fill(select,devices,{leases:{'serial:12':'uat'},owner:'ism',selection:'serial:missing'});assert.equal(select.children,before,'Same inventory does not rebuild an open chooser');assert.equal(select.afterItems.length,1);
document.activeElement=select;window.USB_Radios.fill(select,[],{selection:'auto'});assert.equal(select.children,before,'Focused user choice stays stable during polling');
document.activeElement=null;window.USB_Radios.fill(select,devices,{unique:false,selection:'port:3-1'});assert.equal(select.children[2].disabled,false);assert.equal(select.value,'port:3-1');
console.log('PASS: shared names, ownership, duplicate guards, missing assignment, focus stability and management link');
