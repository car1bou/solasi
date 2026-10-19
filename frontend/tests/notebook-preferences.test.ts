import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'vite';

test('notebook preferences keep each pen and document view independently across reloads',async()=>{
  const values=new Map<string,string>();
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('http://localhost/')});
  Object.defineProperty(globalThis,'window',{configurable:true,value:{localStorage:{getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>values.set(key,value)}}});
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  const asset='a'.repeat(32),hash='b'.repeat(64),otherHash='c'.repeat(64);
  try{
    const prefs=await server.ssrLoadModule('/src/notebook-preferences.ts');
    const initial=await prefs.loadNotebookPreferences(asset,hash);
    assert.equal(initial.view.zoomMode,'fit');
    const tools={...initial.tools,tool:'highlighter',eraserMode:'partial-eraser',penColor:'#123456',penWidth:.004,highlighterColor:'#abcdef',highlighterOpacity:.4,eraserSize:.02};
    assert.equal(await prefs.saveNotebookTools(tools),true);
    const view={zoomMode:'manual',zoom:1.5,rotation:90,notesOpen:false};
    assert.equal(await prefs.saveNotebookView(asset,hash,view),true);
    server.moduleGraph.invalidateAll();
    const restarted=await server.ssrLoadModule('/src/notebook-preferences.ts');
    assert.deepEqual((await restarted.loadNotebookPreferences(asset,hash)).tools,tools);
    assert.deepEqual((await restarted.loadNotebookPreferences(asset,hash)).view,view);
    assert.equal((await restarted.loadNotebookPreferences(asset,otherHash)).view.zoomMode,'fit');
  }finally{await server.close();}
});

test('fit width accounts for rotation and tiny viewports without changing manual zoom',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {notebookZoom}=await server.ssrLoadModule('/src/notebook-preferences.ts');
    const page={width:600,height:900},fit={zoomMode:'fit',zoom:1,rotation:0,notesOpen:true};
    assert.equal(notebookZoom(fit,page,340),.5);
    assert.equal(notebookZoom({...fit,rotation:90},page,340),1/3);
    assert.equal(notebookZoom({...fit,rotation:270},page,340),1/3);
    assert.equal(notebookZoom({...fit,zoomMode:'manual',zoom:2},page,340),2);
    assert.equal(notebookZoom({...fit,zoomMode:'manual',zoom:2},page,900),2);
    assert.equal(notebookZoom({...fit,rotation:180},page,340),.5);
    assert.equal(notebookZoom(fit,page,0),1);
  }finally{await server.close();}
});

test('native preferences use committed app storage and storage errors remain recoverable',async()=>{
  const values=new Map<string,unknown>();let fail=false;
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('solasi-app://app/')});
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
    if(fail)throw new Error('disk unavailable');
    const key=decodeURIComponent(message.path.split('/').pop()!);
    if(message.method==='PUT')values.set(key,JSON.parse(message.body!).value);
    return {status:200,text:JSON.stringify({value:values.get(key)??null})};
  }}}}}});
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const prefs=await server.ssrLoadModule('/src/notebook-preferences.ts');
    const initial=await prefs.loadNotebookPreferences('a'.repeat(32),'b'.repeat(64));
    const tools={...initial.tools,tool:'pen',eraserMode:'partial-eraser',penColor:'#654321'};
    assert.equal(await prefs.saveNotebookTools(tools),true);
    assert.deepEqual(values.get('notebook-tools'),tools);
    server.moduleGraph.invalidateAll();
    const restarted=await server.ssrLoadModule('/src/notebook-preferences.ts');
    assert.deepEqual((await restarted.loadNotebookPreferences('a'.repeat(32),'b'.repeat(64))).tools,tools);
    fail=true;
    assert.equal(await restarted.saveNotebookTools({...tools,eraserSize:.03}),false);
    assert.equal((await restarted.loadNotebookPreferences('a'.repeat(32),'b'.repeat(64))).tools.eraserSize,.03);
  }finally{await server.close();}
});

test('invalid stored values fall back instead of corrupting pen input or page geometry',async()=>{
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('http://localhost/')});
  Object.defineProperty(globalThis,'window',{configurable:true,value:{localStorage:{getItem:()=>'{"penColor":"red","penWidth":999,"zoomMode":"manual","zoom":-4,"rotation":45,"notesOpen":"false"}'}}});
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const prefs=await server.ssrLoadModule('/src/notebook-preferences.ts');
    const value=await prefs.loadNotebookPreferences('a'.repeat(32),'b'.repeat(64));
    assert.equal(value.tools.penColor,'#254f3f');assert.equal(value.tools.penWidth,.0025);
    assert.equal(value.view.zoomMode,'fit');assert.equal(value.view.rotation,0);assert.equal(value.view.notesOpen,true);
  }finally{await server.close();}
});

