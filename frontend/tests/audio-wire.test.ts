import assert from 'node:assert/strict';
import test from 'node:test';
import {encodeFrame,decodeHeader,pcm16,withinBuffer} from '../src/audio-wire.ts';

for(const rate of [44100,48000])test('PCM wire preserves frames at '+rate,()=>{
  const frames=rate/4;
  const samples=new Int16Array(frames);
  samples[0]=-32768;samples[1]=32767;
  const packet=encodeFrame(2,rate,samples);
  assert.equal(packet.byteLength,20+frames*2);
  assert.deepEqual(decodeHeader(packet),{seq:2,first_frame:rate,frame_count:frames});
  const view=new DataView(packet);
  assert.equal(view.getInt16(20,true),-32768);
  assert.equal(view.getInt16(22,true),32767);
  assert.equal(withinBuffer(rate*9,rate,rate),true);
  assert.equal(withinBuffer(rate*10,1,rate),false);
});
test('PCM clips samples and rejects unsafe counters',()=>{
  assert.deepEqual([...pcm16(new Float32Array([-2,-1,0,1,2]))],[-32768,-32768,0,32767,32767]);
  assert.throws(()=>encodeFrame(-1,0,new Int16Array(1)));
  assert.throws(()=>encodeFrame(0,Number.MAX_SAFE_INTEGER+1,new Int16Array(1)));
});
