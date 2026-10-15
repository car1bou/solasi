"""Offline Mac ASR regression comparisons; run as python -m experiments.evaluate_mac_asr."""
import argparse,asyncio,json,platform,runpy,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
from lecture_study import transcription as tr
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.retrieval import save_term
from tests.evaluate_human_audio import score,normalize
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';BASE_COMMAND=tr.command;PAD_MS=200

async def padded(argv,*args,**kwargs):
 if '--vad' in argv:
  argv=list(argv)
  if '--vad-speech-pad-ms' in argv:argv[argv.index('--vad-speech-pad-ms')+1]=str(PAD_MS)
  else:argv.extend(['--vad-speech-pad-ms',str(PAD_MS)])
 return await BASE_COMMAND(argv,*args,**kwargs)

async def vocabulary():
 terms=['세풀베다','깁슨','내셔널 트레저','북발트해','카탈로니아어','TMZ'];clips=[]
 for name in ('human-audio-20261013/provenance.json','asr-comparison-20261013/manifest.json'):
  clips += [c for c in json.loads((RUNTIME/name).read_text())['clips'] if c['row_idx'] in (3,8,12,19,26,9,10,11,13,14)]
 assert len(clips)==10
 report={'ready':False,'model':tr.MODEL_NAME,'model_sha256':tr.MODEL_SHA,'padding_ms':30,'platform':platform.platform(),'limitations':['Known names from reference transcripts supplied as registered prior-course concepts. Conditional vocabulary test, not blind ASR accuracy.','Five positive clips (six names) and five controls, selected from already inspected FLEURS; no unseen-data generalization.','Diagnostic NFKC/lowercase letters/numbers CER; not official corpus metric.'],'clips':[]};output=ROOT/'docs/verification/mac-asr-vocabulary.json'
 for hints in (False,True):
  for c in clips:
   source=Path(c['path']);assert tr.file_hash(source)==c['sha256'];began=time.perf_counter()
   with tempfile.TemporaryDirectory(prefix='lecture-vocabulary-') as temp:
    db=open_db(Path(temp)/'data')
    try:
     course=new_id()
     with db:db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'용어 시험','',now()))
     previous=create_session(db,'lecture','이전',course,1).id;sid=create_session(db,'lecture','현재',course,2).id
     if hints:
      for term in terms:save_term(db,previous,term,[],'시험 명칭',[])
     rid=await tr.register_audio(db,sid,source,RUNTIME);await tr.process_pending(db,rid,RUNTIME);status=tr.transcription_status(db,rid);assert not sum(status[k] for k in ('failed','queued','running','interrupted'))
     segments=tr.list_transcripts(db,sid);duration=round(c['duration_seconds']*1000);assert all(s['final'] and 0<=s['start_ms']<s['end_ms']<=duration for s in segments)
     text=' '.join(s['text'] for s in segments);ref=c['reference_raw_transcription'];expected=[t for t in terms if normalize(t) in normalize(ref)];found=[t for t in terms if normalize(t) in normalize(text)]
     report['clips'].append({'hints':hints,'row_idx':c['row_idx'],'sha256':c['sha256'],'reference':ref,'recognized':text,'expected_terms':expected,'correct_terms':[t for t in expected if t in found],'unexpected_terms':[t for t in found if t not in expected],'elapsed_seconds':time.perf_counter()-began,'ranges':[dict(r) for r in db.execute('SELECT start_frame,end_frame,prompt FROM transcript_ranges WHERE recording_id=?',(rid,))],**score(ref,text)})
    finally:db.close()
   assert tr.file_hash(source)==c['sha256'];output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'hints':hints,'row':c['row_idx'],'cer':report['clips'][-1]['cer']}),flush=True)
 report['aggregate']={}
 for hints in (False,True):
  rows=[c for c in report['clips'] if c['hints']==hints];edits=sum(c['edits'] for c in rows);chars=sum(c['reference_chars'] for c in rows)
  report['aggregate'][str(hints)]={'edits':edits,'reference_chars':chars,'cer':edits/chars,'expected_terms':sum(len(c['expected_terms']) for c in rows),'correct_terms':sum(len(c['correct_terms']) for c in rows),'unexpected_terms':sum(len(c['unexpected_terms']) for c in rows)}
 report['ready']=True;report['originals_untouched']=True;output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report['aggregate']),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('case',choices=['padding','long','baseline','vocabulary','speech']);case=parser.parse_args().case
 if case=='vocabulary':asyncio.run(vocabulary())
 elif case=='speech':
  from experiments.compare_new_local_models import main
  output=ROOT/'docs/verification/whisper-speech-padding200.json'
  with patch.object(tr,'command',new=padded):asyncio.run(main((),output,False,1,None,RUNTIME/'speech-conditions-20261014/manifest.json',True))
  body=json.loads(output.read_text())
  body['conditions']='Actual product Whisper on same39 speech/noise clips with native VAD margin200ms; no other inference; compare with pre-change30ms baseline, no default change from this script'
  body['vad_speech_pad_ms']=200;output.write_text(json.dumps(body,ensure_ascii=False,indent=2))
  assert body['completed'] and not any('error' in r for r in body['audio'])
 else:
  PAD_MS=30 if case=='baseline' else 200
  groups='long1' if case in ('long','baseline') else 'fleurs40,pansori24,deeply18,lowgain5,snr105';output={'long':'mac-adaptive-pad200.json','baseline':'mac-fixed-pad30.json','padding':'mac-short-pad200.json'}[case]
  sys.argv=['evaluate_diverse_audio.py','--engine','turbo','--route','product','--groups',groups,'--output-name',output]
  with patch.object(tr,'command',new=padded),patch.object(tr,'quiet_cut',new=(lambda samples,rate:len(samples)) if case=='baseline' else tr.quiet_cut):runpy.run_path(str(ROOT/'experiments/evaluate_diverse_audio.py'),run_name='__main__')
  path=RUNTIME/'diverse-audio-20261014'/output;body=json.loads(path.read_text());assert body['ready'];body['options']['vad_speech_pad_ms']=PAD_MS;body['options']['adaptive_boundaries']=case!='baseline';encoded=json.dumps(body,ensure_ascii=False,indent=2);path.write_text(encoded);(ROOT/'docs/verification'/('mac-asr-'+case+'.json')).write_text(encoded)
