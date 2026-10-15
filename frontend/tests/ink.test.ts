import test from 'node:test';
import assert from 'node:assert/strict';
import {eraseInk,inkPath} from '../src/ink.ts';
import type {InkStroke} from '../src/types.ts';

const stroke:InkStroke={id:'stroke',tool:'pen',color:'#254f3f',width:.02,opacity:.8,input:'pen',points:[{x:.1,y:.5,pressure:0,tilt_x:-12,tilt_y:24},{x:.9,y:.5,pressure:1,tilt_x:12,tilt_y:-24}]};

test('partial eraser preserves a stroke touched only at its outside boundary',()=>{
  const tangent={...stroke,width:.025,points:[{x:0,y:.5,pressure:1},{x:1,y:.5,pressure:1}]};
  const remaining=eraseInk([tangent],{x:.5,y:.5625},.05,true,1);
  assert.equal(remaining.length,1);
  assert.deepEqual(remaining[0],tangent);
});

test('partial eraser cuts the middle of a sparse segment and interpolates pen metadata',()=>{
  const remaining=eraseInk([stroke],{x:.5,y:.5},.09,true,2);
  assert.equal(remaining.length,2);
  assert.equal(remaining[0].id,'stroke');
  assert.notEqual(remaining[1].id,'stroke');
  assert.ok(Math.abs(remaining[0].points.at(-1)!.x-.4)<1e-12);
  assert.ok(Math.abs(remaining[1].points[0].x-.6)<1e-12);
  assert.ok(Math.abs(remaining[0].points.at(-1)!.pressure-.375)<1e-12);
  assert.ok(Math.abs(remaining[1].points[0].tilt_x!-3)<1e-12);
  assert.equal(remaining[0].opacity,.8);
});

test('JSON export roundtrip preserves normalized geometry and pressure on a portrait page',()=>{
  const exported=JSON.parse(JSON.stringify({page:1,text:'메모',ink:[stroke]}));
  assert.deepEqual(exported.ink,[stroke]);
  assert.equal(inkPath(exported.ink[0],100,200),'M10,100.35L90,101L90,99L10,99.65Z');
  const dot={...stroke,points:[{x:.25,y:.75,pressure:1}]};
  assert.equal(inkPath(dot,100,200),'M24,150a1,1 0 1,0 2,0a1,1 0 1,0 -2,0');
});

test('eraser uses the page aspect ratio instead of stretching its radius vertically',()=>{
  assert.deepEqual(eraseInk([stroke],{x:.5,y:.58},.09,true,2),[stroke]);
  assert.deepEqual(eraseInk([stroke],{x:.5,y:.5},.09,false,2),[]);
});
