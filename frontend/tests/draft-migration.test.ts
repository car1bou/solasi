import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {transferDraft,readNativeDrafts} from '../src/draft-migration.ts';

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
  const value={key:'페이지',text:'한국어 🙂 긴 필기'.repeat(40),backup:{text:'원래 메모'},ink:[]};
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
