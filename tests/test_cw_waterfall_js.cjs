// Regression: schedule against the prior deadline, not now+50ms. At a 60Hz
// display the latter accumulates a backlog and periodically jumps forward.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const scope={requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},setInterval:()=>1,clearInterval:()=>{},document:{hidden:true}};
vm.createContext(scope);vm.runInContext(fs.readFileSync('UI/cw_waterfall.js','utf8')+'\nthis.Waterfall=CWWaterfall;',scope);
const ctx={fillRect(){},fillStyle:''};const w=new scope.Waterfall({getContext:()=>ctx},'test');let drawn=0;w.push=()=>drawn++;
let produced=0,maxPending=0;
for(let frame=0;frame<600;frame++){
 const now=frame*1000/60;
 if(frame%9===0){for(let i=0;i<3;i++){w.pending.push(new Uint8Array(1024));produced++;}}
 w.animate(now);maxPending=Math.max(maxPending,w.pending.length);
}
assert.ok(maxPending<=4,`row backlog ${maxPending}`);assert.ok(produced-drawn<=3);w.close();
console.log('CW animation cadence: sustained 20 rows/s, bounded backlog',maxPending);
