"""Realtime ASGI WebSocket replay of one licensed human clip; no microphone."""
import asyncio
import json
import struct
import tempfile
import time
import wave
from pathlib import Path
from fastapi.testclient import TestClient
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.transcription import command,file_hash,MODEL_NAME,MODEL_SHA
from tests.evaluate_human_audio import score


def check(repeat=1,output_name=None):
    assert 1<=repeat<=3
    if output_name and Path(output_name).name!=output_name:raise ValueError("결과 파일 이름만 입력하세요")
    runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
    folder=runtime/"human-audio-20261013"
    fixtures=json.loads((folder/"provenance.json").read_text())
    fixture=next(c for c in fixtures["clips"] if c["row_idx"]==3)
    source=Path(fixture["path"])
    assert file_hash(source)==fixture["sha256"]
    with tempfile.TemporaryDirectory(prefix="lecture-human-live-") as temp:
        root=Path(temp);clip=root/"pcm.wav"
        asyncio.run(command([runtime/"ffmpeg/bin/ffmpeg","-nostdin","-v","error","-y","-i",source,"-ac","1","-ar","48000","-c:a","pcm_s16le",clip]))
        if repeat>1:
            with wave.open(str(clip)) as original:
                frames=original.readframes(original.getnframes());params=original.getparams()
            with wave.open(str(clip),'wb') as repeated:
                repeated.setparams(params)
                for _ in range(repeat):repeated.writeframes(frames)
        app=create_app(AppConfig(root/"data",runtime,port=8765))
        base="http://127.0.0.1:8765"
        with TestClient(app,base_url=base) as client:
            def request(method,path,**kwargs):
                response=client.request(method,path,**kwargs)
                assert response.is_success,response.text
                return response.json()
            login=request("POST","/api/bootstrap",json={"token":app.state.bootstrap_token},headers={"Origin":base})
            headers={"Origin":base,"X-Session-Token":login["csrf_token"]}
            sid=request("POST","/api/sessions",json={"kind":"lecture","title":"사람 음성 동시 전사"},headers=headers)["id"]
            rid=request("POST","/api/sessions/"+sid+"/audio/start",json={"sample_rate":48000,'transcription_mode':'realtime'},headers=headers)["recording_id"]
            previews=[];peak_queue=0
            with client.websocket_connect("ws://127.0.0.1:8765/api/sessions/"+sid+"/audio",headers={"Origin":base}) as ws,wave.open(str(clip)) as original:
                ws.send_json({"recording_id":rid,"sample_rate":48000,"channels":1,"format":"pcm_s16le","csrf_token":login["csrf_token"]})
                assert ws.receive_json()["type"]=="ready"
                clock=time.perf_counter();cursor=seq=0
                while payload:=original.readframes(12000):
                    count=len(payload)//2
                    time.sleep(max(0,clock+(cursor+count)/48000-time.perf_counter()))
                    ws.send_bytes(struct.pack("<QQI",seq,cursor,count)+payload)
                    ack=ws.receive_json();assert ack["type"]=="ack",ack
                    cursor+=count;seq+=1
                    if seq%4==0:
                        event=request("GET","/api/sessions/"+sid+"/events")
                        previews.append(sum(not s["final"] for s in event["transcripts"]))
                        peak_queue=max(peak_queue,sum(r["transcription"]["queued"]+r["transcription"]["running"] for r in event["recordings"]))
                stop_at=time.perf_counter()
                jid=request("POST","/api/recordings/"+rid+"/stop",json={"end_frame":cursor},headers=headers)["id"]
                for _ in range(200):
                    job=request("GET","/api/jobs/"+jid)
                    if job["status"] not in ("queued","running"): break
                    time.sleep(.05)
                assert job["status"]=="done",job
                elapsed=time.perf_counter()-stop_at
                event=request("GET","/api/sessions/"+sid+"/events");segments=event["transcripts"];record=event["recordings"][0]
                duration_ms=round(fixture["duration_seconds"]*repeat*1000)
                assert record["stored_frames"]==cursor and not record["gaps"]
                assert segments and all(s["final"] and 0<=s["start_ms"]<s["end_ms"]<=duration_ms for s in segments)
                with wave.open(str(root/"data/audio"/rid/"raw.wav")) as saved: assert saved.getnframes()==cursor
                report={"model":MODEL_NAME,"model_sha256":MODEL_SHA,"row_idx":3,"duration_seconds":fixture["duration_seconds"]*repeat,"repeat":repeat,"product_chunk_seconds":30,"sha256":fixture["sha256"],
                        "mode":"ASGI TestClient authenticated WebSocket, realtime 250ms PCM pacing, concurrent native ASR; not browser/network/microphone capture",
                        "ack_packets":seq,"frames":cursor,"sample_rate":48000,"gaps":record["gaps"],"max_observed_pending_ranges":peak_queue,
                        "observed_provisional_counts":previews,"post_stop_seconds":elapsed,"job_status":job["status"],
                        "segments":[{k:s[k] for k in ("start_ms","end_ms","text","final")} for s in segments]}
                report["recognized"]=" ".join(s["text"] for s in segments)
                report.update(score(" ".join([fixture["reference_raw_transcription"]]*repeat),report["recognized"]))
    assert file_hash(source)==fixture["sha256"]
    (folder/(output_name or "live-websocket-"+MODEL_NAME+"-native"+("-repeat"+str(repeat) if repeat>1 else "")+".json")).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--repeat",type=int,default=1);parser.add_argument("--output-name")
    args=parser.parse_args();check(args.repeat,args.output_name)
