import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {transferDraft,readNativeDrafts} from '../src/draft-migration.ts';

test('small native snapshots commit in one request and checkpoints stay journal-only',async()=>{
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  const calls:{path:string;body:any}[]=[];
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;body:string})=>{
    calls.push({path:message.path,body:JSON.parse(message.body)});return {status:200,text:'{"count":1,"sha256":"checked"}'};
  }}}}}});
  const value={key:'page',text:'필기',ink:[],dirty:true};
  await transferDraft(value,'write','page::writer');
  await transferDraft(value,'checkpoint','page::stroke-writer');
  assert.equal(calls.length,2);
  assert.deepEqual(calls,[
    {path:'/api/native/drafts/snapshot',body:{value,journal_key:'page::writer',checkpoint:false}},
    {path:'/api/native/drafts/snapshot',body:{value,journal_key:'page::stroke-writer',checkpoint:true}},
  ]);
});

test('a snapshot expanded by Python number encoding falls back to chunks without swallowing other failures',async()=>{
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  const value={key:'page',text:'',ink:[{id:'boundary',tool:'pen',color:'#254f3f',width:.01,opacity:1,input:'mouse',points:Array.from({length:1000},()=>({x:1e-7,y:.3,pressure:.5}))}],dirty:true};
  value.text='x'.repeat(65536-Buffer.byteLength(JSON.stringify(value)));
  const raw=JSON.stringify(value);assert.equal(Buffer.byteLength(raw),65536);
  assert.ok(Buffer.byteLength(raw.replaceAll('1e-7','1e-07'))>65536);
  let begins=0,failDisk=false;const parts:Buffer[]=[];
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
    const body=message.body?JSON.parse(message.body):{};
    if(message.path==='/api/native/drafts/snapshot')return {status:failDisk?500:422,text:JSON.stringify({detail:failDisk?'disk unavailable':'초안 직접 저장 크기 오류'})};
    if(message.path==='/api/native/drafts/uploads'){begins++;return {status:200,text:'{"id":"boundary","chunk_size":262144}'};}
    if(message.path.endsWith('/commit'))return {status:200,text:'{"count":1,"sha256":"checked"}'};
    parts.push(Buffer.from(body.data,'base64'));return {status:200,text:JSON.stringify({received:parts.reduce((n,p)=>n+p.length,0)})};
  }}}}}});
  for(const kind of ['write','checkpoint']as const){parts.length=0;await transferDraft(value,kind,'page::stroke-writer');assert.equal(Buffer.concat(parts).toString(),raw);}
  assert.equal(begins,2);failDisk=true;
  await assert.rejects(transferDraft(value,'write','page::writer'),/disk unavailable/);assert.equal(begins,2);
});

test('native draft upload preserves UTF-8 across chunks and commits only after every ACK',async()=>{
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  const parts:Buffer[]=[];let committed=false,cancelled=false,fail=false;
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
    const value=message.body?JSON.parse(message.body):{};
    if(message.path==='/api/native/drafts/uploads')return {status:200,text:JSON.stringify({id:'upload',chunk_size:37})};
    if(message.method==='DELETE'){cancelled=true;return {status:200,text:'{}'};}
    if(message.path.endsWith('/commit')){committed=true;return {status:200,text:JSON.stringify({sha256:createHash('sha256').update(Buffer.concat(parts)).digest('hex'),count:1})};}
    assert.equal(committed,false);assert.equal(value.offset,Buffer.concat(parts).length);
    const chunk=Buffer.from(value.data,'base64');parts.push(chunk);
    return {status:200,text:JSON.stringify({received:Buffer.concat(parts).length+(fail?1:0)})};
  }}}}}});
  const value={key:'페이지',text:'한국어 🙂 긴 필기'.repeat(40),backup:{text:'원래 메모'},ink:[],padding:'x'.repeat(65536)};
  const result=await transferDraft(value,'write','페이지::writer');
  assert.equal(committed,true);assert.equal(cancelled,false);
  assert.deepEqual(JSON.parse(Buffer.concat(parts).toString('utf8')),value);
  assert.equal(result.sha256,createHash('sha256').update(JSON.stringify(value)).digest('hex'));
  parts.length=0;committed=false;fail=true;
  await assert.rejects(transferDraft(value,'write','페이지::writer'),/확인 길이/);
  assert.equal(committed,false);assert.equal(cancelled,true);
});

test('native draft reading preserves every journal and rejects a looping cursor',async()=>{
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  const rows=[{key:'page',dirty:false,backup:{text:'kept'}},{key:'page::a',text:'writer A'},{key:'page::b',text:'writer B'}];
  let bad=false;
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string})=>{
    const after=new URL('solasi-app://app'+message.path).searchParams.get('after')||'';
    return {status:200,text:JSON.stringify(bad?[rows[0]]:rows.filter(row=>row.key>after).slice(0,1))};
  }}}}}});
  assert.deepEqual(await readNativeDrafts('page'),rows);
  bad=true;await assert.rejects(readNativeDrafts('page'),/조회 응답/);
});
