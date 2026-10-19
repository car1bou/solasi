"""Compare real local incremental/resumed vectors with a full rebuild in a new vault."""
import argparse,asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lecture_study.db import open_db,create_session
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.materials import save_note
from lecture_study.models import Scope
from lecture_study.direct_models import DirectModels,DirectEmbeddings
from lecture_study.retrieval import sync_embeddings,rebuild_embeddings,retrieve,index_status,semantic_rank,embed_parts
from lecture_study.second_brain import embedding_progress

async def main(a):
 assert not a.output.exists(),'Use a new output directory'
 a.output.mkdir(parents=True);vault=a.output/'vault';db=open_db(vault)
 sid=create_session(db,'lecture','운영체제 지식 검증',None,None).id
 texts=('교착 상태는 상호 배제와 자원 대기가 함께 있을 때 발생할 수 있다.','선점형 스케줄링은 실행 중인 작업에서 CPU를 회수할 수 있다.','가상 메모리는 주소 공간을 분리하고 페이지 단위로 관리한다.')
 save_note(db,sid,'\n'.join(text*10 for text in texts));count=db.execute('SELECT count(*) FROM searchable_chunks').fetchone()[0]
 assert count>1
 manager=DirectModels(a.runtime,a.output/'cache',engine_dir=a.engine);client=DirectEmbeddings(manager,None,reuse=True)
 original_embed=client.embed;calls=0;app=None;report={}
 async def embed(model,text):
  nonlocal calls
  calls+=1;return await original_embed(model,text)
 client.embed=embed
 def vectors():return {(r[0],r[1]):bytes(r[2]) for r in db.execute('SELECT chunk_id,part_no,vector FROM embeddings WHERE index_id=?',(index_status(db)['index_id'],))}
 async def ranks():
  out=[]
  for query in ('교착 상태의 발생 조건','CPU 선점과 스케줄링'):
   result=await retrieve(db,query,Scope(session_id=sid),None,client=client)
   assert result.mode=='hybrid',result.warning
   query_vectors=await embed_parts(client,'embeddinggemma',query,query=True)
   out.append(semantic_rank(db,index_status(db),[dict(r) for r in db.execute('SELECT * FROM searchable_chunks')],query_vectors,8))
  return out
 try:
  t=time.monotonic();await sync_embeddings(db,'embeddinggemma',client,batch_limit=1)
  partial=db.execute("SELECT id FROM embedding_sets WHERE status='building'").fetchone()[0]
  assert embedding_progress(db)['completed_chunks']==1
  await client.close();db.close()
  app=create_app(AppConfig(vault,a.runtime,embedded=True));db=app.state.db
  assert db.execute("SELECT status FROM embedding_sets WHERE id=?",(partial,)).fetchone()[0]=='building'
  await sync_embeddings(db,'embeddinggemma',client)
  assert index_status(db)['index_id']==partial and calls==count
  resumed_seconds=time.monotonic()-t;incremental=vectors()
  before=calls;await sync_embeddings(db,'embeddinggemma',client);assert calls==before
  first=await ranks();t=time.monotonic();before=calls
  await rebuild_embeddings(db,'embeddinggemma',client)
  report.update(resumed_seconds=resumed_seconds,full_rebuild_seconds=time.monotonic()-t,rebuild_document_calls=calls-before)
  full=vectors();assert incremental==full,'float32 vectors changed'
  second=await ranks();assert first==second,'search ranking changed'
  report.update(completed=True,chunks=len(full),reused_after_restart=True,idempotent_extra_calls=0,vectors_byte_identical=True,rankings_identical=True,rankings=first)
 finally:
  await client.close();await manager.stop();db.close()
  if app:app.state.instance_lock.close()
  (a.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ('runtime','engine','output'):p.add_argument('--'+name,type=Path,required=True)
 asyncio.run(main(p.parse_args()))
