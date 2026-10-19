"""Compare existing local Korean inputs with and without job-scoped reuse.

Inputs JSON: {"texts": [...], "queries": [...]}. Keep vectors/texts private.
"""
import argparse,asyncio,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lecture_study.direct_models import DirectModels,DirectEmbeddings


async def main(args):
    assert not args.output.exists(),'Use a new output file'
    assert not args.output.resolve().is_relative_to(ROOT)or args.output.resolve().is_relative_to(ROOT/'.local-state'),'Keep vectors/texts private'
    inputs=json.loads(args.inputs.read_text());texts=inputs['texts']+inputs['queries']
    assert inputs['texts']and inputs['queries']and all(isinstance(t,str)and t for t in texts)
    manager=DirectModels(args.runtime,args.output.parent/'cache',engine_dir=args.engine)
    count=0;spawn=manager._spawn
    async def tracked(argv):
        nonlocal count
        count+=1;return await spawn(argv)
    manager._spawn=tracked
    client=DirectEmbeddings(manager,None,reuse=True)if args.reuse else None
    report={'completed':False,'reuse':args.reuse,'inputs_sha256':hashlib.sha256(args.inputs.read_bytes()).hexdigest(),'rows':[]}
    started=time.perf_counter()
    try:
        for text in texts:
            timings={};first=time.perf_counter()
            values=await manager.embed('embeddinggemma',text,timings=timings,**({'owner':client}if client else {}))
            assert len(values)==768 and abs(sum(v*v for v in values)-1)<1e-6
            report['rows'].append({'vector':values,'timings_ms':timings,'wall_ms':(time.perf_counter()-first)*1000,'retained_workers':len(manager.processes)})
            args.output.write_text(json.dumps(report,indent=2));print('embedding',len(report['rows']),round(report['rows'][-1]['wall_ms']),flush=True)
    finally:
        if client:await client.close()
        await manager.stop()
    assert not manager.processes
    vectors=[r['vector']for r in report['rows']];n=len(inputs['texts'])
    report.update(completed=True,spawn_count=count,total_ms=(time.perf_counter()-started)*1000,ranking=[sorted(range(n),key=lambda i:-sum(x*y for x,y in zip(q,vectors[i])))for q in vectors[n:]],workers_after_close=len(manager.processes))
    args.output.write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','engine','inputs','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--reuse',action='store_true')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    asyncio.run(main(parser.parse_args()))
