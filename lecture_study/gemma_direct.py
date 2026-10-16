"""Direct execution of the two installed Gemma checkpoints, without weight conversion."""
import importlib.metadata
import json
import struct
from pathlib import Path

ENGINE_ID = 'mlx-vlm-0.7.8/mlx-0.32.4/transformers-5.20.0/ollama-gemma-v1'
PROFILES = {
    'gemma4:12b': {'asset_digest': 'c6c61e74c905ac3a15f209c421dddf59444e2b28a10f25e8012a3d222e67c6e1',
                   'model_type': 'gemma4_unified', 'context_tokens': 262144},
    'gemma4:e2b': {'asset_digest': '4b893f18d8d684c37055525725f7eba749ea2a3b1a2b89224edc27a1c6a8cd50',
                   'model_type': 'gemma4', 'context_tokens': 131072},
}


def remap_weights(weights):
    mapped = {}
    for key, value in weights.items():
        if key.startswith('draft.'): continue
        target = key
        if key.endswith('.weight.scale'): target = key[:-len('.weight.scale')]+'.scales'
        if key.endswith('.weight.global_scale'): target = key[:-len('.weight.global_scale')]+'.weight_scale_2'
        if target in mapped: raise ValueError('중복 Gemma tensor key')
        mapped[target] = value
    return mapped


def quantization_from_header(header):
    metadata = header.get('__metadata__', {})
    if 'quant_type' not in metadata: return {}
    mode = metadata['quant_type']
    if mode not in ('nvfp4', 'mxfp8'): raise ValueError('검증하지 않은 Gemma 양자화')
    group, bits = (16, 4) if mode == 'nvfp4' else (32, 8)
    if metadata.get('group_size', str(group)) != str(group): raise ValueError('Gemma 양자화 그룹 오류')
    result = {}
    for key in header:
        if not key.endswith('.weight') or key.startswith('draft.'): continue
        target = key[:-len('.weight')].removeprefix('model.')
        if target.startswith('language_model.') and not target.startswith('language_model.model.'):
            target = 'language_model.model.'+target[len('language_model.'):]
        result[target] = {'group_size': group, 'bits': bits, 'mode': mode}
    return result


def render_prompt(messages, images_count=0):
    # Ollama d9b86018 model/renderers/gemma4.go: BOS, turn markers and adjacent model turns.
    last_user = max((i for i, m in enumerate(messages) if m['role'] == 'user'), default=-1)
    if images_count and last_user < 0: raise ValueError('이미지를 연결할 사용자 메시지가 없습니다')
    parts = ['<bos>']
    for i, message in enumerate(messages):
        role = 'model' if message['role'] == 'assistant' else message['role']
        if not (i and role == 'model' and messages[i-1]['role'] == 'assistant'):
            parts.append('<|turn>'+role+'\n')
        content = message['content'] if role == 'model' else message['content'].strip()
        if i == last_user and images_count: content = '<|image|>\n'*images_count+content
        parts.append(content)
        if not (role == 'model' and i+1 < len(messages) and messages[i+1]['role'] == 'assistant'):
            parts.append('<turn|>\n')
    parts.append('<|turn>model\n')
    return ''.join(parts)


def parse_response(text):
    # Official parser treats <|channel> ... <channel|> as thinking, disabled here.
    content = []
    while '<|channel>' in text:
        before, channel = text.split('<|channel>', 1); content.append(before)
        if '<channel|>' not in channel: return ''.join(content).strip()
        _, text = channel.split('<channel|>', 1)
    content.append(text)
    return ''.join(content).strip()


