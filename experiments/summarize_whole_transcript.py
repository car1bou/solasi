"""Supplemental whole-input model quality probe, separate from production resumable summary."""
import argparse,asyncio,hashlib,json,sqlite3,time
from pathlib import Path
import httpx
from lecture_study.local_models import OwnedOllama,CATALOG
from lecture_study.models import ProviderConfig
from lecture_study.providers import generate
from lecture_study.answers import SYSTEM
from lecture_study.outputs import SUMMARY_SCHEMA,Summary,parsed,check_budget
from lecture_study.merging import cited_ids
ROOT=Path(__file__).resolve().parents[1]
def messages_for(rows):
 assert rows and all(0<=r[0]<r[1] and r[2] for r in rows)
 lines='\n'.join(f's{i+1}|{a}-{b}|{text}' for i,(a,b,text) in enumerate(rows))
 instruction='제공된 녹음 Part1 전체 전사만 한국어로 요약하세요. 원작에 대한 기억이나 제공되지 않은 후반 결말을 추가하지 마세요. 인물 관계·핵심 사건·시간 순서를 최대6개 절로 작성하세요. 발화의 상상·추측을 실제 사건으로 바꾸지 마세요. 각 절은 실제 근거 ID를 evidence_ids에 연결하고 본문에는 출처 ID를 쓰지 마세요. 구어의 불완전한 표현을 고유명사로 단정하지 마세요.'
 return [{'role':'system','content':SYSTEM+' '+instruction},{'role':'user','content':'각 행은 ID|원음 시작-종료 ms|확정 전사입니다.\n'+lines}]
async def main(folder,output):
 assert not output.exists(),'Use a fresh output path'
 trace=json.loads((folder/'trace.json').read_text());assert trace['ready']
 with sqlite3.connect(folder/'data/app.sqlite3') as db:
  active=' AND superseded_by IS NULL' if 'superseded_by' in {r[1]for r in db.execute('PRAGMA table_info(transcripts)')}else ''
  rows=db.execute('SELECT start_ms,end_ms,text FROM transcripts WHERE final=1'+active+' ORDER BY start_ms').fetchall()
 messages=messages_for(rows);schema=json.loads(json.dumps(SUMMARY_SCHEMA));ids={'s'+str(i+1) for i in range(len(rows))};schema['properties']['sections']['items']['properties']['evidence_ids']['items']['enum']=sorted(ids)
 config=ProviderConfig(provider='ollama',model='gemma4:12b',context_limit=32768);check_budget(config,messages,schema)
 report={'completed':False,'model':config.model,'input':trace['input'],'conditions':'Supplemental single native generation with entire actual Whisper transcript only; no authored memo, ASR or other task inference; not production map/reduce artifact, citation subset allowed, engine default temperature','source_folder':str(folder),'input_segments':len(rows),'input_last_ms':max(b for a,b,t in rows),'messages':messages,'messages_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest(),'context_limit':config.context_limit}
 manager=OwnedOllama(ROOT/'.local-state/runtime');started=time.perf_counter()
 try:
  url=await manager.start();result=await generate(config,messages,[],schema,ollama_url=url);report['result']=result.model_dump();body=parsed(Summary,result.text)
  assert result.digest==CATALOG[config.model]['runners']['mlx']['digest'] and cited_ids(body)<=ids
  report.update(completed=True,result=result.model_dump(),body=body,cited_input_segments=len(cited_ids(body)),seconds=time.perf_counter()-started)
 except Exception as exc:report.update(error=str(exc),seconds=time.perf_counter()-started)
 finally:
  try:
   if manager.url:
    async with httpx.AsyncClient(base_url=manager.url,timeout=30,trust_env=False) as client:
     response=await client.post('/api/generate',json={'model':config.model,'keep_alive':0});response.raise_for_status()
  finally:
   await manager.stop();output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({k:report[k] for k in ('completed','input_segments','cited_input_segments','seconds') if k in report}),flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();asyncio.run(main(args.folder,args.output))
