"""Context-preserving OCR retry experiment; outputs are proposals, never source edits."""
import argparse,asyncio,json,math,sys,time,unicodedata
from pathlib import Path
from PIL import Image,ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.compare_handwriting import LITERAL,distance,file_hash,prepare_images,record_run
from experiments.handwriting_regions import crop_regions


def select_suspect(text,regions,size):
    normalize=lambda s:''.join(unicodedata.normalize('NFC',s).split())
    lines=[normalize(line)for line in text.splitlines()if normalize(line)]
    selected=None;best=-1
    for index,row in enumerate(regions):
        box=row.get('bbox');value=row.get('text')
        if not isinstance(value,str)or not normalize(value):continue
        if not isinstance(box,list)or len(box)!=4 or any(type(x)not in(int,float)or not math.isfinite(x)for x in box):continue
        x,y,w,h=box
        if not(0<=x<x+w<=1 and 0<=y<y+h<=1):continue
        value=normalize(value)
        disagreement=min((distance(value,line)/max(len(value),len(line))for line in lines),default=1)
        edge=row.get('edge_touching')is True
        if disagreement<.35 and not edge:continue
        rank=disagreement+.1*edge
        if rank<=best:continue
        width,height=size;margin=max(2,round(h*height*.1))
        bbox=[0,max(0,math.floor(y*height)-margin),width,min(height,math.ceil((y+h)*height)+margin)]
        selected={'bbox':bbox,'region_index':index,'disagreement':disagreement,'edge_touching':edge};best=rank
    return selected


def retry_inputs(image,bbox,mode):
    if mode not in('locate','context'):raise ValueError('Unknown retry mode')
    source=ImageOps.exif_transpose(image).convert('RGB')
    crop_regions(source,[{'id':'target','kind':'mixed','bbox':bbox}])
    whole=prepare_images(source,'upscale')[0];x1,y1,x2,y2=bbox
    shown=[math.floor(x1*whole.width/source.width),math.floor(y1*whole.height/source.height),math.ceil(x2*whole.width/source.width),math.ceil(y2*whole.height/source.height)]
    message=f'첫 번째 이미지는 전체 원본입니다. 크기는 {whole.width}×{whole.height}이고 확인할 범위는 좌상단 원점의 픽셀 xyxy {shown}입니다. 전체 문맥은 읽되 이 범위와 겹치는 문장·수식만 원문 그대로 전사하세요. 범위 밖 내용은 출력하지 마세요.'
    inputs=[whole]
    if mode=='context':
        margin=max(8,math.ceil((y2-y1)/2))
        context=source.crop((0,max(0,y1-margin),source.width,min(source.height,y2+margin)))
        inputs.append(prepare_images(context,'upscale')[0])
        message+=' 두 번째 이미지는 같은 위치의 주변 문맥을 포함한 확대입니다. 확대의 주변 줄을 추가 출력하거나 잘린 말을 완성하지 마세요. 두 이미지는 하나의 원본이며 별개의 내용이 아닙니다.'
    return inputs,[{'role':'system','content':LITERAL},{'role':'user','content':message}]


async def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['locate','context'],required=True);args=p.parse_args()
    manifest=json.loads(args.manifest.read_text());cases=manifest['cases']
    if not cases or len({c['id']for c in cases})!=len(cases):raise ValueError('Empty or duplicate retry targets')
    for case in cases:
        if file_hash(Path(case['image']))!=case['source_sha256']:raise ValueError('Changed source image')
    from lecture_study.direct_models import DirectModels
    from lecture_study.models import ProviderConfig
    from lecture_study.model_assets import installed_asset
    args.output.mkdir(parents=True,exist_ok=True)
    record_run(args.output/'run-config.json',{'manifest_sha256':file_hash(args.manifest),'mode':args.mode,'script_sha256':file_hash(Path(__file__)),'experiment_files':{q.name:file_hash(q)for q in(Path(__file__).parent/'compare_handwriting.py',Path(__file__).parent/'handwriting_regions.py')},'engine_files':{q.name:file_hash(q)for q in(Path(__file__).resolve().parents[1]/'lecture_study').glob('*.py')},'asset':installed_asset(args.runtime/'ollama-models','qwen3.5:4b')['digest'],'output_limit':512})
    manager=DirectModels(args.runtime,args.output/'model-cache');provider=ProviderConfig(provider='local',model='qwen3.5:4b',vision=True,context_limit=8192)
    try:
        for index,case in enumerate(cases):
            target=args.output/(str(index).zfill(2)+'.json')
            if target.exists():continue
            with Image.open(case['image'])as image:inputs,messages=retry_inputs(image,case['bbox'],args.mode)
            paths=[]
            for n,image in enumerate(inputs):
                path=args.output/(str(index).zfill(2)+f'-input-{n}.png');image.save(path);paths.append(path.resolve())
            start=time.monotonic();result=await manager.generate(provider,messages,paths,None,output_limit=512)
            result.update({'id':case['id'],'source_sha256':case['source_sha256'],'bbox':case['bbox'],'messages':messages,'elapsed_seconds':time.monotonic()-start,'timing_scope':'per-request worker, asset preparation and model load included'})
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(case['id'],result['finish_reason'],result['elapsed_seconds'],flush=True)
    finally:await manager.stop()


if __name__=='__main__':asyncio.run(main())
