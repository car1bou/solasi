"""Pinned public audio evaluation; full-clip models and product route stay distinct."""
import argparse,array,ast,hashlib,json,platform,re,resource,subprocess,tempfile,time,unicodedata,wave
from datetime import datetime,timezone
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--engine',choices=['turbo','small','komix','qwen'],required=True);parser.add_argument('--route',choices=['full','product'],default='full');parser.add_argument('--groups',default='fleurs40,pansori24,deeply18,lowgain5,snr105');parser.add_argument('--output-name');parser.add_argument('--chunk-seconds',type=int,choices=(20,30),default=30);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];runtime=root/'.local-state/runtime';folder=runtime/'diverse-audio-20261014';manifest=json.loads((folder/'manifest.json').read_text());assert manifest['ready']
clips=[c for c in manifest['clips'] if c['group'] in args.groups.split(',')];assert clips
if args.route=='product':assert args.engine=='turbo'
# Reuse exactly the existing diagnostic score in the isolated Qwen environment.
module=ast.parse((root/'tests/evaluate_human_audio.py').read_text());functions=[n for n in module.body if isinstance(n,ast.FunctionDef) and n.name in ('normalize','edit_distance','score')];assert len(functions)==3
exec(compile(ast.Module(body=functions,type_ignores=[]),'existing_metrics','exec'));assert score('가 나','가나')['cer']==0
output=folder/(args.output_name or args.engine+'-'+args.route+('-30s' if args.route=='product' and args.chunk_seconds==30 else '')+'.json');report={'tested_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'engine':args.engine,'route':args.route,'product_chunk_seconds':args.chunk_seconds if args.route=='product' else None,'groups_requested':args.groups,'dataset_metadata':manifest['datasets'],'normalization':'Diagnostic NFKC/lowercase Unicode letters/numbers only, spaces/punctuation removed; numerals and parenthetical Romanizations count; not official corpus score.','limitations':manifest['limitations']+['One run; no statistical population ranking.','CPP Metal loads model for each clip; QwenMLX4bit loads once. Precision and loading differ; latency is not controlled architecture comparison.'],'clips':[],'aggregate':{},'ready':False}
def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save():
 temp=output.with_suffix('.partial');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2));temp.replace(output)
model=None;meta={}
if args.engine=='qwen':
 import os
 assert os.environ.get('HF_HUB_OFFLINE')=='1' and os.environ.get('TRANSFORMERS_OFFLINE')=='1'
 import mlx.core as mx
 from mlx_audio.stt.utils import load_model
 location=runtime/'qwen3-asr-1.7b-4bit';provenance=json.loads((location/'provenance.json').read_text());assert provenance['ready'] and provenance['auto_map_absent'];weights=location/'model.safetensors'
 expected=next(c['hash'] for c in provenance['files'] if c['file']=='model.safetensors');assert digest(weights)==expected
 began=time.perf_counter();model=load_model(location,strict=True);mx.synchronize();report['load_seconds']=time.perf_counter()-began
 report['model']={'name':provenance['model'],'revision':provenance['revision'],'sha256':expected,'license':provenance['license']};report['options']={'temperature':0,'language':'Korean','max_tokens':1024,'hotwords':None};report['limitations'].append('Qwen segment times are input ranges, not learned sentence/word alignment; MLX allocator peak is not total system RAM.')
else:
 from lecture_study.transcription import parse_segments,VAD_SHA
 if args.engine=='small':meta=json.loads((runtime/'human-audio-20261013/official-small-comparison.json').read_text())['model_metadata']['small'];weights=Path(meta['path'])
 else:
  name,provenance={'turbo':('ggml-large-v3-turbo.bin','turbo-provenance.json'),'komix':('ggml-medium-komixv2.bin','komixv2-ggml-provenance.json')}[args.engine];weights=runtime/'models'/name;meta=json.loads((runtime/'models'/provenance).read_text())
 assert weights.stat().st_size==meta['bytes'] and digest(weights)==meta['sha256'];vad=runtime/'models/ggml-silero-v6.2.0.bin';assert digest(vad)==VAD_SHA
 report['model']={k:v for k,v in meta.items() if k not in ('path','url','resolved_url')};report['options']={'language':'ko','backend':'native Metal','vad':'Silero6.2.0 defaults','hints':None,'cpp':'1.9.5'}
