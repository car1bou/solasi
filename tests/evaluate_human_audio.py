"""Local diagnostic: licensed human recordings through file and PCM replay paths."""
import asyncio
import json
import platform
import tempfile
import time
import unicodedata
import wave
from datetime import datetime,timezone
from pathlib import Path
from lecture_study.db import open_db,create_session
from lecture_study.audio import start_recording,append_pcm,stop_recording,recording_path,get_recording
from lecture_study.transcription import register_audio,process_pending,plan_chunks,list_transcripts,command,file_hash,MODEL_NAME,MODEL_SHA,VAD_SHA,transcription_status


def normalize(text):
    text=unicodedata.normalize("NFKC",text).lower()
    return "".join(char for char in text if unicodedata.category(char)[0] in ("L","N"))


def edit_distance(reference,hypothesis):
    previous=list(range(len(hypothesis)+1))
    for i,left in enumerate(reference,1):
        current=[i]
        for j,right in enumerate(hypothesis,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
        previous=current
    return previous[-1]


def score(reference,hypothesis):
    reference,hypothesis=normalize(reference),normalize(hypothesis)
    if not reference: raise ValueError("기준 전사가 비어 있습니다")
    edits=edit_distance(reference,hypothesis)
    return {"edits":edits,"reference_chars":len(reference),"cer":edits/len(reference)}


def character_errors(reference,hypothesis):
    reference,hypothesis=normalize(reference),normalize(hypothesis)
    previous=[(i,0,0,i)for i in range(len(hypothesis)+1)]
    for i,left in enumerate(reference,1):
        current=[(i,0,i,0)]
        for j,right in enumerate(hypothesis,1):
            cost,sub,delete,insert=previous[j-1];different=int(left!=right)
            diagonal=(cost+different,sub+different,delete,insert)
            cost,sub,delete,insert=previous[j];removed=(cost+1,sub,delete+1,insert)
            cost,sub,delete,insert=current[-1];added=(cost+1,sub,delete,insert+1)
            current.append(min((diagonal,removed,added),key=lambda x:x[0]))
        previous=current
    _,sub,delete,insert=previous[-1]
    return {'substitutions':sub,'deletions':delete,'insertions':insert}


async def evaluate(additional=False):
    root=Path(__file__).resolve().parents[1]
    runtime=root/".local-state/runtime"
    folder=runtime/("asr-comparison-20261013" if additional else "human-audio-20261013")
    provenance=folder/("manifest.json" if additional else "provenance.json")
    fixtures=json.loads(provenance.read_text())
    results=[]
    with tempfile.TemporaryDirectory(prefix="lecture-human-eval-") as temp:
        db=open_db(Path(temp)/"data")
        try:
            for fixture in fixtures["clips"]:
                source=Path(fixture["path"])
                assert file_hash(source)==fixture["sha256"]
                row={key:fixture[key] for key in ("row_idx","id","duration_seconds","sha256","bytes","reference_raw_transcription","source_row_url")}
                row["topic"]=fixture.get("topic","additional20")
                for route in ("file","pcm_replay"):
                    sid=create_session(db,"lecture","사람 음성 검증 "+str(fixture["row_idx"])+" "+route,None,None).id
                    started=time.perf_counter()
                    if route=="file":
                        rid=await register_audio(db,sid,source,runtime)
                        assert not recording_path(db,rid).exists()
                    else:
                        converted=Path(temp)/"pcm.wav"
                        await command([runtime/"ffmpeg/bin/ffmpeg","-nostdin","-v","error","-y","-i",source,"-ac","1","-ar","48000","-c:a","pcm_s16le",converted])
                        rid=start_recording(db,sid,48000)
                        with wave.open(str(converted)) as handle:
                            cursor=seq=0
                            while payload:=handle.readframes(12000):
                                count=len(payload)//2
                                append_pcm(db,rid,seq,cursor,count,payload)
                                plan_chunks(db,rid)
                                cursor+=count;seq+=1
                        stop_recording(db,rid)
                        plan_chunks(db,rid,True)
                        record=get_recording(db,rid)
                        assert not record["gaps"]
                        with wave.open(str(recording_path(db,rid))) as saved:
                            assert saved.getnframes()==cursor==record["stored_frames"]
                    await process_pending(db,rid,runtime)
                    elapsed=time.perf_counter()-started
                    status=transcription_status(db,rid)
                    if status["failed"] or status["queued"] or status["running"]: raise AssertionError("전사 처리 실패: "+str(status))
                    segments=list_transcripts(db,sid)
                    record=get_recording(db,rid)
                    duration_ms=round(record["source_frames"]*1000/record["sample_rate"])
                    assert all(s["final"] and 0<=s["start_ms"]<s["end_ms"]<=duration_ms for s in segments)
                    recognized=" ".join(s["text"] for s in segments)
                    row[route]={"recognized":recognized,"segments":[{k:s[k] for k in ("start_ms","end_ms","text","final")} for s in segments],
                                "elapsed_seconds":elapsed,"processing_seconds_per_audio_second":elapsed/fixture["duration_seconds"],
                                "status":status,**score(fixture["reference_raw_transcription"],recognized)}
                assert file_hash(source)==fixture["sha256"]
                results.append(row)
                print(json.dumps({k:row[k] for k in ("row_idx","topic","duration_seconds")}|{route:{"cer":row[route]["cer"],"elapsed_seconds":row[route]["elapsed_seconds"]} for route in ("file","pcm_replay")},ensure_ascii=False),flush=True)
        finally: db.close()
    report={"tested_at_utc":datetime.now(timezone.utc).isoformat(),"platform":platform.platform(),"machine":platform.machine(),
            "engine":"whisper.cpp1.9.5","model":MODEL_NAME,"model_sha256":MODEL_SHA,"vad_model":"silero-v6.2.0","vad_sha256":VAD_SHA,"options":["-l","ko","-np","--vad","default beam5/best_of5; native GPU enabled, native VAD defaults"],
            "dataset":fixtures["dataset"],"revision":fixtures["revision"],"dataset_url":fixtures["dataset_url"],"paper_url":fixtures["paper_url"],
            "license":fixtures["license"],"attribution":fixtures["attribution"],"total_seconds":fixtures["duration_seconds_total"],
            "total_audio_bytes":fixtures["audio_bytes_total"],"normalization":"Diagnostic CER: NFKC, lowercase, Unicode letters/numbers only. Spaces/punctuation removed; numeral spelling alternatives count as errors. Not official FLEURS benchmark normalization.",
            "limitations":fixtures["limitations"]+["PCM replay is accelerated software input, not microphone capture or real-time latency test.","No reference transcription or task-specific hints supplied to ASR.","One run per clip and path, not a statistically representative benchmark."],
            "clips":results,"aggregate":{}}
    for route in ("file","pcm_replay"):
        edits=sum(row[route]["edits"] for row in results);chars=sum(row[route]["reference_chars"] for row in results);elapsed=sum(row[route]["elapsed_seconds"] for row in results)
        report["aggregate"][route]={"edits":edits,"reference_chars":chars,"cer":edits/chars,"elapsed_seconds":elapsed,"processing_seconds_per_audio_second":elapsed/report["total_seconds"]}
    output=folder/("evaluation-"+MODEL_NAME+"-native.json");output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"report":str(output),"aggregate":report["aggregate"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--additional",action="store_true")
    asyncio.run(evaluate(parser.parse_args().additional))
