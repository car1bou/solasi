"""Compare public ONNX diarizers on fixed cached Korean two-person interviews.

Use the isolated diarization-eval-venv. No inference dependency enters the app.
TextGrid's single utterance tier supplies turns, not overlapping-speech truth.
"""
import argparse,hashlib,itertools,json,platform,resource,time,wave
from pathlib import Path
from experiments.collect_speech_conditions import utterances
ROOT=Path(__file__).resolve().parents[1]


def reference_turns(rows,start,end):
    reference=[];uem=[]
    for row in rows:
        a=max(start,row['start'])-start;b=min(end,row['end'])-start;text=row['reference'].strip()
        if b<=a:continue
        if text=='<IVER>':speaker='interviewer'
        elif text and '<' not in text:speaker='respondent'
        elif text=='<SIL>':speaker=None
        else:continue
        uem.append((a,b))
        if speaker:reference.append((a,b,speaker))
    return reference,uem


def turn_der(reference,hypothesis,uem,collar=0):
    """Exact interval integration and optimal label permutation within the scored UEM.

    Collar is the full boundary exclusion width: .5 excludes +/- .25 seconds.
    Supports at most two reference speakers, as in this diagnostic corpus tier.
    """
    if collar<0:raise ValueError('Negative collar')
    for rows in (reference,hypothesis,uem):
        if any(not 0<=r[0]<r[1] for r in rows):raise ValueError('Invalid interval')
    names=sorted({r[2]for r in reference});hnames=sorted({r[2]for r in hypothesis})
    if len(names)>2:raise ValueError('This turn metric supports two reference speakers')
    borders={x for r in reference for x in r[:2]}
    exclusions=[(max(0,x-collar/2),x+collar/2)for x in borders]if collar else []
    points=sorted({x for rows in (reference,hypothesis,uem,exclusions)for r in rows for x in r[:2]});atoms=[]
    for a,b in zip(points,points[1:]):
        middle=(a+b)/2
        if not any(s<=middle<e for s,e in uem)or any(s<=middle<e for s,e in exclusions):continue
        ref={n for s,e,n in reference if s<=middle<e};hyp={n for s,e,n in hypothesis if s<=middle<e}
        atoms.append((b-a,ref,hyp))
    intersections={(r,h):sum(d for d,rs,hs in atoms if r in rs and h in hs)for r in names for h in hnames}
    choices=list(itertools.permutations(hnames+[None]*len(names),len(names)))
    chosen=max(choices,key=lambda hs:sum(intersections.get((r,h),0)for r,h in zip(names,hs)),default=())
    mapping={h:r for r,h in zip(names,chosen)if h is not None}
    total=sum(d*len(rs)for d,rs,hs in atoms)
    if total<=0:raise ValueError('No reference speech remains in UEM')
    missed=false_alarm=confusion=0
    for duration,rs,hs in atoms:
        missed+=duration*max(0,len(rs)-len(hs));false_alarm+=duration*max(0,len(hs)-len(rs))
        confusion+=duration*(min(len(rs),len(hs))-len({mapping.get(h)for h in hs}&rs))
    return {'reference_speaker_seconds':total,'scored_seconds':sum(d for d,_,_ in atoms),'miss_seconds':missed,'false_alarm_seconds':false_alarm,'confusion_seconds':confusion,'der':(missed+false_alarm+confusion)/total,'collar_seconds':collar,'mapping':mapping}