save()
for clip in clips:
 source=Path(clip['path']);assert digest(source)==clip['sha256'];row={k:v for k,v in clip.items() if k not in ('path','source_url')};began=time.perf_counter()
 try:
  if args.engine=='qwen':
   mx.reset_peak_memory();result=model.generate(str(source),language='Korean',temperature=0.0,batch_size=1,max_tokens=1024,verbose=False);mx.synchronize();assert result.generation_tokens<1024
   recognized=result.text;row['mlx_peak_bytes']=mx.get_peak_memory();row['segments']=result.segments
  elif args.route=='product':
   import asyncio
   from lecture_study.db import open_db,create_session
   from lecture_study.transcription import register_audio,process_pending,transcription_status,list_transcripts
   import lecture_study.transcription as transcription
   transcription.CHUNK_SECONDS=args.chunk_seconds
   async def product():
    with tempfile.TemporaryDirectory(prefix='lecture-diverse-product-') as temporary:
     db=open_db(Path(temporary));sid=create_session(db,'lecture','공개 음성 검증',None,None).id
     try:
      rid=await register_audio(db,sid,source,runtime);await process_pending(db,rid,runtime);status=transcription_status(db,rid)
      assert not status['failed'] and not status['queued'] and not status['running'];segments=list_transcripts(db,sid)
      assert all(s['final'] and 0<=s['start_ms']<s['end_ms']<=round(clip['duration_seconds']*1000) for s in segments)
      return ' '.join(s['text'] for s in segments),segments,status
     finally:db.close()
   recognized,segments,status=asyncio.run(product());row['segments']=segments;row['status']=status
  else:
   with tempfile.TemporaryDirectory(prefix='lecture-diverse-native-') as temporary:
    temporary=Path(temporary);pcm=temporary/'pcm.wav';prefix=temporary/'result'
    subprocess.run([str(runtime/'ffmpeg/bin/ffmpeg'),'-v','error','-nostdin','-y','-i',str(source),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(pcm)],check=True)
    result=subprocess.run(['/usr/bin/time','-l',str(runtime/'build/whisper/bin/whisper-cli'),'-m',str(weights),'-f',str(pcm),'-l','ko','-oj','-of',str(prefix),'-np','--vad','-vm',str(vad)],capture_output=True,timeout=300)
    assert result.returncode==0,result.stderr.decode(errors='replace')[-1000:]
    segments=parse_segments(json.loads(prefix.with_suffix('.json').read_text()),round(clip['duration_seconds']*1000));recognized=' '.join(s['text'] for s in segments);row['segments']=segments
    peak=re.search(r'(\d+)\s+maximum resident set size',result.stderr.decode(errors='replace'));assert peak;row['peak_rss_bytes']=int(peak.group(1))
  row.update(recognized=recognized,elapsed_seconds=time.perf_counter()-began,**score(clip['reference'],recognized));row['processing_seconds_per_audio_second']=row['elapsed_seconds']/clip['duration_seconds'];row['success']=True
 except Exception as exc:row.update(success=False,error=str(exc),elapsed_seconds=time.perf_counter()-began)
 assert digest(source)==clip['sha256'];report['clips'].append(row);save();print(json.dumps({'engine':args.engine,'route':args.route,'group':clip['group'],'completed':len(report['clips']),'total':len(clips),'success':row['success'],'cer':row.get('cer')},ensure_ascii=False),flush=True)
for group in args.groups.split(','):
 selected=[r for r in report['clips'] if r['group']==group];rows=[r for r in selected if r['success']];chars=sum(r['reference_chars'] for r in rows);edits=sum(r['edits'] for r in rows);seconds=sum(r['duration_seconds'] for r in rows);elapsed=sum(r['elapsed_seconds'] for r in rows)
 report['aggregate'][group]={'clips':len(selected),'successful':len(rows),'failed':len(selected)-len(rows),'edits':edits,'reference_chars':chars,'cer':edits/chars if chars else None,'audio_seconds':seconds,'elapsed_seconds':elapsed,'processing_seconds_per_audio_second':elapsed/seconds if seconds else None}
report['originals_untouched']=True;report['ready']=all(r['success'] for r in report['clips']);assert digest(weights)==(expected if args.engine=='qwen' else meta['sha256']);save();print(json.dumps({'ready':report['ready'],'aggregate':report['aggregate']},ensure_ascii=False),flush=True)
if not report['ready']:raise SystemExit(1)
