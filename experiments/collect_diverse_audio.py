"""Fetch fixed public originals and recreate only CC-BY stress fixtures."""
import array,hashlib,json,math,random,struct,subprocess,wave
from datetime import datetime,timezone
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1];runtime=root/'.local-state/runtime';folder=runtime/'diverse-audio-20261014';folder.mkdir(exist_ok=True)
pansori=json.loads((root/'docs/verification/pansori-selection.json').read_text());assert len(pansori['clips'])==24
manifest={'created_at_utc':datetime.now(timezone.utc).isoformat(),'selection_before_asr':'FLEURS ko_kr/test rows28..67 plus fixed Pansori24 manifest; stress at indices0,8,16,24,32 before any model results','ready':False,'clips':[],'limitations':['FLEURS speaker IDs absent; no 40speaker claim.','Pansori utterance clips are lecture excerpts, not continuous full lectures or meeting conversations.','Stress audio is derived FLEURS with deterministic noise/gain, not field microphone recordings.','Training overlap for all models unknown.'],'datasets':{'fleurs':{'dataset':'google/fleurs','license':'CC-BY-4.0','revision':'70bb2e84b976b7e960aa89f1c648e09c59f894dd','source_url':'https://huggingface.co/datasets/google/fleurs'},'pansori':{k:pansori[k] for k in ('repo','revision','license','selection')}}}
manifest['datasets']['pansori']['source_url']='https://github.com/yc9701/pansori-tedxkr-corpus';manifest['datasets']['pansori']['attribution']='Chang-hyun Choi (2018), Pansori: A Korean Speech Corpus for Public Speech'
output=folder/'manifest.json'
def save():output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
def fetch(url,target,expected=None,size=None,git_sha=None):
 if target.exists():data=target.read_bytes()
 else:
  response=client.get(url);response.raise_for_status();data=response.content
  assert len(data)<10*1024*1024;target.write_bytes(data)
 if expected:assert hashlib.sha256(data).hexdigest()==expected
 if size:assert len(data)==size
 if git_sha:assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==git_sha
 return hashlib.sha256(data).hexdigest(),len(data)
def pcm(source,target):
 subprocess.run([str(runtime/'ffmpeg/bin/ffmpeg'),'-v','error','-nostdin','-y','-i',str(source),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(target)],check=True)
 with wave.open(str(target)) as w:return w.getnframes()/w.getframerate()
with httpx.Client(timeout=60,follow_redirects=True,trust_env=False) as client:
 url='https://datasets-server.huggingface.co/rows?dataset=google%2Ffleurs&config=ko_kr&split=test&offset=28&length=40'
 rows=client.get(url);rows.raise_for_status();body=rows.json();(folder/'rows-response.json').write_text(json.dumps(body,ensure_ascii=False));assert len(body['rows'])==40
 for rec in body['rows']:
  row=rec['row'];idx=rec['row_idx'];assert 28<=idx<68;audio=row['audio'][0]['src'];assert '/70bb2e84b976b7e960aa89f1c648e09c59f894dd/' in audio
  target=folder/f'fleurs-{idx:04d}.wav';digest,size=fetch(audio,target);length=pcm(target,folder/'inspection.wav')
  clip={'group':'fleurs40','id':f'fleurs-{idx:04d}','row_idx':idx,'path':str(target),'sha256':digest,'bytes':size,'duration_seconds':length,'reference':row['raw_transcription'],'speaker_id':None,'gender_class':row.get('gender'),'dataset_id':row['id'],'license':'CC-BY-4.0','revision':manifest['datasets']['fleurs']['revision'],'source_url':url}
  manifest['clips'].append(clip);save()
 for rec in pansori['clips']:
  target=folder/(rec['id']+'.flac');digest,size=fetch(rec['audio_url'],target,rec['sha256'],rec['bytes'],rec['git_blob_sha'])
  clip={'group':'pansori24','id':rec['id'],'row_idx':None,'path':str(target),'sha256':digest,'bytes':size,'duration_seconds':rec['duration_s'],'reference':rec['reference_text'],'speaker_id':rec['speaker_id'],'talk_title':rec['talk_title'],'license':pansori['license'],'revision':pansori['revision'],'source_url':rec['audio_url'],'transcript_sha256':rec['transcript_sha256']}
  manifest['clips'].append(clip);save()
