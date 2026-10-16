"""Explicit local-only compatibility probe; does not modify model blobs or app data."""
import argparse
import importlib.metadata
import json
import time
from pathlib import Path

from lecture_study.model_assets import installed_asset, prepare_mlx_view
from lecture_study.mlx_direct import load as load_qwen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New disposable output directory')
    parser.add_argument('--image', type=Path, required=True, help='SOLASI logo fixture')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    import mlx.core as mx
    from mlx_vlm import generate, stream_generate
    from mlx_vlm.structured import build_json_schema_logits_processor
    from mlx_vlm.prompt_utils import apply_chat_template

    started = time.monotonic()
    asset = installed_asset(args.models_dir, 'qwen3.5:4b')
    view = prepare_mlx_view(asset, args.output/'view')
    model, processor = load_qwen(view)
    report = {'model': asset['model'], 'asset_digest': asset['digest'],
              'engines': {name: importlib.metadata.version(name) for name in ('mlx', 'mlx-metal', 'mlx-vlm', 'transformers', 'llguidance')},
              'load_and_hash_seconds': time.monotonic()-started, 'cases': []}
    tokenizer = processor.tokenizer if hasattr(processor, 'tokenizer') else processor
    schema = {'type': 'object', 'properties': {'subject': {'type': 'string'},
              'state': {'type': 'string', 'enum': ['proposal', 'decision']},
              'quote': {'type': 'string'}}, 'required': ['subject', 'state', 'quote'], 'additionalProperties': False}
    cases = [('korean_text', '대한민국의 수도는 어디인가요? 한 문장으로 답하세요.', 64, None, None),
             ('json', '회의 메모: 지수는 예산이 승인되면 다음 주에 장비를 주문하겠다고 제안했다. 아직 결정되지 않았다. 주어 subject, proposal/decision 중 state, 정확한 원문 quote를 JSON으로 답하세요.', 180, schema, None),
             ('vision', '그림에 적힌 영문 단어를 그대로 답하세요.', 64, None, str(args.image)),
             ('output_limit', '자연수 1부터 100까지 모두 나열하세요.', 2, None, None)]
    for name, text, limit, constraint, image in cases:
        prompt = apply_chat_template(processor, model.config, text, num_images=1 if image else 0, enable_thinking=False)
        options = {'max_tokens': limit, 'temperature': 0.0, 'verbose': False}
        if constraint: options['logits_processors'] = [build_json_schema_logits_processor(tokenizer, constraint)]
        started = time.monotonic()
        result = generate(model, processor, prompt=prompt, image=image, **options)
        row = {'name': name, 'text': result.text, 'finish_reason': result.finish_reason,
               'prompt_tokens': result.prompt_tokens, 'generation_tokens': result.generation_tokens,
               'seconds': time.monotonic()-started}
        if constraint: row['parsed'] = json.loads(result.text)
        report['cases'].append(row)
        (args.output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(row, ensure_ascii=False), flush=True)
    prompt = apply_chat_template(processor, model.config, '1부터 1000까지 세어 주세요.', enable_thinking=False)
    stream = stream_generate(model, processor, prompt, max_tokens=512, temperature=0.0)
    count = 0
    for result in stream:
        count += 1
        if count == 2: break
    stream.close()
    report['iterator_cancel_after_events'] = count
    report['peak_metal_bytes'] = mx.get_peak_memory()
    (args.output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert '서울' in report['cases'][0]['text']
    assert report['cases'][1]['parsed']['subject'] == '지수'
    assert report['cases'][1]['parsed']['state'] == 'proposal'
    assert 'SOLASI' in report['cases'][2]['text'].upper()
    assert report['cases'][3]['generation_tokens'] == 2
    assert report['cases'][3]['finish_reason'] == 'length'
    assert count == 2
    print('PASS: direct Korean/JSON/vision/limit/iterator cancellation', flush=True)


if __name__ == '__main__': main()
