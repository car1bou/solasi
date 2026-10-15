import json
import tempfile
import unittest
from pathlib import Path
import httpx
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.materials import save_note
from lecture_study.models import Scope,SourceRef
from lecture_study.retrieval import index_source,retrieve,save_term,list_terms,concept_detail,rebuild_embeddings,index_status
from lecture_study.lifecycle import delete_session


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=open_db(Path(self.temp.name));self.addCleanup(self.db.close)
        self.course=new_id();self.other_course=new_id()
        with self.db:
            for ident in (self.course,self.other_course): self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(ident,'과목','',now()))
        self.previous=create_session(self.db,'lecture','이전 수업',self.course,1).id
        self.current=create_session(self.db,'lecture','현재 수업',self.course,2).id
        self.unrelated=create_session(self.db,'lecture','다른 과목',self.other_course,1).id
        self.meeting=create_session(self.db,'meeting','회의',None,None).id
        self.loose=create_session(self.db,'lecture','독립 수업',None,None).id
        self.prev_ref=save_note(self.db,self.previous,'데드락은 자원 대기입니다. OR 연산을 설명합니다.')
        self.cur_ref=save_note(self.db,self.current,'오늘은 교착 상태를 다룹니다.')
        save_note(self.db,self.unrelated,'데드락 교착 OR 다른 과목')
        save_note(self.db,self.meeting,'데드락 교착 OR 회의')
        save_note(self.db,self.loose,'데드락 교착 OR 독립 수업')
        self.scope=Scope(session_id=self.current)

    def evidence_fixture(self,texts):
        refs=[]
        for text in texts:
            sid=create_session(self.db,'lecture','중복 사례',self.course,len(refs)+3).id
            refs.append(save_note(self.db,sid,text))
        rows=[dict(r) for r in self.db.execute('SELECT c.*,s.ref FROM chunks c JOIN sources s ON s.id=c.source_id') if r['source_id'] in {ref.id for ref in refs}]
        return refs,rows,[ref.id+':chunk:0' for ref in refs]

    def test_repeated_evidence_moves_after_distinct_sources(self):
        from lecture_study.retrieval import collect_evidence
        text='프로세스는 실행 중인 프로그램이며 독립된 주소 공간을 갖습니다. 스레드는 메모리를 공유하며 동기화가 필요합니다.'
        refs,rows,ranked=self.evidence_fixture([text,text,'프로세스의 상태 전이는 준비, 실행, 대기 상태를 오갑니다.'])
        found=collect_evidence(self.db,ranked,rows,[self.current],2)
        self.assertEqual([e.ref.id for e in found],[refs[0].id,refs[2].id])
        all_found=collect_evidence(self.db,ranked,rows,[self.current],3)
        self.assertEqual([e.ref.id for e in all_found],[refs[0].id,refs[2].id,refs[1].id])
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(refs[1].id,)).fetchone()[0],text)

    def test_near_repeat_demoted_without_hiding_changed_facts(self):
        from lecture_study.retrieval import collect_evidence
        base='원음 보존 정책은 수업 자료의 근거 확인과 사용자 수정 이력의 유지에 사용되며 저장 위치와 관리 책임을 함께 기록합니다. '
        texts=[base+'파일은 금요일에 3개 삭제합니다.',base+'파일은 금요일에 3개 삭제합니다. 이 내용의 설명입니다.',base+'파일은 월요일에 3개 삭제합니다.',base+'파일은 금요일에 4개 삭제합니다.',base+'파일은 금요일에 3개 삭제하지 않습니다.']
        refs,rows,ranked=self.evidence_fixture(texts)
        found=collect_evidence(self.db,ranked,rows,[self.current],4)
        self.assertEqual([e.ref.id for e in found],[refs[0].id,refs[2].id,refs[3].id,refs[4].id])

    async def test_keyword_and_hybrid_demote_repeat_without_extra_embeddings(self):
        from unittest.mock import patch
        text='전용검색어 프로세스는 독립된 주소 공간을 갖고 스레드는 메모리를 공유합니다.'
        refs,rows,ranked=self.evidence_fixture([text,text,'전용검색어 프로세스의 상태 전이는 준비, 실행, 대기 상태를 오갑니다.'])
        snapshot={'session_ids':[r.session_id for r in refs],'chunk_ids':ranked}
        calls=[]
        def respond(request):
            if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'embeddinggemma:latest','digest':'a'*64}]})
            if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['embedding']})
            calls.append(json.loads(request.content));return httpx.Response(200,json={'embeddings':[[1,0]]})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(respond)) as client:
            # Ranking is fixed here; collection, snapshots and both real retrieval paths remain in use.
            with patch('lecture_study.retrieval.keyword_rank',return_value=ranked):
                result=await retrieve(self.db,'전용검색어',self.scope,None,limit=2,snapshot=snapshot)
                self.assertEqual(result.mode,'keyword');self.assertEqual([e.ref.id for e in result.evidence],[refs[0].id,refs[2].id])
                await rebuild_embeddings(self.db,'embeddinggemma',client);calls.clear()
                with patch('lecture_study.retrieval.semantic_rank',return_value=ranked):
                    result=await retrieve(self.db,'전용검색어',self.scope,None,limit=2,client=client,snapshot=snapshot)
                self.assertEqual(result.mode,'hybrid');self.assertEqual([e.ref.id for e in result.evidence],[refs[0].id,refs[2].id])
                self.assertEqual(len(calls),1)
                self.assertTrue(calls[0]['input'][0].startswith('task: search result | query:'))

    async def test_cumulative_scope_alias_and_fts_input(self):
        term=save_term(self.db,self.current,'데드락',['교착'],'자원 대기',[self.prev_ref])
        found=await retrieve(self.db,'교착',self.scope,None)
        ids={e.ref.id for e in found.evidence}
        self.assertEqual(ids,{self.prev_ref.id,self.cur_ref.id})
        self.assertEqual(found.mode,'keyword')
        current=await retrieve(self.db,'교착',Scope(session_id=self.current,mode='current'),None)
        self.assertEqual({e.ref.id for e in current.evidence},{self.cur_ref.id})
        selected=await retrieve(self.db,'교착',Scope(session_id=self.current,mode='selected',lecture_ids=[self.previous]),None)
        self.assertEqual({e.ref.id for e in selected.evidence},{self.prev_ref.id})
        for query in ('"OR"','"OR" * NEAR(교착)','교착%_','"'):
            result=await retrieve(self.db,query,self.scope,None)
            self.assertTrue(all(e.ref.session_id in (self.previous,self.current) for e in result.evidence))
        for sid in (self.meeting,self.loose):
            result=await retrieve(self.db,'교착',Scope(session_id=sid),None)
            self.assertTrue(all(e.ref.session_id==sid for e in result.evidence))
        with self.assertRaises(ValueError):
            await retrieve(self.db,'교착',Scope(session_id=self.current,mode='selected',lecture_ids=[self.unrelated]),None)
        with self.assertRaises(ValueError):
            await retrieve(self.db,'교착',Scope(session_id=self.current,mode='selected',lecture_ids=[]),None)
        self.assertEqual(list_terms(self.db,self.previous)[0]['id'],term)

    async def test_latest_versions_chunk_boundaries_and_frozen_history(self):
        newer=save_note(self.db,self.previous,'갱신된 정의입니다. 교착')
        found=await retrieve(self.db,'데드락',self.scope,None)
        self.assertNotIn(self.prev_ref.id,{e.ref.id for e in found.evidence})
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(self.prev_ref.id,)).fetchone()[0],'데드락은 자원 대기입니다. OR 연산을 설명합니다.')
        long=save_note(self.db,self.current,'첫 문단\n\n'+'교착 '*180+'\n\n| 표 | 값 |\n| 자원 | 대기 |')
        chunks=self.db.execute('SELECT * FROM chunks WHERE source_id=? ORDER BY ordinal',(long.id,)).fetchall()
        self.assertGreater(len(chunks),3)
        self.assertTrue(all(0<len(r['text'])<=512 for r in chunks))
        self.assertEqual(chunks[0]['text'],'첫 문단')
        index_source(self.db,long,self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(long.id,)).fetchone()[0])
        self.assertEqual(self.db.execute('SELECT count(*) FROM chunks WHERE source_id=?',(long.id,)).fetchone()[0],len(chunks))
        self.assertIn(long.id,{e.ref.id for e in (await retrieve(self.db,'교착',self.scope,None)).evidence})

    async def test_term_identity_evidence_scope_and_session_cleanup(self):
        ident=save_term(self.db,self.current,'데드락',['교착'],'첫 정의',[self.prev_ref])
        same=save_term(self.db,self.previous,'데드락',['교착'],'수정 정의',[self.cur_ref],ident)
        self.assertEqual(ident,same)
        self.assertEqual(concept_detail(self.db,self.current,ident)['term']['revision'],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM term_versions WHERE term_id=?',(ident,)).fetchone()[0],2)
        with self.assertRaises(KeyError): concept_detail(self.db,self.unrelated,ident)
        with self.assertRaises(ValueError): save_term(self.db,self.meeting,'데드락',[],'잘못된 근거',[self.prev_ref])
        fabricated=self.prev_ref.model_copy(update={'version':900})
        with self.assertRaises(ValueError): save_term(self.db,self.current,'데드락',[],'위조',[fabricated])
        meeting_ref=save_note(self.db,self.meeting,'회의만의 원문')
        meeting_term=save_term(self.db,self.meeting,'회의 개념',[],'회의 정의',[meeting_ref])
        delete_session(self.db,self.meeting,True)
        self.assertIsNone(self.db.execute('SELECT id FROM terms WHERE id=?',(meeting_term,)).fetchone())
        self.assertEqual(self.db.execute('SELECT count(*) FROM chunks WHERE source_id=?',(meeting_ref.id,)).fetchone()[0],0)
        delete_session(self.db,self.previous,True)
        self.assertNotIn(self.prev_ref.id,{e.ref.id for e in (await retrieve(self.db,'교착',self.scope,None)).evidence})
        self.assertEqual(concept_detail(self.db,self.current,ident)['term']['explanation'],'수정 정의')

    async def test_embedding_limit_and_atomic_rebuild(self):
        save_note(self.db,self.current,'가'*400+'\n\n파란 물체')
        calls=[];digest='a'*64;bad=False
        def respond(request):
            nonlocal bad
            if request.url.path=='/api/tags': return httpx.Response(200,json={'models':[{'name':'embeddinggemma:latest','digest':digest}]})
            if request.url.path=='/api/show': return httpx.Response(200,json={'capabilities':['embedding']})
            body=json.loads(request.content);calls.append(body)
            self.assertIs(body['truncate'],False)
            text=body['input'][0]
            if len(text)>160: return httpx.Response(400,json={'error':'the input length exceeds the context length'})
            vector=[1,0,0] if bad and len(calls)%2 else ([0,1] if '파란' in text or '청색' in text else [1,0])
            return httpx.Response(200,json={'embeddings':[vector],'prompt_eval_count':5})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(respond)) as client:
            first=await rebuild_embeddings(self.db,'embeddinggemma',client)
            self.assertTrue(first['ready'])
            old=index_status(self.db)['index_id']
            self.assertGreater(len(calls),self.db.execute('SELECT count(*) FROM chunks').fetchone()[0])
            self.assertTrue(any('title:' in c['input'][0] for c in calls))
            result=await retrieve(self.db,'청색',self.scope,None,client=client)
            self.assertEqual(result.mode,'hybrid')
            self.assertIn('파란 물체',result.evidence[0].text)
            self.assertTrue(any(c['input'][0].startswith('task: search result | query:') for c in calls))
            bad=True
            with self.assertRaisesRegex(ValueError,'차원'): await rebuild_embeddings(self.db,'embeddinggemma',client)
            self.assertEqual(index_status(self.db)['index_id'],old)
            bad=False;digest='b'*64
            result=await retrieve(self.db,'교착',self.scope,None,client=client)
            self.assertEqual(result.mode,'keyword')
            self.assertIn('재색인',result.warning)

    async def test_api_scope_and_glossary_without_embedding_connection(self):
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        app=create_app(AppConfig(Path(self.temp.name),Path(self.temp.name)/'runtime',port=8765));self.addCleanup(app.state.db.close)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
            origin={'Origin':'http://127.0.0.1:8765'}
            login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin)
            headers=origin|{'X-Session-Token':login.json()['csrf_token']}
            search=await client.post('/api/sessions/'+self.current+'/search',json={'query':'데드락','scope':self.scope.model_dump()},headers=headers)
            self.assertEqual(search.status_code,200,search.text)
            self.assertEqual(search.json()['mode'],'keyword')
            self.assertIn(self.prev_ref.id,{e['ref']['id'] for e in search.json()['evidence']})
            saved=await client.put('/api/sessions/'+self.current+'/terms',json={'canonical':'데드락','aliases':['교착'],'explanation':'정의','evidence':[self.prev_ref.model_dump()]},headers=headers)
            self.assertEqual(saved.status_code,200,saved.text)
            detail=await client.get('/api/sessions/'+self.current+'/terms/'+saved.json()['id'])
            self.assertEqual(detail.status_code,200,detail.text)
            rebuild=await client.post('/api/index/rebuild',json={'session_id':self.current,'model':'embeddinggemma'},headers=headers)
            self.assertEqual(rebuild.status_code,422)


    async def test_material_membership_and_changed_page_version(self):
        aid=new_id();other=new_id()
        with self.db:
            for ident in (aid,other): self.db.execute("INSERT INTO assets(id,filename,kind,sha256,size,status,created_at,extraction_sha256) VALUES (?,?,'txt','fixture',1,'ready',?,'fixture')",(ident,'연결자료.txt',now()))
            self.db.execute('INSERT INTO session_assets VALUES (?,?)',(self.previous,aid))
            self.db.execute('INSERT INTO session_assets VALUES (?,?)',(self.unrelated,other))
            refs=[SourceRef(id=ident+':v1:page:1',kind='material',asset_id=ident,page=1) for ident in (aid,other)]
            for ref in refs:
                self.db.execute('INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(ref.id,ref.model_dump_json(),'자료의 교착 정의'))
                index_source(self.db,ref,'자료의 교착 정의')
        found=await retrieve(self.db,'교착',self.scope,None)
        self.assertIn(refs[0].id,{e.ref.id for e in found.evidence})
        self.assertNotIn(refs[1].id,{e.ref.id for e in found.evidence})
        self.assertEqual(next(e.label for e in found.evidence if e.ref.id==refs[0].id),'과목 · 연결자료.txt · 1쪽')
        with self.db: self.db.execute("UPDATE assets SET sha256='changed' WHERE id=?",(aid,))
        self.assertNotIn(refs[0].id,{e.ref.id for e in (await retrieve(self.db,'교착',self.scope,None)).evidence})
        with self.db: self.db.execute("UPDATE assets SET version=2,sha256='fixture' WHERE id=?",(aid,))
        self.assertNotIn(refs[0].id,{e.ref.id for e in (await retrieve(self.db,'교착',self.scope,None)).evidence})
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(refs[0].id,)).fetchone()[0],'자료의 교착 정의')

    async def test_final_cutoff_and_transcript_edit_updates_search(self):
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts,edit_segment
        rid=start_recording(self.db,self.current,48000)
        append_pcm(self.db,rid,0,0,48000,bytes([255,31])*48000)
        append_pcm(self.db,rid,1,48000,48000,bytes([255,31])*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],1,True,[{'start_ms':0,'end_ms':900,'text':'교착 앞부분'},{'start_ms':1000,'end_ms':2000,'text':'교착 뒤부분'}])
        records=list_transcripts(self.db,self.current)
        found=await retrieve(self.db,'교착',Scope(session_id=self.current,mode='current'),1000)
        ids={e.ref.id for e in found.evidence}
        self.assertIn(records[0]['id']+':v1',ids);self.assertNotIn(records[1]['id']+':v1',ids)
        edit_segment(self.db,records[0]['id'],'정정한 교착 정의')
        updated=await retrieve(self.db,'교착',self.scope,1000)
        self.assertIn(records[0]['id']+':v2',{e.ref.id for e in updated.evidence})
        self.assertNotIn(records[0]['id']+':v1',{e.ref.id for e in updated.evidence})
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(records[0]['id']+':v1',)).fetchone()[0],'교착 앞부분')

    def test_vector_validation_and_float32_storage(self):
        from lecture_study.retrieval import vector
        for value in (None,[],[True,1],[float('nan'),1],[float('inf'),1],[10**400,1],[0,0]):
            with self.assertRaises(ValueError): vector(value)
        values=vector([3,4])
        self.assertAlmostEqual(values[0],.6);self.assertAlmostEqual(values[1],.8)

    async def test_rebuild_pauses_for_new_recording_and_cancel_keeps_index(self):
        import asyncio
        from lecture_study.audio import start_recording
        from lecture_study.jobs import submit_job,get_job
        paused=False;embed_count=0
        def respond(request):
            nonlocal embed_count
            if request.url.path=='/api/tags': return httpx.Response(200,json={'models':[{'name':'embeddinggemma:latest','digest':'a'*64}]})
            if request.url.path=='/api/show': return httpx.Response(200,json={'capabilities':['embedding']})
            embed_count+=1
            if paused and embed_count==1: start_recording(self.db,self.current,48000)
            return httpx.Response(200,json={'embeddings':[[1,0]]})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(respond)) as client:
            await rebuild_embeddings(self.db,'embeddinggemma',client)
            active=index_status(self.db)['index_id'];paused=True;embed_count=0
            job=submit_job(self.db,self.current,'index',{'model':'embeddinggemma'})
            task=asyncio.create_task(rebuild_embeddings(self.db,'embeddinggemma',client,job['id']))
            await asyncio.sleep(.02)
            self.assertEqual(embed_count,1)
            self.assertEqual(get_job(self.db,job['id'])['result']['paused_reason'],'녹음·전사 중 · 색인 대기')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertEqual(index_status(self.db)['index_id'],active)
            self.assertEqual(self.db.execute("SELECT count(*) FROM embedding_sets WHERE status='building'").fetchone()[0],0)
            with self.db: self.db.execute("UPDATE jobs SET status='failed',result='{}' WHERE id=?",(job['id'],))
            retry=submit_job(self.db,self.current,'index',{'model':'embeddinggemma'},job['id'])
            self.assertEqual(retry['id'],job['id']);self.assertIsNone(retry['result'])

    async def test_remote_embedding_rejected_and_empty_semantic_falls_back(self):
        from lecture_study.retrieval import model_digest
        remote=False
        def respond(request):
            if request.url.path=='/api/tags':
                return httpx.Response(200,json={'models':[{'name':'embeddinggemma:latest','digest':'a'*64,**({'remote_host':'https://ollama.com'} if remote else {})}]})
            if request.url.path=='/api/show': return httpx.Response(200,json={'capabilities':['embedding']})
            return httpx.Response(200,json={'embeddings':[[1,0]]})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(respond)) as client:
            await rebuild_embeddings(self.db,'embeddinggemma',client)
            with self.db: self.db.execute('DELETE FROM embeddings')
            found=await retrieve(self.db,'데드락',self.scope,None,client=client)
            self.assertEqual(found.mode,'keyword');self.assertIn(self.prev_ref.id,{e.ref.id for e in found.evidence})
            self.assertIn('의미 색인',found.warning)
            remote=True
            with self.assertRaisesRegex(ValueError,'로컬'): await model_digest(client,'embeddinggemma')


    def test_changed_signs_and_english_negation_remain_distinct(self):
        from lecture_study.retrieval import collect_evidence
        base='이 실험의 설정은 같은 자료와 같은 입력 조건을 사용하고 원본과 결과를 모두 저장하여 변경 사항을 확인합니다. '
        refs,rows,ranked=self.evidence_fixture([base+'threshold is -10.',base+'threshold is 10.',base+'threshold is not 10.',base+'threshold is never 10.'])
        found=collect_evidence(self.db,ranked,rows,[self.current],3)
        self.assertEqual([e.ref.id for e in found],[r.id for r in refs[:3]])
        self.assertEqual([e.ref.id for e in collect_evidence(self.db,ranked,rows,[self.current],4)],[r.id for r in refs])


class WrittenFactTests(unittest.TestCase):
    def test_near_repeat_does_not_demote_written_counts_or_months(self):
        from types import SimpleNamespace
        from lecture_study.retrieval import diverse_evidence
        base='프로젝트의 진행 상황과 세부 논의 내용 및 담당 업무를 이번 문서에서 자세히 설명합니다. '*5
        for before,after in [('파일은 세 개 삭제합니다.','파일은 네 개 삭제합니다.'),('마감은 January 15일입니다.','마감은 February 15일입니다.')]:
            items=[SimpleNamespace(text=base+before),SimpleNamespace(text=base+after),SimpleNamespace(text='별개의 설명')]
            self.assertEqual(diverse_evidence(items,2),items[:2])
