"""Prepare local, fixed denoising ablations without altering source recordings."""
import argparse,asyncio,hashlib,json,sys,time,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lecture_study import transcription as tr

# At 16kHz afftdn buffers two 200-sample hops; flush its tail before aligning.
FILTERS={'bandpass':'highpass=f=80,lowpass=f=7600','afftdn':'apad=pad_len=400,afftdn=nr=12:nf=-50:tn=1,atrim=start_sample=400:end_sample={end},asetpts=PTS-STARTPTS'}


def digest(path):
    with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def pcm(path):
    with wave.open(str(path))as w:
        count=w.getnframes()
        if (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getcomptype())!=(1,2,16000,'NONE')or not count:raise ValueError('Use nonempty mono PCM16 16kHz input')
        raw=w.readframes(count)
    if len(raw)!=count*2:raise ValueError('Truncated PCM frames')
    return count,raw


async def preprocess(source,output,method,runtime,model=None):
    if method not in (*FILTERS,'dfnet3'):raise ValueError('Unknown preprocessing method')
    if output.exists()or output.resolve()==source.resolve():raise ValueError('Use a new output file')
    before=digest(source);count,raw=pcm(source);started=time.perf_counter()
    if method=='dfnet3':
        import numpy as np
        from scipy.signal import resample_poly
        if model is None:raise ValueError('Local DeepFilterNet model required')
        signal=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
        high=resample_poly(signal,3,1)
        clean=model.enhance_array(high)
        if clean.shape!=high.shape or not np.isfinite(clean).all():raise ValueError('Invalid denoised samples')
        low=resample_poly(clean,1,3)
        if len(low)!=count:raise ValueError('Denoising changed frame count')
        clipped=int(np.count_nonzero((low < -1)|(low > 32767/32768)))
        if clipped:raise ValueError('Denoising would clip PCM')
        values=np.rint(low*32768).astype('<i2')
        with wave.open(str(output),'wb')as w:
            w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(values.tobytes())
    else:
        from lecture_study.runtime import asr_binary
        await tr.command([asr_binary(runtime,'ffmpeg'),'-nostdin','-v','error','-n','-i',source,'-af',FILTERS[method].format(end=count+400),'-ac','1','-ar','16000','-c:a','pcm_s16le',output])
    actual,_=pcm(output)
    if actual!=count:raise ValueError('Preprocessing changed frame count')
    if digest(source)!=before:raise ValueError('Source changed during preprocessing')
    return {'frames':count,'sha256':digest(output),'source_sha256':before,'seconds':time.perf_counter()-started}


def load_model(folder):
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from mlx_audio.sts.models.deepfilternet import DeepFilterNetModel,DeepFilterNet3Config
    from mlx_audio.sts.models.deepfilternet.network import DfNet
    from mlx_audio.sts.models.deepfilternet.weight_loader import get_weight_mapping,set_weight
    body=json.loads((folder/'config.json').read_text())
    if body.get('model_version')!='DeepFilterNet3':raise ValueError('Expected DeepFilterNet3')
    config=DeepFilterNet3Config.from_dict(body)
    if config.sample_rate!=48000:raise ValueError('Expected 48kHz DeepFilterNet')
    net=DfNet(config);weights=mx.load(str(folder/'model.safetensors'))
    names={k for k,_ in tree_flatten(net.parameters())};mapping=get_weight_mapping(set(weights),names)
    if not weights or set(mapping)!=set(weights)or set(mapping.values())!=names:raise ValueError('Unmapped denoising weights')
    # The library's dict-child finalizer misses GRUs; bias_hh must precede bias_ih.
    for name in sorted(mapping):
        if not set_weight(net,mapping[name],weights[name]):raise ValueError('Unassigned denoising weights')
    return DeepFilterNetModel(config=config,model=net,model_dir=folder,model_version='DeepFilterNet3')


async def main(args):
    if args.output.exists():raise ValueError('Use a fresh manifest output')
    if args.method=='dfnet3'and args.model_folder is None:raise ValueError('Local model folder required')
    if args.method!='dfnet3'and args.model_folder is not None:raise ValueError('Unused model folder')
    original=json.loads(args.manifest.read_text());clips=original['clips']
    if original.get('completed')is False:raise ValueError('Incomplete input manifest')
    if not clips or len({c['id']for c in clips})!=len(clips):raise ValueError('Empty or duplicate clip IDs')
    for c in clips:
        if digest(c['path'])!=c['sha256']:raise ValueError('Changed source audio')
        pcm(c['path'])
    folder=args.output.parent/(args.output.stem+'-audio');folder.mkdir(parents=True,exist_ok=False)
    model=load_model(args.model_folder)if args.method=='dfnet3'else None
    report={'completed':False,'preprocessing':args.method,'filter':FILTERS.get(args.method),'source_manifest_sha256':digest(args.manifest),'script_sha256':digest(__file__),'clips':[]}
    if args.model_folder is not None:report['model_files']={name:digest(args.model_folder/name)for name in ('config.json','model.safetensors')}
    def save():
        partial=args.output.with_suffix('.json.partial');partial.write_text(json.dumps(report,ensure_ascii=False,indent=2));partial.replace(args.output)
    save()
    for i,c in enumerate(clips):
        target=folder/f'{i:03}.wav'
        stats=await preprocess(Path(c['path']),target,args.method,args.runtime,model)
        report['clips'].append({**c,**stats,'path':str(target.resolve()),'category':c.get('category','speech'if c['reference']else'control'),'hint_terms':[],'distractor_terms':[],'hint_provenance':'No terms: fixed preprocessing comparison, reference not provided to model'})
        save();print(args.method,c['id'],'prepared',stats['frames'],flush=True)
    report['completed']=True;save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--method',choices=[*FILTERS,'dfnet3'],required=True);parser.add_argument('--model-folder',type=Path)
    parser.add_argument('--output',type=Path,required=True);asyncio.run(main(parser.parse_args()))
