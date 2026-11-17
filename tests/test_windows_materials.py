import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from PIL import Image


def crop_pdf(path, rotation=90):
    stream=b'1 1 1 rg 0 0 300 200 re f 1 0 0 rg 50 25 100 50 re f 0 0 1 rg 150 75 100 50 re f'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /CropBox [50 25 250 125] /Rotate {rotation} /Contents 4 0 R >>'.encode(),b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data);data+=b'xref\n0 5\n0000000000 65535 f \n'
    data+=b''.join(f'{n:010d} 00000 n \n'.encode()for n in offsets[1:])
    path.write_bytes(data+f'trailer\n<< /Root 1 0 R /Size 5 >>\nstartxref\n{start}\n%%EOF\n'.encode())


class PortableMaterialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_pdf_crop_rotation_metadata_and_ink_alignment(self):
        from lecture_study.materials_portable import read_metadata,render_page,render_ink
        source=self.root/'강의 자료.pdf';crop_pdf(source);before=source.read_bytes()
        self.assertEqual(read_metadata(source),[{'page':1,'width':100.,'height':200.,'rotation':90}])
        output=self.root/'page.png';render_page(source,1,output,size=(300,600))
        with Image.open(output)as image:
            self.assertEqual(image.size,(300,600));self.assertEqual(image.getpixel((50,50))[:3],(255,0,0));self.assertEqual(image.getpixel((250,550))[:3],(0,0,255))
        result=render_ink({'page_width':100.,'page_height':200.,'strokes':[{'tool':'pen','width':.02,'points':[{'x':.25,'y':.25,'pressure':1.}]}]},output,page_source=source,page=1)
        self.assertEqual((result['width'],result['height']),(300,600))
        with Image.open(output)as image:self.assertEqual(image.getpixel((75,150))[:3],(0,0,0))
        self.assertEqual(source.read_bytes(),before)

    def test_every_pdf_rotation_uses_crop_dimensions(self):
        from lecture_study.materials_portable import read_metadata,render_page
        for rotation in (0,90,180,270):
            source=self.root/f'{rotation}.pdf';crop_pdf(source,rotation);metadata=read_metadata(source)[0]
            expected=(100.,200.)if rotation in (90,270)else(200.,100.)
            self.assertEqual((metadata['width'],metadata['height']),expected)
            render_page(source,1,self.root/'page.png',size=tuple(int(n)for n in expected))
            with Image.open(self.root/'page.png')as image:self.assertEqual(image.size,expected)

    def test_exif_image_metadata_background_and_out_of_range(self):
        from lecture_study.materials_portable import read_metadata,render_page
        source=self.root/'회전.jpg';image=Image.new('RGB',(80,40),'red');exif=image.getexif();exif[274]=6;image.save(source,exif=exif)
        self.assertEqual(read_metadata(source),[{'page':1,'width':40,'height':80,'rotation':0}])
        render_page(source,1,self.root/'page.png')
        with Image.open(self.root/'page.png')as rendered:self.assertEqual(rendered.size,(40,80))
        with self.assertRaises(ValueError):render_page(source,2,self.root/'bad.png')

    def test_transparent_background_composites_on_white(self):
        from lecture_study.materials_portable import render_page
        source=self.root/'transparent.png';Image.new('RGBA',(40,30),(0,0,0,0)).save(source)
        render_page(source,1,self.root/'page.png')
        with Image.open(self.root/'page.png')as image:self.assertEqual(image.getpixel((0,0)),(255,255,255))

    def test_pressure_top_left_highlighter_and_input_bounds(self):
        from lecture_study.materials_portable import render_ink
        payload={'page_width':100.,'page_height':100.,'strokes':[{'tool':'pen','width':.1,'points':[{'x':.2,'y':.2,'pressure':0.}]},{'tool':'pen','width':.1,'points':[{'x':.2,'y':.8,'pressure':1.}]},{'tool':'highlighter','width':.1,'points':[{'x':.8,'y':.2,'pressure':1.}]}]}
        target=self.root/'ink.png';render_ink(payload,target)
        with Image.open(target)as image:
            self.assertEqual(image.size,(300,300));self.assertEqual(image.getpixel((60,60)),(0,0,0));self.assertEqual(image.getpixel((240,60)),(255,255,255))
            self.assertLess(sum(image.getpixel((x,60))==(0,0,0)for x in range(300)),sum(image.getpixel((x,240))==(0,0,0)for x in range(300)))
        for bad in (float('nan'),0,-1,100001):
            with self.assertRaises(ValueError):render_ink(payload|{'page_width':bad},target)
        with self.assertRaises(ValueError):render_ink(payload|{'strokes':[{'tool':'pen','width':.01,'points':[{'x':1.1,'y':0.,'pressure':.5}]}]},target)

    def test_tsv_line_regions_confidence_clipping_and_limit(self):
        from lecture_study.handwriting_windows import parse_tsv
        header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        rows='5\t1\t1\t1\t1\t1\t10\t20\t20\t10\t90\t교착\n5\t1\t1\t1\t1\t2\t35\t20\t20\t10\t70\t상태\n5\t1\t1\t1\t2\t1\t-2\t90\t20\t20\t50\tedge\n'
        regions=parse_tsv(header+rows,100,100)
        self.assertEqual(regions[0]['text'],'교착 상태');[self.assertAlmostEqual(a,b)for a,b in zip(regions[0]['bbox'],[.1,.2,.45,.1])];self.assertEqual(regions[0]['candidates'],[{'text':'교착 상태','score':.8}]);self.assertFalse(regions[0]['edge_touching'])
        [self.assertAlmostEqual(a,b)for a,b in zip(regions[1]['bbox'],[0,.9,.18,.1])];self.assertTrue(regions[1]['edge_touching'])
        with self.assertRaises(ValueError):parse_tsv(header+rows.replace('\t90\t교착','\tnan\t교착'),100,100)
        with self.assertRaises(ValueError):parse_tsv('invalid\tformat\n',100,100)

    def test_windows_worker_metadata_and_render_dispatch(self):
        from lecture_study.material_worker import main
        source=self.root/'원본.pdf';crop_pdf(source)
        with patch('sys.platform','win32'),patch('lecture_study.material_worker.subprocess.run',side_effect=AssertionError('Swift must not run')):
            metadata=self.root/'metadata.json'
            with patch('sys.argv',['worker','metadata',str(source),str(metadata),str(self.root),'asset','1','pdf']):main()
            self.assertEqual(json.loads(metadata.read_text())[0]['rotation'],90)
            output=self.root/'render.png'
            with patch('sys.argv',['worker','render',str(source),str(output),str(self.root),'asset','1','pdf','1']):main()
            with Image.open(output)as image:self.assertEqual(image.size,(209,417))

    def test_mac_worker_keeps_existing_metadata_helper(self):
        from lecture_study.material_worker import main
        source=self.root/'source.pdf';metadata=self.root/'metadata.json';expected=b'[{"page":1,"width":100,"height":200,"rotation":90}]'
        with patch('sys.platform','darwin'),patch('sys.frozen',True,create=True),patch('sys.argv',['worker','metadata',str(source),str(metadata),str(self.root),'asset','1','pdf']),patch('lecture_study.material_worker.subprocess.run',return_value=type('Result',(),{'stdout':expected})())as helper:
            main()
        self.assertEqual(metadata.read_bytes(),expected);self.assertEqual(Path(helper.call_args.args[0][0]).name,'MaterialMetadata')


class WindowsHandwritingDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_worker_composites_ink_and_reaps_process(self):
        from lecture_study.handwriting_windows import render_ink
        with tempfile.TemporaryDirectory()as folder:
            image=Path(folder)/'필기 이미지.png'
            result=await render_ink({'page_width':120,'page_height':80,'strokes':[{'tool':'pen','width':.02,'points':[{'x':.25,'y':.75,'pressure':1.}]}]},image)
            self.assertEqual(result['renderer'],'pillow-pdfium-v1')
            with Image.open(image)as rendered:self.assertEqual(rendered.getpixel((90,180)),(0,0,0))

    async def test_ocr_uses_validated_binary_tessdata_unicode_path_and_tsv(self):
        from lecture_study.handwriting_windows import recognize_image
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);image=root/'한글 입력.png';Image.new('RGB',(100,100),'white').save(image)
            process=type('Process',(),{'returncode':0,'wait':AsyncMock(return_value=0)})()
            async def start(*args,**kwargs):
                self.assertEqual(args,(str(root/'ocr/bin/tesseract.exe'),str(image.resolve()),'stdout','--tessdata-dir',str(root/'tessdata'),'-l','kor+eng','--psm','3','-c','tessedit_create_tsv=1'))
                kwargs['stdout'].write(b'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t20\t10\t90\tmutex\n')
                return process
            with patch('lecture_study.runtime.ocr_binary',return_value=root/'ocr/bin/tesseract.exe',create=True)as binary,patch('lecture_study.handwriting_windows.ocr_data_ready',return_value=True),patch('asyncio.create_subprocess_exec',side_effect=start):
                result=await recognize_image(image,runtime_dir=root)
            binary.assert_called_once_with(root);self.assertEqual(result['regions'][0]['text'],'mutex');self.assertNotIn('apple',result['engine'])

    async def test_tampered_tessdata_does_not_launch_ocr(self):
        from lecture_study.handwriting_windows import recognize_image
        with patch('lecture_study.runtime.ocr_binary',return_value=Path('/engine/tesseract.exe'),create=True),patch('lecture_study.handwriting_windows.ocr_data_ready',return_value=False),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('OCR must not launch')):
            with self.assertRaisesRegex(ValueError,'데이터 검증 실패'):await recognize_image('/unused.png',runtime_dir=Path('/runtime'))

    async def test_cancelled_ocr_terminates_and_reaps_child(self):
        from lecture_study.handwriting_windows import recognize_image
        started=asyncio.Event()
        process=type('Process',(),{})();process.returncode=None;process.terminate=lambda:setattr(process,'returncode',-15);process.communicate=AsyncMock(return_value=(b'',b''))
        async def wait():started.set();await asyncio.Event().wait()
        process.wait=wait
        with tempfile.TemporaryDirectory()as folder:
            image=Path(folder)/'ink.png';Image.new('RGB',(100,100),'white').save(image)
            with patch('lecture_study.runtime.ocr_binary',return_value=Path('/engine/tesseract.exe'),create=True),patch('lecture_study.handwriting_windows.ocr_data_ready',return_value=True),patch('asyncio.create_subprocess_exec',AsyncMock(return_value=process)):
                task=asyncio.create_task(recognize_image(image,runtime_dir=Path('/runtime')))
                await asyncio.wait_for(started.wait(),2);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual(process.returncode,-15);process.communicate.assert_awaited_once()

    async def test_windows_defaults_pass_runtime_without_loading_swift(self):
        from lecture_study.handwriting import recognize_ink
        snapshot={'page_width':100.,'page_height':80.,'document_sha256':'a'*64,'revision':1,'ink':[{'id':'s','tool':'pen','width':.01,'color':'#000000','opacity':1.,'input':'pen','points':[{'x':.1,'y':.2,'pressure':1.}]}],'page':1}
        renderer=AsyncMock();recognizer=AsyncMock(return_value={'engine':'tesseract-5/kor+eng','regions':[]})
        with patch('sys.platform','win32'),patch('lecture_study.handwriting_windows.render_ink',renderer),patch('lecture_study.handwriting_windows.recognize_image',recognizer):
            result=await recognize_ink(snapshot,runtime_dir=Path('/runtime'))
        self.assertEqual(result['engine'],'tesseract-5/kor+eng');renderer.assert_awaited_once();self.assertEqual(recognizer.call_args.kwargs,{'runtime_dir':Path('/runtime')})

    async def test_windows_empty_default_does_not_claim_apple(self):
        from lecture_study.handwriting import recognize_ink
        snapshot={'page_width':100.,'page_height':80.,'document_sha256':'a'*64,'revision':1,'ink':[],'page':1}
        with patch('sys.platform','win32'):self.assertEqual(await recognize_ink(snapshot),{'engine':'empty-ink','regions':[]})
