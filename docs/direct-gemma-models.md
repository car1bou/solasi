# Existing Gemma models: direct Mac execution

Verified on this Apple Silicon Mac on 2026-10-16. The adapter reuses the installed
model blobs read-only; it does not download, convert or overwrite weights.

## Supported adapter

`lecture_study/gemma_direct.py` exposes the same `generate(view, messages, images,
schema, output_limit, context_limit)` interface as the Qwen adapter. The coordinator
must first validate the installed model's content-addressed manifest and all
assets. `PROFILES` pins the two tested manifests; a matching model type alone is
not proof of compatibility.

| Installed model | Manifest SHA256 | Architecture context maximum |
| --- | --- | --- |
| `gemma4:12b` | `c6c61e74c905ac3a15f209c421dddf59444e2b28a10f25e8012a3d222e67c6e1` | 262144 |
| `gemma4:e2b` | `4b893f18d8d684c37055525725f7eba749ea2a3b1a2b89224edc27a1c6a8cd50` | 131072 |

Engine: `mlx-vlm-0.7.8/mlx-0.32.4/transformers-5.20.0/ollama-gemma-v1`.
Dependency versions are checked against the common `mlx_direct.VERSIONS` pins.
The configuration maxima above are not measured usable context sizes on this
Mac. Generation enforces the smaller requested/configured limit using the actual
prepared input tokens, including expanded image tokens, plus output allowance.

### Compatibility fixes

- Stored `.weight.scale` names are mapped to MLX `.scales` in memory. Each
  safetensor's `__metadata__` supplies its quantization mode and group size. E2B
  has **35 MXFP8/group32 modules and 282 NVFP4/group16 modules**; treating every
  module as NVFP4 is incorrect. The mode-implied group is used when omitted by
  the 12B export. Other modes/groups are rejected.
- 12B `.weight.global_scale` is a direct multiplier. Quantized linear modules use
  the pinned MLX-VLM `weight_scale_2` adapter. The tied token embedding applies
  the same multiplier after dequantization/matmul and casts back to the original
  output dtype. This follows Ollama's published implementation; it is not an
  arbitrary scale adjustment.
- Draft-model tensors are excluded from the main model load. Strict weight
  loading remains enabled for the target model.
- The installed tokenizer assets have **no chat template**. Calling their
  processor's fallback chat method produced only the user's raw sentence.
  That path yielded repeated `-` tokens with finite, unsaturated logits. Adding
  the official BOS/turn format resolved the observed failure with the same
  weights. The adapter renders the format explicitly, including adjacent
  assistant turns and image placeholders.
- Official `<|channel> ... <channel|>` blocks are parsed as disabled thinking.
  The answer outside those blocks is retained, including ordinary punctuation
  and Korean statements. An unfinished channel is not exposed as an answer.

### Source attribution

The mapping, prompt and channel behavior were checked against official Ollama
revision `d9b86018cba1d222fd28e28f42e5cdc15a060f39`:

