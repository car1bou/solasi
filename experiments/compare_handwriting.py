"""Local-only public handwriting comparison; dataset stays outside the repository."""
import argparse,asyncio,json,subprocess,time,unicodedata,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

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
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--helper',type=Path,required=True);p.add_argument('--runtime',type=Path);p.add_argument('--model',default='qwen3.5:4b');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);cases=[];manager=None
    if args.runtime:
        from lecture_study.direct_models import DirectModels
        from lecture_study.models import ProviderConfig
        manager=DirectModels(args.runtime,args.output/'model-cache')
        provider=ProviderConfig(provider='local',model=args.model,vision=True,context_limit=8192)
    try:
        for image in sorted((args.dataset/'images').glob('*.jpg')):
            reference=(args.dataset/'ground_truth'/(image.stem+'.txt')).read_text()
            vision_path=args.output/(image.stem+'-vision.json');started=time.monotonic()
            if vision_path.exists():vision=json.loads(vision_path.read_text())
            else:
                response=subprocess.run([str(args.helper),'--recognize-image',str(image.resolve())],capture_output=True,timeout=120,check=True)
                vision=json.loads(response.stdout);vision['elapsed_seconds']=time.monotonic()-started;vision_path.write_text(json.dumps(vision,ensure_ascii=False,indent=2))
            text='\n'.join(r['text'] for r in vision['regions']);case={'image':image.name,'type':'printed_control' if image.stem.startswith('05_') else 'real_handwritten','vision':score(reference,text)|{'seconds':vision['elapsed_seconds']}}
            if manager:
                output=args.output/(image.stem+'-'+args.model.replace(':','-')+'.json');started=time.monotonic()
                if output.exists():result=json.loads(output.read_text())
                else:
                    result=await manager.generate(provider,[{'role':'system','content':'이미지에 실제 보이는 글자만 읽으세요. 설명·요약·정정하지 마세요. 읽을 수 없는 부분은 [판독 불가]로 남기세요. 인쇄된 머리글·쪽 번호도 보이면 그대로 적으세요.'},{'role':'user','content':'이 이미지의 글을 읽는 순서대로 그대로 전사하세요.'}],[image.resolve()],None,output_limit=2048)
                    result['elapsed_seconds']=time.monotonic()-started;output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
                case['model']=args.model;case['vlm']=score(reference,result['text'])|{'seconds':result['elapsed_seconds'],'finish_reason':result.get('finish_reason')}
            cases.append(case);(args.output/'results.json').write_text(json.dumps({'conditions':'whole public page; includes printed headers and non-linear layout; whitespace stripped NFC CER; no manual GT corrections','cases':cases},ensure_ascii=False,indent=2));print(json.dumps(case,ensure_ascii=False),flush=True)
    finally:
        if manager:await manager.stop()

if __name__=='__main__':asyncio.run(main())
