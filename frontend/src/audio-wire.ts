export function pcm16(samples:Float32Array):Int16Array {
  return Int16Array.from(samples,value=>{
    const clipped=Math.max(-1,Math.min(1,value));
    return Math.round(clipped*(clipped<0?32768:32767));
  });
}
export function encodeFrame(seq:number,first:number,samples:Int16Array):ArrayBuffer {
  if (![seq,first,samples.length].every(n=>Number.isSafeInteger(n)&&n>=0)||!samples.length)throw new Error('프레임 위치 오류');
  const buffer=new ArrayBuffer(20+samples.length*2);
  const view=new DataView(buffer);
  view.setBigUint64(0,BigInt(seq),true);
  view.setBigUint64(8,BigInt(first),true);
  view.setUint32(16,samples.length,true);
  samples.forEach((value,index)=>view.setInt16(20+index*2,value,true));
  return buffer;
}
export function decodeHeader(buffer:ArrayBuffer) {
  const view=new DataView(buffer);
  return {seq:Number(view.getBigUint64(0,true)),first_frame:Number(view.getBigUint64(8,true)),frame_count:view.getUint32(16,true)};
}
export function withinBuffer(pending:number,incoming:number,rate:number):boolean {
  return pending+incoming<=rate*10;
}
