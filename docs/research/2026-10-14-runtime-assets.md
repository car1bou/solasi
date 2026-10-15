# C4 공개 런타임 자산 인벤토리

확인일: 2026-10-14 (Asia/Seoul). 기준 디렉토리: `<project-root>/.local-state/runtime`.

범위: 지정된 공개 archive·소스·설치 결과·provenance와 추가 허용된 앱 LiteParse 2.16.0 package/dist-info. 사용자 .ollama, 키, 녹음·노트·DB 내용은 읽지 않았다. 제품 runtime-manifest.json·코드·테스트를 수정하지 않았고 runtime 실행·서버 기동·새 archive/wheel 다운로드는 하지 않았다. PyPI JSON 메타데이터만 추가 조회했다.

## 1. 다운로드 원본: 현재 bytes·SHA 재확인

모든 SHA는 SHA-256이며 아래 8개 파일의 현재 bytes/SHA가 기존 provenance.json (로컬 검증 자료·공개본 미포함)과 일치했다. 원 URL/revision은 그 파일의 준비 기록에서 읽었으며 이번에 다운로드 URL의 실제 payload를 다시 받지는 않았다.

| 로컬 파일 | bytes | 현재 SHA-256 |
|---|---:|---|
| downloads/whisper.cpp-v1.9.5.tar.gz (로컬 검증 자료·공개본 미포함) | 9,631,456 | `645445da884df6dbd52b30f82d7be7c01d1767c938714e477e786b88d529e9f4` |
| downloads/ffmpeg-9.0.2.tar.gz (로컬 검증 자료·공개본 미포함) | 17,333,895 | `0aa2b1de2a5698b20a23e93d539a9a8e82ca0117496c5bdf05d198805f42bb3b` |
| downloads/cmake-3.31.12-macos-universal.tar.gz (로컬 검증 자료·공개본 미포함) | 79,954,716 | `799af7fd545db9bf1b9cfe72f8095880e727a2d4e0df0e3dffc3bc7b95c2d3b0` |
| downloads/ollama-darwin-v0.40.3.tgz (로컬 검증 자료·공개본 미포함) | 167,455,486 | `a2d1d906a2c8febd9cb18f5c183854d0a6db5dc522940d68b0c0ed048e8dfdea` |
| tessdata/kor.traineddata (로컬 검증 자료·공개본 미포함) | 12,528,128 | `f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff` |
| tessdata/eng.traineddata (로컬 검증 자료·공개본 미포함) | 15,400,601 | `8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba` |
| tessdata/LICENSE.Apache2.txt (로컬 검증 자료·공개본 미포함) | 10,173 | `a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9` |
| ollama/LICENSE (로컬 검증 자료·공개본 미포함) | 1,058 | `5934ed2ce0d15154bcdb9c85203210abac0da4314af34081e36df4599f90b226` |

### 공식 출처와 digest 근거

