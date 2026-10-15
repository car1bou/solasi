import hashlib,json,tempfile,unittest
from pathlib import Path
from tokenizers import Tokenizer,models,pre_tokenizers
from lecture_study.models import ProviderConfig
from lecture_study.outputs import check_budget

class TokenBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'tokenizer.json'
        tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'hello':1},unk_token='[UNK]'));tokenizer.pre_tokenizer=pre_tokenizers.Whitespace();tokenizer.save(str(self.path))
        self.profile={'path':str(self.path),'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),'model':'test','model_digest':'a'*64}
    def test_model_tokens_replace_overly_conservative_byte_bound(self):
        config=ProviderConfig(provider='ollama',model='test',context_limit=8192);messages=[{'role':'user','content':'hello '*1000}]
        with self.assertRaises(ValueError):check_budget(config,messages,{},output_limit=2048)
        bound=check_budget(config,messages,{},output_limit=2048,tokenizer_profile=self.profile)
        self.assertGreaterEqual(bound,1200);self.assertLess(bound,2000)
    def test_changed_tokenizer_or_other_provider_is_rejected(self):
        config=ProviderConfig(provider='ollama',model='test');messages=[{'role':'user','content':'hello'}]
        check_budget(config,messages,{},tokenizer_profile=self.profile)
        self.path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'토크나이저'):check_budget(config,messages,{},tokenizer_profile=self.profile)
        with self.assertRaisesRegex(ValueError,'모델'):check_budget(config.model_copy(update={'provider':'openai'}),messages,{},tokenizer_profile=self.profile)
    def test_unprepared_models_keep_byte_fallback(self):
        from lecture_study.token_budget import local_profile
        self.assertIsNone(local_profile(ProviderConfig(provider='ollama',model='custom'),Path(self.temp.name)))
        self.assertIsNone(local_profile(ProviderConfig(provider='ollama',model='qwen3.5:4b'),Path(self.temp.name)))

    def test_profile_matches_current_tag_and_ignores_old_runner_blob(self):
        from unittest.mock import patch
        from lecture_study.local_models import CATALOG
        from lecture_study.token_budget import local_profile
        root=Path(self.temp.name)/'ollama-models';blobs=root/'blobs';blobs.mkdir(parents=True)
        checksum=self.profile['sha256'];(blobs/('sha256-'+checksum)).write_bytes(self.path.read_bytes())
        raw=json.dumps({'layers':[{'name':'tokenizer.json','digest':'sha256:'+checksum}]}).encode();digest=hashlib.sha256(raw).hexdigest()
        (blobs/('sha256-'+digest)).write_bytes(raw)
        tag=root/'manifests/registry.ollama.ai/library/qwen3.5/4b';tag.parent.mkdir(parents=True);tag.write_bytes(raw)
        config=ProviderConfig(provider='ollama',model='qwen3.5:4b')
        with patch.dict(CATALOG,{'qwen3.5:4b':{'runners':{'mlx':{'digest':digest}}}}):
            self.assertEqual(local_profile(config,Path(self.temp.name))['model_digest'],digest)
            wrapped=json.loads(raw);wrapped['layers'] += [{'mediaType':'application/vnd.ollama.manifest.list.v2+json','digest':'sha256:'+'b'*64},{'mediaType':'application/vnd.docker.distribution.manifest.v2+json','digest':'sha256:'+digest}]
            tag.write_text(json.dumps(wrapped,indent=2))
            self.assertEqual(local_profile(config,Path(self.temp.name))['model_digest'],digest)
            tag.write_text('{"runner":"llamacpp"}')
            self.assertIsNone(local_profile(config,Path(self.temp.name)))
            tag.unlink()
            self.assertIsNone(local_profile(config,Path(self.temp.name)))