def noise_coverage(reference,hypothesis):
    # Background speech is unlabeled: extra clusters and activity are diagnostics, not DER.
    total=sum(b-a for a,b,_ in reference);uncovered=0
    for start,end,_ in reference:
        points=sorted({start,end}|{max(start,min(end,x))for r in hypothesis for x in r[:2]})
        uncovered+=sum(b-a for a,b in zip(points,points[1:])if not any(s<=(a+b)/2<e for s,e,_ in hypothesis))
    return {'labeled_target_seconds':total,'target_activity_uncovered_seconds':uncovered,'target_activity_coverage':1-uncovered/total,'limit':'Activity coverage can be supplied by background speakers; not target identity accuracy or DER'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output,models,groups,oracle,manifest=None):
    import numpy as np
    import sherpa_onnx as so
    assets=ROOT/'.local-state/runtime/diarization-20261015';provenance=json.loads((assets/'manifest.json').read_text());assert provenance['ready']
    for item in provenance['files']:
        path=assets/item['file'];assert path.stat().st_size==item['bytes']and sha(path)==item['sha256']
    data=json.loads((manifest or ROOT/'.local-state/runtime/conversation-20261014/manifest.json').read_text());assert data['ready']
    label_files={Path(item['name']).stem:item for item in data['sources_proof']['files']if item['kind']=='label'};labels={}
    for name,item in label_files.items():
        path=Path(item['path']);assert sha(path)==item['sha256'];labels[name]=utterances(path.read_text(encoding='utf-16'))
    settings={'provider':'cpu','num_threads':2,'window_shift_ratio':.1,'min_duration_on':.3,'min_duration_off':.5,'threshold':.5,'num_clusters':2 if oracle else -1}
    report={'completed':False,'metric':'Seoul Corpus utterance-tier-derived turn DER, specified UEM; not overlap-aware meeting DER'if labels else'No DER: distributed public-interview annotations lack stable speaker IDs','condition':'Known two-speaker count (oracle diagnostic)'if oracle else'Automatic speaker count at fixed threshold .5','settings':settings,'versions':{'python':platform.python_version(),'sherpa_onnx':so.__version__,'numpy':np.__version__},'assets':provenance,'data_sources':data['datasets'],'input_manifest':str(manifest or ROOT/'.local-state/runtime/conversation-20261014/manifest.json'),'label_files':list(label_files.values()),'selection':data['selection_before_inference'],'limitations':[*(['Small fixed six adult interview windows, no meeting-domain or overlap ground truth','<IVER> has turn identity but no word transcription and may contain pauses; interviewer recorded without a microphone','Tagged noise, laughter, private and unknown intervals excluded; explicit silence included']if labels else['Two edited public Korean interviews, not complete meeting-domain speaker/time ground truth','ASD TXT has words and utterance times but no stable speaker IDs; no DER or speaker identity accuracy']),'No DER for environmental mixtures with unlabeled background speech','Measured serially on a shared Mac, not an isolated hardware speed ranking'],'results':[]}
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for model in models:
        began=time.perf_counter()
        config=so.OfflineSpeakerDiarizationConfig(segmentation=so.OfflineSpeakerSegmentationModelConfig(pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(assets/'segmentation.onnx'),window_shift_ratio=.1),num_threads=2,provider='cpu'),embedding=so.SpeakerEmbeddingExtractorConfig(model=str(assets/(model+'.onnx')),num_threads=2,provider='cpu'),clustering=so.FastClusteringConfig(num_clusters=settings['num_clusters'],threshold=.5),min_duration_on=.3,min_duration_off=.5)
        if not config.validate():raise ValueError('Invalid diarization config')
        diarizer=so.OfflineSpeakerDiarization(config);load_seconds=time.perf_counter()-began
        for clip in data['conversations']:
            if clip['group']not in groups:continue
            path=Path(clip['path']);assert sha(path)==clip['sha256']
            with wave.open(str(path))as handle:
                assert(handle.getnchannels(),handle.getsampwidth(),handle.getframerate())==(1,2,diarizer.sample_rate)
                samples=np.frombuffer(handle.readframes(handle.getnframes()),dtype='<i2').astype(np.float32)/32768
            reference,uem=reference_turns(labels[clip['speaker_id']],clip['start_seconds'],clip['start_seconds']+len(samples)/diarizer.sample_rate)if clip['speaker_id']in labels else([],[])
            began=time.perf_counter();result=diarizer.process(samples).sort_by_start_time();seconds=time.perf_counter()-began
            hypothesis=[(float(r.start),float(r.end),str(r.speaker))for r in result];assert all(0<=s<e<=len(samples)/diarizer.sample_rate+.05 for s,e,_ in hypothesis)
            row={'model':model,'input':{k:clip[k]for k in ('path','sha256','group','speaker_id','start_seconds','duration_seconds')},'load_seconds':load_seconds,'seconds':seconds,'rtf':seconds/clip['duration_seconds'],'host_process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'speaker_count':len({r[2]for r in hypothesis}),'segments':hypothesis,'reference_turns':reference,'uem':uem}
            if reference and clip['group']=='clean':row['scores']=[turn_der(reference,hypothesis,uem,c)for c in (0,.5)]
            elif reference:row['diagnostic']=noise_coverage(reference,hypothesis)
            else:row['diagnostic']={'limit':'No complete speaker/time reference supplied: operational counts and segments only; no DER or speaker identity accuracy'}
            report['results'].append(row);save();print(json.dumps({k:v for k,v in row.items()if k not in ('segments','reference_turns','uem')},ensure_ascii=False),flush=True)
        del diarizer
    report['completed']=True;save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--models',nargs='+',choices=['resnet34','camplusplus'],default=['resnet34','camplusplus']);parser.add_argument('--groups',nargs='+',choices=['clean','office','cafeteria','public-interview'],default=['clean','office','cafeteria']);parser.add_argument('--oracle-two-speakers',action='store_true');parser.add_argument('--manifest',type=Path);args=parser.parse_args();assert not args.output.exists();main(args.output,args.models,args.groups,args.oracle_two_speakers,args.manifest)
