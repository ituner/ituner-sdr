/* Small incremental row requests; metadata/history use their existing cadence. */
class CWWaterfall {
  constructor(canvas,id){
    this.canvas=canvas;this.ctx=canvas.getContext('2d',{alpha:false});this.id=id;
    this.epoch='';this.seq=0;this.pending=[];this.running=true;this.closed=false;
    this.next=0;this.busy=false;this.controller=null;
    this.ctx.fillStyle='#081b25';this.ctx.fillRect(0,0,1024,240);
    this.timer=setInterval(()=>this.fetchRows(),150);this.fetchRows();
    this.frame=requestAnimationFrame(t=>this.animate(t));
  }
  async fetchRows(){
    if(this.closed||this.busy||document.hidden||!this.running)return;
    const box=this.canvas.getBoundingClientRect();if(box.bottom<0||box.top>innerHeight||box.height===0)return;
    this.busy=true;this.controller=new AbortController();const timeout=setTimeout(()=>this.controller?.abort(),3000);
    try{
      const response=await fetch('/api/cw/waterfall?id='+encodeURIComponent(this.id)+'&epoch='+encodeURIComponent(this.epoch)+'&after='+this.seq,{cache:'no-store',signal:this.controller.signal});
      if(!response.ok)return;const data=await response.json();if(this.closed)return;
      if(data.width!==1024||data.height!==240)return;
      const bytes=Uint8Array.from(atob(data.rows),c=>c.charCodeAt(0));
      if(data.reset){this.pending=[];this.ctx.fillRect(0,0,1024,240);}
      for(let i=0;i<bytes.length;i+=1024)this.pending.push(bytes.slice(i,i+1024));
      this.epoch=data.epoch;this.seq=data.seq;
      // On return from another tab, catch up immediately, not over many seconds.
      if(data.reset||this.pending.length>12){for(const row of this.pending)this.push(row);this.pending=[];this.next=0;}
    }catch(e){/* A later bounded request resumes from the last acknowledged row. */}
    finally{clearTimeout(timeout);this.controller=null;this.busy=false;}
  }
  push(row){
    this.ctx.drawImage(this.canvas,0,0,1024,239,0,1,1024,239);
    const line=this.ctx.createImageData(1024,1);
    for(let x=0;x<1024;x++){const v=row[x]/255,i=x*4;line.data[i]=v*v*.7*255;line.data[i+1]=v*.95*255;line.data[i+2]=(v*.8+.035)*255;line.data[i+3]=255;}
    this.ctx.putImageData(line,0,0);
  }
  animate(now){
    if(this.closed)return;
    if(now>=this.next&&this.pending.length){this.push(this.pending.shift());this.next=this.next?this.next+50:now+50;if(now-this.next>150)this.next=now+50;}
    this.frame=requestAnimationFrame(t=>this.animate(t));
  }
  close(){this.closed=true;clearInterval(this.timer);cancelAnimationFrame(this.frame);this.controller?.abort();}
}
