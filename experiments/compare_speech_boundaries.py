"""Compare gap-based boundaries without overlap or changing app recordings."""
import argparse,asyncio,json,sys,time
from array import array
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lecture_study import transcription as tr
from experiments.compare_audio_preprocessing import digest,pcm
from experiments.compare_chunk_context import main as recognize


def boundaries(samples,activity,min_gap_ms):
    if type(min_gap_ms)is not int or min_gap_ms not in (0,200,400)or not samples:raise ValueError('Invalid boundary condition')
    count=len(samples);previous=0;gaps=[]
    for s in activity or []:
        a,b=s['start_ms'],s['end_ms']
        if type(a)is not int or type(b)is not int or not 0<=previous<=a<b or b*16>count+16:raise ValueError('Invalid activity bounds')
        previous=b
    for left,right in zip(activity or [],(activity or [])[1:]):
        a,b=left['end_ms'],right['start_ms']
        if b-a>=min_gap_ms:gaps.append((a+b)*8)
    result=[0];choices=[]
    while result[-1]<count:
        first=result[-1];last=min(first+480000,count);cut=first+tr.quiet_cut(samples[first:last],16000)
        candidates=[p for p in gaps if first+384000<=p<=last]if min_gap_ms and last-first==480000 else []
        if candidates:cut=max(candidates)
        if not first<cut<=last:raise ValueError('Invalid continuous partition')
        result.append(cut);choices.append({'end_frame':cut,'reason':'vad-gap'if candidates else'energy-fallback'if min_gap_ms else'baseline'})
    return result,choices


async def prepare(manifest,runtime,output):
    if output.exists():raise ValueError('Use a fresh output directory')
    body=json.loads(manifest.read_text());clips=body['clips']
    if body.get('completed')is not True or not clips or len({c['id']for c in clips})!=len(clips):raise ValueError('Incomplete or duplicate inputs')
    for c in clips:
        if c['continuous']is not True or digest(c['path'])!=c['sha256']:raise ValueError('Changed or discontinuous source')
        count,_=pcm(c['path'])
        if count!=c['frames']:raise ValueError('Changed PCM count')
    output.mkdir(parents=True);metadata={'completed':False,'source_manifest_sha256':digest(manifest),'script_sha256':digest(__file__),'transcription_sha256':digest(Path(tr.__file__)),'clips':[]};plans={n:[]for n in (0,200,400)}
    def save():
        target=output/'preparation.json';partial=target.with_suffix('.partial');partial.write_text(json.dumps(metadata,ensure_ascii=False,indent=2));partial.replace(target)
    save()
    for c in clips:
        if digest(c['path'])!=c['sha256']:raise ValueError('Source changed before planning')
        count,raw=pcm(c['path']);samples=array('h');samples.frombytes(raw)
        if sys.byteorder!='little':samples.byteswap()
        baseline,_=boundaries(samples,None,0)
        if baseline!=c['boundaries']:raise ValueError('Baseline no longer matches fixed product boundaries')
        stamp=time.perf_counter();error=None
        try:
            activity=await tr.speech_activity(c['path'],runtime);status='unavailable'if activity is None else'speech'if activity else'speech-not-detected'
        except Exception as exc:activity=None;status='failed';error=str(exc)
        record={'id':c['id'],'activity_status':status,'activity_error':error,'activity_seconds':time.perf_counter()-stamp,'activity':activity,'plans':{}}
        for gap in plans:
            bounds,choices=boundaries(samples,activity,gap);record['plans'][str(gap)]=choices;plans[gap].append({**c,'boundaries':bounds})
        if digest(c['path'])!=c['sha256']:raise ValueError('Source changed during planning')
        metadata['clips'].append(record);save();print('planned',c['id'],status,[len(plans[n][-1]['boundaries'])-1 for n in plans],flush=True)
    for gap,rows in plans.items():
        (output/f'manifest-{gap}.json').write_text(json.dumps({'completed':True,'source_manifest_sha256':metadata['source_manifest_sha256'],'boundary_planner_sha256':metadata['script_sha256'],'min_gap_ms':gap,'native_vad_padding_ms':1000,'clips':rows},ensure_ascii=False,indent=2))
    metadata['completed']=True;save();return metadata


async def main(args):
    await prepare(args.manifest,args.runtime,args.output)
    for gap in (0,200,400):
        await recognize(SimpleNamespace(manifest=args.output/f'manifest-{gap}.json',runtime=args.runtime,output=args.output/f'results-{gap}.json',overlap_ms=[0]))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);asyncio.run(main(parser.parse_args()))
