import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'vite';
import {mkdtemp,readdir,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('worklet build uses a same-origin file allowed by CSP',async()=>{
  const output=await mkdtemp(join(tmpdir(),'solasi-worklet-build-'));
  try{
  await build({configFile:false,logLevel:'silent',cacheDir:join(output,'cache'),build:{assetsInlineLimit:0,outDir:join(output,'dist')}});
  const assets=join(output,'dist/assets');
  const files=await readdir(assets);
  const worklet=files.find(name=>name.startsWith('pcm-worklet-')&&name.endsWith('.js'));
  assert.ok(worklet,'AudioWorklet must remain a separate same-origin file');
  const entry=files.find(name=>name.startsWith('index-')&&name.endsWith('.js'))!;
  const source=await readFile(join(assets,entry),'utf8');
  assert.ok(source.includes(worklet));
  assert.ok(!source.includes('data:text/javascript'));
  }finally{await rm(output,{recursive:true,force:true});}
});
