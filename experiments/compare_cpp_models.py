"""Same-clip unprompted native ASR comparison; not a product runtime."""
import argparse
import hashlib
import json
import platform
import re
import subprocess
import tempfile
import time
import wave
from datetime import datetime,timezone
from pathlib import Path
from lecture_study.transcription import parse_segments,file_hash,VAD_SHA,engine_paths
from tests.evaluate_human_audio import score

parser=argparse.ArgumentParser()
parser.add_argument("model",choices=["turbo","komixv2"])
parser.add_argument("--vad-mode",choices=["default","pad250","off"],default="default")
parser.add_argument("--backend",choices=["cpu","metal"],default="cpu")
args=parser.parse_args()
runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
ffmpeg,whisper,_=engine_paths(runtime)
model_file,meta_file={"turbo":("ggml-large-v3-turbo.bin","turbo-provenance.json"),"komixv2":("ggml-medium-komixv2.bin","komixv2-ggml-provenance.json")}[args.model]
model=runtime/"models"/model_file
meta=json.loads((runtime/"models"/meta_file).read_text())
assert model.stat().st_size==meta["bytes"] and file_hash(model)==meta["sha256"]
vad=runtime/"models/ggml-silero-v6.2.0.bin"
assert file_hash(vad)==VAD_SHA
groups=[("familiar5",runtime/"human-audio-20261013/provenance.json"),("additional20",runtime/"asr-comparison-20261013/manifest.json")]
report={"tested_at_utc":datetime.now(timezone.utc).isoformat(),"platform":platform.platform(),"model":args.model,"model_metadata":meta,
        "runtime":"whisper.cpp1.9.5","options":["-l","ko",args.backend,"-np",args.vad_mode,"native beam/best-of5,no prompt"],
        "normalization":"Diagnostic NFKC/lowercase/Unicode letters+numbers, no spaces/punctuation; includes Romanization annotations, not official benchmark.",
        "route":"full clip subprocess, model loaded each invocation, sequential; not product20second chunk or microphone capture",
        "peak_ram_measurement":"macOS /usr/bin/time -l maximum resident set size bytes, process RSS; Metal buffers may use different accounting",
        "groups":{}}
for label,manifest_path in groups:
    manifest=json.loads(manifest_path.read_text())
    assert manifest.get("ready",True)
    rows=[]
    with tempfile.TemporaryDirectory(prefix="lecture-model-eval-") as temp:
        temp=Path(temp)
        for fixture in manifest["clips"]:
            source=Path(fixture["path"]);assert file_hash(source)==fixture["sha256"]
            clip=temp/"pcm.wav";prefix=temp/"result"
            began=time.perf_counter()
            subprocess.run([str(ffmpeg),"-nostdin","-v","error","-y","-i",str(source),"-ac","1","-ar","16000","-c:a","pcm_s16le",str(clip)],check=True,timeout=120)
            converted=time.perf_counter()-began
            with wave.open(str(clip)) as pcm: duration=round(pcm.getnframes()*1000/pcm.getframerate())
            argv=["/usr/bin/time","-l",str(whisper),"-m",str(model),"-f",str(clip),"-l","ko","-oj","-of",str(prefix),"-np"]
            if args.backend=="cpu": argv += ["-ng"]
            if args.vad_mode!="off": argv += ["--vad","-vm",str(vad)]
            if args.vad_mode=="pad250": argv += ["--vad-speech-pad-ms","250"]
            began=time.perf_counter();result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
            elapsed=time.perf_counter()-began
            if result.returncode: raise RuntimeError("native model failed: "+result.stderr.decode(errors="replace")[-1000:])
            body=json.loads(prefix.with_suffix(".json").read_text())
            segments=parse_segments(body,duration)
            assert all(0<=s["start_ms"]<s["end_ms"]<=duration for s in segments)
            recognized=" ".join(s["text"] for s in segments)
            usage=result.stderr.decode(errors="replace")
            peak=re.search(r"(\d+)\s+maximum resident set size",usage)
            assert peak,"time -l RSS missing"
            row={k:fixture[k] for k in ("row_idx","id","duration_seconds","sha256","reference_raw_transcription")}
            row.update({"recognized":recognized,"segments":segments,"peak_rss_bytes":int(peak.group(1)),"inference_process_seconds":elapsed,"conversion_plus_inference_seconds":converted+elapsed,
                        **score(row["reference_raw_transcription"],recognized)})
            assert file_hash(source)==fixture["sha256"];rows.append(row)
            print(json.dumps({"group":label,"row":row["row_idx"],"cer":row["cer"],"seconds":elapsed},ensure_ascii=False),flush=True)
    chars=sum(c["reference_chars"] for c in rows);edits=sum(c["edits"] for c in rows);elapsed=sum(c["inference_process_seconds"] for c in rows)
    report["groups"][label]={"dataset":manifest["dataset"],"revision":manifest["revision"],"license":manifest["license"],"attribution":manifest["attribution"],"clips":rows,
                            "audio_seconds_total":manifest["duration_seconds_total"],"aggregate":{"edits":edits,"reference_chars":chars,"cer":edits/chars,
                            "inference_process_seconds":elapsed,"conversion_plus_inference_seconds":sum(c["conversion_plus_inference_seconds"] for c in rows),"peak_rss_bytes":max(c["peak_rss_bytes"] for c in rows)}}
assert file_hash(model)==meta["sha256"] and file_hash(vad)==VAD_SHA
report["originals_models_untouched"]=True
output=runtime/"asr-comparison-20261013"/(args.model+("" if args.backend=="cpu" else "-metal")+("" if args.vad_mode=="default" else "-vad-"+args.vad_mode)+"-comparison.json")
output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:g["aggregate"] for k,g in report["groups"].items()},ensure_ascii=False,indent=2))
