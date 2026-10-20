import importlib.util,json,shutil,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import AsyncMock,patch
from experiments.compare_audio_preprocessing import preprocess,main,load_model


class PreprocessingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.wav'
        self.enterContext(patch('lecture_study.runtime.asr_binary',return_value=self.root/'ffmpeg'))
        with wave.open(str(self.source),'wb')as w:
            w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\x01\x00'*1601)

    async def test_filters_preserve_original_and_validate_frame_count(self):
        before=self.source.read_bytes();output=self.root/'filtered.wav'
        async def copy(argv):shutil.copyfile(self.source,argv[-1])
        with patch('lecture_study.transcription.command',new=AsyncMock(side_effect=copy))as command:
            result=await preprocess(self.source,output,'afftdn',self.root)
        self.assertEqual(result['frames'],1601);self.assertEqual(self.source.read_bytes(),before)
        self.assertIn('apad=pad_len=400,afftdn=nr=12:nf=-50:tn=1,atrim=start_sample=400:end_sample=2001,asetpts=PTS-STARTPTS',command.call_args.args[0])
        with self.assertRaises(ValueError):await preprocess(self.source,output,'afftdn',self.root)
        with self.assertRaises(ValueError):await preprocess(self.source,self.source,'afftdn',self.root)

    async def test_truncated_output_is_not_silently_padded(self):
        async def wrong(argv):
            with wave.open(str(argv[-1]),'wb')as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*1600)
        with patch('lecture_study.transcription.command',new=AsyncMock(side_effect=wrong)):
            with self.assertRaisesRegex(ValueError,'frame'):await preprocess(self.source,self.root/'bad.wav','bandpass',self.root)

    async def test_unsupported_input_and_method_fail_before_running(self):
        with patch('lecture_study.transcription.command',new=AsyncMock())as command:
            with self.assertRaises(ValueError):await preprocess(self.source,self.root/'bad.wav','unknown',self.root)
            stereo=self.root/'stereo.wav'
            with wave.open(str(stereo),'wb')as w:w.setparams((2,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0'*40)
            with self.assertRaises(ValueError):await preprocess(stereo,self.root/'bad.wav','bandpass',self.root)
        command.assert_not_called()

    async def test_interrupted_input_manifest_is_rejected_before_preparation(self):
        from types import SimpleNamespace
        manifest=self.root/'input.json';manifest.write_text(json.dumps({'completed':False,'clips':[{'id':'fixture'}]}))
        args=SimpleNamespace(manifest=manifest,output=self.root/'out.json',method='bandpass',model_folder=None,runtime=self.root)
        with self.assertRaisesRegex(ValueError,'Incomplete'):await main(args)
        self.assertFalse(args.output.exists());self.assertFalse((self.root/'out-audio').exists())

    def test_dfnet_weights_load_once_before_wrapper_caches_filterbanks(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock
        (self.root/'config.json').write_text(json.dumps({'model_version':'DeepFilterNet3','sample_rate':48000}))
        config=SimpleNamespace(sample_rate=48000);net=SimpleNamespace(loaded=False,parameters=Mock(return_value={}))
        weights={'gru.bias_ih_l0':1,'gru.bias_hh_l0':2};order=[]
        mapping={'gru.bias_ih_l0':'gru.b','gru.bias_hh_l0':'gru.bhn'}
        def assign(raw,name,value):
            self.assertIs(raw,net);order.append((name,value))
            if name=='gru.b':
                self.assertEqual(order,[('gru.bhn',2),('gru.b',1)]);raw.loaded=True
            return True
        def wrap(**kwargs):
            self.assertTrue(net.loaded);self.assertIs(kwargs['model'],net)
            return SimpleNamespace(config=config)
        setter=Mock(side_effect=assign);mapper=Mock(return_value=mapping);wrapper=Mock(side_effect=wrap)
        wrapper.from_pretrained=Mock(side_effect=AssertionError('factory already loads weights'))
        mx=SimpleNamespace(load=Mock(return_value=weights))
        modules={'mlx':SimpleNamespace(core=mx),'mlx.core':mx,'mlx.utils':SimpleNamespace(tree_flatten=Mock(return_value=[('gru.b',0),('gru.bhn',0)])),'mlx_audio':SimpleNamespace(),'mlx_audio.sts':SimpleNamespace(),'mlx_audio.sts.models':SimpleNamespace(),'mlx_audio.sts.models.deepfilternet':SimpleNamespace(DeepFilterNetModel=wrapper,DeepFilterNet3Config=SimpleNamespace(from_dict=Mock(return_value=config))),'mlx_audio.sts.models.deepfilternet.network':SimpleNamespace(DfNet=Mock(return_value=net)),'mlx_audio.sts.models.deepfilternet.weight_loader':SimpleNamespace(get_weight_mapping=mapper,set_weight=setter,load_weights=Mock(side_effect=AssertionError('set-order dependent loader')))}
        with patch.dict(sys.modules,modules):
            self.assertIs(load_model(self.root).config,config)
            self.assertEqual(setter.call_count,2);wrapper.from_pretrained.assert_not_called()
            mapper.return_value={}
            with self.assertRaisesRegex(ValueError,'weights'):load_model(self.root)
            mapper.return_value=mapping;setter.side_effect=None;setter.return_value=False
            with self.assertRaisesRegex(ValueError,'weights'):load_model(self.root)
            config.sample_rate=44100
            with self.assertRaisesRegex(ValueError,'48kHz'):load_model(self.root)
            (self.root/'config.json').write_text(json.dumps({'model_version':'DeepFilterNet2'}))
            with self.assertRaisesRegex(ValueError,'DeepFilterNet3'):load_model(self.root)
        self.assertEqual(wrapper.call_count,1)

    @unittest.skipUnless(importlib.util.find_spec('scipy'),'Optional resampling dependency')
    async def test_dfnet_checks_shape_finiteness_and_odd_length_roundtrip(self):
        import numpy as np
        from types import SimpleNamespace
        good=SimpleNamespace(enhance_array=lambda x:x)
        result=await preprocess(self.source,self.root/'df.wav','dfnet3',self.root,good)
        self.assertEqual(result['frames'],1601)
        for i,(change,error)in enumerate(((lambda x:x[:-1],'denoised'),(lambda x:np.full_like(x,np.nan),'denoised'),(lambda x:np.full_like(x,2),'clip'))):
            with self.assertRaisesRegex(ValueError,error):await preprocess(self.source,self.root/f'invalid{i}.wav','dfnet3',self.root,SimpleNamespace(enhance_array=change))