- [`ReadGlobalScale` / `ToMLXGlobalScale`](https://github.com/ollama/ollama/blob/d9b86018cba1d222fd28e28f42e5cdc15a060f39/mlxrunner/model/globalscale.go)
  and [`scaleAndCast` / dequantization](https://github.com/ollama/ollama/blob/d9b86018cba1d222fd28e28f42e5cdc15a060f39/mlx/ops_extra.go):
  stored multiplier is converted through the internal `448*6` convention, then
  applied after scale-free dequantization/matmul. The net multiplier is the
  original stored value, not its reciprocal.
- [Prompt renderer](https://github.com/ollama/ollama/blob/d9b86018cba1d222fd28e28f42e5cdc15a060f39/model/renderers/gemma4.go),
  SHA256 `17d9bd5e43a641c0383504474520f92beef0fde25030467215c60425647bb7ed`,
  and its [reference cases](https://github.com/ollama/ollama/blob/d9b86018cba1d222fd28e28f42e5cdc15a060f39/model/renderers/gemma4_reference_test.go).
- [Response parser](https://github.com/ollama/ollama/blob/d9b86018cba1d222fd28e28f42e5cdc15a060f39/model/parsers/gemma4.go),
  SHA256 `7f31d6df737e8b24d7293021d332b5d68f062578151c4cc427a440cd10bf93a5`.

Ollama MIT attribution is retained in `docs/licenses/ollama-MIT.txt`. The model
licenses and the licenses of MLX/MLX-VLM/Transformers remain their own; this
adapter does not change them.

## Observed execution checks

Both models passed the following through the product adapter:

| Check | 12B | E2B |
| --- | --- | --- |
| Korean capital question | 서울, normal stop | 서울, normal stop |
| Constrained JSON | `{"city": "서울"}` | `{"city": "서울"}` |
| 128×128 solid red image | 빨강; 282 input tokens | 빨강; 282 input tokens |
| 12-token output cap | 12 tokens; `length` | 12 tokens; `length` |
| Oversized input against 512-token budget | Rejected before generation | Rejected before generation |
| SIGTERM after load and generation start | Exited -15 in 0.282 s | Exited -15 in 0.341 s |
| Open Internet sockets during that run | `lsof` exit 1, empty output | `lsof` exit 1, empty output |

The earlier same-weight diagnostic also correctly separated “the wife imagined
feeling lonely if her parents died” from “the husband visited a hospital last
week.” This is a small synthetic interpretation check, not the long real-audio
summary benchmark. The image check establishes basic visual-input execution,
not document OCR accuracy. Audio input has not been validated for these adapters.

One sequential, already-loaded-model contract run observed:

| Measurement | 12B | E2B |
| --- | --- | --- |
| Model load | 5.71 s | 7.30 s |
| Korean response | 4.05 s | 1.15 s |
| JSON response | 2.70 s | 3.54 s |
| Red-image response | 3.94 s | 1.15 s |
| MLX peak allocated memory | 7.74 GB | 7.81 GB |

These are single observations affected by cache/compilation state, not a fair
throughput comparison or evidence that E2B uses less memory. The app's coordinator
uses separate owned processes so cancellation can terminate the active engine
without leaving both generation and embedding resident.

Reusable checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_gemma_direct -v

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
SOLASI_GEMMA_MODEL_VIEW=/absolute/path/to/verified-read-only-model-view \
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_gemma_direct -v
```

The optional test loads one real model, then checks Korean text, JSON, image
expansion, output limits and actual input-budget rejection. Protocol/process
supervision is additionally checked in the coordinator tests. The frozen-engine
execution check below covers bundled inference. App installation, large real
PDFs, long contexts and long summaries still require separate validation.

## Frozen engine verification

On 2026-10-16, `frozen-engine-v3/solasi-engine` executed the following checks on
this Mac. Executable SHA256:
`52a3520d590a48f016e728e20d52605c0171694ae03e5537e878be6c3646db25`.
The bundle manifest declares arm64 and minimum macOS **27.0**, derived from all
of its bundled Mach-O dependencies. This is the packaged runtime's requirement;
the native embedding component's lower minimum does not lower the whole app's.

The supervisor used the product `DirectModels` coordinator with the frozen
executable as its Python/worker path. Inference ran in that executable, not the
supervisor's development Python. The working directory was `/private/tmp`;
`PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, `DYLD_LIBRARY_PATH` and `CONDA_PREFIX`
were removed, PATH contained only system directories, and Hugging Face and
Transformers offline mode was enabled. Model views and caches were isolated.
Observed open library paths for all seven MLX workers were inside the bundle's
`_internal`, including Python, MLX, NumPy, tokenizers, llguidance and the Metal
shader library; no development-environment library path was observed.

| Frozen inference check | Result | Elapsed time |
| --- | --- | --- |
| Qwen3.5 4B, Korean text | 서울특별시; normal stop | 11.69 s |
| Qwen3.5 4B, constrained JSON | `{"city": "서울"}`; normal stop | 6.47 s |
| Gemma4 E2B, Korean text | 서울; normal stop | 14.40 s |
| Gemma4 E2B, constrained JSON | `{"city": "서울"}`; normal stop | 10.25 s |
| Gemma4 12B, Korean text | 서울; normal stop | 20.98 s |
| Gemma4 12B, constrained JSON | `{"city": "서울"}`; normal stop | 16.62 s |
| EmbeddingGemma GGUF | 768 finite values; L2 norm 1.0 | 2.94 s |
| Qwen3-ASR, FLEURS `fleurs-0068` | Exact reference match | 6.23 s |

Generation used an output cap of 64 and context budget of 2048. Each request
created and closed its own worker. These are single sequential end-to-end
observations, including startup and asset checks as needed, not comparable
warm-model throughput measurements. ASR used the same real 15.78-second Korean
clip as the earlier compatibility check, normalized by bundled FFmpeg to mono
16 kHz PCM16. Its output matched both the reference and the prior Python-worker
output. That one clip does not establish general Korean ASR accuracy.

The first frozen build exposed a real exit failure: Gemma E2B JSON timed out
while Python finalization waited for a `multiprocessing.resource_tracker` child.
The frozen executable had interpreted the helper's `-c` arguments as an app
launch. Calling `multiprocessing.freeze_support()` before app/model imports
activates PyInstaller's supplied helper routing. The corrected build passed the
same JSON request, and a separate exact resource-tracker command exited 0 on
pipe EOF with empty stdout/stderr. All seven helper processes observed during
inference exited; no owned model/helper processes remained afterward.

All 130 sampled `lsof -i` checks returned no Internet sockets. This is sampled
runtime evidence together with the offline settings, not continuous network
packet capture. After the run, every blob of Qwen4B, E2B, 12B and EmbeddingGemma,
plus all nine Qwen-ASR model files, matched their pinned SHA256 values. The probe
did not install an app or write to a user's records, audio or handwriting DB.

Local evidence: `.local-state/serverless-mac-20261016/embedding-probe/frozen-v3/`
contains `verify.py`, `results.json`, `run.log` and the normalized ASR fixture.
The earlier failed run and its native stack sample are preserved separately
under `frozen-v2/`. Full app startup and UI validation are recorded by the
integrating task, separately from these inference-worker results.

## EmbeddingGemma 2 investigation

The installed `embeddinggemma-2:270m-mxfp8-text` manifest
`078984ed5177fd9d7fb14595e8a5beb73f930b676e2efdbcccb0395d180ded5f`
also executed offline in a disposable MLX probe. Its 217 MXFP8/group32 modules
use the existing MLX-VLM `embedding_gemma2` implementation. Six Korean document
and query vectors were finite, 768-dimensional and L2 normalized; all three
queries ranked their corresponding document first. The observed MLX peak was
496,828,228 bytes. Exact cosine scores were 0.76015, 0.70517 and 0.77685 for the
matching documents; these are not directly comparable with another embedding
model's cosine values.

This is compatibility evidence for a later adapter. It is not registered as a
usable provider in this migration: the default existing EmbeddingGemma GGUF has
the separately verified native worker. EmbeddingGemma 2 needs its own provider
fingerprint, input/token contract and independent index before activation.
