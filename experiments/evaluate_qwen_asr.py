"""Isolated MLX Qwen3-ASR comparison; original audio, no hints or reference input."""
import ast,hashlib,importlib.metadata,json,os,platform,resource,time,unicodedata
from datetime import datetime,timezone
from pathlib import Path
app=Path(__file__).resolve().parents[1]
runtime=app/".local-state/runtime"
model_path=runtime/'qwen3-asr-1.7b-4bit'
output=runtime/'asr-comparison-20261013/qwen3-asr-1.7b-mlx-q4.json'
assert os.environ.get('HF_HUB_OFFLINE')=='1' and os.environ.get('TRANSFORMERS_OFFLINE')=='1'
provenance=json.loads((model_path/'provenance.json').read_text())
assert provenance['ready'] and provenance['auto_map_absent']
weights=model_path/'model.safetensors'
expected=next(row['hash'] for row in provenance['files'] if row['file']=='model.safetensors')
with weights.open('rb') as handle: assert hashlib.file_digest(handle,'sha256').hexdigest()==expected
# Reuse only the existing pure metric functions, keeping app dependencies out of this environment.
metrics=ast.parse((app/'tests/evaluate_human_audio.py').read_text())
selected=[node for node in metrics.body if isinstance(node,ast.FunctionDef) and node.name in ('normalize','edit_distance','score')]
assert len(selected)==3
exec(compile(ast.Module(body=selected,type_ignores=[]),'shared_diagnostic_metrics','exec'))
assert score('가 나','가나')['cer']==0 and score('가나다','가마')['edits']==2
sources=[('familiar5',runtime/'human-audio-20261013/provenance.json'),('additional20',runtime/'asr-comparison-20261013/manifest.json')]
clips=[]
for group,path in sources:
 source=json.loads(path.read_text())
 assert group!='additional20' or source['ready']
 for fixture in source['clips']:clips.append((group,fixture))
assert len(clips)==25
started=time.perf_counter()
import mlx.core as mx
from mlx_audio.stt.utils import load_model
import_elapsed=time.perf_counter()-started
load_started=time.perf_counter();model=load_model(model_path,strict=True);mx.synchronize();load_elapsed=time.perf_counter()-load_started
report={'tested_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'machine':platform.machine(),'model':provenance['model'],'revision':provenance['revision'],'model_sha256':next(row['hash'] for row in provenance['files'] if row['file']=='model.safetensors'),'model_kind':provenance['artifact_kind'],'model_license':provenance['license'],'versions':{p:importlib.metadata.version(p) for p in ('mlx-audio','mlx','transformers','numpy','huggingface_hub')},'options':{'language':'Korean','temperature':0.0,'batch_size':1,'max_tokens':1024,'system_prompt':None,'hotwords':None,'stream':False},'cold_import_seconds':import_elapsed,'model_load_seconds':load_elapsed,'normalization':'Diagnostic CER: NFKC, lowercase, Unicode letters/numbers only; spaces/punctuation removed; numeral spelling alternatives count as errors. Not official FLEURS normalization.','limitations':['Community MLX text-weight quantization; not official BF16 model scores.','One run per clip; files may be cached; not a representative Korean meeting benchmark.','All input clips are human read speech. Speaker IDs absent. Training overlap unknown.','Additional20 includes repeat sentences and one sentence shared with familiar5, with different recordings.','ASR segment timestamps are input chunk ranges, not learned word or sentence timing.','MLX peak memory is allocator peak, not whole-system RAM; process max RSS is cumulative.','No microphone capture, real-time PCM input, forced alignment, or concurrent LLM measurement.','Reference transcripts used only for scoring after inference; no prompts/hotwords beyond language mode supplied.'],'clips':[],'aggregate':{},'ready':False}
def save():
 temp=output.with_suffix('.json.partial');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2));temp.replace(output)
save();print(json.dumps({'status':'model_loaded','import_seconds':import_elapsed,'load_seconds':load_elapsed,'active_mlx_bytes':mx.get_active_memory()}),flush=True)
for group,fixture in clips:
 path=Path(fixture['path']);digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==fixture['sha256']
 mx.reset_peak_memory();started=time.perf_counter()
 result=model.generate(str(path),language='Korean',temperature=0.0,batch_size=1,max_tokens=1024,verbose=False)
 mx.synchronize();elapsed=time.perf_counter()-started
 assert result.generation_tokens<1024,'Generation reached token limit'
 assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
 row={'group':group,'row_idx':fixture['row_idx'],'id':fixture['id'],'duration_seconds':fixture['duration_seconds'],'sha256':digest,'reference':fixture['reference_raw_transcription'],'recognized':result.text,'segments':result.segments,'language':result.language,'prompt_tokens':result.prompt_tokens,'generation_tokens':result.generation_tokens,'elapsed_seconds':elapsed,'processing_seconds_per_audio_second':elapsed/fixture['duration_seconds'],'mlx_peak_bytes':mx.get_peak_memory(),'mlx_active_bytes':mx.get_active_memory(),'mlx_cache_bytes':mx.get_cache_memory(),'process_cumulative_max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**score(fixture['reference_raw_transcription'],result.text)}
 report['clips'].append(row);save();print(json.dumps({k:row[k] for k in ('group','row_idx','cer','elapsed_seconds','mlx_peak_bytes')},ensure_ascii=False),flush=True)
for group in ('familiar5','additional20','all25'):
 rows=[row for row in report['clips'] if group=='all25' or row['group']==group];edits=sum(row['edits'] for row in rows);chars=sum(row['reference_chars'] for row in rows);duration=sum(row['duration_seconds'] for row in rows);elapsed=sum(row['elapsed_seconds'] for row in rows)
 report['aggregate'][group]={'clips':len(rows),'edits':edits,'reference_chars':chars,'cer':edits/chars,'duration_seconds':duration,'elapsed_seconds':elapsed,'processing_seconds_per_audio_second':elapsed/duration,'max_mlx_peak_bytes':max(row['mlx_peak_bytes'] for row in rows)}
with weights.open('rb') as handle: assert hashlib.file_digest(handle,'sha256').hexdigest()==expected
report['ready']=True;save();print(json.dumps({'ready':True,'output':str(output),'aggregate':report['aggregate']},ensure_ascii=False),flush=True)
