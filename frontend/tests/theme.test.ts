import test from 'node:test';
import assert from 'node:assert/strict';
import {initializeTheme,getThemePreference,setThemePreference} from '../src/theme.ts';

function environment(stored:string|null=null,dark=true,blocked=false){
  let change=()=>{};
  const media={matches:dark,addEventListener:(_name:string,listener:()=>void)=>{change=listener;}};
  const root={dataset:{theme:''},style:{colorScheme:''}},meta={content:''};
  Object.defineProperty(globalThis,'window',{configurable:true,value:{matchMedia:()=>media,localStorage:{
    getItem:()=>{if(blocked)throw new Error('storage unavailable');return stored;},
    setItem:(_key:string,value:string)=>{if(blocked)throw new Error('storage unavailable');stored=value;},
  }}});
  Object.defineProperty(globalThis,'document',{configurable:true,value:{documentElement:root,querySelector:()=>meta}});
  return {root,meta,stored:()=>stored,system:(value:boolean)=>{media.matches=value;change();}};
}
test('default follows the system and updates native control colors',()=>{
  const env=environment();initializeTheme();
  assert.equal(getThemePreference(),'system');assert.equal(env.root.dataset.theme,'dark');
  assert.equal(env.root.style.colorScheme,'dark');assert.equal(env.meta.content,'#171717');
  env.system(false);assert.equal(env.root.dataset.theme,'light');assert.equal(env.meta.content,'#FFFFFF');
});
test('manual theme persists and takes priority over system changes',()=>{
  const env=environment('light');initializeTheme();assert.equal(env.root.dataset.theme,'light');
  assert.equal(setThemePreference('dark'),true);assert.equal(env.stored(),'dark');
  env.system(false);assert.equal(env.root.dataset.theme,'dark');
  initializeTheme();assert.equal(getThemePreference(),'dark');
  setThemePreference('system');assert.equal(env.root.dataset.theme,'light');
});
test('invalid or blocked storage falls back safely and manual choice still works',()=>{
  const invalid=environment('invalid');initializeTheme();assert.equal(getThemePreference(),'system');
  assert.equal(invalid.root.dataset.theme,'dark');
  const blocked=environment(null,true,true);initializeTheme();
  assert.equal(setThemePreference('light'),false);assert.equal(blocked.root.dataset.theme,'light');
  blocked.system(true);assert.equal(blocked.root.dataset.theme,'light');
});