def load(view: Path):
    from .mlx_direct import VERSIONS
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version: raise ValueError('검증된 직접 실행 엔진 버전이 아닙니다: '+name)
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_vlm.utils import get_model_and_args, update_module_configs, sanitize_weights, load_model_weights, load_processor
    config = json.loads((view/'config.json').read_text())
    if config.get('model_type') not in ('gemma4_unified', 'gemma4'): raise ValueError('직접 실행 Gemma 모델이 아닙니다')
    config['quantization'] = {'group_size': 16, 'bits': 4, 'mode': 'nvfp4'}
    config.pop('quantization_config', None)
    module, _ = get_model_and_args(config, view)
    args = update_module_configs(module.ModelConfig.from_dict(config), module, config,
                                 ['text', 'vision', 'perceiver', 'projector', 'audio'])
    model = module.Model(args); weights = {}
    for file in sorted(view.glob('model-*.safetensors')):
        with file.open('rb') as stream:
            prefix = stream.read(8)
            if len(prefix) != 8: raise ValueError('Gemma tensor header 없음')
            size, = struct.unpack('<Q', prefix)
            if not 2 <= size <= 1024*1024: raise ValueError('Gemma tensor header 크기 오류')
            config['quantization'].update(quantization_from_header(json.loads(stream.read(size))))
        shard = remap_weights(mx.load(str(file)))
        if weights.keys() & shard.keys(): raise ValueError('중복 Gemma tensor key')
        weights.update(shard)
    weights = sanitize_weights(model, weights)
    for name, field in (('VisionModel', 'vision_config'), ('LanguageModel', 'text_config'), ('AudioModel', 'audio_config')):
        if hasattr(module, name): weights = sanitize_weights(getattr(module, name), weights, getattr(args, field))
    embedding_scale = weights.pop('language_model.model.embed_tokens.weight_scale_2', None)
    model = load_model_weights(model, config, weights, view, lazy=False, strict=True)
    if embedding_scale is not None:
        class ScaledEmbedding(nn.Module):
            def __init__(self, base, scale): super().__init__(); self.base = base; self.scale = scale
            def __call__(self, indices):
                value = self.base(indices)
                return (value.astype(mx.float32)*self.scale).astype(value.dtype)
            def as_linear(self, value):
                return (self.base.as_linear(value.astype(mx.float32))*self.scale).astype(value.dtype)
        model.language_model.model.embed_tokens = ScaledEmbedding(model.language_model.model.embed_tokens, embedding_scale)
    processor = load_processor(view, trust_remote_code=False, local_files_only=True)
    return model, processor


def generate(view: Path, messages: list, images: list[Path], schema: dict | None,
             output_limit: int, context_limit: int) -> dict:
    if type(output_limit) is not int or not 1 <= output_limit <= 4096: raise ValueError('출력 예산 오류')
    if type(context_limit) is not int or not 512 <= context_limit <= 262144: raise ValueError('문맥 예산 오류')
    if (not isinstance(messages, list) or not messages or
            any(not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant') or
                not isinstance(m.get('content'), str) for m in messages) or
            sum(len(m['content']) for m in messages) > 1_000_000): raise ValueError('모델 메시지 오류')
    if schema is not None and not isinstance(schema, dict): raise ValueError('출력 schema 오류')
    if len(images) > 4: raise ValueError('이미지는 최대 4개입니다')
    for path in images:
        if not isinstance(path, Path) or not path.is_file() or path.stat().st_size > 20*1024**2: raise ValueError('이미지 파일 오류')
        with path.open('rb') as handle: signature = handle.read(8)
        if not (signature.startswith(b'\xff\xd8\xff') or signature == b'\x89PNG\r\n\x1a\n'): raise ValueError('PNG·JPEG 이미지만 지원합니다')
    from mlx_vlm import generate as mlx_generate
    from mlx_vlm.structured import build_json_schema_logits_processor
    from mlx_vlm.utils import prepare_inputs
    model, processor = load(view)
    prompt = render_prompt(messages, len(images))
    inputs = prepare_inputs(processor, images=[str(path) for path in images] or None,
                            prompts=prompt, add_special_tokens=False)
    limit = min(context_limit, model.config.text_config.max_position_embeddings)
    if inputs['input_ids'].shape[-1]+output_limit > limit: raise ValueError('문맥 예산을 초과했습니다')
    inputs['mask'] = inputs.pop('attention_mask', None)
    options = {'max_tokens': output_limit, 'temperature': 0.0, 'verbose': False, **inputs}
    if schema is not None:
        tokenizer = processor.tokenizer if hasattr(processor, 'tokenizer') else processor
        options['logits_processors'] = [build_json_schema_logits_processor(tokenizer, schema)]
    result = mlx_generate(model, processor, prompt=prompt, **options)
    return {'text': parse_response(result.text), 'finish_reason': result.finish_reason,
            'usage': {'prompt_eval_count': result.prompt_tokens, 'eval_count': result.generation_tokens}}
