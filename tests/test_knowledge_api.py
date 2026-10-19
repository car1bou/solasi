import json
from test_materials import MaterialsTests
from fixtures import png_fixture
from lecture_study.db import new_id,now
from lecture_study.course_materials import save_page_document
from lecture_study.models import PageDocumentInput
from lecture_study.handwriting import capture_ink,save_recognition

class KnowledgeApiTests(MaterialsTests):
    async def test_suggestions_load_for_session_and_course_page(self):
        response=await self.client.get('/api/knowledge/suggestions',params={'session_id':self.session_id},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),[])
        cid=new_id()
        asset=(await self.select('ink.png',png_fixture())).json()[0]['asset']['id']
        with self.db:
            self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(cid,'과목','',now()))
            self.db.execute('INSERT INTO course_assets VALUES (?,?)',(cid,asset))
        response=await self.client.get('/api/knowledge/suggestions',params={'course_id':cid,'asset_id':asset,'page':1},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),[])

    async def test_handwriting_approval_and_foreign_course_guard(self):
        response=await self.select('ink.png',png_fixture());aid=response.json()[0]['asset']['id']
        asset=self.db.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone();digest=asset['sha256'];cid=new_id();other=new_id()
        with self.db:
            for c in (cid,other):self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(c,'과목','',now()))
            self.db.execute('INSERT INTO course_assets VALUES (?,?)',(cid,aid))
            self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(aid,digest,json.dumps({'total_pages':1,'pages':[{'page':1,'width':80,'height':40}]}),now()))
        ink=[{'id':'one','tool':'pen','color':'#000000','width':.01,'opacity':1.,'input':'pen','points':[{'x':.2,'y':.2,'pressure':.5}]}]
        save_page_document(self.db,cid,aid,1,PageDocumentInput(document_sha256=digest,expected_revision=0,text='',ink=ink))
        candidate=save_recognition(self.db,capture_ink(self.db,cid,aid,1,digest),{'engine':'fixture','regions':[{'bbox':[.1,.1,.5,.5],'text':'교착 상태'}]})
        payload={'text':'교착 상태','expected_ink_hash':candidate['ink_hash']}
        bad=await self.client.put(f'/api/courses/{other}/handwriting/{candidate["id"]}/approve',headers=self.headers,json=payload)
        self.assertEqual(bad.status_code,404,bad.text)
        approved=await self.client.put(f'/api/courses/{cid}/handwriting/{candidate["id"]}/approve',headers=self.headers,json=payload)
        self.assertEqual(approved.status_code,200,approved.text)
        source=await self.client.get('/api/sources/'+approved.json()['id'],headers=self.headers)
        self.assertEqual(source.status_code,200,source.text);self.assertEqual(source.json()['ink_snapshot'],ink)
        options=await self.client.put('/api/knowledge/options',headers=self.headers,json={'enabled':False})
        self.assertEqual(options.status_code,200,options.text);self.assertFalse(options.json()['enabled'])
        reopened=await self.client.get('/api/knowledge/status',headers=self.headers);self.assertFalse(reopened.json()['enabled'])

    async def test_concept_approval_uses_viewed_course(self):
        from lecture_study.materials import save_note
        from lecture_study.db import create_session
        cid,other=new_id(),new_id()
        with self.db:
            for c in (cid,other):self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(c,'과목','',now()))
        sid=create_session(self.db,'lecture','회차',other,1).id
        ref=save_note(self.db,sid,'교착 상태의 조건')
        with self.db:self.db.execute("INSERT INTO concept_proposals VALUES (?,?,?,?,?,'candidate',?)",('candidate',ref.id,'course:'+other,'교착 상태','교착 상태의 조건',now()))
        bad=await self.client.post('/api/knowledge/concepts/candidate/decision',headers=self.headers,json={'course_id':cid,'apply':True})
        self.assertEqual(bad.status_code,422,bad.text)
        approved=await self.client.post('/api/knowledge/concepts/candidate/decision',headers=self.headers,json={'course_id':other,'apply':True})
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(self.db.execute('SELECT scope_key FROM terms').fetchone()[0],'course:'+other)

    async def test_unknown_concept_source_is_a_client_error(self):
        response=await self.client.post('/api/knowledge/concepts',headers=self.headers,json={'source_id':'missing','session_id':self.session_id})
        self.assertEqual(response.status_code,404,response.text)
