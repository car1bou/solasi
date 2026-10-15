import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

const segments=[
  {id:'a',chunk_id:'r1:0',recording_id:'r1',start_ms:10000,end_ms:11000,text:'첫 문장.',original_text:'첫 문장.',revision:1,final:1},
  {id:'b',chunk_id:'r1:3',recording_id:'r1',start_ms:13000,end_ms:14000,text:'다음 문장.',original_text:'다음 문장.',revision:2,final:1},
  {id:'c',chunk_id:'r2:0',recording_id:'r2',start_ms:60000,end_ms:62000,text:'다른 녹음.',original_text:'다른 녹음.',revision:1,final:1},
  {id:'p',chunk_id:'r2:2',recording_id:'r2',start_ms:62000,end_ms:64000,text:'잠정 전사',original_text:'잠정 전사',revision:1,final:0},
];

test('partial words select full touched confirmed segments and keep the selected revision frozen',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/transcript-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const helper=await server.ssrLoadModule('/src/transcript-script.ts');
    assert.equal(typeof helper.selectTranscriptRange,'function','a transcript selection snapshot must exist');
    const selected=helper.selectTranscriptRange(segments,2,9);
    assert.deepEqual(selected.map((s:typeof segments[number])=>s.id),['a','b']);
    assert.deepEqual(selected.map((s:typeof segments[number])=>[s.start_ms,s.end_ms]),[[10000,11000],[13000,14000]]);
    const originals=segments.map(s=>({...s}));
    const snapshot=helper.selectTranscriptRange(originals,6,20);
    originals[1].text='1초 뒤 갱신';originals[1].revision=3;
    assert.deepEqual(snapshot.map((s:typeof segments[number])=>[s.id,s.revision,s.text]),[['b',2,'다음 문장.'],['c',1,'다른 녹음.']]);
    assert.deepEqual(helper.selectTranscriptRange(segments,0,6).map((s:typeof segments[number])=>s.id),['a']);
    assert.deepEqual(helper.selectTranscriptRange(segments,0,100).map((s:typeof segments[number])=>s.id),['a','b','c']);
    assert.deepEqual(helper.selectTranscriptRange(segments,2,2),[]);
    assert.equal(helper.transcriptStamp(61234),'1:01.234');
  }finally{await server.close();}
});

test('playback resolves each selected source revision and uses stored WAV positions across gaps and recordings',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/transcript-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const helper=await server.ssrLoadModule('/src/transcript-script.ts');
    assert.equal(typeof helper.resolveTranscriptAudio,'function','selection playback must resolve versioned sources');
    const sources:Record<string,unknown>={
      'a:v1':{open_url:'/api/recordings/r1/audio',seek_seconds:0,end_seconds:1},
      'b:v2':{open_url:'/api/recordings/r1/audio',seek_seconds:1,end_seconds:2},
      'c:v1':{open_url:'/api/recordings/r2/audio',seek_seconds:0,end_seconds:2},
    };
    const queue=await helper.resolveTranscriptAudio(segments.slice(0,3),async(id:string)=>{
      assert.ok(Object.hasOwn(sources,id),'only snapshot revision source IDs are requested');
      return sources[id];
    });
    assert.deepEqual(queue.map((q:{id:string;open_url:string;seek_seconds:number;end_seconds:number})=>[q.id,q.open_url,q.seek_seconds,q.end_seconds]),[
      ['a:v1','/api/recordings/r1/audio',0,1],['b:v2','/api/recordings/r1/audio',1,2],['c:v1','/api/recordings/r2/audio',0,2],
    ]);
    await assert.rejects(helper.resolveTranscriptAudio(segments.slice(0,1),async()=>({open_url:null,seek_seconds:null,end_seconds:null})),/원음/);
    await assert.rejects(helper.resolveTranscriptAudio([segments[3]],async()=>sources['c:v1']),/확정/);
    await assert.rejects(helper.resolveTranscriptAudio(segments.slice(0,1),async()=>({open_url:'/api/audio',seek_seconds:3,end_seconds:2})),/원음/);
  }finally{await server.close();}
});

test('native seeking during playback stays inside the selected source bounds without another play event',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/transcript-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const helper=await server.ssrLoadModule('/src/transcript-script.ts');
    assert.equal(typeof helper.enforceTranscriptBounds,'function','native seeking needs the same bounds as timed playback');
    const clip={id:'a:v1',open_url:'/api/recordings/r1/audio',seek_seconds:30,end_seconds:35};
    const audio={currentTime:32,paused:false};
    assert.equal(helper.enforceTranscriptBounds(audio,clip,true),false);
    assert.equal(audio.currentTime,32,'seeking within the selected segment remains supported');
    audio.currentTime=0;
    assert.equal(helper.enforceTranscriptBounds(audio,clip),false);
    assert.equal(audio.currentTime,30,'scrubbing backward while playing returns to the selected start');
    audio.currentTime=40;
    assert.equal(helper.enforceTranscriptBounds(audio,clip,true),true,'scrubbing past the end while playing advances to the next selected segment');
    audio.currentTime=35;
    assert.equal(helper.enforceTranscriptBounds(audio,clip),true,'the exact end is outside the selected playback interval');
  }finally{await server.close();}
});

test('seeking past the end while paused keeps playback paused while natural completion still advances',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/transcript-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const helper=await server.ssrLoadModule('/src/transcript-script.ts');
    const clip={id:'a:v1',open_url:'/api/recordings/r1/audio',seek_seconds:30,end_seconds:35};
    const audio={currentTime:40,paused:true};
    assert.equal(helper.enforceTranscriptBounds(audio,clip,true),false,'paused seeking must not advance and autoplay the next clip');
    assert.equal(audio.currentTime,30);
    assert.equal(audio.paused,true);
    audio.currentTime=35;
    assert.equal(helper.enforceTranscriptBounds(audio,clip),true,'natural completion still advances when the native player becomes paused');
  }finally{await server.close();}
});

test('script renders continuous confirmed text with keyboard sentence actions and separates provisional text without starting audio',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/transcript-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {TranscriptScript}=await server.ssrLoadModule('/src/TranscriptView.tsx');
    assert.equal(typeof TranscriptScript,'function','the transcript has a script view');
    const markup=renderToStaticMarkup(React.createElement(TranscriptScript,{sessionId:'sid',segments,reviews:[],refresh:async()=>{},review:async()=>{}}));
    assert.match(markup,/대본/);
    assert.match(markup,/role="button"[^>]*tabindex="0"|tabindex="0"[^>]*role="button"/);
    assert.match(markup,/aria-label="0:10\.000–0:11\.000 첫 문장\. 문장 선택"/);
    assert.match(markup,/첫 문장\./);
    assert.match(markup,/다음 문장\./);
    assert.match(markup,/잠정 전사/);
    assert.match(markup,/200/);
    assert.doesNotMatch(markup,/<audio|<textarea/);
    assert.doesNotMatch(markup,/class="transcript final"/);
  }finally{await server.close();}
});
