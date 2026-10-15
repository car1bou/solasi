import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'vite';
import {readdir,readFile} from 'node:fs/promises';

test('worklet build uses a same-origin file allowed by CSP',async()=>{
  await build({logLevel:'silent'});
  const files=await readdir('dist/assets');
  const worklet=files.find(name=>name.startsWith('pcm-worklet-')&&name.endsWith('.js'));
  assert.ok(worklet,'AudioWorklet must remain a separate same-origin file');
  const entry=files.find(name=>name.startsWith('index-')&&name.endsWith('.js'))!;
  const source=await readFile('dist/assets/'+entry,'utf8');
  assert.ok(source.includes(worklet));
  assert.ok(!source.includes('data:text/javascript'));
});
