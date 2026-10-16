# Direct Mac embedding worker

`macos/EmbeddingWorker.cpp` reads the existing EmbeddingGemma model through the
llama.cpp C API. It uses stdin/stdout pipes, without a server or HTTP listener.
The Python model coordinator owns its lifetime, verifies the model asset before
launch, and terminates/waits for the process when finished or cancelled.

## Supported assets

This adapter supports the existing `embeddinggemma:latest` deployment only:

| Asset | Pinned value |
| --- | --- |
| Model GGUF | 621,867,104 bytes |
| Model SHA256 | `0800cbac9c2064dde519420e75e512a83cb360de3ad5df176185dc69652fc515` |
| Ollama manifest SHA256 | `d1a9ad04c64272d78aab43641947f5cb18eec9e8cbf13d26223caeae2432d112` |
| Engine ID | `llama.cpp-b11669/ollama-embeddinggemma-v1` |
| llama.cpp revision | `620d2225cc436ab0b001e3200e590e3b286ef9ab` |
| Engine archive SHA256 | `dbed55493d72bc1ba2babc8770d669c2289b5bc4ee9fb2a4dfc158d45b7d13fd` |
| Platform | Apple Silicon, macOS 13.3 or newer |

The caller must verify the manifest and model hashes before launch. Native checks
add file-size, architecture, tensor-count, shape and mapped-range guards; they do
not replace the caller's digest verification. Model files are opened read-only,
with `O_NOFOLLOW`, and mapped privately with `PROT_READ`.

