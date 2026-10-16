"""Optional, installed-only MLX candidate; a short-lived worker owns model memory."""
import asyncio,importlib.metadata,json,os,platform,sys,tempfile,wave
from pathlib import Path

MODEL='mlx-community/Qwen3-ASR-1.7B-4bit'
REVISION='78a389c776a5483b2d0d4ea5494e11012e0d6159'
ALTERNATIVE='qwen3-asr-1.7b-4bit'
LEGACY_VERSIONS={'mlx-audio':'0.5.8','mlx':'0.32.3','transformers':'5.19.0','numpy':'2.5.4','huggingface_hub':'2.2.0'}
BUNDLED_VERSIONS={**LEGACY_VERSIONS,'mlx':'0.32.4','transformers':'5.20.0'}
FILES={
    'chat_template.json':{'bytes':1161,'sha256':'75a8cfca24f00de72d796fbfed6858fc9614ef3dabd8696684cc3bc03a9c58ff'},
    'config.json':{'bytes':7188,'sha256':'539c6c9d482349066e2e740241e39896f3bf4de0866c245f6539c85dbb19d93c'},
    'generation_config.json':{'bytes':142,'sha256':'1da527824d81e07118facff437e03f2e24a23311e3bdeb2368973fe77e5f275c'},
    'merges.txt':{'bytes':1671853,'sha256':'8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5'},
    'model.safetensors':{'bytes':1603081617,'sha256':'9848eaf7a5c1589c671b35035ac27b72e248dd0c604eacae547e7e403d29db45'},
    'model.safetensors.index.json':{'bytes':78968,'sha256':'2612ab715223843b3dec0742737bc85f50914ca1484ade45955f99b4e012f2bb'},
    'preprocessor_config.json':{'bytes':330,'sha256':'45e120a4eda2c20c5d7f2ea9354e63536bf35e27aa573fb7cdf78017b378770d'},
    'tokenizer_config.json':{'bytes':12487,'sha256':'4942d005604266809309cabc9f4e9cb89ce855d59b14681fdc0e1cc62ea26c4c'},
    'vocab.json':{'bytes':2776833,'sha256':'ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910'},
}

def available(runtime):
    runtime=Path(runtime)
    return platform.system()=='Darwin' and platform.machine()=='arm64' and (getattr(sys,'frozen',False) or (runtime/'qwen-eval-venv/bin/python').is_file()) and all((runtime/ALTERNATIVE/name).is_file()for name in FILES)

def verify_files(folder):
    from .runtime import matches
    allowed=set(FILES)|{'README.md','provenance.json','model.safetensors.range-plan.json'}
    if set(p.name for p in folder.iterdir())-allowed or any((folder/name).is_symlink()or not matches(folder/name,item)for name,item in FILES.items()):raise ValueError('Qwen 전사 모델 파일 검증 실패')

def read_pcm(path):
    with wave.open(str(path))as handle:
        frames=handle.getnframes()
        if (handle.getnchannels(),handle.getsampwidth(),handle.getframerate())!=(1,2,16000)or not 0<frames<=16000*31:raise ValueError('Qwen 후보는 31초 이하 mono PCM16 16kHz 원음이 필요합니다')
        pcm=handle.readframes(frames)
    if len(pcm)!=frames*2:raise ValueError('Qwen 후보 원음이 짧습니다')
    return pcm

def worker(folder,clip,output):
    import resource
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
    verify_files(folder);pcm=read_pcm(clip)
    if not any(pcm):
        output.write_text(json.dumps({'text':'','generation_tokens':0,'mlx_peak_bytes':0,'process_peak_rss_bytes':0,'skipped_digital_silence':True}));return
    for name,version in (BUNDLED_VERSIONS if getattr(sys,'frozen',False) else LEGACY_VERSIONS).items():
        if importlib.metadata.version(name)!=version:raise ValueError('Qwen 후보 실행 환경 버전이 다릅니다')
    import numpy as np
    import mlx.core as mx
    from mlx_audio.stt.utils import load_model
    mx.reset_peak_memory();model=load_model(folder,strict=True)
    result=model.generate(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768,language='Korean',temperature=0.0,batch_size=1,max_tokens=1024,verbose=False)
    mx.synchronize()
    if result.generation_tokens>=1024:raise ValueError('Qwen 후보가 토큰 상한에 도달했습니다')
    output.write_text(json.dumps({'text':result.text,'generation_tokens':result.generation_tokens,'mlx_peak_bytes':mx.get_peak_memory(),'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},ensure_ascii=False))

async def transcribe(clip,runtime):
    from . import transcription as tr
    runtime=Path(runtime);ffmpeg,_,_=await asyncio.to_thread(tr.engine_paths,runtime)
    with tempfile.TemporaryDirectory(prefix='lecture-qwen-')as temp:
        normalized=Path(temp)/'input.wav';output=Path(temp)/'result.json'
        await tr.command([ffmpeg,'-nostdin','-v','error','-y','-i',clip,'-ac','1','-ar','16000','-c:a','pcm_s16le',normalized])
        from .execution import worker_command
        args=[runtime/ALTERNATIVE,normalized,output]
        argv=worker_command('qwen-worker',args) if getattr(sys,'frozen',False) else [runtime/'qwen-eval-venv/bin/python','-I',Path(__file__).resolve(),*args]
        await tr.command(argv)
        try:
            if output.stat().st_size>65536:raise ValueError('Qwen 후보 결과가 너무 큽니다')
            body=json.loads(output.read_text())
        except (OSError,json.JSONDecodeError):raise ValueError('Qwen 후보 결과를 읽을 수 없습니다')from None
    if not isinstance(body,dict)or not isinstance(body.get('text'),str)or len(body['text'])>10000 or any(type(body.get(k))is not int or body[k]<0 for k in ('generation_tokens','mlx_peak_bytes','process_peak_rss_bytes')):raise ValueError('Qwen 후보 결과 형식이 유효하지 않습니다')
    if body['generation_tokens']>=1024:raise ValueError('Qwen 후보가 토큰 상한에 도달했습니다')
    return body

if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lecture_study.qwen_asr import worker
    worker(*(Path(value)for value in sys.argv[1:]))
