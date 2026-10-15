"""Summarize completed real-browser traces, optionally align their saved waveforms.

Use the existing ASR evaluation environment (numpy/scipy) for --align:
.local-state/runtime/qwen-eval-venv/bin/python experiments/build_long_recording_report.py --align /tmp/long-a /tmp/long-b
"""
import argparse,hashlib,json,math,re,sqlite3,subprocess,sys,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'

def distribution(values):
 values=sorted(values)
 return {'count':len(values),'min':values[0],'median':values[len(values)//2],'p95':values[max(0,math.ceil(len(values)*.95)-1)],'max':values[-1]} if values else {'count':0}

def alignment(folder,rid):
 import numpy as np
 from scipy.signal import correlate
 def read(path):
  result=subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-v','error','-i',str(path),'-ac','1','-ar','1000','-f','f32le','-'],capture_output=True,check=True)
  return np.frombuffer(result.stdout,dtype='<f4').astype(float)
 original=read(folder/'input.wav');captured=read(folder/'data/audio'/rid/'raw.wav');points=[]
 for t in range(10,int(len(captured)/1000)-2,30):
  q=captured[t*1000:(t+2)*1000];q=q-q.mean();lo=max(0,(t-90)*1000);hi=min(len(original),(t+92)*1000);v=original[lo:hi]
  dots=correlate(v,q,mode='valid',method='fft');cs=np.r_[0,np.cumsum(v*v)];power=cs[len(q):]-cs[:-len(q)];scores=dots/np.sqrt(np.maximum(power,1e-15)*max(np.dot(q,q),1e-15));i=int(np.argmax(scores))
  points.append({'stored_seconds':t,'source_seconds':(lo+i)/1000,'correlation':round(float(scores[i]),5),'offset_seconds':round((lo+i)/1000-t,3)})
 reliable=[p['offset_seconds'] for p in points if p['correlation']>.9]
 offset=round(float(np.median(reliable))*1000) if reliable else 0
 source_start=max(0,offset);stored_start=max(0,-offset);length=min(len(original)-source_start,len(captured)-stored_start)
 a=original[source_start:source_start+length];b=captured[stored_start:stored_start+length];den=float(np.linalg.norm(a)*np.linalg.norm(b));corr=float(np.dot(a,b)/den) if den else 0
 return {'method':'1000 Hz waveform, 2s correlations every 30s within +/-90s, plus global correlation at median high-confidence offset; sampled diagnostic, not word ground truth','points':points,'median_high_confidence_offset_ms':offset,'global_correlation':corr,'aligned_source_seconds':length/1000,'uncovered_source_seconds':(len(original)-length)/1000}

def summarize(folder,align):
 trace=json.loads((folder/'trace.json').read_text());assert trace['ready'],'trace not complete: '+str(folder)
 with (folder/'input.wav').open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==trace['input']['sha256']
 db=sqlite3.connect(folder/'data/app.sqlite3');db.row_factory=sqlite3.Row
 result={'fixture_folder':str(folder),'model':trace.get('model','qwen3.5:4b'),'input':trace['input'],'capture_route':trace.get('capture_route',trace['runs'][0].get('capture_route','Actual browser capture fixture')),'runs':[],'ready':True}
 for run in trace['runs']:
  assert run.get('done');rids={a['recording_id'] for a in run['acks']};assert len(rids)==1;rids=list(rids);rid=rids[0]
  record=dict(db.execute('SELECT * FROM recordings WHERE id=?',(rid,)).fetchone());record['gaps']=json.loads(record['gaps'])
  with wave.open(str(folder/'data/audio'/rid/'raw.wav')) as handle:
   assert handle.getnframes()==record['stored_frames'] and handle.getframerate()==record['sample_rate']
  assert record['status'] in ('stopped','interrupted')
  statuses=[dict(r) for r in db.execute('SELECT status,final,count(*) AS n FROM transcript_ranges WHERE recording_id=? GROUP BY status,final',(rid,))];assert all(r['status']=='done' for r in statuses),statuses
  ranges=[a for a in trace['asr'] if a['recording_id']==rid and 'ended' in a];final=[a for a in ranges if a['final'] and a['status']=='done']
  job_ids={j['id'] for j in run['generations']};jobs=[j for j in run['jobs'] if j['id'] in job_ids];assert len(jobs)==len(job_ids) and all(j['status']=='done' for j in jobs)
  gens=[g for g in trace['generation'] if g.get('request_started',0)>=run['play_started']/1000 and g.get('submitted',0)<=run['stopped']/1000+600 and 'ended' in g]
  if run['mode']=='asr_only':gens=[]
  overlaps=[{'asr_id':a['id'],'final':a['final'],'seconds':max(0,min(a['ended'],g['ended'])-max(a['started'],g['request_started']))} for a in ranges for g in gens if g.get('request_started') and a['started']<g['ended'] and g['request_started']<a['ended']]
  samples=[]
  for sample in trace['samples']:
   if not run['play_started']<=sample['at']<=run['stopped']:continue
   current=next((r for r in sample['recordings'] if r['id']==rid),None)
   if current:samples.append({'render_or_player_seconds':sample['audio_seconds'],'stored_seconds':current['stored_frames']/record['sample_rate'],'source_timeline_seconds':current['source_frames']/record['sample_rate'],'final_lag_ms':max(0,current['source_frames']*1000/record['sample_rate']-max(0,sample['final_end_ms']-record['offset_ms'])),'pending_final_or_preview_ranges':current['transcription']['queued']+current['transcription']['running']})
  item={'mode':run['mode'],'wall_play_seconds':(run['stopped']-run['play_started'])/1000,'all_jobs_after_stop_seconds':(run['done']-run['stopped'])/1000,'recording':{k:record[k] for k in ('id','sample_rate','stored_frames','source_frames','gaps','status','error')},'stored_seconds':record['stored_frames']/record['sample_rate'],'source_timeline_seconds':record['source_frames']/record['sample_rate'],'range_statuses':statuses,'ack_ms':distribution([a['ms'] for a in run['acks']]),'asr_final_call_seconds':distribution([a['ended']-a['started'] for a in final]),'final_asr_after_stop_seconds':max(0,max(a['ended'] for a in final)-run['stopped']/1000),'generation_jobs':len(jobs),'generation':gens,'asr_generation_overlaps':overlaps,'asr_calls_during_capture':sum(a['started']<run['stopped']/1000 for a in ranges),'generation_calls_during_capture':sum(g.get('request_started',0)<run['stopped']/1000 for g in gens),'final_lag_ms':distribution([s['final_lag_ms'] for s in samples]),'timeline_samples_every_30':samples[::30],'all_jobs_done':True}
  if run['mode']=='after_stop':assert item['asr_calls_during_capture']==0 and item['generation_calls_during_capture']==0 and not overlaps,item
  if align:item['waveform_alignment']=alignment(folder,rid)
  result['runs'].append(item)
 host=[json.loads(line) for line in (folder/'host-samples.jsonl').read_text().splitlines()] if (folder/'host-samples.jsonl').exists() else []
 swaps=[float(re.search(r'used = ([\d.]+)M',h.get('swapusage',h.get('swap',''))).group(1)) for h in host];result['whole_host_swap_used_mib']=distribution(swaps);result['host_sample_count']=len(host)
 db.close();return result
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folders',nargs='+',type=Path);parser.add_argument('--align',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'docs/verification/long-human-recording.json');args=parser.parse_args();align=args.align;folders=[p.resolve() for p in args.folders]
 report={'hardware':'Apple M4, 16 GiB, macOS 27.0.1','conditions':['Capture route per fixture: browser/worklet or paced real TCP PCM replay; actual WAV/Whisper/Ollama, no ASR/generation doubles','Input substitution is recorded per run: shared-clock direct graph, independent-context MediaStream bridge, or paced TCP; no physical microphone claim','Host state and render-clock pace are recorded per fixture; not an isolated repeated hardware benchmark','Whole host memory, not per-model peak GPU RAM','Input type per fixture; public narration or adult interview mixed with actual ambience, not an on-site meeting benchmark','No complete lexical ground truth for continuous fixtures; no whole-conversation CER or diarization claim'],'fixtures':[summarize(p,align) for p in folders]}
 output=args.output;output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(output)
