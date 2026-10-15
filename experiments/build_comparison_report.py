"""Join measured results without copying runtime paths or expiring download URLs."""
import json
from pathlib import Path
from tests.evaluate_human_audio import score
app=Path(__file__).resolve().parents[1];runtime=app/".local-state/runtime"
def read(name): return json.loads((runtime/name).read_text())
small=[read("human-audio-20261013/official-small-comparison.json"),read("asr-comparison-20261013/official-base-small-comparison.json")]
report={"device":"Apple M4,16GiB,macOS27.0.1","dataset":"google/fleurs ko_kr/test","revision":"70bb2e84b976b7e960aa89f1c648e09c59f894dd",
 "license":"CC-BY-4.0","source":"https://huggingface.co/datasets/google/fleurs","attribution":"FLEURS: Fleurs Lang-uage Evaluation of Universal Representations of Speech, Conneau et al.,2022. https://arxiv.org/abs/2205.12446",
 "normalization":"Diagnostic NFKC,lowercase,Unicode letters and numbers; excludes spacing/punctuation,counts numeral spelling and reference Romanizations. Not official FLEURS normalization.",
 "limitations":["25 read-speech clips,312.36seconds; speaker IDs absent,training overlap unknown.","Additional20 has19unique sentences; row25 repeats familiar row5 sentence with different audio.","One pass per condition; not a meeting,room microphone,overlap or statistical benchmark.","Whisper CPU/Metal reload each process; Qwen Metal4bit stays loaded. Times are measured configurations,not controlled architecture speed comparisons.","Qwen segment times are input chunk ranges; Whisper segments are ASR sentence estimates,neither manually aligned here."],
 "fixtures":{},"models":{}}
def clean(row,group):
 data={k:row[k] for k in ("recognized","segments","edits","reference_chars","cer")}
 data["fixture_id"]=group+":"+str(row["row_idx"])
 for key in ("inference_process_seconds","conversion_plus_inference_seconds","peak_rss_bytes","elapsed_seconds","mlx_peak_bytes","process_cumulative_max_rss_bytes"):
  if key in row: data[key]=row[key]
 reference=report["fixtures"][data["fixture_id"]]["reference"]
 assert score(reference,data["recognized"])["edits"]==data["edits"]
 return data
for group,raw in zip(("familiar5","additional20"),small):
 for row in raw["clips"]:
  ident=group+":"+str(row["row_idx"])
  report["fixtures"][ident]={"row_idx":row["row_idx"],"duration_seconds":row["duration_seconds"],"sha256":row["sha256"],"reference":row["reference_raw_transcription"]}
for name in ("base","small"):
 report["models"][name]={"engine":"whisper.cpp1.9.5,CPU,SileroVAD defaults,no hints,load each clip","sha256":small[0]["model_metadata"][name]["sha256"],"bytes":small[0]["model_metadata"][name]["bytes"],"groups":{}}
 for group,raw in zip(("familiar5","additional20"),small):
  report["models"][name]["groups"][group]={"aggregate":raw["aggregate"][name],"clips":[clean(row[name]|{"row_idx":row["row_idx"]},group) for row in raw["clips"]]}
for name,file in (("turbo","turbo-comparison.json"),("komixv2","komixv2-comparison.json"),("turbo-metal","turbo-metal-comparison.json"),("turbo-vad-pad250","turbo-vad-pad250-comparison.json"),("turbo-vad-off","turbo-vad-off-comparison.json")):
 raw=read("asr-comparison-20261013/"+file)
 report["models"][name]={"engine":raw["runtime"],"options":raw["options"],"sha256":raw["model_metadata"]["sha256"],"bytes":raw["model_metadata"]["bytes"],"groups":{}}
 for group,body in raw["groups"].items():
  for row in body["clips"]: assert row["sha256"]==report["fixtures"][group+":"+str(row["row_idx"])]["sha256"]
  report["models"][name]["groups"][group]={"aggregate":body["aggregate"],"clips":[clean(row,group) for row in body["clips"]]}
raw=read("asr-comparison-20261013/qwen3-asr-1.7b-mlx-q4.json");assert raw["ready"] and len(raw["clips"])==25
qwen={"engine":"MLX-Audio0.5.8,Metal,community4bit,no hints,load once","revision":raw["revision"],"sha256":raw["model_sha256"],"cold_import_seconds":raw["cold_import_seconds"],"model_load_seconds":raw["model_load_seconds"],"versions":raw["versions"],"groups":{}}
for group in ("familiar5","additional20"):
 rows=[row for row in raw["clips"] if row["group"]==group]
 for row in rows: assert row["sha256"]==report["fixtures"][group+":"+str(row["row_idx"])]["sha256"]
 qwen["groups"][group]={"aggregate":raw["aggregate"][group],"clips":[clean(row,group) for row in rows]}
report["models"]["qwen3-asr-1.7b-mlx-q4"]=qwen
assert len(report["fixtures"])==25
for name,model in report["models"].items():
 for group,count in (("familiar5",5),("additional20",20)):
  rows=model["groups"][group]["clips"];assert len(rows)==count
  aggregate=model["groups"][group]["aggregate"]
  assert sum(row["edits"] for row in rows)==aggregate["edits"]
  assert sum(row["reference_chars"] for row in rows)==aggregate["reference_chars"]
output=app/"docs/verification/asr-model-comparison.json"
output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({"report":str(output),"models":len(report["models"]),"clips":len(report["fixtures"])},ensure_ascii=False))