- **Whisper.cpp 1.9.5 소스:** [기록된 공식 다운로드 URL](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/d1be6fde11ac6e0407606b4e42fe72d34add8037), revision `d1be6fde11ac6e0407606b4e42fe72d34add8037`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.
- **FFmpeg 9.0.2 소스:** [기록된 공식 다운로드 URL](https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/946fcce07b6dcd0331c8cc609192aeff5e1924f8), revision `946fcce07b6dcd0331c8cc609192aeff5e1924f8`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.
- **CMake 3.31.12 macOS universal:** [기록된 공식 다운로드 URL](https://github.com/Kitware/CMake/releases/download/v3.31.12/cmake-3.31.12-macos-universal.tar.gz), revision `3.31.12`. provenance의 expected_sha256와 일치; digest_basis는 publisher-or-approved-plan.
- **Ollama 0.40.3 Darwin:** [기록된 공식 다운로드 URL](https://github.com/ollama/ollama/releases/download/v0.40.3/ollama-darwin.tgz), revision `0.40.3`. provenance의 expected_sha256와 일치; digest_basis는 publisher-or-approved-plan.
- **Tessdata best 한국어:** [기록된 공식 다운로드 URL](https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/kor.traineddata), revision `e12c65a915945e4c28e237a9b52bc4a8f39a0cec`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.
- **Tessdata best 영어:** [기록된 공식 다운로드 URL](https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/eng.traineddata), revision `e12c65a915945e4c28e237a9b52bc4a8f39a0cec`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.
- **Tessdata 라이선스:** [기록된 공식 다운로드 URL](https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/LICENSE), revision `e12c65a915945e4c28e237a9b52bc4a8f39a0cec`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.
- **Ollama MIT 고지:** [기록된 공식 다운로드 URL](https://raw.githubusercontent.com/ollama/ollama/v0.40.3/LICENSE), revision `v0.40.3`. 공식 발표 SHA 미기록; 현재 파일에서 계산한 SHA.

Ollama 태그의 공식 소스 commit은 앞선 고정 소스 조사에서 `eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`로 확인했으나, 이번 archive provenance는 release version 0.40.3을 기록한다. CMake의 source commit은 이 허용된 자료에서는 미확인이다. expected_sha256가 있다는 기록만으로 publisher 서명이나 독립적인 진위 검증까지 완료됐다고 표현하지 않는다.

8개 원본 파일 합계는 **302,315,513 bytes**다. 이는 압축 해제·빌드·모델·임시 파일·filesystem overhead를 포함한 디스크 요구량이 아니다.

## 2. 실행 파일: 공개 archive 결과와 로컬 빌드 결과 구분

| 현재 파일 | bytes | SHA-256 |
|---|---:|---|
| build/whisper/bin/whisper-cli (로컬 검증 자료·공개본 미포함) | 8,033,032 | `0c693fcecdecf4e1b7749d0424d420bf015e2dc78d0f57b973bc4ee2d3837e52` |
| ffmpeg/bin/ffmpeg (로컬 검증 자료·공개본 미포함) | 21,963,112 | `31184dc6cdd9e1a7259ae6e265a74623cd01f561ef6212af9908148bf2b1e33c` |
| ffmpeg/bin/ffprobe (로컬 검증 자료·공개본 미포함) | 21,788,008 | `6a85fcd03ea542266e501b50f3841dfc4cad192b0d27dacb79af10310563ea2f` |
| cmake/CMake.app/Contents/bin/cmake (로컬 검증 자료·공개본 미포함) | 23,876,688 | `84d61153cfcb96949945f6b04a57ec7e052aedf9580107acd5a2d9957e162e53` |
| ollama/llama-server (로컬 검증 자료·공개본 미포함) | 17,993,312 | `3efd976f34a2469901b62c838f8b47a47f2a31bec403b4a287567a40f38658d4` |
| ollama/ollama (로컬 검증 자료·공개본 미포함) | 52,076,880 | `76535100c7aaf5aa94fe749b1bf0cfe3a702fa0743c7421fed059b783f4969de` |

- **Whisper.cpp 1.9.5:** 소스에서 로컬 빌드한 arm64 실행 파일이다. CMake source의 version 1/9/5와 빌드 provenance를 확인했다. Release, WHISPER_BUILD_IS_DEV=OFF, tests/server OFF, BUILD_SHARED_LIBS=OFF, OpenMP OFF, Metal ON, GGML_METAL_EMBED_LIBRARY=ON; target은 whisper-cli다. otool -L은 시스템 framework/library만 보여준다. 현재 구성의 실행에 별도 libwhisper.dylib 또는 whisper용 metallib 파일은 필요하지 않은 것으로 판단된다. 빌드 기록 (로컬 검증 자료·공개본 미포함), CMakeLists (로컬 검증 자료·공개본 미포함)
- **FFmpeg/FFprobe 9.0.2:** 고정 소스에서 이 PC의 Apple clang 21로 빌드했다. RELEASE·생성 ffversion.h·기존 version 기록은 9.0.2다. configure는 --disable-doc --disable-debug --disable-ffplay --disable-autodetect. config.mak는 static=yes, shared/GPL/nonfree/version3 비활성을 기록한다. otool -L에서 외부 FFmpeg dylib 없이 시스템 library만 확인했다. CLI 실행 파일 둘의 직접 다운로드 URL은 없고, 표의 SHA는 이 로컬 빌드 결과다. 빌드 기록 (로컬 검증 자료·공개본 미포함), 빌드 설정 (로컬 검증 자료·공개본 미포함)
- **Ollama 0.40.3:** 공식 Darwin archive의 universal x86_64/arm64 파일이다. 본 CLI뿐 아니라 llama-server·dylib·MLX Metal 파일이 있다. archive의 47개 regular member를 현재 파일과 SHA/bytes 대조했고 10개 symlink target도 archive와 일치했다. 빠진 member·다른 regular 내용은 0개다.
- **CMake 3.31.12:** 공식 macOS universal archive에서 준비했다. 기존 provenance에 cmake --version 성공이 기록됐고 현재 binary SHA가 그 기록과 일치한다. **이번에는 실행하지 않았다.** 소스 빌드 도구이며 완성된 앱 실행과 구분한다.
- source archive를 고정해도 compiler/SDK/경로가 달라지면 로컬 빌드 binary SHA는 달라질 수 있다. 다른 PC의 빌드 결과를 이 PC의 binary SHA와 동일하다고 가정하지 않는다.

## 3. 라이선스·필수 파일

| 항목 | 확인한 라이선스 | 보존하거나 준비할 파일 |
|---|---|---|
| Whisper.cpp 엔진 | 로컬 LICENSE의 MIT | whisper-cli와 LICENSE. 모델 weight·VAD는 별도 자산이며 이번 inventory에 포함하지 않았다. |
| FFmpeg 현재 빌드 | LICENSE.md 및 기존 -L 기록은 LGPL 2.1 이상; GPL/nonfree 빌드는 비활성 | ffmpeg·ffprobe, LICENSE.md, COPYING.LGPLv2.1, 해당 소스·빌드 기록. static 빌드 배포 시 제공할 소스/재링크 자료 조건은 완성된 배포물에서 별도 확인해야 한다. |
| Ollama | 핵심 MIT + 동봉된 제3자 고지 | archive tree와 12개 LICENSE/NOTICE. **핵심 MIT LICENSE는 원 archive에 없고 공식 raw URL에서 별도로 준비한 파일이다. archive만 풀면 누락된다.** |
| CMake | Copyright.txt의 BSD 3-Clause 형태 + 동봉된 제3자 고지 | CMake.app의 bin/cmake와 share/cmake-3.31 resources, doc/cmake 고지. 본 조사에서 CLI용 최소 subset으로 잘라 실행하는 검증은 하지 않았다. |
| Tessdata best kor/eng | Apache-2.0 | kor.traineddata·eng.traineddata·LICENSE.Apache2.txt. 언어 데이터이며 독립 OCR 실행 프로그램은 아니다. |
| LiteParse | METADATA의 Apache-2.0; SBOM의 tesseract-rs binding 0.2.0은 MIT | Python package, native extension, libpdfium.dylib 및 dist-info/고지. binding 라이선스로 native Tesseract·Leptonica·PDFium 전체 고지를 대체하지 않는다. |

라이선스 파일 fingerprint:

| 로컬 파일 | bytes | SHA-256 |
|---|---:|---|
| sources/whisper.cpp/LICENSE (로컬 검증 자료·공개본 미포함) | 1,078 | `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d` |
| sources/ffmpeg/LICENSE.md (로컬 검증 자료·공개본 미포함) | 4,346 | `2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af` |
| sources/ffmpeg/COPYING.LGPLv2.1 (로컬 검증 자료·공개본 미포함) | 26,517 | `246041b6ecf9bc32d718a62c57877c78b5eb397b6467e74ed7ae2626ab189c30` |
| cmake/CMake.app/Contents/doc/cmake/Copyright.txt (로컬 검증 자료·공개본 미포함) | 5,477 | `0676e30827684487aa0ea8f72f01e9460a6320fa34a2888df0ad1dd3e8a06eb8` |

Whisper/FFmpeg를 다른 Mac에서 소스 빌드하려면 CMake 외에 compiler·macOS SDK 등 Apple Command Line Tools에 해당하는 도구가 필요하다. 현재 build 기록에는 /usr/bin/make, Apple clang 21이 사용됐다. **새 Mac의 CLT 설치·빌드 성공이나 배포 고지 전체 충족은 이번 조사로 확인하지 않았다.**

Ollama에는 mlx_metal_v3/mlx_metal_v4 tree, CPU backend 파일과 symlink가 있다. 사용할 runner/OS/CPU별 최소 subset은 실행 확인 없이 단정하지 않는다. C4 준비 경로는 원래 tree 구조를 보존하는 편이 현재 inventory와 일치한다. llama-server의 x86_64 쪽은 @rpath/libllama-server-impl.dylib, libllama-common/libmtmd/libllama/libggml/libggml-base에 의존한다. arm64 MLX의 모든 동적 로딩 경로는 otool -L만으로 확인하지 못한다.

## 4. LiteParse wheel의 OCR 엔진 내포 여부

추가 읽기 범위는 `<project-root>/.venv/lib/python3.12/site-packages/liteparse`와 해당 2.16.0 dist-info만이다.

- WHEEL tag는 **cp310-abi3-macosx_11_0_arm64**, Python 요구는 >=3.10이다.
- _liteparse.abi3.so의 nm -m에서 _TessBaseAPICreate, _TessBaseAPIInit3, _TessBaseAPIRecognize 등 함수가 __TEXT의 실제 정의로 확인됐다. otool -L에는 외부 libtesseract dylib가 없다. **현재 arm64 wheel의 native extension에 Tesseract 코드가 내포돼 있다.**
- libpdfium.dylib도 package 안에 있다. SBOM은 tesseract-rs 0.2.0과 LiteParse/PDFium wrapper들을 기록한다. native Tesseract·Leptonica의 정확한 upstream revision은 이 자료에서 미확인이다.
- runtime 폴더에 별도 tesseract CLI가 준비됐다는 증거는 없다. **이를 LiteParse OCR 엔진이 없다는 뜻으로 해석하지 않는다.** 부모가 수행한 기존 한국어 OCR 제품 검증은 별도 실행 기록이며 이번 파일 검사에서는 OCR를 재실행하지 않았다.

현재 파일 모두 wheel RECORD의 SHA-256(base64url)과 byte length에 일치했다:

| 설치 파일 | bytes | SHA-256 | RECORD |
|---|---:|---|---|
| liteparse/_liteparse.abi3.so (로컬 검증 자료·공개본 미포함) | 20,427,632 | `fccb65776cb8a17bc8b1b7aec0ec6a3ddb19a4693f2a57fd6d2f4bcf8c17dca1` | 일치 |
| liteparse/libpdfium.dylib (로컬 검증 자료·공개본 미포함) | 6,711,520 | `62e3f2943aa6d22a8422cb0e385fd20bdf29d9c9a77614fbd81b152d9f496b34` | 일치 |
| liteparse-2.16.0.dist-info/METADATA (로컬 검증 자료·공개본 미포함) | 9,055 | `babad49e9d263a39f5fcdcf7872edc968b78017db69a64d84e7ad7827ba822c1` | 일치 |
| liteparse-2.16.0.dist-info/WHEEL (로컬 검증 자료·공개본 미포함) | 104 | `d404f69d20caabae3a0b518edec34ec4110e814d1c05998819a45efc3ad5dce9` | 일치 |
| liteparse-2.16.0.dist-info/sboms/liteparse-python.cyclonedx.json (로컬 검증 자료·공개본 미포함) | 425,480 | `1b1eaee7bad43a7f839a125e3cdbde71dca94a3a50d52c0c02cf89e4b299cbdc` | 일치 |

### 공식 PyPI 원 wheel metadata

[LiteParse 2.16.0 공식 PyPI](https://pypi.org/project/liteparse/2.16.0/)와 [JSON metadata](https://pypi.org/pypi/liteparse/2.16.0/json)에서 현재 설치 tag에 대응하는 파일 1개를 확인했다.

- 파일: `liteparse-2.16.0-cp310-abi3-macosx_11_0_arm64.whl`
- [원 wheel 다운로드 URL](https://files.pythonhosted.org/packages/b2/a5/1d17a610cac28d91ee068ee99da5451d50c1bf12ad641b980fa2eeaa912d/liteparse-2.16.0-cp310-abi3-macosx_11_0_arm64.whl)
- bytes: **12,113,978**
- SHA-256: `eeba58366851592efd2a19b8b6199bc979aadaa0014d36f314559462c1f88f89`
- 업로드: `2026-10-12T20:12:59.055636Z`, yanked=false, license expression Apache-2.0.
- 원 wheel archive는 이번에 받거나 hash하지 않았다. 공식 metadata의 전체 wheel SHA와 설치 파일의 RECORD 대조는 서로 다른 확인이다. Python 환경의 다른 package·pip cache·사용자 홈은 조사하지 않았다.

## 5. 현재 폴더 점유의 파일 byte 합계

아래는 regular file의 logical bytes 합계다. symlink, filesystem block allocation, 공유/압축 공간, 모델과 다른 runtime 진단 폴더를 제외한다. source 폴더에는 로컬 빌드로 생긴 산출물이 섞여 있으므로 pristine upstream source 크기로 해석하지 않는다. 디렉토리 SHA는 계산하지 않았다.

| 폴더 | regular file 수 | logical bytes |
|---|---:|---:|
| sources/whisper.cpp (로컬 검증 자료·공개본 미포함) | 2,040 | 39,975,216 |
| sources/ffmpeg (로컬 검증 자료·공개본 미포함) | 14,755 | 244,620,248 |
| build/whisper (로컬 검증 자료·공개본 미포함) | 558 | 44,380,793 |
| ffmpeg (로컬 검증 자료·공개본 미포함) | 193 | 75,833,302 |
| cmake/CMake.app (로컬 검증 자료·공개본 미포함) | 8,051 | 228,508,702 |
| ollama (로컬 검증 자료·공개본 미포함) | 48 | 545,152,855 |
| tessdata (로컬 검증 자료·공개본 미포함) | 3 | 27,938,902 |

## 6. C4에 옮길 확인 규칙 예

1. 새 다운로드는 위 **원본 archive/언어 데이터 SHA**로 검증하고, 임시 파일에서 완전 다운로드가 확인된 뒤 공개 자산 위치로 전환한다. 로컬 빌드 SHA를 공식 배포 SHA로 등록하지 않는다.
2. archive를 준비한 뒤 필요한 실행 파일·고지·library/resource tree가 있는지 확인한다. Ollama MIT LICENSE의 별도 준비를 포함한다.
3. Whisper/FFmpeg 소스 빌드에는 CMake·compiler/SDK가 필요하고, 완료 파일은 버전/architecture/실행 결과와 원본 source revision을 함께 기록한다. 이 문서는 구현이나 새 실행 확인을 대신하지 않는다.
4. OCR는 LiteParse native package+PDFium+kor/eng tessdata를 확인한다. 독립 Tesseract CLI가 없다는 이유로 추가 엔진 다운로드를 요구하지 않는다.
5. 기존 runtime/provenance 기록의 성공, 이번 SHA/구조 검사, 부모의 제품 실행 결과를 각각 구분한다. Windows/Linux·Intel용 새 로컬 빌드·clean Mac 재현·서명/공증·업데이트·전체 라이선스 고지는 미확인이다.

## 부록: Ollama 원 tree fingerprint

원 archive 59 member(47 regular, 10 symlink, 2 directory)의 regular 내용·symlink가 모두 일치한다. 현재 tree의 regular file은 48개이며 추가 1개는 별도 준비한 핵심 MIT LICENSE다. AppleDouble ._mlx.metallib 2개도 기존 준비 과정에서 그대로 보존됐다. 이 표는 runtime manifest를 수정한 결과가 아니다.

<details>
<summary>48개 regular file의 경로·bytes·SHA</summary>

| 현재 파일 | bytes | SHA-256 |
|---|---:|---|
| ollama/CPP_HTTPLIB_LICENSE (로컬 검증 자료·공개본 미포함) | 1,075 | `4b45cbe16d7b71b89ae6127e26e0d90a029198ca5e958ad8e3d0b8bbed364d8b` |
| ollama/DLPACK_LICENSE (로컬 검증 자료·공개본 미포함) | 11,345 | `3e8f6bc39276a586d60c8c5aaece2ff989262181cf2b3d2a128db58f97a9300c` |
| ollama/FMT_LICENSE (로컬 검증 자료·공개본 미포함) | 1,431 | `07580f2a3b35709ce703d523f447b242f6dfec7582a8c0df102c7fa2849375f8` |
| ollama/GO_LICENSE (로컬 검증 자료·공개본 미포함) | 147,791 | `e1e097d113ea8aef3687cc6451fdfc60b1d57f0cfd06de590aea4c9f9f17b7a4` |
| ollama/LICENSE (로컬 검증 자료·공개본 미포함) | 1,058 | `5934ed2ce0d15154bcdb9c85203210abac0da4314af34081e36df4599f90b226` |
| ollama/LLAMA_CPP_LICENSE (로컬 검증 자료·공개본 미포함) | 1,078 | `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d` |
| ollama/LLAMA_CPP_VENDORS_LICENSE (로컬 검증 자료·공개본 미포함) | 7,257 | `eb17b411e39c75c4ac40916d66e39287ee9723b8bbe54daf020fc27acf670c11` |
| ollama/MLX_C_LICENSE (로컬 검증 자료·공개본 미포함) | 1,067 | `44326a4ea062241ae6fc26ee2ec90bdc81af7eb7b9d3966181b733fa69d42057` |
| ollama/MLX_LICENSE (로컬 검증 자료·공개본 미포함) | 1,066 | `ccfab7ccb2ea306f71531c8ca77bb55507606cd90768b1e32b8b52ab5b48cf01` |
| ollama/PICOJSON_LICENSE (로컬 검증 자료·공개본 미포함) | 1,414 | `52a7da16781b4b899382c9ddfcf059235cdee73e2f45cfd7402c2ae9a2e9d28d` |
| ollama/XGRAMMAR_LICENSE (로컬 검증 자료·공개본 미포함) | 11,357 | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| ollama/XGRAMMAR_NOTICE (로컬 검증 자료·공개본 미포함) | 54 | `769c6907073c65801bfcfe3ce1c0e80bf0ae4e124e2769d4f026c038ad583c0f` |
| ollama/libggml-base.0.25.3.dylib (로컬 검증 자료·공개본 미포함) | 794,416 | `a7dd2a63375ac4ed95c51acac7b44aa74ef08d10e4189c07164f158e6c2b9fe3` |
| ollama/libggml-blas.so (로컬 검증 자료·공개본 미포함) | 52,560 | `7bed849094cf01a3d926ce6ea1d3d8c8f6308f616bc1c7702c9af0a863efd50b` |
| ollama/libggml-cpu-alderlake.so (로컬 검증 자료·공개본 미포함) | 1,616,000 | `9a51b4d3972c6fd30fb6296e093c6ab1f23340a798d991253ece23a440900cd5` |
| ollama/libggml-cpu-cannonlake.so (로컬 검증 자료·공개본 미포함) | 1,867,808 | `b553fa3298c331db4decc8de91261bd5001eb670e8224f82f702a49128930380` |
| ollama/libggml-cpu-cascadelake.so (로컬 검증 자료·공개본 미포함) | 1,852,688 | `ced0bb2ecfeca50bbf482a4dd25ea1ce4354636d1a7a730149ac287bbef7823d` |
| ollama/libggml-cpu-cooperlake.so (로컬 검증 자료·공개본 미포함) | 1,856,928 | `32bd80e5b292f9ba94a5441852fcc5a3e7bc1c9c2f440121d2ab1a1d774cd407` |
| ollama/libggml-cpu-haswell.so (로컬 검증 자료·공개본 미포함) | 1,624,256 | `9924c45cf15ee8e035436ac0e7bb3cd1d1475f4161cb9862d800076cba4d6470` |
| ollama/libggml-cpu-icelake.so (로컬 검증 자료·공개본 미포함) | 1,860,944 | `635cf4eb01c37d5e05fc52352e8f320832ce34bea1f0655520e834dc86f519fe` |
| ollama/libggml-cpu-ivybridge.so (로컬 검증 자료·공개본 미포함) | 1,439,616 | `83dfe6e14a3e176c31e9d8307c85f2c6e4d82379a3f9b88e7e1f8b38eee09530` |
| ollama/libggml-cpu-piledriver.so (로컬 검증 자료·공개본 미포함) | 1,447,872 | `44c582d8ed6104e74879d457776515ef620138c6f3d42b026b64ae625af22ecd` |
| ollama/libggml-cpu-sandybridge.so (로컬 검증 자료·공개본 미포함) | 1,422,320 | `484d23feefdc2ec1cf938ed52f1cb7b12d8c75a43d3979d78cd98c28ecde7fa8` |
| ollama/libggml-cpu-sapphirerapids.so (로컬 검증 자료·공개본 미포함) | 2,099,808 | `6a9bc8a9de2b8cd8f79b669bc91d170d90dbd917fc974468f35baebd403c27f2` |
| ollama/libggml-cpu-skylakex.so (로컬 검증 자료·공개본 미포함) | 1,859,552 | `d8c1a051bfffc13550d74af95f9018d7a43f9f9d4aad17d205a87f95011ac815` |
| ollama/libggml-cpu-sse42.so (로컬 검증 자료·공개본 미포함) | 1,056,800 | `6c98fba51c112e28fcc743f7f06fa2b55ba11f258ba84183bc43c64f66cd6795` |
| ollama/libggml-cpu-x64.so (로컬 검증 자료·공개본 미포함) | 1,069,184 | `523ddd845ca692a08aa087090eacb609ef4fe8128ce93a29acaa1dd9ca237c44` |
| ollama/libggml-cpu-zen4.so (로컬 검증 자료·공개본 미포함) | 1,861,056 | `ca9b74f2ff537f1205ad8214c66b6b9d626364091db85d6b7fa76e2c2b8c3f3b` |
| ollama/libggml.0.25.3.dylib (로컬 검증 자료·공개본 미포함) | 57,840 | `dfa3d25ac8bb8e3387f99e26e39cd0659b9d223d1234ceb68b2fdcfd85770902` |
| ollama/libllama-common.0.5.0.dylib (로컬 검증 자료·공개본 미포함) | 5,307,616 | `29ad3be2e494cb7335a14c2a82ebe6f4679db2c7d19b46fae1829cc2b5c41570` |
| ollama/libllama-quantize-impl.dylib (로컬 검증 자료·공개본 미포함) | 89,984 | `38391972435244f1aafefa2d19ee3d4bfa6d619037b056dd6e28f5825224623b` |
| ollama/libllama-server-impl.dylib (로컬 검증 자료·공개본 미포함) | 3,470,864 | `49841bfd099e9b2d8e8193c7966ef1a1041ba84b6231f118891051980d8353aa` |
| ollama/libllama.0.5.0.dylib (로컬 검증 자료·공개본 미포함) | 3,782,192 | `e7b7c02028b9bf0867a3f4f5499de1743534b6e1d68b76bda38836b3777cb4c0` |
| ollama/libmtmd.0.5.0.dylib (로컬 검증 자료·공개본 미포함) | 1,515,408 | `31d49aa40831f4872d7e199d36bd480b1ccd948521db22ed335a53ce3bdbd051` |
| ollama/llama-quantize (로컬 검증 자료·공개본 미포함) | 10,950,112 | `9937af66494ffb0f278976517e9dea4736328c8733c8fef758a562d4614a263c` |
| ollama/llama-server (로컬 검증 자료·공개본 미포함) | 17,993,312 | `3efd976f34a2469901b62c838f8b47a47f2a31bec403b4a287567a40f38658d4` |
| ollama/mlx_metal_v3/._mlx.metallib (로컬 검증 자료·공개본 미포함) | 9,663 | `61d3fff95481069572af4c8da0aea241e048d24b3f3ec55bc9868b6aafcf2fa0` |
| ollama/mlx_metal_v3/libmlx.dylib (로컬 검증 자료·공개본 미포함) | 48,549,584 | `519760038705ce0bb6b648e8fe2ee7227454ddbdab18c458365bd1394f001788` |
| ollama/mlx_metal_v3/libmlxc.dylib (로컬 검증 자료·공개본 미포함) | 2,062,064 | `891e8487b26d3b55d3fc124294b96f48b336653321bab315a44d167f08ce05bc` |
| ollama/mlx_metal_v3/libollama_xgrammar.dylib (로컬 검증 자료·공개본 미포함) | 5,192,592 | `ad0bd5b17fda448e81236c5da9db16426494a8edf6ae30dc96dae6b1b001a18d` |
| ollama/mlx_metal_v3/mlx.metallib (로컬 검증 자료·공개본 미포함) | 140,747,632 | `ff564bb78c2f344ca91c086c1948a3235dc87a50787f19216c5874ee09a534e8` |
| ollama/mlx_metal_v4/._mlx.metallib (로컬 검증 자료·공개본 미포함) | 9,663 | `1880e7f92c3894a79ee7126aa94f9f6bc487c1a7447fcd16e99b5648d7275967` |
| ollama/mlx_metal_v4/libjaccl.dylib (로컬 검증 자료·공개본 미포함) | 2,137,056 | `2c80f7c0f4592d4d9bebef11a8d2411a2e8b7a346f761210650e29ce83c20fd8` |
| ollama/mlx_metal_v4/libmlx.dylib (로컬 검증 자료·공개본 미포함) | 21,042,848 | `60c5b75c6aacfd48d9b1ee0ade390f4b61a65ad74466bfdf1ad688aa28a10ccd` |
| ollama/mlx_metal_v4/libmlxc.dylib (로컬 검증 자료·공개본 미포함) | 1,029,744 | `cd526a889206e49c0113f5647855e03f45c05a0d1965279a75e53d04d45099e6` |
| ollama/mlx_metal_v4/libollama_xgrammar.dylib (로컬 검증 자료·공개본 미포함) | 2,489,552 | `74c1443631c47b5373fee089e9fc816fcaf40921128e03ae081f98f7936b856a` |
| ollama/mlx_metal_v4/mlx.metallib (로컬 검증 자료·공개본 미포함) | 202,670,448 | `325c1ea72d9ce15b8fe45d03b6cf03052a7475e65c81118299a00f1a3fa87b99` |
| ollama/ollama (로컬 검증 자료·공개본 미포함) | 52,076,880 | `76535100c7aaf5aa94fe749b1bf0cfe3a702fa0743c7421fed059b783f4969de` |

</details>

<details>
<summary>10개 symlink와 원 target</summary>

| 현재 symlink | 상대 target | 확인 |
|---|---|---|
| ollama/libggml-base.0.dylib (로컬 검증 자료·공개본 미포함) | `libggml-base.0.25.3.dylib` | 존재·archive와 일치 |
| ollama/libggml-base.dylib (로컬 검증 자료·공개본 미포함) | `libggml-base.0.dylib` | 존재·archive와 일치 |
| ollama/libggml.0.dylib (로컬 검증 자료·공개본 미포함) | `libggml.0.25.3.dylib` | 존재·archive와 일치 |
| ollama/libggml.dylib (로컬 검증 자료·공개본 미포함) | `libggml.0.dylib` | 존재·archive와 일치 |
| ollama/libllama-common.0.dylib (로컬 검증 자료·공개본 미포함) | `libllama-common.0.5.0.dylib` | 존재·archive와 일치 |
| ollama/libllama-common.dylib (로컬 검증 자료·공개본 미포함) | `libllama-common.0.dylib` | 존재·archive와 일치 |
| ollama/libllama.0.dylib (로컬 검증 자료·공개본 미포함) | `libllama.0.5.0.dylib` | 존재·archive와 일치 |
| ollama/libllama.dylib (로컬 검증 자료·공개본 미포함) | `libllama.0.dylib` | 존재·archive와 일치 |
| ollama/libmtmd.0.dylib (로컬 검증 자료·공개본 미포함) | `libmtmd.0.5.0.dylib` | 존재·archive와 일치 |
| ollama/libmtmd.dylib (로컬 검증 자료·공개본 미포함) | `libmtmd.0.dylib` | 존재·archive와 일치 |

</details>
