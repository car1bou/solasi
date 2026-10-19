import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from lecture_study import transcription as tr, materials


class StagePerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def wav(self,rate=16000,channels=1):
        path=self.root/'source.wav'
        with wave.open(str(path),'wb')as f:
            f.setparams((channels,2,rate,0,'NONE','not compressed'))
            f.writeframes(bytes(rate*channels*2))
        return path

    async def test_pcm_skips_conversion_and_preserves_offsets(self):
        source=self.wav();calls=[]
        async def command(argv,**kwargs):
            calls.append(argv)
            self.assertEqual(Path(argv[argv.index('-f')+1]),source)
            Path(str(argv[argv.index('-of')+1])+'.json').write_text(json.dumps({'transcription':[{'offsets':{'from':0,'to':1000},'text':'그대로'}]}))
        timings={}
        with patch.object(tr,'engine_paths',return_value=('ffmpeg','whisper','model')),patch.object(tr,'verify_model'),patch.object(tr,'command',new=command):
            result=await tr.transcribe_range(source,500,'',self.root,timings=timings)
        self.assertEqual(len(calls),1)
        self.assertEqual(result,[{'start_ms':500,'end_ms':1500,'text':'그대로'}])
        self.assertTrue(timings['pcm_reused'])
        self.assertGreaterEqual(timings['total_ms'],timings['audio_prepare_ms'])

    def test_non_pcm_or_truncated_wav_must_not_bypass_conversion(self):
        self.assertIsNone(tr.pcm16_duration(self.wav(rate=48000)))
        self.assertIsNone(tr.pcm16_duration(self.wav(channels=2)))
        path=self.wav();path.write_bytes(path.read_bytes()[:-2])
        self.assertIsNone(tr.pcm16_duration(path))
        self.assertIsNone(tr.pcm16_duration(self.root/'missing'))

    async def test_native_timing_parser_does_not_capture_transcript(self):
        timings={}
        out=await tr.command([sys.executable,'-c',"import sys;sys.stderr.write('private speech\\nwhisper_print_timings: load time = 12.50 ms\\nwhisper_print_timings: encode time = 8 ms\\n');print('ok')"],timings=timings)
        self.assertEqual(out,b'ok\n')
        self.assertEqual(timings,{'load_time_ms':12.5,'encode_time_ms':8.0})

    async def test_cached_page_keeps_metadata_and_version_validation(self):
        sha='a'*64;cached=self.root/f'document-{sha}-page-1.png';cached.write_bytes(b'cached')
        metadata=AsyncMock(return_value={'sha256':sha,'total_pages':1})
        with patch.object(materials,'asset_dir',return_value=(self.root,{'kind':'pdf','version':1})),patch('lecture_study.course_materials.document_metadata',metadata),patch('lecture_study.course_materials.checked_document_path')as checked,patch.object(materials,'worker',new_callable=AsyncMock)as worker:
            self.assertEqual(await materials.render_page(None,'id',1,self.root,sha),cached)
            checked.assert_not_called();worker.assert_not_called();metadata.assert_awaited_once()
            with self.assertRaises(HTTPException):await materials.render_page(None,'id',1,self.root,'b'*64)
            with self.assertRaises(KeyError):await materials.render_page(None,'id',2,self.root)
            metadata.side_effect=ValueError('original changed')
            with self.assertRaisesRegex(ValueError,'original changed'):await materials.render_page(None,'id',1,self.root)

    async def test_uncached_page_rechecks_original_after_render(self):
        sha='a'*64
        with patch.object(materials,'asset_dir',return_value=(self.root,{'kind':'pdf','version':1})),patch('lecture_study.course_materials.document_metadata',new=AsyncMock(return_value={'sha256':sha,'total_pages':1})),patch('lecture_study.course_materials.checked_document_path',side_effect=[self.root/'original.pdf',ValueError('original changed')])as checked,patch.object(materials,'worker',new_callable=AsyncMock)as worker:
            with self.assertRaisesRegex(ValueError,'original changed'):await materials.render_page(None,'id',1,self.root)
            self.assertEqual(checked.call_count,2);worker.assert_awaited_once()
