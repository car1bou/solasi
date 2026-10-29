import asyncio,hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from fastapi import HTTPException
from fixtures import pdf_fixture
from lecture_study.db import open_db,new_id,now
from lecture_study.materials import inspect_file,register_file
from lecture_study.models import PageDocumentInput
from lecture_study.course_materials import save_page_document
from lecture_study.notebook_pdf import saved_pages,export_pdf


def ink(tool='pen',**extra):
    return dict(id=tool,tool=tool,color='#1c7040',width=.02,opacity=1,input='pen',
                points=[dict(x=.2,y=.3,pressure=1),dict(x=.7,y=.3,pressure=.2)])|extra


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/'vault');self.addCleanup(self.db.close)
        self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'PDF','',now()))
        self.original=self.root/'original.pdf';self.original.write_bytes(pdf_fixture())
        self.asset=register_file(self.db,None,inspect_file(self.original),course_id=self.cid)
        metadata=dict(total_pages=3,pages=[dict(page=p,width=600,height=800)for p in range(1,4)])
        with self.db:self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(self.asset['id'],self.asset['sha256'],json.dumps(metadata),now()))

    def test_snapshot_contains_latest_saved_ink_not_memo_and_preserves_history(self):
        body=PageDocumentInput(document_sha256=self.asset['sha256'],expected_revision=0,text='outside memo',ink=[ink()])
        save_page_document(self.db,self.cid,self.asset['id'],2,body)
        before=list(self.db.execute('SELECT * FROM page_document_revisions'))
        path,asset,pages=saved_pages(self.db,self.cid,self.asset['id'],self.asset['sha256'])
        self.assertEqual(path,self.original.resolve());self.assertEqual(len(pages),3)
        self.assertEqual([p['page']for p in pages],[1,2,3]);self.assertEqual(pages[1]['ink'][0]['tool'],'pen')
        self.assertNotIn('outside memo',json.dumps(pages));self.assertEqual(before,list(self.db.execute('SELECT * FROM page_document_revisions')))
        self.original.write_bytes(pdf_fixture()+b' changed')
        with self.assertRaises(HTTPException):saved_pages(self.db,self.cid,self.asset['id'],self.asset['sha256'])
        with self.assertRaises(KeyError):saved_pages(self.db,new_id(),self.asset['id'],self.asset['sha256'])

    def test_unsaved_native_draft_blocks_export_until_same_content_is_saved(self):
        from lecture_study.native_drafts import NativeDrafts
        NativeDrafts(self.db)
        key=json.dumps([self.cid,self.asset['id'],self.asset['sha256'],2],separators=(',',':'))
        value=dict(key=key,dirty=True,text='draft',ink=[ink()],revision=0,token='test')
        with self.db:self.db.execute('INSERT INTO native_drafts VALUES (?,?)',(key,json.dumps(value)))
        with self.assertRaisesRegex(HTTPException,'2쪽'):saved_pages(self.db,self.cid,self.asset['id'],self.asset['sha256'])
        save_page_document(self.db,self.cid,self.asset['id'],2,PageDocumentInput(document_sha256=self.asset['sha256'],expected_revision=0,text='draft',ink=[ink()]))
        self.assertEqual(len(saved_pages(self.db,self.cid,self.asset['id'],self.asset['sha256'])[2]),3)


