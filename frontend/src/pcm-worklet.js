class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples=new Int16Array(Math.round(sampleRate/4));
    this.used=0;this.first=0;this.origin=null;this.seq=0;this.unacked=0;this.active=true;
    this.port.onmessage=event=>{
      if(event.data.type==='ack')this.unacked=Math.max(0,this.unacked-event.data.frames);
      if(event.data.type==='stop') {
        this.flush();this.active=false;
        this.port.postMessage({type:'stopped',end_frame:Math.max(this.first,this.origin===null?0:currentFrame-this.origin)});
      }
    };
  }
  flush() {
    if(!this.used)return;
    const samples=this.samples.slice(0,this.used);
    this.unacked+=samples.length;
    this.port.postMessage({type:'frame',seq:this.seq++,first_frame:this.first,samples},[samples.buffer]);
    this.first+=this.used;this.used=0;
  }
  process(inputs) {
    if(!this.active)return true;
    this.origin??=currentFrame;
    const sourceFrame=currentFrame-this.origin;
    if(sourceFrame>this.first+this.used){this.flush();this.first=sourceFrame;}
    const channels=inputs[0];
    if(!channels?.length){this.flush();return true;}
    for(let i=0;i<channels[0].length;i++) {
      if(this.unacked+this.used>=sampleRate*10) {
        this.active=false;
        this.port.postMessage({type:'overflow',end_frame:this.first+this.used});
        return true;
      }
      const value=Math.max(-1,Math.min(1,channels.reduce((sum,channel)=>sum+channel[i],0)/channels.length));
      this.samples[this.used++]=Math.round(value*(value<0?32768:32767));
      if(this.used===this.samples.length)this.flush();
    }
    return true;
  }
}
registerProcessor('pcm-capture',Capture);
