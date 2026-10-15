"""Actual browser/ASR/generation fixture. Use a new output directory; no microphone.

Run: .venv/bin/python experiments/serve_long_recording_fixture.py /tmp/long-recording-check
The default input concatenates cached FLEURS recordings once each, never repeats a file.
"""
import asyncio,json,shutil,subprocess,sys,time,wave
from pathlib import Path
import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lecture_study import server,answers,outputs,transcription as tr
from lecture_study.config import AppConfig
from lecture_study.db import create_session
from lecture_study.materials import save_note
from lecture_study.launcher import bind_listener

RUNTIME=ROOT/'.local-state/runtime'

def prepare_audio(folder):
    rows=[]
    for name in ('human-audio-20261013/provenance.json','asr-comparison-20261013/manifest.json','diverse-audio-20261014/manifest.json'):
        for row in json.loads((RUNTIME/name).read_text())['clips']:
            if row.get('dataset','')=='google/fleurs' or row.get('group')=='fleurs40':rows.append(row)
    unique={r['sha256']:r for r in rows};rows=list(unique.values())
    assert len(rows)==65,len(rows)
    for row in rows:assert tr.file_hash(row['path'])==row['sha256']
    # All paths are owned local fixture paths, not shell commands.
    listing=folder/'concat.txt';listing.write_text(''.join("file '"+r['path'].replace("'","'\\''")+"'\n" for r in rows))
    target=folder/'input.wav'
    subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-nostdin','-v','error','-f','concat','-safe','0','-i',str(listing),'-ac','1','-ar','48000','-c:a','pcm_s16le',str(target)],check=True)
    with wave.open(str(target)) as w:duration=w.getnframes()/w.getframerate()
    assert duration>780
    provenance={'input_type':'65 human read-speech files concatenated once each; not a continuous lecture','duration_seconds':duration,'sha256':tr.file_hash(target),'license':'CC BY 4.0','attribution':'Google FLEURS, Conneau et al. (2022), dataset revision 70bb2e84b976b7e960aa89f1c648e09c59f894dd','source_manifests':['human-audio-20261013/provenance.json','asr-comparison-20261013/manifest.json','diverse-audio-20261014/manifest.json'],'clips':[{k:r.get(k) for k in ('path','row_idx','sha256','source_row_url','reference_raw_transcription','reference','duration_seconds')} for r in rows]}
    (folder/'input-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
    return target,provenance

if __name__=='__main__':
    model=sys.argv[4] if len(sys.argv)>4 else 'qwen3.5:4b'
    mode='after_stop' if 'after-stop' in sys.argv[5:] else 'realtime'
    folder=Path(sys.argv[1]).resolve()
    if folder.exists():raise SystemExit('Use a new disposable folder')
    folder.mkdir(parents=True)
    if len(sys.argv)>2:
        original=Path(sys.argv[2]).resolve(strict=True);audio=folder/'input.wav'
        subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-nostdin','-v','error','-i',str(original),'-ac','1','-ar','48000','-c:a','pcm_s16le',str(audio)],check=True)
        with wave.open(str(audio)) as w:duration=w.getnframes()/w.getframerate()
        assert duration>600
        sidecar=json.loads(original.with_suffix('.json').read_text())
        provenance={'input_type':sidecar.get('input_type','continuous human Korean narration; not a lecture or meeting'),'duration_seconds':duration,'sha256':tr.file_hash(audio),'original_sha256':tr.file_hash(original),'source':sidecar}
        (folder/'input-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
    else:audio,provenance=prepare_audio(folder)
    listener=bind_listener();port=listener.getsockname()[1]
    trace={'ready':False,'model':model,'transcription_mode':mode,'input':provenance,'asr':[],'asr_review':[],'generation':[],'samples':[],'runs':[]}
    def save():(folder/'trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
    original_asr=server.process_chunk
    async def traced_asr(db,chunk,runtime):
        item={k:chunk[k] for k in ('id','recording_id','start_frame','end_frame','final','revision')};item['started']=time.time();trace['asr'].append(item)
        try:return await original_asr(db,chunk,runtime)
        finally:item['ended']=time.time();item['status']=db.execute('SELECT status FROM transcript_ranges WHERE id=?',(chunk['id'],)).fetchone()[0];save()
    server.process_chunk=traced_asr
    original_review=server.process_review
    async def traced_review(db,job,runtime):
        item={'job_id':job['id'],'recording_id':job['request']['recording_id'],'started':time.time()};trace['asr_review'].append(item)
        try:return await original_review(db,job,runtime)
        finally:item['ended']=time.time();save()
    server.process_review=traced_review
    original_generate=answers.generate
    async def traced_generate(*args,**kwargs):
        item={'submitted':time.time(),'model':args[0].model};trace['generation'].append(item);before=kwargs.get('before_local')
        async def gate():
            if before:await before()
            item['request_started']=time.time();save()
        kwargs['before_local']=gate
        try:
            result=await original_generate(*args,**kwargs);item.update(usage=result.usage,provider_elapsed_ms=result.elapsed_ms,digest=result.digest);return result
        finally:item['ended']=time.time();save()
    answers.generate=outputs.generate=traced_generate
    app=server.create_app(AppConfig(folder/'data',RUNTIME,port=port))
    app.routes[:]=[route for route in app.routes if route.name!='frontend']
    sid=create_session(app.state.db,'lecture','긴 사람 음성 동시 실행 검증',None,None).id
    save_note(app.state.db,sid,'프로세스는 실행 중인 프로그램이며 독립된 주소 공간을 갖습니다. 스레드는 프로세스의 메모리를 공유하며 공유 자원 접근에 동기화가 필요합니다.')
    @app.get('/api/fixture/audio')
    async def source_audio():return FileResponse(audio,media_type='audio/wav')
    @app.post('/api/fixture/telemetry')
    async def telemetry(body:dict):
        if 'capture_route' in body:trace['capture_route']=body['capture_route']
        trace['runs']=body.get('runs',[]);trace['samples']=body.get('samples',[]);trace['ready']=body.get('ready',False)
        if trace['ready']:assert all(run.get('done') and not run.get('recording_error') and run.get('last_state',{}).get('seconds',0)>=provenance['duration_seconds']-.1 for run in trace['runs']),'Cannot mark an incomplete recording as successful'
        with (folder/'host-samples.jsonl').open('a') as handle:handle.write(json.dumps({'at':time.time(),'swapusage':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip(),'free_bytes':shutil.disk_usage(folder).free})+'\n')
        save();return {'saved':True}
    entry=folder/'fixture.tsx';entry.write_text('import {mount} from '+json.dumps(str(ROOT/'frontend/tests/long-recording-fixture.tsx'))+';mount('+json.dumps(sid)+','+str(provenance['duration_seconds'])+','+('false' if 'single' in sys.argv[3:] else 'true')+','+json.dumps(provenance['input_type'])+','+json.dumps(model)+','+json.dumps(mode)+','+('true'if 'direct'in sys.argv[5:]else'false')+');')
    (folder/'index.html').write_text('<html lang="ko"><meta charset="utf-8"><title>긴 사람 음성 동시 실행 검증</title><div id="root"></div><script type="module" src="./fixture.tsx"></script></html>')
    subprocess.run(['node','--input-type=module','-e',"import {build} from 'vite';await build({configFile:false,root:process.argv[1],build:{assetsInlineLimit:0,outDir:'dist'}});",str(folder)],cwd=ROOT/'frontend',check=True)
    if app.routes[-1].name=='frontend':app.routes.pop()
    app.mount('/',StaticFiles(directory=folder/'dist',html=True))
    url=f'http://127.0.0.1:{port}/#bootstrap='+app.state.bootstrap_token
    (folder/'info.json').write_text(json.dumps({'url':url,'session_id':sid,'folder':str(folder)}));save();print(url,flush=True)
    try:uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False)).run(sockets=[listener])
    except KeyboardInterrupt:pass
    finally:listener.close()
