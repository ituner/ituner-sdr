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

// Real push method must insert at top and move existing pixels down.
const pixels=Array(240).fill(0);
const raster={fillRect(){},createImageData:()=>({data:new Uint8ClampedArray(4096)}),
 drawImage(canvas,sx,sy,sw,sh,dx,dy,dw,dh){const old=pixels.slice();for(let i=0;i<sh;i++)pixels[dy+i]=old[sy+i];},
 putImageData(line,x,y){pixels[y]=line.data[1];}};
const view=new scope.Waterfall({getContext:()=>raster},'direction');
view.push(new Uint8Array(1024).fill(100));view.push(new Uint8Array(1024).fill(200));
assert.equal(pixels[0],190);assert.equal(pixels[1],95);assert.equal(pixels[2],0);view.close();
console.log('CW waterfall: newest at top, earlier row moves down');
