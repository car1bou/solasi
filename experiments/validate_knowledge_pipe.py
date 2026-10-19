"""Exercise the bundled no-port engine in an isolated vault with real audio replay."""
import argparse,asyncio,json,os,sqlite3,struct,time,wave,hashlib,shutil
from pathlib import Path

class Pipe:
 def __init__(self,engine,vault,runtime,log):self.engine,self.vault,self.runtime,self.log=engine,vault,runtime,log;self.counter=0
 async def start(self):
  env=dict(os.environ);env.pop('SOLASI_OWNER_PID',None)
  self.process=await asyncio.create_subprocess_exec(str(self.engine),'--data-dir',str(self.vault),'--runtime-dir',str(self.runtime),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=self.log,env=env)
  h,_=await self.frame();assert h.get('event')=='ready',h
 async def frame(self):
  size=struct.unpack('>I',await self.process.stdout.readexactly(4))[0];h=json.loads(await self.process.stdout.readexactly(size));b=await self.process.stdout.readexactly(h['body_length']);return h,b
 async def send(self,op,body=b'',**fields):
  self.counter+=1;ident=str(self.counter);h=json.dumps(dict(version=1,id=ident,op=op,body_length=len(body),**fields)).encode();self.process.stdin.write(struct.pack('>I',len(h))+h+body);await self.process.stdin.drain();return ident
 async def receive(self,ident):
  chunks=[];status=None
  while True:
   h,b=await asyncio.wait_for(self.frame(),180)
   if h.get('id')!=ident:continue
   if h['event']=='response_start':status=h['status']
   elif h['event']=='body':chunks.append(b);await self.send('ack',target=ident,sequence=h['sequence'])
   elif h['event'] in ('complete','error'):return status,b''.join(chunks),h
 async def http(self,method,path,data=None):
  ident=await self.send('http',json.dumps(data,ensure_ascii=False).encode() if data is not None else b'',method=method,path=path,headers={});status,body,h=await self.receive(ident)
  assert status is not None and 200<=status<300,(path,status,body[:300],h)
  return json.loads(body) if body else None
 async def audio(self,sid,pcm,rate,mode='after_stop'):
  r=await self.http('POST',f'/api/sessions/{sid}/audio/start',{'sample_rate':rate,'transcription_mode':mode});stream=await self.send('audio_open',session_id=sid,recording_id=r['recording_id'],sample_rate=rate);_,_,h=await self.receive(stream);assert h['payload']['type']=='ready';return r['recording_id'],stream
 async def packet(self,stream,seq,offset,data):
  ident=await self.send('audio_packet',struct.pack('<QQI',seq,offset,len(data)//2)+data,stream_id=stream);_,_,h=await self.receive(ident);assert h['payload']['stored_frames']==offset+len(data)//2,h
 async def stop(self):
  if hasattr(self,'process') and self.process.returncode is None:self.process.stdin.close();await asyncio.wait_for(self.process.wait(),15)

async def main(a):
 a.output.mkdir(parents=True,exist_ok=True);fixture=json.loads(a.fixture.read_text());vault=a.output/'vault';vault.mkdir()
 source=sqlite3.connect(Path(fixture['vault'])/'app.sqlite3');dest=sqlite3.connect(vault/'app.sqlite3');source.backup(dest);source.close();dest.close()
 if (Path(fixture['vault'])/'assets').exists():shutil.copytree(Path(fixture['vault'])/'assets',vault/'assets')
 log=(a.output/'engine.log').open('wb');client=Pipe(a.engine.resolve(),vault.resolve(),a.runtime.resolve(),log);report={};started=time.monotonic()
 try:
  await client.start();cid,sid,aid,digest=fixture['course'],fixture['current'],fixture['asset'],fixture['digest']
  document_path=f'/api/courses/{cid}/assets/{aid}/pages/1/document'
  document=await client.http('GET',document_path+'?document_sha256='+digest)
  document['ink'][0]['id']='qa-'+str(time.monotonic_ns())
  await client.http('PUT',document_path,{'document_sha256':digest,'expected_revision':document['revision'],'text':document['text'],'ink':document['ink']})
  await client.http('PUT','/api/knowledge/options',{'enabled':True})
  path=f'/api/courses/{cid}/assets/{aid}/pages/1/handwriting'
  for _ in range(90):
   rows=await client.http('GET',path+'?document_sha256='+digest)
   rows=[r for r in rows if r['status']=='candidate']
   if rows:break
   await asyncio.sleep(1)
  assert rows,'no automatic handwriting candidate';candidate=rows[0];report['automatic_candidate']=candidate['status']=='candidate'
  ref=await client.http('PUT',f'/api/courses/{cid}/handwriting/{candidate["id"]}/approve',{'text':'검증용 선','expected_ink_hash':candidate['ink_hash']})
  detail=await client.http('GET','/api/sources/'+ref['id']);assert detail['ink_snapshot'];report['approved_source_ink']=True
  found=await client.http('POST',f'/api/sessions/{sid}/search',{'query':'검증용 선','scope':{'session_id':sid}})
  if 'kind' in found:
   for _ in range(120):
    found=await client.http('GET','/api/jobs/'+found['id'])
    if found['status'] not in ('queued','running'):break
    await asyncio.sleep(1)
   assert found['status']=='done',found;found=found['result']
  assert any(e['ref']['id']==ref['id'] for e in found['evidence']);report['approved_searchable']=True
  suggestions=await client.http('GET',f'/api/knowledge/suggestions?course_id={cid}&asset_id={aid}&page=1')
  assert isinstance(suggestions,list);report['suggestions_api']=True
  with wave.open(str(a.audio),'rb') as f:rate=f.getframerate();assert f.getsampwidth()==2 and f.getnchannels()==1;pcm=f.readframes(f.getnframes())
  rid,stream=await client.audio(sid,pcm,rate)
  summary=await client.http('POST','/api/ai/jobs',{'session_id':sid,'kind':'summary','prompt':'확정된 기록의 핵심을 원문으로 요약하세요.','scope':{'session_id':sid}})
  paused=await client.http('GET','/api/knowledge/status');assert not paused['idle'];report['background_yields_recording']=True
  offset=0
  for seq,start in enumerate(range(0,len(pcm),16000)):
   packet=pcm[start:start+16000];await client.packet(stream,seq,offset,packet);offset+=len(packet)//2
  transcription=await client.http('POST',f'/api/recordings/{rid}/stop',{'end_frame':offset});ident=await client.send('audio_close',stream_id=stream);await client.receive(ident)
  for _ in range(180):
   t=await client.http('GET','/api/jobs/'+transcription['id']);s=await client.http('GET','/api/jobs/'+summary['id'])
   if t['status'] not in ('queued','running') and s['status'] not in ('queued','running'):break
   await asyncio.sleep(1)
  report['transcription_status']=t['status'];report['summary_status']=s['status'];report['summary_error']=s.get('error');report['transcription_error']=t.get('error')
  assert t['status']=='done',t;assert s['status']=='done',s
  raw=vault/'audio'/rid/'raw.wav'
  with wave.open(str(raw),'rb') as f:assert f.readframes(f.getnframes())==pcm
  report['audio_frames']=offset;report['pcm_exact']=True
  await client.http('PUT','/api/knowledge/options',{'enabled':False})
  second,stream=await client.audio(sid,pcm,rate);await client.packet(stream,0,0,pcm[:16000]);second_path=vault/'audio'/second/'raw.wav';before=hashlib.sha256(second_path.read_bytes()).hexdigest()
  client.process.kill();await client.process.wait();await client.start()
  records=await client.http('GET',f'/api/sessions/{sid}/recordings');recovered=next(r for r in records if r['id']==second)
  assert recovered['status']=='interrupted' and recovered['stored_frames']==8000
  assert hashlib.sha256(second_path.read_bytes()).hexdigest()==before
  detail=await client.http('GET','/api/sources/'+ref['id']);assert detail['ink_snapshot'] and detail['text_snapshot']=='검증용 선'
  doc=await client.http('GET',f'/api/courses/{cid}/assets/{aid}/pages/1/document?document_sha256={digest}');assert doc['text']=='필기 저장·복구 검증 메모' and doc['ink']
  report.update(force_kill_pcm_recovery=True,ink_and_note_preserved=True,approved_source_preserved=True,elapsed_seconds=time.monotonic()-started,finished=True)
 finally:
  await client.stop();log.close();(a.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ('engine','runtime','fixture','audio','output'):p.add_argument('--'+name,type=Path,required=True)
 asyncio.run(main(p.parse_args()))
