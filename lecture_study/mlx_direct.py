"""Direct, offline MLX execution for the installed checkpoint tested on this Mac."""
import importlib.metadata
import json
import time
from pathlib import Path

ENGINE_ID = 'mlx-vlm-0.7.8/mlx-0.32.4/transformers-5.20.0/ollama-nvfp4-v1'
VERSIONS = {'mlx': '0.32.4', 'mlx-metal': '0.32.4', 'mlx-vlm': '0.7.8',
            'transformers': '5.20.0', 'llguidance': '1.9.1'}
SUPPORTED_MODELS = {'qwen3.5:4b': {
    'asset_digest': '3b6225ff07117608fdd54a729806671494c57980272eab2b7e7dd2b972423c1c',
    'model_type': 'qwen3_5', 'vision': True, 'completion': True, 'context_tokens':262144,
    'engine':ENGINE_ID+'/chat-template-no-thinking-v1'}}


def remap_qwen_weights(weights):
    mapped = {}
    for key, value in weights.items():
        if key.endswith('.weight.global_scale'): raise ValueError('미검증 global scale 모델입니다')
        target = key[:-len('.weight.scale')]+'.scales' if key.endswith('.weight.scale') else key
        if target in mapped: raise ValueError('중복 tensor key')
        mapped[target] = value
    return mapped


def load(view: Path):
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version: raise ValueError('검증된 직접 실행 엔진 버전이 아닙니다: '+name)
    import mlx.core as mx
    from mlx_vlm.utils import get_model_and_args, update_module_configs, sanitize_weights, load_model_weights, load_processor
    config = json.loads((view/'config.json').read_text())
    if config.get('model_type') != 'qwen3_5': raise ValueError('직접 실행을 검증하지 않은 모델입니다')
    config['quantization'] = {'group_size': 16, 'bits': 4, 'mode': 'nvfp4'}
    module, _ = get_model_and_args(config, view)
    args = update_module_configs(module.ModelConfig.from_dict(config), module, config,
                                 ['text', 'vision', 'perceiver', 'projector', 'audio'])
    model = module.Model(args)
    weights = {}
    for file in sorted(view.glob('model-*.safetensors')):
        shard = mx.load(str(file))
        if weights.keys() & shard.keys(): raise ValueError('중복 tensor key')
        weights.update(shard)
    weights = sanitize_weights(model, remap_qwen_weights(weights))
    for name, field in (('VisionModel', 'vision_config'), ('LanguageModel', 'text_config')):
        if hasattr(module, name): weights = sanitize_weights(getattr(module, name), weights, getattr(args, field))
    model = load_model_weights(model, config, weights, view, lazy=False, strict=True)
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
    if json.loads((view/'config.json').read_text()).get('model_type')!='qwen3_5':raise ValueError('현재 로컬 AI는 Qwen3.5 4B를 사용합니다')
    from mlx_vlm import generate as mlx_generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.structured import build_json_schema_logits_processor
    from mlx_vlm.utils import prepare_inputs, should_add_special_tokens
    started=time.perf_counter()
    model, processor = load(view)
    loaded=time.perf_counter()
    prompt = apply_chat_template(processor, model.config, messages, num_images=len(images), enable_thinking=False)
    inputs = prepare_inputs(processor, images=[str(path) for path in images] or None, prompts=prompt,
                            image_token_index=getattr(model.config, 'image_token_index', None),
                            add_special_tokens=should_add_special_tokens(model.config.model_type, processor))
    if inputs['input_ids'].shape[-1] + output_limit > context_limit: raise ValueError('문맥 예산을 초과했습니다')
    inputs['mask'] = inputs.pop('attention_mask', None)
    options = {'max_tokens': output_limit, 'temperature': 0.0, 'verbose': False, **inputs}
    if schema is not None:
        tokenizer = processor.tokenizer if hasattr(processor, 'tokenizer') else processor
        options['logits_processors'] = [build_json_schema_logits_processor(tokenizer, schema)]
    prepared=time.perf_counter()
    result = mlx_generate(model, processor, prompt=prompt, **options)
    completed=time.perf_counter()
    return {'text': result.text, 'finish_reason': result.finish_reason,
            'usage': {'prompt_eval_count': result.prompt_tokens, 'eval_count': result.generation_tokens,
                      'timings_ms':{'model_load_ms':(loaded-started)*1000,'input_prepare_ms':(prepared-loaded)*1000,'inference_ms':(completed-prepared)*1000}}}