@unittest.skipUnless(sys.platform=='darwin'and shutil.which('xcrun'),'Mac Swift required')
class NativePDFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.root=Path(cls.temp.name)
        source=Path(__file__).resolve().parents[1]/'macos/NotebookPDF.swift'
        cls.binary=cls.root/'NotebookPDF'
        result=subprocess.run(['xcrun','swiftc','-module-cache-path',str(Path(__file__).resolve().parents[1]/'.local-state/swift-cache'),str(source),'-o',str(cls.binary)],capture_output=True,text=True,timeout=120)
        if result.returncode:raise RuntimeError(result.stderr)

    def test_vectors_text_alpha_all_pages_and_original_unchanged(self):
        import pypdfium2 as pdf
        original=self.root/'original.pdf';original.write_bytes(pdf_fixture());before=original.read_bytes()
        output=self.root/'result.pdf'
        text=ink('text',text='한국어 확률 P(A)>0\nE = mc²\n\n조건 x ≤ 3',width=.025,points=[dict(x=.1,y=.5,pressure=.5),dict(x=.9,y=.85,pressure=.5)])
        highlight=ink('highlighter',color='#ffff00',width=.05,opacity=.3,points=[dict(x=.2,y=.4,pressure=1),dict(x=.8,y=.4,pressure=1)])
        pages=[dict(page=1,ink=[ink(),highlight,text]),dict(page=2,ink=[]),dict(page=3,ink=[])]
        run=subprocess.run([str(self.binary),str(original),str(output)],input=json.dumps(pages).encode(),capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr.decode());self.assertEqual(original.read_bytes(),before)
        with pdf.PdfDocument(str(output))as document:
            self.assertEqual(len(document),3)
            page=document[0];self.assertEqual(page.get_size(),(600,800))
            rendered=page.render(scale=1).to_pil().convert('RGB')
            self.assertLess(rendered.getpixel((250,240))[1],160)
            r,g,b=rendered.getpixel((250,320));self.assertGreater(r,245);self.assertGreater(g,245);self.assertTrue(160<b<200,(r,g,b))
            extracted=page.get_textpage().get_text_range()
            self.assertIn('한국어',extracted);self.assertIn('P(A)>0',extracted);self.assertIn('mc²',extracted);self.assertIn('조건',extracted)
            self.assertIn('Lecture page 2',document[1].get_textpage().get_text_range())
        prior=output.read_bytes()
        rerun=subprocess.run([str(self.binary),str(original),str(output)],input=json.dumps(pages).encode(),capture_output=True)
        self.assertNotEqual(rerun.returncode,0);self.assertEqual(output.read_bytes(),prior)

    def test_crop_rotation_source_annotations_and_overlay_positions(self):
        import pypdfium2 as pdf
        from PIL import ImageChops,ImageStat
        original=self.root/'rotate-base.pdf';original.write_bytes(pdf_fixture())
        source=self.root/'rotate.pdf'
        script=self.root/'rotate.swift';script.write_text('''import PDFKit
import AppKit
let doc=PDFDocument(url:URL(fileURLWithPath:CommandLine.arguments[1]))!
for i in 0..<3 {
 let p=doc.page(at:i)!
 p.setBounds(CGRect(x:30,y:40,width:500,height:700),for:.cropBox)
 p.rotation=[90,180,270][i]
 let a=PDFAnnotation(bounds:CGRect(x:200,y:500,width:60,height:30),forType:.square,withProperties:nil)
 a.interiorColor = .red; a.color = .red; p.addAnnotation(a)
}
doc.write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
''')
        result=subprocess.run(['swift','-module-cache-path',str(Path(__file__).resolve().parents[1]/'.local-state/swift-cache'),str(script),str(original),str(source)],capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        pages=[dict(page=p,ink=[])for p in range(1,4)]
        blank=self.root/'rotate-blank.pdf'
        result=subprocess.run([str(self.binary),str(source),str(blank)],input=json.dumps(pages).encode(),capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        with pdf.PdfDocument(str(source))as a,pdf.PdfDocument(str(blank))as b:
            for i in range(3):
                self.assertEqual(a[i].get_size(),b[i].get_size())
                left=a[i].render().to_pil().convert('RGB');right=b[i].render().to_pil().convert('RGB')
                self.assertLess(sum(ImageStat.Stat(ImageChops.difference(left,right)).mean),3)
        for p in pages:p['ink']=[ink(points=[dict(x=.1,y=.1,pressure=1)])]
        annotated=self.root/'rotate-ink.pdf'
        result=subprocess.run([str(self.binary),str(source),str(annotated)],input=json.dumps(pages).encode(),capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        with pdf.PdfDocument(str(annotated))as doc:
            for i in range(3):
                w,h=doc[i].get_size();image=doc[i].render().to_pil().convert('RGB')
                r,g,b=image.getpixel((round(w*.1),round(h*.1)))
                self.assertTrue(g>r and g>b,(i,r,g,b))

    def test_helper_rejects_invalid_ink_and_page_count(self):
        source=self.root/'bad-original.pdf';source.write_bytes(pdf_fixture())
        for pages in ([],[dict(page=p,ink=[ink(points=[dict(x=-1,y=.1,pressure=1)])])for p in range(1,4)]):
            target=self.root/'invalid.pdf'
            result=subprocess.run([str(self.binary),str(source),str(target)],input=json.dumps(pages).encode(),capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(target.exists())

    def test_disk_write_failure_rejects_and_removes_partial_pdf(self):
        import resource,signal
        source=self.root/'full-original.pdf';source.write_bytes(pdf_fixture());target=self.root/'full-output.pdf'
        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE,(512,512));signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
        result=subprocess.run([str(self.binary),str(source),str(target)],input=json.dumps([dict(page=p,ink=[])for p in range(1,4)]).encode(),capture_output=True,preexec_fn=limit)
        self.assertNotEqual(result.returncode,0);self.assertFalse(target.exists())

class ExportAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_cleanup_and_changed_original_rejection(self):
        import httpx
        from unittest.mock import patch
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);app=create_app(AppConfig(root/'vault',root/'runtime',port=8765));db=app.state.db
            try:
                cid=new_id()
                with db:db.execute('INSERT INTO courses VALUES (?,?,?,?)',(cid,'PDF','',now()))
                original=root/'자료.pdf';original.write_bytes(pdf_fixture());asset=register_file(db,None,inspect_file(original),course_id=cid)
                with db:db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(asset['id'],asset['sha256'],json.dumps(dict(asset_id=asset['id'],sha256=asset['sha256'],total_pages=3,pages=[dict(page=i,width=600,height=800,ref=dict(id=f'fixture-{i}',kind='material',asset_id=asset['id'],page=i))for i in range(1,4)])),now()))
                path=f"/api/courses/{cid}/assets/{asset['id']}/notebook.pdf?document_sha256={asset['sha256']}"
                paths=[]
                async def render(source,destination,pages):
                    paths.append(destination);self.assertEqual(source.read_bytes(),original.read_bytes());self.assertEqual(len(pages),3)
                    destination.write_bytes(b'%PDF-export')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765')as client:
                    await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers={'Origin':'http://127.0.0.1:8765'})
                    real_thread=asyncio.to_thread
                    async def file_thread(function,*args,**kwargs):
                        import sqlite3
                        self.assertFalse(any(isinstance(value,sqlite3.Connection)for value in args),'shared SQLite connection crossed into a file worker')
                        return await real_thread(function,*args,**kwargs)
                    with patch('lecture_study.notebook_pdf.export_pdf',side_effect=render),patch('asyncio.to_thread',side_effect=file_thread):
                        result=await client.get(path)
                    self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.content,b'%PDF-export')
                    self.assertEqual(result.headers['content-type'],'application/pdf');self.assertIn('attachment',result.headers['content-disposition'])
                    self.assertFalse(paths[0].parent.exists())
                    with patch('asyncio.to_thread',side_effect=file_thread):
                        metadata=await client.get('/api/assets/'+asset['id']+'/document')
                    self.assertEqual(metadata.status_code,200,metadata.text)
                    async def changed(source,destination,pages):
                        await render(source,destination,pages);original.write_bytes(pdf_fixture()+b'changed')
                    with patch('lecture_study.notebook_pdf.export_pdf',side_effect=changed):result=await client.get(path)
                    self.assertEqual(result.status_code,409);self.assertFalse(paths[-1].parent.exists())
            finally:
                db.close();app.state.instance_lock.close()
