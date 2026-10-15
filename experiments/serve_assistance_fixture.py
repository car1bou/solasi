"""Disposable production UI fixture with model doubles and a delayed memo apply.

Build frontend first, then run:
.venv/bin/python experiments/serve_assistance_fixture.py /tmp/assistance-ui-check
All data is authored, no microphone or real model inference.
"""
import asyncio,json,sys
from pathlib import Path
import uvicorn
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lecture_study import server,assistance,answers,outputs
from lecture_study.config import AppConfig
from lecture_study.models import ProviderResult
from lecture_study.db import create_session
from lecture_study.audio import start_recording,append_pcm,stop_recording
from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts
from lecture_study.materials import save_note
from lecture_study.launcher import bind_listener
folder=Path(sys.argv[1]).resolve()
if folder.exists():raise SystemExit('Use a new disposable folder')
folder.mkdir(parents=True)
listener=bind_listener();port=listener.getsockname()[1]
app=server.create_app(AppConfig(folder/'data',ROOT/'.local-state/runtime',port=port));db=app.state.db
sid=create_session(db,'lecture','메모·질문 카드 검증',None,None).id
rid=start_recording(db,sid,48000);append_pcm(db,rid,0,0,48000,b'\0\1'*48000);chunk=plan_chunks(db,rid,True)[0]
text='뮤텍스와 세마포어는 어떻게 다른가요? 공유 자원의 접근을 제어합니다. 금요일 4개는 제안입니다. 월요일 3개로 정정했으며 아직 확정하지 않았습니다.'
accept_transcription(db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':text}]);stopped=stop_recording(db,rid)
with db:db.execute("UPDATE jobs SET status='done' WHERE id=?",(stopped['id'],))
tid=list_transcripts(db,sid)[0]['id']+':v1';save_note(db,sid,'동기화 차이 복습',anchor_ms=500)
async def generated(config,messages,images,schema,**kwargs):
 if kwargs.get('before_local'):await kwargs['before_local']()
 data=next(json.loads(m['content'])for m in messages if m['role']=='user' and m['content'].startswith('{'));kind=data.get('kind');await asyncio.sleep(.3)
 if kind=='note':body={'addition':'공유 자원의 접근을 제어합니다. 일정은 월요일 3개 제안으로 정정했으며 아직 미확정입니다.','evidence_ids':[tid]}
 elif kind=='candidates':body={'cards':[{'prompt':'뮤텍스와 세마포어는 어떻게 다른가요?','quote':'뮤텍스와 세마포어는 어떻게 다른가요?','source_id':tid}]}
 elif kind=='answer':body={'answer':'공유 자원의 접근을 제어합니다.','citations':[{'source_id':tid}],'uncertainty':'구체적인 차이 설명은 원문에 없습니다.'}
 elif 'chronological_parts' in data:
  from lecture_study.merging import cited_ids
  body={'sections':[{'title':'정정·미결','text':'금요일 4개 제안을 월요일 3개로 정정했으며 아직 확정하지 않았다.','evidence_ids':sorted(cited_ids(data['chronological_parts']))}]}
 elif 'candidates'in data:body={'selected_ids':list(data['candidates'])[:data['target_items']]}
 else:
  e=data['evidence'][0];section={'title':'확정 근거','text':e['text'],'evidence_ids':[e['source_id']]}
  if 'subject_quote'in schema['properties']['sections']['items']['properties']:section.update(subject_quote='뮤텍스' if '뮤텍스'in e['text'] else '',subject_source_id=e['source_id'],event_type='condition' if '조건'in e['text'] else 'fact')
  if 'subject'in schema['properties']['sections']['items']['properties']:section.update(subject='뮤텍스' if '뮤텍스'in e['text'] else '불명확',event_type='condition' if '조건'in e['text'] else 'fact')
  body={'sections':[section]}
 return ProviderResult(text=json.dumps(body,ensure_ascii=False),model='UI-double; no real inference',usage={'prompt_eval_count':0,'eval_count':0},elapsed_ms=300)
assistance.generate=answers.generate=outputs.generate=generated
@app.middleware('http')
async def delayed_apply(request,call_next):
 if request.url.path.endswith('/apply-note'):await asyncio.sleep(5)
 return await call_next(request)
url=f'http://127.0.0.1:{port}/#bootstrap='+app.state.bootstrap_token
(folder/'info.json').write_text(json.dumps({'url':url,'session_id':sid,'note':'UI double with 5s apply delay; no model performance claim'}));print(url,flush=True)
uvicorn.Server(uvicorn.Config(app,access_log=False)).run(sockets=[listener])
