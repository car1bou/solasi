import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from PIL import Image
from lecture_study.db import open_db,new_id,now
from lecture_study.models import PageDocumentInput,Scope
from lecture_study.materials import inspect_file,register_file
from lecture_study.course_materials import save_page_document
from lecture_study.handwriting import capture_ink,save_recognition,approve_recognition,recognize_ink,recognize_local_ink
from lecture_study.retrieval import eligible_chunks


class HandwritingAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.db=open_db(self.root/'vault');self.addCleanup(self.db.close);self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'과목','',now()))
        original=self.root/'page.png';Image.new('RGB',(100,80),'white').save(original)
        asset=register_file(self.db,None,inspect_file(original),course_id=self.cid,handwritten=True);self.aid=asset['id'];self.digest=asset['sha256']
        with self.db:self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(self.aid,self.digest,json.dumps({'total_pages':1,'pages':[{'page':1,'width':100,'height':80}]}),now()))
        self.ink=[{'id':'p','tool':'pen','width':.02,'color':'#123456','opacity':1.,'input':'pen','points':[{'x':.1,'y':.2,'pressure':.5},{'x':.5,'y':.3,'pressure':.7}]}]
        save_page_document(self.db,self.cid,self.aid,1,PageDocumentInput(document_sha256=self.digest,expected_revision=0,text='',ink=self.ink))
        self.snapshot=capture_ink(self.db,self.cid,self.aid,1,self.digest)

    async def render(self,payload,image_path,**context):
        self.assertEqual(len(payload['strokes']),1);self.assertEqual(context,{'page_source':self.snapshot['page_source'],'page':1})
        Image.new('RGB',(300,240),'white').save(image_path)
        return {'renderer':'portable-fixture','width':300,'height':240}

    def sources(self):return {r['source_id']for r in eligible_chunks(self.db,[],None,None,Scope(course_id=self.cid))}

    async def test_non_mac_backend_preserves_approval_search_and_historical_source(self):
        async def recognize(image_path):
            with Image.open(image_path)as image:self.assertEqual(image.size,(300,240))
            return {'engine':'portable-fixture','regions':[{'bbox':[.1,.1,.5,.4],'text':'교착 상태 mutex','candidates':[]}]}
        with patch('sys.platform','win32'),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('Mac helper must not run')):
            result=await recognize_ink(self.snapshot,renderer=self.render,recognizer=recognize)
        self.assertEqual(result['engine'],'portable-fixture/page')
        candidate=save_recognition(self.db,self.snapshot,result);self.assertFalse(self.sources())
        from lecture_study.second_brain import reconcile
        reconcile(self.db);self.assertFalse(self.db.execute("SELECT 1 FROM brain_work WHERE kind='ink' AND state='pending'").fetchone())
        ref=approve_recognition(self.db,candidate['id'],'교착 상태 mutex',candidate['ink_hash']);self.assertEqual(self.sources(),{ref.id})
        save_page_document(self.db,self.cid,self.aid,1,PageDocumentInput(document_sha256=self.digest,expected_revision=1,text='',ink=[]))
        self.assertFalse(self.sources());self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(ref.id,)).fetchone()[0],'교착 상태 mutex')

    async def test_local_image_engine_needs_no_renderer_or_vision(self):
        from lecture_study.handwriting import recognize_local_image
        image=self.root/'ready.png';Image.new('RGB',(120,90),'white').save(image);before=image.read_bytes()
        async def generate(provider,messages,images,*args,**kwargs):
            self.assertEqual(images,[image]);self.assertEqual(provider.model,'qwen3.5:4b');self.assertIn('[판독 불가]',messages[0]['content'])
            return {'text':'CDF F(x)=P(X≤x)','finish_reason':'stop','usage':{'output_tokens':10}}
        manager=type('Manager',(),{})();manager.status=AsyncMock(return_value={'digest':'a'*64});manager.generate=AsyncMock(side_effect=generate)
        with patch('sys.platform','win32'),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('Mac helper must not run')):
            result=await recognize_local_image(image,manager)
        self.assertEqual(result['text'],'CDF F(x)=P(X≤x)');self.assertEqual(result['engine'],'qwen3.5:4b/'+'a'*64+'/literal-v2')
        self.assertEqual(image.read_bytes(),before)

    async def test_portable_local_pipeline_does_not_invent_a_clear_edge_diagnosis(self):
        manager=type('Manager',(),{})();manager.status=AsyncMock(return_value={'digest':'a'*64});manager.generate=AsyncMock(return_value={'text':'교착 상태','usage':{}})
        with patch('sys.platform','linux'),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('Mac helper must not run')):
            result=await recognize_local_ink(self.snapshot,manager,renderer=self.render)
        self.assertEqual(result['engine'],'qwen3.5:4b/'+'a'*64+'/literal-v2/page')
        self.assertNotIn('edge_touching',result);self.assertEqual(result['regions'][0]['text'],'교착 상태')

    async def test_failed_renderer_cleans_owned_image_and_keeps_database_unchanged(self):
        paths=[]
        async def fail(payload,image_path,**context):
            paths.append(image_path);Image.new('RGB',(30,30),'white').save(image_path);raise ValueError('renderer failed')
        with self.assertRaisesRegex(ValueError,'renderer failed'):
            await recognize_ink(self.snapshot,renderer=fail,recognizer=AsyncMock())
        self.assertEqual(len(paths),1);self.assertFalse(paths[0].exists());self.assertFalse(self.db.execute('SELECT 1 FROM ink_recognitions').fetchone())
        self.assertEqual(capture_ink(self.db,self.cid,self.aid,1,self.digest),self.snapshot)

    async def test_empty_portable_input_does_not_claim_an_apple_engine(self):
        snapshot=self.snapshot|{'ink':[],'page_source':None}
        with patch('sys.platform','win32'):
            result=await recognize_ink(snapshot,renderer=AsyncMock(),recognizer=AsyncMock())
        self.assertEqual(result,{'engine':'empty-ink','regions':[]})

    async def test_cancelled_recognizer_cleans_owned_image_without_saving_a_candidate(self):
        entered=asyncio.Event();paths=[]
        async def recognize(image_path):
            paths.append(image_path);entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(recognize_ink(self.snapshot,renderer=self.render,recognizer=recognize))
        await asyncio.wait_for(entered.wait(),2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(paths[0].exists());self.assertFalse(self.db.execute('SELECT 1 FROM ink_recognitions').fetchone())
        self.assertEqual(capture_ink(self.db,self.cid,self.aid,1,self.digest),self.snapshot)
