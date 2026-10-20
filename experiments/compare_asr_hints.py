"""Offline, fixed-audio vocabulary ablation; raw results stay outside public docs."""
import argparse,ast,asyncio,hashlib,importlib.metadata,json,os,sys,tempfile,time,unicodedata,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lecture_study.asr_hints import validate_hotwords


def condition_terms(clip,condition):
    if condition not in('none','relevant','distractor'):raise ValueError('Unknown vocabulary condition')
    return validate_hotwords([]if condition=='none'else clip['hint_terms'if condition=='relevant'else'distractor_terms'])


def condition_sequence(reverse):
    return ('distractor','relevant','none')if reverse else('none','relevant','distractor')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text).lower()if unicodedata.category(c)[0]in('L','N'))


def vocabulary_counts(reference,text,terms):
    ref,out=normalize(reference),normalize(text)
    present=[t for t in terms if normalize(t)in ref];absent=[t for t in terms if normalize(t)not in ref]
    return {'present_terms':present,'correct_terms':[t for t in present if normalize(t)in out],'absent_terms':absent,'absent_terms_in_output':[t for t in absent if normalize(t)in out]}


def occurrence_counts(reference,text,terms):
    ref,out=normalize(reference),normalize(text)
    result=[]
    for term in terms:
        word=normalize(term)
        if not word:raise ValueError('Empty normalized vocabulary')
        expected,observed=ref.count(word),out.count(word)
        result.append({'term':term,'reference':expected,'output':observed,'missing':max(0,expected-observed),'excess':max(0,observed-expected)})
    return result


def split_pcm(path,folder):
    folder.mkdir(parents=True,exist_ok=True);parts=[]
    with wave.open(str(path))as source:
        if(source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('Use mono PCM16 16kHz WAV')
        total=source.getnframes()
        if not total:raise ValueError('Empty audio')
        for start in range(0,total,480000):
            end=min(total,start+480000);raw=source.readframes(end-start)
            if len(raw)!=2*(end-start):raise ValueError('Truncated PCM')
            target=folder/f'{start}.wav'
            with wave.open(str(target),'wb')as handle:
                handle.setparams((1,2,16000,0,'NONE','not compressed'));handle.writeframes(raw)
            parts.append({'path':str(target),'start_frame':start,'end_frame':end,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    return parts


async def main(args):
    if args.output.exists():raise ValueError('Use a fresh output file')
    data=json.loads(args.manifest.read_text());clips=data['clips']
    if not clips or len({c['sha256']for c in clips})!=len(clips):raise ValueError('Empty or duplicate clips')
    digest=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for clip in clips:
        if digest(clip['path'])!=clip['sha256']:raise ValueError('Changed audio')
        for condition in condition_sequence(args.reverse_order):condition_terms(clip,condition)
    metric_tree=ast.parse((Path(__file__).resolve().parents[1]/'tests/evaluate_human_audio.py').read_text())
    metrics={n.name:n for n in metric_tree.body if isinstance(n,ast.FunctionDef)}
    shared={'unicodedata':unicodedata};exec(compile(ast.Module(body=[metrics[n]for n in('normalize','edit_distance','score','character_errors')],type_ignores=[]),'shared_metrics','exec'),shared)
    report={'completed':False,'engine':args.engine,'manifest_sha256':digest(args.manifest),'script_sha256':digest(__file__),'validator_sha256':digest(Path(__file__).resolve().parents[1]/'lecture_study/asr_hints.py'),'condition_order':condition_sequence(args.reverse_order),'rows':[],'timing_scope':'inference per call; Qwen one shared model load, Whisper per-call normalization/model load; compare within each engine','versions':{n:importlib.metadata.version(n)for n in('mlx','mlx-audio','transformers')}}
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    if args.engine=='qwen':
        from lecture_study import qwen_asr
        qwen_asr.verify_files(args.runtime/qwen_asr.ALTERNATIVE)
        import mlx.core as mx
        from mlx_audio.stt.utils import load_model,merge_hotwords
        started=time.perf_counter();model=load_model(args.runtime/qwen_asr.ALTERNATIVE,strict=True);mx.synchronize();report.update(model=qwen_asr.MODEL,load_seconds=time.perf_counter()-started)
    else:
        from lecture_study import transcription as tr
        report.update(model=tr.MODEL_NAME,model_sha256=tr.MODEL_SHA)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        partial=args.output.with_suffix('.json.partial');partial.write_text(json.dumps(report,ensure_ascii=False,indent=2));partial.replace(args.output)
    save()
    for clip in clips:
      with tempfile.TemporaryDirectory(prefix='solasi-hint-eval-')as folder:
        parts=split_pcm(Path(clip['path']),Path(folder));evaluation_terms=list(dict.fromkeys(clip['hint_terms']+clip['distractor_terms']))
        for condition in condition_sequence(args.reverse_order):
            terms=condition_terms(clip,condition);row={'id':clip['id'],'sha256':clip['sha256'],'group':clip['group'],'category':clip['category'],'condition':condition,'terms':terms,'reference':clip['reference'],'hint_provenance':clip['hint_provenance'],'chunks':[]};started=time.perf_counter()
            try:
                for part in parts:
                    chunk={k:v for k,v in part.items()if k!='path'};stamp=time.perf_counter()
                    if digest(part['path'])!=part['sha256']:raise ValueError('Changed chunk')
                    if args.engine=='qwen':
                        mx.reset_peak_memory();result=model.generate(part['path'],language='Korean',temperature=0.0,batch_size=1,max_tokens=1024,verbose=False,hotwords=terms)
                        mx.synchronize();chunk.update(text=result.text,prompt_tokens=result.prompt_tokens,generation_tokens=result.generation_tokens,mlx_peak_bytes=mx.get_peak_memory(),system_prompt=merge_hotwords(None,terms))
                        if result.generation_tokens>=1024:raise ValueError('Generation reached token limit')
                    else:
                        segments=await tr.transcribe_range(Path(part['path']),round(part['start_frame']/16),', '.join(terms),args.runtime,padding_ms=1000)
                        chunk.update(text=' '.join(s['text']for s in segments),segments=segments)
                    chunk['seconds']=time.perf_counter()-stamp;row['chunks'].append(chunk)
                text=' '.join(c['text']for c in row['chunks'])
                scores=shared['score'](clip['reference'],text)if normalize(clip['reference'])else{'edits':len(normalize(text)),'reference_chars':0,'cer':None}
                row.update(recognized=text,**scores,**shared['character_errors'](clip['reference'],text),**vocabulary_counts(clip['reference'],text,evaluation_terms),term_occurrences=occurrence_counts(clip['reference'],text,evaluation_terms),status='ok')
            except Exception as error:row.update(status='failed',error=str(error))
            row['seconds']=time.perf_counter()-started
            if digest(clip['path'])!=clip['sha256']:raise ValueError('Audio changed during inference')
            report['rows'].append(row);save();print(clip['id'],condition,row['status'],row.get('edits'),round(row['seconds'],3),flush=True)
    report['completed']=all(r['status']=='ok'for r in report['rows']);save()
    if not report['completed']:raise RuntimeError('Incomplete conditions; inspect failed rows')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--engine',choices=['whisper','qwen'],required=True);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--reverse-order',action='store_true')
    asyncio.run(main(parser.parse_args()))
