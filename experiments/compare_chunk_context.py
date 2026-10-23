"""Compare physical chunk overlap on fixed continuous PCM; never rewrite app transcripts."""
import argparse,asyncio,json,sys,tempfile,time,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lecture_study import transcription as tr
from experiments.compare_audio_preprocessing import digest,pcm
from tests.evaluate_human_audio import normalize,character_errors


def context_bounds(first,last,run_first,run_last,margin):
    if any(type(n)is not int for n in (first,last,run_first,run_last,margin))or not 0<=run_first<=first<last<=run_last or margin<0:raise ValueError('Invalid continuous-run bounds')
    return max(run_first,first-margin),min(run_last,last+margin)


def owned_segments(segments,first,last,decode_first,decode_last):
    if any(type(n)is not int for n in (first,last,decode_first,decode_last))or not 0<=decode_first<=first<last<=decode_last:raise ValueError('Invalid decode bounds')
    owned=[]
    for s in segments:
        a,b,text=s['start_ms'],s['end_ms'],s['text']
        if type(a)is not int or type(b)is not int or not decode_first<=a<b<=decode_last or not isinstance(text,str)or not text.strip():raise ValueError('Segment outside decoded audio')
        if 2*first<=a+b<2*last:owned.append(dict(s))
    return owned


def seam_warnings(segments):
    result={'start_reversals':sum(b['start_ms']<a['start_ms']for a,b in zip(segments,segments[1:])),'cross_core_time_overlaps':0,'text_overlap_candidates':[]}
    for i,a in enumerate(segments):
        for j in range(i+1,len(segments)):
            b=segments[j];overlap=min(a['end_ms'],b['end_ms'])-max(a['start_ms'],b['start_ms'])
            if a['core_index']==b['core_index']or overlap<=0:continue
            result['cross_core_time_overlaps']+=1
            left,right=normalize(a['text']),normalize(b['text'])
            shared=next((n for n in range(min(len(left),len(right)),3,-1)if left[-n:]==right[:n]),0)
            if shared:result['text_overlap_candidates'].append({'left':i,'right':j,'shared_chars':shared,'overlap_ms':overlap})
    return result


async def main(args):
    if args.output.exists():raise ValueError('Use a fresh output file')
    if not args.overlap_ms or len(set(args.overlap_ms))!=len(args.overlap_ms)or any(type(n)is not int or n not in (0,1000,2000)for n in args.overlap_ms):raise ValueError('Invalid overlap conditions')
    manifest=json.loads(args.manifest.read_text());clips=manifest['clips']
    if manifest.get('completed')is not True or not clips or len({c['id']for c in clips})!=len(clips):raise ValueError('Incomplete or duplicate inputs')
    for c in clips:
        if c['continuous']is not True or digest(c['path'])!=c['sha256']:raise ValueError('Changed or discontinuous source')
        count,_=pcm(c['path']);bounds=c['boundaries']
        if count!=c['frames']or not isinstance(bounds,list)or len(bounds)<2 or any(type(n)is not int for n in bounds)or bounds[0]!=0 or bounds[-1]!=count or any(a>=b for a,b in zip(bounds,bounds[1:])):raise ValueError('Invalid fixed core boundaries')
        if c['reference_kind']not in ('manual-complete','reviewed-captions','partial-conversation','silence','target-absent-noise'):raise ValueError('Unknown reference scope')
    report={'completed':False,'manifest_sha256':digest(args.manifest),'script_sha256':digest(__file__),'transcription_sha256':digest(Path(tr.__file__)),'model':tr.MODEL_NAME,'model_sha256':tr.MODEL_SHA,'vad_sha256':tr.VAD_SHA,'overlap_ms':args.overlap_ms,'ownership':'whole native segment midpoint in original half-open core; actual times retained; no text deduplication','rows':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        partial=args.output.with_suffix('.json.partial');partial.write_text(json.dumps(report,ensure_ascii=False,indent=2));partial.replace(args.output)
    save()
    prepared=time.perf_counter();await asyncio.to_thread(tr.engine_paths,args.runtime);await asyncio.to_thread(tr.verify_model,args.runtime/'models/ggml-silero-v6.2.0.bin',tr.VAD_SHA)
    report['asset_prepare_seconds']=time.perf_counter()-prepared;save()
    for c in clips:
      for margin_ms in args.overlap_ms:
        row={'id':c['id'],'group':c['group'],'reference_kind':c['reference_kind'],'reference':c['reference'],'sha256':c['sha256'],'overlap_ms':margin_ms,'chunks':[],'status':'running'};started=time.perf_counter();report['rows'].append(row);save()
        try:
            if digest(c['path'])!=c['sha256']:raise ValueError('Source changed before comparison')
            for index,(first,last)in enumerate(zip(c['boundaries'],c['boundaries'][1:])):
                a,b=context_bounds(first,last,0,c['frames'],margin_ms*16)
                with tempfile.TemporaryDirectory(prefix='solasi-overlap-')as folder:
                    clip=Path(folder)/'input.wav'
                    with wave.open(c['path'])as source:source.setpos(a);raw=source.readframes(b-a)
                    if len(raw)!=(b-a)*2:raise ValueError('Truncated context PCM')
                    with wave.open(str(clip),'wb')as out:out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(raw)
                    stamp=time.perf_counter();timings={};segments=[]if not any(raw)else await tr.transcribe_range(clip,round(a/16),'',args.runtime,padding_ms=1000,timings=timings)
                    selected=owned_segments(segments,round(first/16),round(last/16),round(a/16),round(b/16))
                    row['chunks'].append({'core_index':index,'core_start_frame':first,'core_end_frame':last,'decode_start_frame':a,'decode_end_frame':b,'decode_sha256':digest(clip),'seconds':time.perf_counter()-stamp,'timings':timings,'decoded_segments':segments,'owned_segments':selected})
                    save();print('chunk',c['id'],margin_ms,index+1,'/',len(c['boundaries'])-1,flush=True)
            owned=[dict(s,core_index=k['core_index'])for k in row['chunks']for s in k['owned_segments']]
            row.update(seam_warnings(owned));ordered=sorted(owned,key=lambda s:(s['start_ms'],s['end_ms'],s['core_index']))
            text=' '.join(s['text']for s in ordered);row.update(segments=ordered,recognized=text,output_chars=len(normalize(text)),status='ok')
            if c['reference_kind']!='partial-conversation':
                errors=character_errors(c['reference'],text);n=len(normalize(c['reference']))
                row.update(**errors,edits=sum(errors.values()),reference_chars=n,cer=sum(errors.values())/n if n else None)
            else:row.update(edits=None,reference_chars=None,cer=None)
            if digest(c['path'])!=c['sha256']:raise ValueError('Source changed during comparison')
        except Exception as error:row.update(status='failed',error=str(error))
        row['seconds']=time.perf_counter()-started;save();print(c['id'],margin_ms,row['status'],row.get('edits'),round(row['seconds'],3),flush=True)
    report['completed']=all(r['status']=='ok'for r in report['rows']);save()
    if not report['completed']:raise RuntimeError('Incomplete comparison; inspect retained failures')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--overlap-ms',type=int,nargs='+',choices=[0,1000,2000],default=[0,1000,2000]);asyncio.run(main(parser.parse_args()))
