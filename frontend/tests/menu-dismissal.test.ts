import test from 'node:test';
import assert from 'node:assert/strict';
import {closeMenu,listenForMenuDismissal} from '../src/menu-dismissal.ts';

class NodeStub extends EventTarget{
 open=false;children:NodeStub[]=[];focused=false;action=false;paper=false;
 contains(node:unknown):boolean{return node===this||this.children.some(child=>child.contains(node));}
 closest(selector:string){return selector==='[data-menu-action]'&&this.action||selector==='.page-viewport'&&this.paper?this:null;}
 querySelectorAll(){return this.children.filter(child=>child.open);}
 querySelector(){return {focus:()=>{this.focused=true;}};}
}
function fixture(){
 Object.defineProperty(globalThis,'Element',{configurable:true,value:NodeStub});
 const doc=new EventTarget(),events=new EventTarget(),menu=new NodeStub(),inside=new NodeStub(),nested=new NodeStub();
 menu.children=[inside,nested];menu.open=true;nested.open=true;
 const cleanup=listenForMenuDismissal(menu as unknown as HTMLDetailsElement,doc as Document,events as Window);
 function send(target:EventTarget,type:string,node:NodeStub,fields={}){const event=new Event(type,{cancelable:true});Object.defineProperties(event,{target:{value:node},...Object.fromEntries(Object.entries(fields).map(([key,value])=>[key,{value}]))});target.dispatchEvent(event);return event;}
 return {doc,events,menu,inside,nested,cleanup,send};
}

test("outside pointer and completed Tab navigation close menus; WebKit body focus does not cancel selection",async()=>{
 const f=fixture();try{
  f.send(f.doc,'pointerdown',f.inside);assert.equal(f.menu.open,true);
  f.send(f.doc,'pointerdown',new NodeStub());assert.equal(f.menu.open,false);assert.equal(f.nested.open,false);
  f.menu.open=true;f.send(f.doc,'focusin',new NodeStub());assert.equal(f.menu.open,true);
  Object.defineProperty(f.doc,'activeElement',{value:new NodeStub()});f.send(f.doc,'keydown',f.inside,{key:'Tab'});await new Promise(resolve=>setTimeout(resolve,0));assert.equal(f.menu.open,false);
  f.menu.open=true;const paper=new NodeStub();paper.paper=true;
  assert.equal(f.send(f.doc,'pointerdown',paper).defaultPrevented,true);assert.equal(f.menu.open,false);
 }finally{f.cleanup();}
});

test('Escape returns focus, menu actions close, and another popup or successful navigation dismisses it',()=>{
 const f=fixture();try{
  assert.equal(f.send(f.doc,'keydown',f.inside,{key:'Escape'}).defaultPrevented,true);assert.equal(f.menu.open,false);assert.equal(f.menu.focused,true);
  f.menu.open=true;f.nested.open=true;closeMenu(f.menu as unknown as HTMLDetailsElement);assert.equal(f.menu.open,false);assert.equal(f.nested.open,false);
  f.menu.open=true;f.events.dispatchEvent(new CustomEvent('solasi-popup-open',{detail:f.inside}));assert.equal(f.menu.open,true);
  f.events.dispatchEvent(new CustomEvent('solasi-popup-open',{detail:new NodeStub()}));assert.equal(f.menu.open,false);
  f.menu.open=true;f.events.dispatchEvent(new Event('solasi-navigated'));assert.equal(f.menu.open,false);
  f.cleanup();f.menu.open=true;f.send(f.doc,'pointerdown',new NodeStub());assert.equal(f.menu.open,true);
 }finally{f.cleanup();}
});
