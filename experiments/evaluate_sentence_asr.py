"""Same fixed 90 human clips; references are used only for scoring, no downloads.

Run with app .venv for whisper, existing qwen-eval-venv for qwen.
Raw results contain human transcripts: use /private/tmp, not tracked docs.
"""
import argparse,ast,asyncio,hashlib,json,math,os,time,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
MANIFESTS=('conversation-20261014/manifest.json','speech-conditions-20261014/manifest.json','kmsav-eval-20261015/manifest.json')


def token_scores(body):
    values=[]
    for line in body.splitlines():
        token,separator,value=line.rpartition(b'\t')
        if not separator or not token.strip()or token.startswith((b'[_',b'<|')):continue
        value=float(value)
        if not math.isfinite(value)or not 0<=value<=1:raise ValueError('Invalid token score')
        values.append(value)
    return values


async def main(engine,output):
    if output.exists():raise ValueError('Use a new output file')
    if output.is_relative_to(ROOT)and not output.is_relative_to(RUNTIME):raise ValueError('Human transcript output must stay outside tracked source')
    # Reuse pure metrics without importing app dependencies into the separate MLX environment.
    metric_tree=ast.parse((ROOT/'tests/evaluate_human_audio.py').read_text())
    metrics={n.name:n for n in metric_tree.body if isinstance(n,ast.FunctionDef)}
    exec(compile(ast.Module(body=[metrics[n]for n in ('normalize','edit_distance','score','character_errors')],type_ignores=[]),'shared_metrics','exec'),globals())
    assert score('가 나','가나')['edits']==0 and score('가나다','가마')['edits']==2
    assert token_scores(b'word\t0.5\n[_SOT_]\t1.0\n')==[.5]
    clips=[]
    for name in MANIFESTS:
        clips.extend(json.loads((RUNTIME/name).read_text())['clips'])
    assert len(clips)==90 and len({c['sha256']for c in clips})==90
    report={'completed':False,'engine':engine,'condition':'Same fixed human clips, Korean, no reference hints, serial offline diagnostic; no default model change or calibrated confidence claim','manifest_sha256':{name:hashlib.sha256((RUNTIME/name).read_bytes()).hexdigest()for name in MANIFESTS},'rows':[]}
    if engine=='qwen':
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
        model_path=RUNTIME/'qwen3-asr-1.7b-4bit';proof=json.loads((model_path/'provenance.json').read_text())
        assert proof['ready']and proof['auto_map_absent']
        with (model_path/'model.safetensors').open('rb')as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==next(c['hash']for c in proof['files']if c['file']=='model.safetensors')
        import mlx.core as mx
        from mlx_audio.stt.utils import load_model
        model=load_model(model_path,strict=True);report['model']=proof['model']
    else:
        import sys
        sys.path.insert(0,str(ROOT))
        from lecture_study import transcription as tr
        from unittest.mock import patch
        command=tr.command;report['model']=tr.MODEL_NAME
    for clip in clips:
        assert hashlib.sha256(Path(clip['path']).read_bytes()).hexdigest()==clip['sha256']
        values=[];started=time.perf_counter()
        if engine=='qwen':
            result=model.generate(clip['path'],language='Korean',temperature=0.0,batch_size=1,max_tokens=256,verbose=False)
            mx.synchronize();assert result.generation_tokens<256;text=result.text
        else:
            async def native(argv,**kwargs):
                if Path(argv[0]).name!='whisper-cli':return await command(argv,**kwargs)
                result=await command([*argv,'-ls'],**kwargs)
                values.extend(token_scores(Path(argv[argv.index('-of')+1]).with_suffix('.score.txt').read_bytes()))
                return result
            with patch.object(tr,'command',new=native):segments=await tr.transcribe_range(clip['path'],0,'',RUNTIME,padding_ms=1000)
            text=' '.join(s['text']for s in segments)
        report['rows'].append({'sha256':clip['sha256'],'group':clip['group'],'reference':clip['reference'],'recognized':text,'seconds':time.perf_counter()-started,'token_scores':values,**score(clip['reference'],text),**character_errors(clip['reference'],text)})
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('clip',len(report['rows']),report['rows'][-1]['edits'],flush=True)
    report['completed']=True;output.write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('engine',choices=('whisper','qwen'));parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();asyncio.run(main(args.engine,args.output.resolve()))
