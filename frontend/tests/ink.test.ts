import test from 'node:test';
import assert from 'node:assert/strict';
import {eraseInk,inkBounds,inkPath,textInkAt,textInkBox} from '../src/ink.ts';
import type {InkStroke,InkText} from '../src/types.ts';

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

const text:InkText={id:'text',tool:'text',text:'같은 문장 같은 문장\n\n🙂 <script> & 한글',color:'#123456',width:.025,opacity:1,input:'mouse',points:textInkBox({x:.2,y:.3})};

test('text hit testing selects the topmost box, including its edges, without selecting vector strokes',()=>{
  const top={...text,id:'top'};
  assert.equal(textInkAt([text,stroke,top],{x:.3,y:.35}),top);
  assert.equal(textInkAt([text],text.points[0]),text);
  assert.equal(textInkAt([text],text.points[1]),text);
  assert.equal(textInkAt([text,stroke],{x:.1,y:.5}),undefined);
});

test('text boxes remain within the page at corners and after extreme drag coordinates',()=>{
  for(const origin of [{x:0,y:0},{x:1,y:1},{x:-100,y:100},{x:100,y:-100}]){
    const points=textInkBox(origin);
    assert.ok(points.every(point=>point.x>=0&&point.x<=1&&point.y>=0&&point.y<=1));
    assert.ok(Math.abs(points[1].x-points[0].x-.36)<1e-12);
    assert.ok(Math.abs(points[1].y-points[0].y-.12)<1e-12);
  }
  assert.deepEqual(textInkBox({x:1,y:1},2,2),[{x:0,y:0,pressure:.5},{x:1,y:1,pressure:.5}]);
});

test('typed text roundtrips literally, has selectable bounds, and never becomes erasable handwriting',()=>{
  const restored=JSON.parse(JSON.stringify(text));
  assert.equal(restored.text,text.text);
  assert.deepEqual(restored.points,text.points);
  assert.equal(inkPath(restored,600,800),'');
  assert.deepEqual(inkBounds([restored]),{x:.2,y:.3,width:.36000000000000004,height:.12});
  for(const partial of [true,false])assert.deepEqual(eraseInk([restored],{x:.3,y:.35},1,partial,1),[restored]);
});
