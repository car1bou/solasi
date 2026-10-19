"""Offline paired stage measurement. Output contains transcripts: keep it private.

Run twice with the same manifest and a new output, before/after code changes.
No reference text is sent to a model. Inputs and original audio remain read-only.
"""
import argparse, asyncio, hashlib, json, os, sys, time
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lecture_study import transcription as tr
from lecture_study.direct_models import DirectModels
from lecture_study.models import ProviderConfig
from tests.evaluate_human_audio import score, character_errors


async def main(args):
    assert not args.output.exists(), 'Use a new output file'
    assert not args.output.resolve().is_relative_to(ROOT) or args.output.resolve().is_relative_to(ROOT/'.local-state'), 'Keep human transcripts private'
    clips=json.loads(args.manifest.read_text())['clips']
    assert clips and len({c['sha256']for c in clips})==len(clips)
    report={'completed':False,'manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),'asr':[],'generation':[],'embedding':[]}
    def save():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for index,c in enumerate(clips):
        assert hashlib.sha256(Path(c['path']).read_bytes()).hexdigest()==c['sha256']
        variants=(['normalize','reuse']if index%2==0 else ['reuse','normalize'])if args.pcm_pairs else ['current']
        for variant in variants:
            timings={}
            with patch.object(tr,'pcm16_duration',return_value=None)if variant=='normalize'else nullcontext():
                segments=await tr.transcribe_range(c['path'],0,'',args.runtime,timings=timings)
            text=' '.join(s['text']for s in segments)
            report['asr'].append({'sha256':c['sha256'],'group':c['group'],'variant':variant,'segments':segments,'timings_ms':timings,**score(c['reference'],text),**character_errors(c['reference'],text)})
            save();print('asr',index+1,variant,round(timings['total_ms']),flush=True)
    if args.pcm_pairs:
        report['completed']=True;save();return
    # Persist the first inputs, then reuse them verbatim in the after run.
    request=args.manifest.with_name('model-inputs.json')
    if not request.exists():
        excerpts=[{'id':i+1,'text':' '.join(s['text']for s in row['segments'])}for i,row in enumerate(report['asr'])if row['segments']][:6]
        assert excerpts
        request.write_text(json.dumps({'excerpts':excerpts,'query':'이 대화에서 말한 내용과 조건을 찾아줘'},ensure_ascii=False))
    inputs=json.loads(request.read_text());report['model_input_sha256']=hashlib.sha256(request.read_bytes()).hexdigest()
    manager=DirectModels(args.runtime,args.output.parent/'model-cache',engine_dir=args.engine)
    schema={'type':'object','properties':{'source_ids':{'type':'array','items':{'type':'integer','enum':[row['id']for row in inputs['excerpts']]},'minItems':1,'maxItems':3}},'required':['source_ids'],'additionalProperties':False}
    messages=[{'role':'system','content':'핵심 원문을 고르세요. 원문을 재작성하지 말고 중요한 원문 ID를 최대 3개 선택하세요.'},{'role':'user','content':json.dumps(inputs['excerpts'],ensure_ascii=False)}]
    for repeat in range(3):
        result=await manager.generate(ProviderConfig(provider='local',model='qwen3.5:4b'),messages,[],schema,output_limit=128)
        assert all(value>=0 for value in result['usage']['timings_ms'].values())
        ids=json.loads(result['text'])['source_ids'];assert ids and all(i in [r['id']for r in inputs['excerpts']]for i in ids)
        report['generation'].append(result);save();print('generation',repeat+1,flush=True)
        timings={};started=time.perf_counter()
        vector=await manager.embed('embeddinggemma',inputs['query']+'\n'+inputs['excerpts'][0]['text'],timings=timings)
        timings['wall_with_cleanup_ms']=(time.perf_counter()-started)*1000
        assert all(value>=0 for value in timings.values()) and timings['wall_with_cleanup_ms']>=timings['total_before_cleanup_ms']
        report['embedding'].append({'vector':vector,'timings_ms':timings});save();print('embedding',repeat+1,flush=True)
    report['completed']=True;save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','engine','manifest','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--pcm-pairs',action='store_true',help='Only ASR, alternate old normalization and current reuse for each clip')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    asyncio.run(main(parser.parse_args()))
