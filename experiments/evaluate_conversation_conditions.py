"""Isolated labeled accuracy and incomplete-reference conversation diagnostics, sequential native ASR."""
import argparse,asyncio,json,platform,tempfile,time,wave
from pathlib import Path
from lecture_study import transcription as tr
from tests.evaluate_human_audio import score,character_errors
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';FOLDER=RUNTIME/'conversation-20261014'

async def main(mode,output,legacy,windows,resume=False,padding_ms=200):
    manifest=json.loads((FOLDER/'manifest.json').read_text());assert manifest['ready']
    clips=manifest['clips']
    if legacy:clips+=json.loads((RUNTIME/'speech-conditions-20261014/manifest.json').read_text())['clips']
    report={'ready':False,'platform':platform.platform(),'mode':mode,'model':tr.MODEL_NAME,'model_sha256':tr.MODEL_SHA,'vad_sha256':tr.VAD_SHA,'speech_pad_ms':padding_ms,'input':manifest['datasets'],'conditions':'Isolated full-clip native Metal decoding, no hints or concurrent generation; separate from live browser and automatic review scheduling. Labeled respondent only CER; original continuous conversation has incomplete interviewer reference. Edit-operation components are one minimum-edit alignment (diagonal/deletion/insertion tie order), not semantic hallucination counts.','clips':[],'conversations':[],'controls':[]}
    if resume:
        saved=json.loads(output.read_text());assert not saved['ready'] and saved['mode']==mode and saved['model_sha256']==tr.MODEL_SHA and saved['speech_pad_ms']==padding_ms
        assert len(saved['clips'])<=len(clips) and all((r['sha256'],r['reference'],r['group'])==(c['sha256'],c['reference'],c['group'])for r,c in zip(saved['clips'],clips))
        assert len(saved['conversations'])<=len(manifest['conversations']) and all(r['sha256']==c['sha256']for r,c in zip(saved['conversations'],manifest['conversations']))
        report=saved
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    options={'padding_ms':padding_ms,'min_speech_ms':int(mode)}if mode!='off'else {'padding_ms':padding_ms,'vad_enabled':False}
    async def decode(path,duration=None):
        began=time.perf_counter();segments=await tr.transcribe_range(path,0,'',RUNTIME,**options)
        if duration is None:
            with wave.open(str(path))as wav:duration=round(wav.getnframes()*1000/wav.getframerate())
        assert all(0<=s['start_ms']<s['end_ms']<=duration for s in segments)
        return {'recognized':' '.join(s['text']for s in segments),'segments':segments,'seconds':time.perf_counter()-began}
    for index,c in enumerate(clips):
        if index<len(report['clips']):continue
        path=Path(c['path']);assert tr.file_hash(path)==c['sha256']
        row={k:v for k,v in c.items()if k!='path'};row.update(await decode(path,round(c['duration_seconds']*1000)));row.update(score(c['reference'],row['recognized'])|character_errors(c['reference'],row['recognized']))
        assert row['edits']==sum(row[k]for k in ('substitutions','deletions','insertions'));assert tr.file_hash(path)==c['sha256']
        report['clips'].append(row);save();print(json.dumps({'mode':mode,'clip':index+1,'total':len(clips),'group':row['group'],'edits':row['edits'],'seconds':row['seconds']},ensure_ascii=False),flush=True)
    if windows:
        for index,c in enumerate(manifest['conversations']):
            if index<len(report['conversations']):continue
            path=Path(c['path']);assert tr.file_hash(path)==c['sha256'];row={k:v for k,v in c.items()if k!='path'};row.update(await decode(path));assert tr.file_hash(path)==c['sha256'];assert not row['whole_conversation_cer_valid']
            report['conversations'].append(row);save();print(json.dumps({'mode':mode,'conversation':len(report['conversations']),'group':row['group'],'seconds':row['seconds']}),flush=True)
    with tempfile.TemporaryDirectory(prefix='conversation-control-')as temp:
        controls=[]
        for seconds in (1,6):
            path=Path(temp)/('zero'+str(seconds)+'.wav')
            with wave.open(str(path),'wb')as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(bytes(seconds*32000))
            controls.append((path,'digital-zero',True))
        for environment in ('OOFFICE','PCAFETER'):
            source=FOLDER/(environment+'-ch08.wav');path=Path(temp)/(environment+'.wav')
            with wave.open(str(source))as original:original.setpos(30*16000);data=original.readframes(6*16000)
            with wave.open(str(path),'wb')as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(data)
            controls.append((path,'actual-'+environment+'-ambient',False))
        for path,label,known_silent in controls:
            result=await decode(path);report['controls'].append({'condition':label,'known_speech_free':known_silent,'whole_cer_valid':False,**result});save()
    report['aggregate']={}
    for group in sorted({r['group']for r in report['clips']}):
        rows=[r for r in report['clips']if r['group']==group];chars=sum(r['reference_chars']for r in rows);edits=sum(r['edits']for r in rows)
        report['aggregate'][group]={'clips':len(rows),'empty_outputs':sum(not r['recognized']for r in rows),'reference_chars':chars,'edits':edits,'cer':edits/chars,**{key:sum(r[key]for r in rows)for key in ('substitutions','deletions','insertions','seconds')}}
    report['ready']=True;save();print(json.dumps({'ready':True,'aggregate':report['aggregate']},ensure_ascii=False),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['250','100','off'],required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--legacy',action='store_true');parser.add_argument('--windows',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--padding-ms',type=int,choices=[200,500,1000],default=200);args=parser.parse_args();assert args.resume or not args.output.exists(),'Use a new output path or resume an incomplete matching run';asyncio.run(main(args.mode,args.output,args.legacy,args.windows,args.resume,args.padding_ms))
