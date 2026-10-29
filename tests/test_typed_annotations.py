import base64
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from fixtures import png_fixture
from lecture_study.course_materials import page_document, save_page_document
from lecture_study.db import new_id, now, open_db
from lecture_study.handwriting import approve_recognition, capture_ink, ink_hash, ink_payload, save_recognition
from lecture_study.lifecycle import resolve_source
from lecture_study.materials import inspect_file, register_file
from lecture_study.models import InkStroke, InkText, PageDocumentInput, Scope, SourceRef
from lecture_study.native_drafts import NativeDrafts
from lecture_study.retrieval import eligible_chunks


def typed(text='PDF에 직접 쓴 글', **fields):
    return dict(id='text-1', tool='text', text=text, color='#123456', width=.025,
                opacity=1., input='mouse', points=[{'x':.1,'y':.2,'pressure':.5},
                                                  {'x':.8,'y':.4,'pressure':.5}]) | fields


def stroke():
    return dict(id='pen-1', tool='pen', color='#123456', width=.01, opacity=1.,
                input='pen', points=[{'x':.1,'y':.2,'pressure':.5}, {'x':.5,'y':.3,'pressure':.7}])


class TypedAnnotationValidationTests(unittest.TestCase):
    def body(self, ink, text=''):
        return PageDocumentInput(document_sha256='a'*64, expected_revision=0, text=text, ink=ink)

    def test_tagged_union_leaves_legacy_strokes_unchanged(self):
        pen=stroke();highlighter={**pen,'id':'highlight-1','tool':'highlighter'};text=typed()
        value=self.body([pen,highlighter,text])
        self.assertIsInstance(value.ink[0],InkStroke)
        self.assertIsInstance(value.ink[2],InkText)
        self.assertEqual([item.model_dump(exclude_none=True)for item in value.ink],[pen,highlighter,text])
        with self.assertRaises(ValidationError):self.body([{**pen,'text':'cannot silently become text'}])

    def test_text_requires_content_and_two_ordered_normalized_corners(self):
        text=typed()
        invalid=[{**text,'text':value}for value in ('',' \n\t','x'*10001,None,17)]
        invalid += [{**text,'points':points}for points in ([],text['points'][:1],text['points']*2,
                    list(reversed(text['points'])),[text['points'][0]]*2)]
        for field,value in (('x',-0.01),('y',1.01),('x',float('nan')),('pressure',float('inf'))):
            invalid.append({**text,'points':[dict(text['points'][0],**{field:value}),text['points'][1]]})
        invalid += [{**text,field:value}for field,value in (('width',.00019),('width',.10001),
                    ('width','0.025'),('opacity',.049),('color','#fff'),('input','keyboard'),('tool','unknown'))]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):self.body([value])
        self.assertEqual(self.body([typed('한글\n수식 x² < 3')]).ink[0].text,'한글\n수식 x² < 3')

    def test_shared_record_point_text_and_encoded_size_limits(self):
        text=typed()
        with self.assertRaises(ValidationError):self.body([text,{**text,'id':'text-1'}])
        with self.assertRaises(ValidationError):self.body([text,{**stroke(),'id':'text-1'}])
        with self.assertRaises(ValidationError):self.body([{**text,'id':str(i)}for i in range(2001)])
        with self.assertRaises(ValidationError):self.body([text],text='x'*(200001-len(text['text'])))
        self.body([text],text='x'*(200000-len(text['text'])))
        pen=stroke();pen['points']=[pen['points'][0]]*100000
        with self.assertRaisesRegex(ValidationError,'100,000'):self.body([pen,text])
        dense=dict(x=.1234567890123456,y=.1234567890123456,pressure=.1234567890123456,
                   tilt_x=12.123456789012345,tilt_y=12.123456789012345)
        pen['points']=[dense]*99998
        with self.assertRaisesRegex(ValidationError,'8 MiB'):self.body([pen,text])

    def test_old_hash_is_exact_and_text_is_never_sent_to_ocr(self):
        ink=[stroke(),{**stroke(),'id':'highlight-1','tool':'highlighter'}]
        original=hashlib.sha256(json.dumps(ink,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(ink_hash(ink),original)
        self.assertEqual(ink_hash([typed(),*ink,typed('다른 글',id='text-2')]),original)
        snapshot=dict(document_sha256='a'*64,revision=1,ink=[*ink,typed()],page_width=80,page_height=40)
        self.assertEqual(ink_payload(snapshot)['strokes'],ink[:1])


class TypedAnnotationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/'vault');self.addCleanup(self.db.close)
        self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'과목','',now()))
        path=self.root/'original.png';path.write_bytes(png_fixture())
        asset=register_file(self.db,None,inspect_file(path),course_id=self.cid)
        self.aid=asset['id'];self.digest=asset['sha256']
        with self.db:self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(
            self.aid,self.digest,json.dumps({'total_pages':1,'pages':[{'page':1,'width':80,'height':40}]}),now()))

    def save(self, ink, revision=0, text=''):
        body=PageDocumentInput(document_sha256=self.digest,expected_revision=revision,text=text,ink=ink)
        return save_page_document(self.db,self.cid,self.aid,1,body)

    def snapshot(self):return capture_ink(self.db,self.cid,self.aid,1,self.digest)

    def chunks(self):return eligible_chunks(self.db,[],None,None,Scope(course_id=self.cid))

    def test_save_restart_versions_index_and_removal_keep_original_sources(self):
        ink=[stroke(),typed('트랜잭션 원자성 typed-unique')]
        first=self.save(ink,text='별도 페이지 메모')
        self.assertEqual(first['ink'],ink);self.assertEqual(first['text'],'별도 페이지 메모')
        self.assertEqual(self.db.execute('SELECT ink FROM page_document_revisions WHERE document_id=? AND revision=1',(first['id'],)).fetchone()[0],
                         json.dumps(ink,ensure_ascii=False,separators=(',',':')))
        chunks=self.chunks()
        self.assertTrue(any('typed-unique'in item['text']for item in chunks))
        self.assertEqual({item['source_id']for item in chunks},{first['source_id']})
        ref=resolve_source(self.db,SourceRef.model_validate_json(
            self.db.execute('SELECT ref FROM sources WHERE id=?',(first['source_id'],)).fetchone()[0]))
        self.assertEqual(ref['ref']['kind'],'page_note')
        self.assertEqual(ref['text_snapshot'],'별도 페이지 메모\n트랜잭션 원자성 typed-unique')
        other=open_db(self.root/'vault')
        try:self.assertEqual(page_document(other,self.cid,self.aid,1,self.digest),first)
        finally:other.close()
        second=self.save([stroke()],1,'별도 페이지 메모')
        self.assertNotIn(first['source_id'],{item['source_id']for item in self.chunks()})
        self.assertFalse(any('typed-unique'in item['text']for item in self.chunks()))
        self.assertEqual(page_document(self.db,self.cid,self.aid,1,self.digest,revision=1),first)
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(first['source_id'],)).fetchone()[0],ref['text_snapshot'])
        with self.assertRaises(HTTPException):self.save([typed('충돌')],1)
        self.assertEqual(page_document(self.db,self.cid,self.aid,1,self.digest),second)

    def test_text_only_edit_keeps_approval_current_but_stroke_change_invalidates(self):
        pen=stroke();self.save([pen])
        snapshot=self.snapshot()
        candidate=save_recognition(self.db,snapshot,{'engine':'fixture','regions':[{'bbox':[.1,.1,.5,.4],'text':'확인한 손글씨'}]})
        self.save([pen,typed()],1)
        self.assertEqual(self.snapshot()['ink_hash'],snapshot['ink_hash'])
        ref=approve_recognition(self.db,candidate['id'],'확인한 손글씨',snapshot['ink_hash'])
        self.save([pen,typed('수정한 글상자')],2)
        self.assertEqual(resolve_source(self.db,ref)['status'],'current')
        self.assertIn(ref.id,{item['source_id']for item in self.chunks()})
        self.save([pen],3)
        self.assertEqual(resolve_source(self.db,ref)['status'],'current')
        changed=deepcopy(pen);changed['points'][0]['x']=.11
        self.save([changed],4)
        self.assertEqual(resolve_source(self.db,ref)['status'],'changed')
        self.assertNotIn(ref.id,{item['source_id']for item in self.chunks()})
        self.assertEqual(resolve_source(self.db,ref)['ink_snapshot'],[pen])

    def test_typed_only_page_is_direct_knowledge_and_has_empty_ocr_payload(self):
        saved=self.save([typed('직접 쓴 지식')])
        self.assertTrue(any('직접 쓴 지식'in item['text']for item in self.chunks()))
        self.assertEqual(ink_payload(self.snapshot())['strokes'],[])
        self.assertEqual(self.db.execute('SELECT count(*) FROM ink_recognitions').fetchone()[0],0)
        self.assertEqual(saved['text'],'')

    def test_page_api_round_trips_text_and_rejects_invalid_updates(self):
        from fastapi.testclient import TestClient
        from lecture_study.config import AppConfig
        from lecture_study.server import create_app
        app=create_app(AppConfig(self.root/'vault',self.root/'runtime',port=8765))
        self.addCleanup(app.state.instance_lock.close);self.addCleanup(app.state.db.close)
        client=TestClient(app,base_url='http://127.0.0.1:8765');self.addCleanup(client.close)
        origin={'Origin':'http://127.0.0.1:8765'}
        login=client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin)
        headers={**origin,'X-Session-Token':login.json()['csrf_token']}
        path=f'/api/courses/{self.cid}/assets/{self.aid}/pages/1/document'
        body=dict(document_sha256=self.digest,expected_revision=0,text='페이지 메모',ink=[stroke(),typed()])
        saved=client.put(path,json=body,headers=headers)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['ink'],body['ink'])
        self.assertEqual(client.get(path,params={'document_sha256':self.digest}).json(),saved.json())
        invalid={**body,'expected_revision':1,'ink':[{**typed(),'text':' '}]}
        response=client.put(path,json=invalid,headers=headers)
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(client.get(path,params={'document_sha256':self.digest}).json(),saved.json())

    def upload(self,store,value,**options):
        raw=json.dumps(value,ensure_ascii=False).encode();handle=store.begin(len(raw),**options)['id']
        for offset in range(0,len(raw),37):store.append(handle,offset,base64.b64encode(raw[offset:offset+37]).decode())
        return store.commit(handle)

    def test_native_raw_drafts_import_journals_and_preferences_preserve_text(self):
        store=NativeDrafts(self.db)
        row=dict(key='typed-page',text='메모',ink=[stroke(),typed()],revision=3,token='writer',dirty=True,
                 backup={'text':'전 메모','ink':[typed('전 글상자')]})
        self.upload(store,row,kind='write',journal_key='typed-page::writer')
        other=open_db(self.root/'vault')
        try:
            reopened=NativeDrafts(other)
            self.assertEqual(reopened.read(row['key']),[row,{**row,'key':'typed-page::writer'}])
        finally:other.close()
        export=dict(version=1,vault_id=store.state()['vault_id'],origin='fixture',theme='dark',drafts=[row])
        self.upload(store,export,kind='import')
        self.assertEqual(store.read(row['key'])[0],row)
        preferences=dict(tool='text',penColor='#254f3f',penWidth=.0025,penOpacity=1,
                         highlighterColor='#ffe066',highlighterWidth=.018,highlighterOpacity=.35,eraserSize=.014)
        store.write_preference('notebook-tools',preferences)
        for size in (.012,.025,.08):
            expected={**preferences,'textSize':size}
            store.write_preference('notebook-tools',expected)
            self.assertEqual(store.read_preference('notebook-tools')['value'],expected)
        other=open_db(self.root/'vault')
        try:self.assertEqual(NativeDrafts(other).read_preference('notebook-tools')['value'],expected)
        finally:other.close()
        for size in (True,None,'0.025',.0119,.0801,float('nan'),float('inf')):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):store.write_preference('notebook-tools',{**preferences,'textSize':size})
                self.assertEqual(store.read_preference('notebook-tools')['value'],expected)

    def test_page_layout_preference_is_optional_validated_and_per_document(self):
        store=NativeDrafts(self.db)
        key='notebook-view:'+self.cid+':'+self.digest
        legacy=dict(zoomMode='fit',zoom=1,rotation=0,notesOpen=True)
        self.assertEqual(store.write_preference(key,legacy)['value'],legacy)
        for layout in ('continuous','single'):
            expected={**legacy,'pageLayout':layout}
            self.assertEqual(store.write_preference(key,expected)['value'],expected)
            other=open_db(self.root/'vault')
            try:self.assertEqual(NativeDrafts(other).read_preference(key)['value'],expected)
            finally:other.close()
        for layout in (None,True,'spread','',{},[]):
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):store.write_preference(key,{**legacy,'pageLayout':layout})
                self.assertEqual(store.read_preference(key)['value'],expected)
        with self.assertRaises(ValueError):store.write_preference(key,{**expected,'unknown':True})
        other_key='notebook-view:'+self.cid+':'+('f'*64)
        self.assertEqual(store.read_preference(other_key),{'value':None})
        self.assertEqual(store.write_preference(other_key,legacy)['value'],legacy)
        self.assertEqual(store.read_preference(key)['value'],expected)


if __name__=='__main__':unittest.main()
