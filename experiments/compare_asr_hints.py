"""Offline, fixed-audio vocabulary ablation; raw results stay outside public docs."""
import argparse,ast,asyncio,hashlib,importlib.metadata,json,os,sys,time,unicodedata
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
        for condition in condition_sequence(args.reverse_order):
            terms=condition_terms(clip,condition);row={'id':clip['id'],'sha256':clip['sha256'],'group':clip['group'],'category':clip['category'],'condition':condition,'terms':terms,'reference':clip['reference'],'hint_provenance':clip['hint_provenance']};started=time.perf_counter()
            try:
                if args.engine=='qwen':
                    mx.reset_peak_memory();result=model.generate(clip['path'],language='Korean',temperature=0.0,batch_size=1,max_tokens=1024,verbose=False,hotwords=terms)
                    mx.synchronize();text=result.text;row.update(prompt_tokens=result.prompt_tokens,generation_tokens=result.generation_tokens,mlx_peak_bytes=mx.get_peak_memory(),system_prompt=merge_hotwords(None,terms))
                    if result.generation_tokens>=1024:raise ValueError('Generation reached token limit')
                else:
                    segments=await tr.transcribe_range(Path(clip['path']),0,', '.join(terms),args.runtime,padding_ms=1000)
                    text=' '.join(s['text']for s in segments);row['segments']=segments
                row.update(recognized=text,**shared['score'](clip['reference'],text),**shared['character_errors'](clip['reference'],text),**vocabulary_counts(clip['reference'],text,terms),status='ok')
            except Exception as error:row.update(status='failed',error=str(error))
            row['seconds']=time.perf_counter()-started
            if digest(clip['path'])!=clip['sha256']:raise ValueError('Audio changed during inference')
            report['rows'].append(row);save();print(clip['id'],condition,row['status'],row.get('edits'),round(row['seconds'],3),flush=True)
    report['completed']=True;save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--engine',choices=['whisper','qwen'],required=True);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--reverse-order',action='store_true')
    asyncio.run(main(parser.parse_args()))