test('one damaged native preference never replaces the other healthy setting with defaults',async t=>{
  const asset='a'.repeat(32),hash='b'.repeat(64);
  for(const broken of ['notebook-tools','notebook-view:'+asset+':'+hash])await t.test(broken,async()=>{
    Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('solasi-app://app/')});
    let puts=0,lastSaved:unknown;
    const tools={tool:'highlighter',penColor:'#123456',penWidth:.006,penOpacity:.8,highlighterColor:'#abcdef',highlighterWidth:.025,highlighterOpacity:.25,eraserSize:.03};
    const view={zoomMode:'manual',zoom:1.5,rotation:270,notesOpen:false};
    Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
      const key=decodeURIComponent(message.path.split('/').pop()!);
      if(message.method==='PUT'){puts++;lastSaved=JSON.parse(message.body!).value;return {status:200,text:JSON.stringify({value:lastSaved})};}
      return key===broken?{status:422,text:JSON.stringify({detail:'saved preference damaged'})}:{status:200,text:JSON.stringify({value:key==='notebook-tools'?tools:view})};
    }}}}}});
    const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
    try{
      const prefs=await server.ssrLoadModule('/src/notebook-preferences.ts');
      const result=await prefs.loadNotebookPreferences(asset,hash);
      assert.equal(puts,0);assert.match(result.warning,/불러오지 못해/);
      if(broken==='notebook-tools'){
        assert.deepEqual(result.tools,prefs.defaultTools);assert.deepEqual(result.view,view);
        await prefs.saveNotebookView(asset,hash,{...result.view,notesOpen:true});
        assert.deepEqual(lastSaved,{...view,notesOpen:true});
      }else{
        assert.deepEqual(result.tools,tools);assert.deepEqual(result.view,prefs.defaultView);
        await prefs.saveNotebookTools({...result.tools,tool:'pen'});
        assert.deepEqual(lastSaved,{...tools,tool:'pen'});
      }
    }finally{await server.close();}
  });
});

test('rapid settings changes persist the latest snapshot before a close flush completes',async()=>{
  const writes:string[]=[];
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('http://localhost/')});
  Object.defineProperty(globalThis,'window',{configurable:true,value:{localStorage:{getItem:()=>null,setItem:(_key:string,value:string)=>writes.push(value)}}});
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const prefs=await server.ssrLoadModule('/src/notebook-preferences.ts');
    void prefs.saveNotebookTools({...prefs.defaultTools,penWidth:.003});
    void prefs.saveNotebookTools({...prefs.defaultTools,penWidth:.004});
    void prefs.saveNotebookTools({...prefs.defaultTools,penWidth:.005});
    await prefs.flushNotebookPreferences();
    assert.equal(writes.length,1);assert.equal(JSON.parse(writes[0]).penWidth,.005);
  }finally{await server.close();}
});

test('page export identifies the original page and base revision while preserving ink bytes',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {notebookExport}=await server.ssrLoadModule('/src/notebook-preferences.ts');
    const identity={course_id:'course',asset_id:'a'.repeat(32),document_sha256:'b'.repeat(64),page:4};
    const ink=[{id:'stroke',tool:'pen',color:'#fFaA22',width:.0025,opacity:.7,input:'pen',points:[{x:.25,y:.7,pressure:.45,tilt_x:12,tilt_y:-4}]}];
    const content={revision:3,status:'saved',text:'원문 메모',ink},before=JSON.stringify(content);
    const result=notebookExport('원본.pdf',identity,content);
    assert.equal(result.filename,'원본-bbbbbbbb-p4-v3-saved.json');
    assert.deepEqual(result.value,{format:'solasi-page-notebook-v1',...identity,base_revision:3,saved:true,text:'원문 메모',ink});
    assert.equal(JSON.stringify(content),before);
    const draft=notebookExport('원본.pdf',identity,{...content,status:'pending'});
    assert.equal(draft.value.saved,false);assert.match(draft.filename,/-v3-draft.json$/);
    assert.equal(new TextEncoder().encode(notebookExport('한'.repeat(300)+'.pdf',identity,content).filename).length<256,true);
  }finally{await server.close();}
});
