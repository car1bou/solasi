"""Local-only public handwriting comparison; dataset stays outside the repository."""
import argparse,asyncio,json,subprocess,time,unicodedata,sys,hashlib,importlib.metadata
from pathlib import Path
from PIL import Image,ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

LITERAL='보이는 문자와 수식만 그대로 전사하세요. 설명하거나 문장을 완성하지 마세요. 이미지 가장자리에서 잘렸거나 판독할 수 없는 부분은 [판독 불가]로 남기세요. 수학 지식으로 기호·단어를 정정하거나 추가하지 마세요. 부호·첨자·분수·극한의 방향을 원본 그대로 보존하고, 도형의 관계는 추측하지 마세요.'

def record_run(path,config):
    if not path.exists()and any(path.parent.glob('*.json')):raise ValueError('Unidentified cached responses require a fresh output directory')
    if path.exists()and json.loads(path.read_text())!=config:raise ValueError('Use a fresh output directory for different conditions')
    path.write_text(json.dumps(config,ensure_ascii=False,indent=2))

def file_hash(path):
    with path.open('rb')as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def prepare_images(image,variant):
    image=ImageOps.exif_transpose(image).convert('RGB')
    if variant=='original':return [image]
    if variant=='upscale':
        scale=min(3,2048/max(image.size))
        return [image.resize(tuple(round(d*scale)for d in image.size),Image.Resampling.LANCZOS)]
    if variant=='padding':return [ImageOps.expand(image,max(8,round(max(image.size)*.05)),fill='white')]
    if variant=='contrast':return [ImageOps.autocontrast(image,cutoff=.5)]
    if variant=='binary':
        import cv2,numpy as np
        _,pixels=cv2.threshold(np.asarray(image.convert('L')),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        return [Image.fromarray(pixels).convert('RGB')]
    if variant=='tiles':
        width,height=image.size;middle=height//2;overlap=max(12,round(height*.08))
        return [image.crop((0,0,width,min(height,middle+overlap))),image.crop((0,max(0,middle-overlap),width,height))]
    raise ValueError('Unknown preprocessing variant')

def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=row
    return previous[-1]

def score(reference,hypothesis):
    ref=''.join(unicodedata.normalize('NFC',reference).split());hyp=''.join(unicodedata.normalize('NFC',hypothesis).split())
    return {'reference_chars':len(ref),'output_chars':len(hyp),'cer_no_whitespace':distance(ref,hyp)/max(1,len(ref))}

async def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--helper',type=Path,required=True);p.add_argument('--runtime',type=Path);p.add_argument('--model',default='qwen3.5:4b');p.add_argument('--model-path',type=Path);p.add_argument('--variant',choices=['original','upscale','padding','contrast','binary','tiles'],default='original');p.add_argument('--literal',action='store_true');p.add_argument('--task',choices=['ocr','formula'],default='ocr');p.add_argument('--cases',nargs='+');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);cases=[];manager=None
    config={'model':args.model,'model_path':str(args.model_path.resolve())if args.model_path else None,'variant':args.variant,'literal':args.literal,'literal_prompt':LITERAL if args.literal else None,'task':args.task,'cases':args.cases,'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted((args.dataset/'images').glob('*.jpg'))if not args.cases or p.stem in args.cases}}
    config['helper_sha256']=file_hash(args.helper)
    config['script_sha256']=file_hash(Path(__file__))
    config['versions']={name:importlib.metadata.version(name)for name in('mlx','mlx-vlm','transformers','pillow')}
    if args.variant=='binary':config['versions']['opencv-python']=importlib.metadata.version('opencv-python')
    if args.model_path:config['model_files']={str(p.relative_to(args.model_path)):file_hash(p)for p in sorted(args.model_path.rglob('*'))if p.is_file()}
    elif args.runtime:
        from lecture_study.model_assets import installed_asset
        config['installed_asset']=installed_asset(args.runtime/'ollama-models',args.model)['digest']
        config['engine_files']={p.name:file_hash(p)for p in(Path(__file__).resolve().parents[1]/'lecture_study').glob('*.py')}
    config_path=args.output/'run-config.json';record_run(config_path,config)
    if args.model_path:
        from mlx_vlm import load,generate as vlm_generate,apply_chat_template
        started=time.monotonic();model,processor=load(str(args.model_path.resolve()),trust_remote_code=False,local_files_only=True);load_seconds=time.monotonic()-started
        if model.config.model_type=='paddleocr_vl':
            from mlx_vlm.models.paddleocr_vl.processing_paddleocr_vl import ImageProcessor
            processor.image_processor=ImageProcessor(**json.loads((args.model_path/'preprocessor_config.json').read_text()))
        prompt=('Formula Recognition:'if args.task=='formula'else'OCR:')if model.config.model_type=='paddleocr_vl'else''
    elif args.runtime:
        from lecture_study.direct_models import DirectModels
        from lecture_study.models import ProviderConfig
        manager=DirectModels(args.runtime,args.output/'model-cache')
        provider=ProviderConfig(provider='local',model=args.model,vision=True,context_limit=8192)
    try:
        for image in sorted((args.dataset/'images').glob('*.jpg')):
            if args.cases and image.stem not in args.cases:continue
            paths=[image.resolve()]
            if args.variant!='original':
                paths=[]
                with Image.open(image)as original:prepared=prepare_images(original,args.variant)
                for n,part in enumerate(prepared):
                    target=args.output/(image.stem+'-input-'+str(n)+'.png');part.save(target);paths.append(target.resolve())
            reference=(args.dataset/'ground_truth'/(image.stem+'.txt')).read_text()
            vision_path=args.output/(image.stem+'-vision.json');started=time.monotonic()
            if vision_path.exists():vision=json.loads(vision_path.read_text())
            else:
                regions=[]
                for path in paths:
                    response=subprocess.run([str(args.helper),'--recognize-image',str(path)],capture_output=True,timeout=120,check=True);regions+=json.loads(response.stdout)['regions']
                vision={'regions':regions,'elapsed_seconds':time.monotonic()-started};vision_path.write_text(json.dumps(vision,ensure_ascii=False,indent=2))
            # The upstream handwritten label for 03 is wrong: the image is a printed book page.
            text='\n'.join(r['text'] for r in vision['regions']);case={'image':image.name,'type':'printed_control' if image.stem.startswith(('03_','05_')) else 'real_handwritten','vision':score(reference,text)|{'seconds':vision['elapsed_seconds']}}
            if manager or args.model_path:
                output=args.output/(image.stem+'-'+args.model.replace(':','-')+'.json');started=time.monotonic()
                if output.exists():result=json.loads(output.read_text())
                else:
                    parts=[]
                    for path in paths:
                        if args.model_path:
                            formatted=apply_chat_template(processor,model.config,prompt,num_images=1,enable_thinking=False)
                            response=vlm_generate(model,processor,prompt=formatted,image=[str(path)],max_tokens=2048,temperature=0.0,verbose=False)
                            parts.append({'text':response.text,'finish_reason':response.finish_reason,'prompt_tokens':response.prompt_tokens,'generation_tokens':response.generation_tokens,'peak_memory_gb':response.peak_memory})
                        else:
                            parts.append(await manager.generate(provider,[{'role':'system','content':LITERAL if args.literal else'이미지에 실제 보이는 글자만 읽으세요. 설명·요약·정정하지 마세요. 읽을 수 없는 부분은 [판독 불가]로 남기세요. 인쇄된 머리글·쪽 번호도 보이면 그대로 적으세요.'},{'role':'user','content':'이 이미지의 글을 읽는 순서대로 그대로 전사하세요.'}],[path],None,output_limit=2048))
                    result={'text':'\n'.join(part['text']for part in parts),'finish_reason':'length'if any(part['finish_reason']=='length'for part in parts)else'stop','parts':parts,**({'model_load_seconds':load_seconds,'native_prompt':prompt}if args.model_path else{})}
                    result['elapsed_seconds']=time.monotonic()-started;result['timing_scope']='inference only; one shared model load reported separately'if args.model_path else'per-request worker, asset preparation and model load included';output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
                case['model']=args.model;case['vlm']=score(reference,result['text'])|{'seconds':result['elapsed_seconds'],'timing_scope':result.get('timing_scope'),'model_load_seconds':result.get('model_load_seconds'),'finish_reason':result.get('finish_reason')}
            cases.append(case);(args.output/'results.json').write_text(json.dumps({'conditions':config,'warning':'Diagnostic CER uses supplied GT, not a validated math/diagram accuracy score. Review visible symbols and clipped boundaries separately. Tile overlap is retained, not deduplicated.','cases':cases},ensure_ascii=False,indent=2));print(json.dumps(case,ensure_ascii=False),flush=True)
    finally:
        if manager:await manager.stop()

if __name__=='__main__':asyncio.run(main())
