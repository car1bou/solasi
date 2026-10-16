import test from 'node:test';
import assert from 'node:assert/strict';
import {materialView,rememberMaterialView,connectedMaterialView} from '../src/material-selection.ts';

test('returning to a material restores its page without sharing another owner selection',()=>{
  assert.deepEqual(materialView('/courses/a'),{selected:null,page:1});
  rememberMaterialView('/courses/a',{selected:'pdf-a',page:3});
  assert.deepEqual(materialView('/courses/a'),{selected:'pdf-a',page:3});
  assert.deepEqual(materialView('/sessions/a'),{selected:null,page:1});
});
test('native selection opens the first connected material at page one and cancellation keeps the view',()=>{
  const current={selected:'previous',page:3};
  assert.deepEqual(connectedMaterialView(current,[{asset:{id:'new-pdf'}},{asset:{id:'other'}}]),{selected:'new-pdf',page:1});
  assert.equal(connectedMaterialView(current,[]),current);
});
