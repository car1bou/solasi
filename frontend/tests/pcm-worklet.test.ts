import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function processor(){
  const messages:any[]=[];let Processor:any;
  const scope:any={sampleRate:48000,currentFrame:0,Int16Array,AudioWorkletProcessor:class{port={onmessage:null,postMessage:(m:any)=>messages.push(m)};},registerProcessor:(_:string,type:any)=>{Processor=type;}};
  vm.runInNewContext(readFileSync(new URL('../src/pcm-worklet.js',import.meta.url),'utf8'),scope);
  return {node:new Processor(),messages,scope};
}
test('worklet exposes a short missing-input gap instead of silently joining speech',()=>{
  const {node,messages,scope}=processor();
  node.process([[new Float32Array(128).fill(.1)]]);
  scope.currentFrame=128;node.process([[]]);
  scope.currentFrame=256;node.process([[new Float32Array(128).fill(.2)]]);
  scope.currentFrame=384;node.port.onmessage({data:{type:'stop'}});
  const packets=messages.filter(m=>m.type==='frame');
  assert.deepEqual(packets.map(m=>[m.first_frame,m.samples.length]),[[0,128],[256,128]]);
  assert.equal(messages.at(-1).end_frame,384);
});
test('worklet keeps quiet samples and counts a missing tail without adding fake silence',()=>{
  const {node,messages,scope}=processor();
  node.process([[new Float32Array(128)]]);scope.currentFrame=128;node.process([[]]);scope.currentFrame=512;
  node.port.onmessage({data:{type:'stop'}});
  assert.equal(messages.find(m=>m.type==='frame').samples.length,128);
  assert.equal(messages.at(-1).end_frame,512);
});

test('late worklet origin starts at zero and continuous packets have no gaps',()=>{
  const {node,messages,scope}=processor();scope.currentFrame=100000;
  for(let n=0;n<200;n++){scope.currentFrame=100000+n*128;node.process([[new Float32Array(128).fill(.2)]]);}
  scope.currentFrame=125600;node.port.onmessage({data:{type:'stop'}});
  const packets=messages.filter(m=>m.type==='frame');let end=0;
  for(const packet of packets){assert.equal(packet.first_frame,end);end+=packet.samples.length;}
  assert.equal(end,25600);assert.equal(messages.at(-1).end_frame,end);
});