Stock llama.cpp does not load this Ollama GGUF directly: it declares `gemma3`
and adds two embedding projection tensors. `EmbeddingCompat.hpp` follows
[Ollama's MIT-licensed `handle_embeddinggemma`](https://github.com/ollama/ollama/blob/adc4aae9d68c025a455bea09fe04e42dd59fcc9f/llama/compat/llama-ollama-compat.cpp#L398)
at revision `adc4aae9d68c025a455bea09fe04e42dd59fcc9f` (source SHA256
`bf0b956f2a4c27a798301f33f87514d7bb2212e2baff3a4e99d0ec22b7b193e8`).
The adapter changes metadata and tensor names only in memory: `gemma-embedding`,
the matching scalar metadata, SWA RoPE base 10000 and `dense_2`/`dense_3` projection
names. The [public user-loader API](https://github.com/ggml-org/llama.cpp/blob/620d2225cc436ab0b001e3200e590e3b286ef9ab/include/llama.h)
requests optional tensors too; the adapter supplies the tied output weight,
zero biases and scalar-one quantization scales where appropriate. Unexpected
missing tensors or byte counts fail. Stored weights are not rewritten or copied
to a converted model file.

## Build

On a development Mac, obtain the official
[`llama-b11669-bin-macos-arm64.tar.gz`](https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-macos-arm64.tar.gz)
and the seven headers listed in `scripts/build_embedding_worker.py`, from that
script's pinned revision (`include/llama.h`, others under `ggml/include/`). Then:

```sh
python3 scripts/build_embedding_worker.py \
  --archive /path/to/llama-b11669-bin-macos-arm64.tar.gz \
  --headers /path/to/pinned-headers \
  --destination .local-state/direct-engines-build
```

The script verifies every input hash, refuses an existing destination, snapshots
the source/headers for compilation and writes `receipt.json` last. It does not
download weights or install anything into the current app. `receipt.files`
records the executable and real library file digests; `receipt.sources` records
the source inputs separately. Build outputs are disposable, not repository files.

Ship the executable, `lib/`, receipt and both license files together. The default
relative layout is `direct-engines/EmbeddingWorker` and `direct-engines/lib`.
The library directory contains seven real dylibs (11,164,088 bytes), plus relative
unversioned and `.0.dylib` aliases. Preserve the aliases and sign the final bundle.
The executable uses `@executable_path/lib`; backend discovery receives this same
private directory. The pinned distribution links `libggml-rpc` as a dependency;
the worker configures no RPC endpoint. Do not omit a linked library. The upstream
Metal library includes its shaders. The official engine requires macOS 13.3,
so a package containing it must not advertise 13.0 compatibility.

llama.cpp and the adapted Ollama mapping are MIT licensed; attribution is in
`docs/licenses/llama.cpp-MIT.txt` and `docs/licenses/ollama-MIT.txt`. The model's
existing Gemma terms remain separate and unchanged.

## Pipe contract

```text
EmbeddingWorker <verified-GGUF-path> <private-dylib-directory>
```

Each request and response is a four-byte unsigned **big-endian** byte length,
followed by exactly that many bytes. The limit is **100,000 bytes**. Requests
are raw UTF-8 text, including embedded newlines; responses are UTF-8 JSON.
There is one sequential request at a time, without request IDs. Engine logs go
to stderr; stdout contains only frames. The first response is:

```json
{"ready":true,"dim":768,"pooling":"mean","context_tokens":2048,"engine":"llama.cpp-b11669/ollama-embeddinggemma-v1"}
```

Successful requests return `{"tokens":N,"vector":[...]}`. Every vector has
768 finite values and is L2 normalized after mean pooling. Token counts include
special tokens. A request exceeding 2048 tokens is rejected before inference;
it is not truncated. The caller supplies the retrieval prefixes:

```text
task: search result | query: <question>
title: <title-or-none> | text: <document>
```

Errors use `{"error":{"code":"...","message":"..."},"fatal":false}`.
`empty`, `invalid_utf8` and `context_limit` are recoverable: the next frame can be
processed. `frame_too_large`, `truncated_frame` and `arguments` are fatal and exit
with status 2. An oversized header is rejected immediately without draining an
unbounded payload. Engine failures emit `engine`, `fatal:true`, then exit 3;
detailed diagnostics stay on stderr. EOF between complete frames exits 0.
Cancellation is process termination; cooperative interruption inside a Metal
operation is not implemented.

## Verification and limits

Portable framing/build checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_embedding_worker -v
```

The real-model test is opt-in and reads the original model without modification:

```sh
SOLASI_EMBEDDING_WORKER=/absolute/path/direct-engines/EmbeddingWorker \
SOLASI_EMBEDDING_LIB=/absolute/path/direct-engines/lib \
SOLASI_EMBEDDING_MODEL=/absolute/path/to/verified-model.gguf \
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_embedding_worker -v
```

Coverage includes fragmented frames, Korean/newline/emoji preservation, malformed
UTF-8, empty requests, oversized/truncated frames, rejection recovery and output
bounds. The real-model check verifies three Korean queries against three documents,
finite 768-dimensional normalized vectors, token-limit rejection, repeatability
after errors and unchanged model SHA256. These small fixtures establish the
execution contract, not broad Korean retrieval quality.

The compatibility probe on this M4 Mac observed approximately 1.8 GB peak RSS
and 1.2 GB peak physical footprint; the optional tied-output allocation adds
memory. Startup time varies with caches and concurrent model work. No speedup,
memory saving, or numerical parity with the old Ollama vectors is established.
Use an engine/template/pooling-specific index and rebuild rather than mixing old
and new vectors. Full app signing, index rebuilding and cancellation must also
be checked by the integrating caller.

The frozen-engine-v3 package was additionally exercised from `/private/tmp`
with Python/virtual-environment variables removed and system-only PATH. Its
`engines/EmbeddingWorker` and private `engines/lib` were selected by the product
coordinator, including receipt/hash verification. The existing read-only GGUF
returned 768 finite values with L2 norm 1.0 in a single observed 2.94-second
end-to-end call; the child exited and the original model's SHA256 still matched.
This verifies packaged execution, not a speed comparison or full app/UI use.
The [frozen engine report](direct-gemma-models.md#frozen-engine-verification)
records the executable hash, dependency paths, socket samples and child cleanup.
The complete frozen package requires macOS 27.0 because of its other bundled
dependencies, although this embedding component alone requires macOS 13.3.