# Only CC-BY FLEURS is transformed; Pansori originals remain unchanged.
for idx in (0,8,16,24,32):
 source=manifest['clips'][idx];pcm(Path(source['path']),folder/'inspection.wav')
 with wave.open(str(folder/'inspection.wav')) as w: values=array.array('h',w.readframes(w.getnframes()))
 rms=math.sqrt(sum(v*v for v in values)/len(values));generator=random.Random(20261014+idx)
 for kind in ('lowgain','snr10'):
  modified=array.array('h',(max(-32768,min(32767,round(v*.1 if kind=='lowgain' else v+generator.gauss(0,rms/math.sqrt(10))))) for v in values))
  target=folder/(source['id']+'-'+kind+'.wav')
  with wave.open(str(target),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(modified.tobytes())
  manifest['clips'].append(source|{'id':source['id']+'-'+kind,'group':kind+'5','path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'derived_from':source['id'],'modification':'gain0.1' if kind=='lowgain' else 'seeded Gaussian white noise; RMS SNR10dB before clipping'})
  save()
# Ten minutes or more of concatenated human read-speech, no claim of spontaneous lecture.
long=folder/'fleurs-long.wav';reference=[];seconds=0
with wave.open(str(long),'wb') as w:
 w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
 while seconds<600:
  for source in manifest['clips'][:40]:
   pcm(Path(source['path']),folder/'inspection.wav')
   with wave.open(str(folder/'inspection.wav')) as clip:w.writeframes(clip.readframes(clip.getnframes()))
   seconds+=source['duration_seconds'];reference.append(source['reference'])
   if seconds>=600:break
manifest['clips'].append({'id':'fleurs-long','group':'long1','path':str(long),'sha256':hashlib.sha256(long.read_bytes()).hexdigest(),'bytes':long.stat().st_size,'duration_seconds':seconds,'reference':' '.join(reference),'speaker_id':None,'license':'CC-BY-4.0','modification':'Concatenated existing new FLEURS clips until >=600s; repeated samples if needed, no independent new speech.'})
(folder/'inspection.wav').unlink();assert len(manifest['clips'])==75
source=json.loads((root/'docs/verification/deeply-selection.json').read_text())
with httpx.Client(timeout=60,follow_redirects=True,trust_env=False) as client:
 for rec in source['clips']:
  target=folder/(rec['id']+'.wav')
  if not target.exists():r=client.get(rec['audio_url']);r.raise_for_status();target.write_bytes(r.content)
  data=target.read_bytes();assert len(data)==rec['bytes'];assert hashlib.sha256(data).hexdigest()==rec['sha256'];assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==rec['git_blob_sha']
  if not any(c['id']==rec['id'] for c in manifest['clips']):manifest['clips'].append({'id':rec['id'],'group':'deeply18','path':str(target),'sha256':rec['sha256'],'bytes':len(data),'duration_seconds':rec['duration_s'],'reference':rec['reference_text'],'speaker_id':rec['speaker_id'],'room':rec['room'],'paired_group_id':rec['paired_group_id'],'voice_sentiment':rec['voice_sentiment'],'device':rec['device'],'distance_m':rec['distance_m'],'license':source['license'],'revision':source['revision'],'source_url':rec['audio_url']})
manifest['datasets']['deeply']={k:source[k] for k in ('repo','revision','license','source_url','selection','metadata_sha256')};manifest['datasets']['deeply']['attribution']='Deeply Inc., Korean Read Speech Corpus public sample'
manifest['limitations'].append('Deeply18 is six matched groups across3rooms,2reported female speakers,5unique sentences,iPhoneX at0.4m; no2/4m or microphone-device comparison.')
assert len(manifest['clips'])==93
manifest['ready']=True;manifest['total_seconds']=sum(c['duration_seconds'] for c in manifest['clips']);manifest['total_bytes']=sum(c['bytes'] for c in manifest['clips']);save()
print(json.dumps({'ready':True,'clips':len(manifest['clips']),'seconds':manifest['total_seconds'],'bytes':manifest['total_bytes'],'groups':{g:len([c for c in manifest['clips'] if c['group']==g]) for g in {c['group'] for c in manifest['clips']}}}),flush=True)
