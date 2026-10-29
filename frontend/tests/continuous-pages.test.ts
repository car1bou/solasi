import test from 'node:test';
import assert from 'node:assert/strict';
import {pageAtPosition,pageShortcut,parsePageNumber,notebookViewportHeight} from '../src/continuous-pages.ts';

test('the notebook uses remaining visible height after wrapping controls and window resizing',()=>{
  assert.equal(notebookViewportHeight(720,120),588);
  assert.equal(notebookViewportHeight(480,220),248);
  assert.equal(notebookViewportHeight(480,260),208);
  assert.equal(notebookViewportHeight(480,-30),468);
  assert.equal(notebookViewportHeight(480,500),180);
});

test('the current page follows the page at the reading position',()=>{
  const pages=[{page:1,top:-300,bottom:120},{page:2,top:130,bottom:900},{page:3,top:910,bottom:1500}];
  assert.equal(pageAtPosition(pages,200),2);
  assert.equal(pageAtPosition(pages,100),1);
  assert.equal(pageAtPosition([],100),null);
});

test('page entry accepts only a whole page within the document',()=>{
  assert.equal(parsePageNumber('1',300),1);
  assert.equal(parsePageNumber('300',300),300);
  assert.equal(parsePageNumber(' 025 ',300),25);
  for(const value of ['', '0','301','-1','1.5','1e2','Infinity','999999999999999999999999'])assert.equal(parsePageNumber(value,300),null,value);
});

test('arrow navigation respects page boundaries and ignores editable controls and modifiers',()=>{
  assert.equal(pageShortcut('ArrowRight',false,false,2,3),3);
  assert.equal(pageShortcut('ArrowLeft',false,false,2,3),1);
  assert.equal(pageShortcut('ArrowLeft',false,false,1,3),null);
  assert.equal(pageShortcut('ArrowRight',false,false,3,3),null);
  assert.equal(pageShortcut('ArrowRight',true,false,2,3),null);
  assert.equal(pageShortcut('ArrowRight',false,true,2,3),null);
  assert.equal(pageShortcut('ArrowDown',false,false,2,3),null);
});
