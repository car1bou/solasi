"""Fixed adult interview diagnostics and real ambient mixtures; original conversation CER is undefined."""
import hashlib,json,math,subprocess,tarfile,time,urllib.request,wave
from array import array
from pathlib import Path
from experiments.collect_speech_conditions import zip_prefix,utterances
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';FOLDER=RUNTIME/'conversation-20261014'
LABELS={'s11m25f1':'231654384c70d65bba10b73b3b8108f24d819d073fdbf86a2fd34b020fc1f6f3','s12m23f1':'5ae21610afab2fb69ea6c837ce68b81cb959a1485b383085ab0a6dc327d228e9','s16f22m1':'f195f921ea5d85c0e7ae6de9e39944afd867b4888ee784c5ace205c53d5608e9'}
WINDOWS={'s11m25f1':[(148.986041063,208.331029872),(515.881097565,574.981197570)],'s12m23f1':[(224.202630504,282.389390415),(420.385949008,479.412876393)],'s16f22m1':[(351.910249153,409.790658695),(551.835181072,611.764025672)]}
NOISES={'office':('OOFFICE','88995191','7b61cc2d182d5a654cb9c3101ddd4041'),'cafeteria':('PCAFETER','107431494','99927d148128254141a9417d051510bb')}
class Counted:
    def __init__(self,source,limit,label):self.source=source;self.limit=limit;self.label=label;self.total=0;self.last=0
    def read(self,n=-1):
        data=self.source.read(n);self.total+=len(data)
        if self.total>self.limit:raise ValueError('Public data transfer exceeded bounded prefix')
        if self.total-self.last>=32*1024**2:self.last=self.total;print(json.dumps({'source':self.label,'http_prefix_bytes':self.total}),flush=True)
        return data

def choose_reference_clips(rows,start,end):
    eligible=[r for r in rows if start<=r['start']<r['end']<=end and r['reference'].strip() and '<'not in r['reference']]
    short=[r for r in eligible if .12<=r['end']-r['start']<1]
    long=[r for r in eligible if 1<=r['end']-r['start']<=8]
    assert short and len(long)>=4,'Need a short turn and four labeled ordinary utterances'
    selected=[min(short,key=lambda r:r['end']-r['start'])]+[long[round(n*(len(long)-1)/3)]for n in range(4)]
    return sorted(selected,key=lambda r:r['start'])

def mix_pcm(signal,noise,gain,offset):
    result=array('h');clipped=0
    assert noise and gain>=0
    for n,value in enumerate(signal):
        mixed=round(value+noise[(n+offset)%len(noise)]*gain)
        clipped+=not -32768<=mixed<=32767;result.append(max(-32768,min(32767,mixed)))
    return result,clipped

def digest(path):
    with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read_pcm(path):
    with wave.open(str(path))as source:
        assert source.getframerate()==16000 and source.getsampwidth()==2 and source.getnchannels()==1
        values=array('h');values.frombytes(source.readframes(source.getnframes()));return values

def write_pcm(path,values):
    with wave.open(str(path),'wb')as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(values.tobytes())

def fetch_archive(kind,suffix):
    url='https://openslr.trmal.net/resources/113/'+kind+'.tgz';limit=(1536 if kind=='sound' else 57)*1024**2
    selected={name+'.'+suffix for name in LABELS}
    with urllib.request.urlopen(url,timeout=120)as response:
        assert response.status==200;counted=Counted(response,limit,kind)
        with tarfile.open(fileobj=counted,mode='r|gz')as archive:
            item=next(iter(archive));assert item.isfile()and item.name.endswith('.zip')
            with archive.extractfile(item)as source:files,inner=zip_prefix(source,suffix,91,names=selected,max_bytes=limit)
    assert {name for name,_ in files}==selected,'Sound and label archive order differs; stop before increasing transfer'
    return files,{'url':url,'http_prefix_bytes':counted.total,'inner_zip_prefix_bytes':inner,'verified_entries':91,'whole_archive_complete':False,'whole_archive_checksum_verified':False}

def collect():
    FOLDER.mkdir(parents=True,exist_ok=True);proof_path=FOLDER/'sources.json'
    proof=json.loads(proof_path.read_text())if proof_path.exists()else{'files':[],'transfers':[]}
    def save():proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    for kind,suffix in [('label','TextGrid'),('sound','flac')]:
        existing=[r for r in proof['files']if r['kind']==kind]
        if existing:
            assert len(existing)==3 and all(digest(Path(r['path']))==r['sha256']for r in existing);continue
        files,transfer=fetch_archive(kind,suffix)
        for name,data in files:
            if kind=='label':assert hashlib.sha256(data).hexdigest()==LABELS[Path(name).stem]
            path=FOLDER/name;path.write_bytes(data);proof['files'].append({'kind':kind,'name':name,'path':str(path),'bytes':len(data),'sha256':digest(path),'zip_crc_verified':True})
        proof['transfers'].append(transfer);save();print('Collected selected '+kind,flush=True)
    for group,(environment,size,official_md5)in NOISES.items():
        path=FOLDER/(environment+'-ch08.wav');existing=next((r for r in proof['files']if r['kind']==group),None)
        if existing:assert digest(path)==existing['sha256'];continue
        url='https://zenodo.org/records/1227121/files/'+environment+'_16k.zip?download=1'
        with urllib.request.urlopen(url,timeout=120)as response:
            counted=Counted(response,32*1024**2,group);files,inner=zip_prefix(counted,'wav',1,max_bytes=32*1024**2)
        assert len(files)==1 and files[0][0]==environment+'/ch08.wav';path.write_bytes(files[0][1]);assert abs(len(read_pcm(path))/16000-300)<.01
        proof['files'].append({'kind':group,'name':path.name,'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path),'zip_crc_verified':True})
        proof['transfers'].append({'url':url,'http_prefix_bytes':counted.total,'inner_zip_prefix_bytes':inner,'archive_bytes':int(size),'official_archive_md5':official_md5,'whole_archive_checksum_verified':False});save();print('Collected actual '+group+' noise channel',flush=True)
    report={'ready':False,'selection_before_inference':'Three adult interview files and six exact label-boundary windows fixed from independent label inspection; first window per speaker selects shortest .12-1s labeled turn and four evenly spread 1-8s utterances before inference','datasets':{'seoul':{'source':'https://www.openslr.org/113/','license':'CC BY-NC2.0','limitations':'Interviewer <IVER> has no lexical reference. No whole-conversation CER. Original and mixtures used for local noncommercial evaluation, original audio not bundled.'},'demand':{'source':'https://zenodo.org/records/1227121','license':'Producer PDF says CC BY-SA3.0; record JSON says CC BY4.0. Use producer conditions conservatively, no mixture redistribution.','limitations':'Actual French office/cafeteria ambience, can contain competing speech. Mixtures are derived, not on-site Korean meetings.'}},'clips':[],'conversations':[],'mixtures':[],'sources_proof':proof}
    for speaker,windows in WINDOWS.items():
        rows=utterances((FOLDER/(speaker+'.TextGrid')).read_text(encoding='utf-16'));clean=FOLDER/(speaker+'-clean.wav')
        if not clean.exists():subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-v','error','-nostdin','-y','-i',str(FOLDER/(speaker+'.flac')),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(clean)],check=True)
        signal=read_pcm(clean);assert max(r['end']for r in rows)<=len(signal)/16000+.002
        all_audio={'clean':signal};signal_rms=math.sqrt(sum(v*v for v in signal)/len(signal))
        for group,(environment,_,_)in NOISES.items():
            noise=read_pcm(FOLDER/(environment+'-ch08.wav'));noise_rms=math.sqrt(sum(v*v for v in noise)/len(noise));gain=signal_rms/noise_rms*10**(-10/20)
            mixed,clipped=mix_pcm(signal,noise,gain,0);path=FOLDER/(speaker+'-'+group+'.wav');write_pcm(path,mixed);all_audio[group]=mixed
            report['mixtures'].append({'speaker':speaker,'group':group,'path':str(path),'sha256':digest(path),'audio_seconds':len(mixed)/16000,'snr_db_before_clipping':10,'noise_gain':gain,'clipped_samples':clipped,'total_samples':len(mixed),'noise_repeated_after_seconds':len(noise)/16000,'target':'Original continuous interview, both interviewer and respondent; no concatenated target utterances'})
        for index,(start,end)in enumerate(windows):
            in_window=[r for r in rows if start<=r['start']<r['end']<=end];assert any('<IVER>'in r['reference']for r in in_window)
            for group,values in all_audio.items():
                path=FOLDER/(speaker+'-'+group+'-window'+str(index)+'.wav');write_pcm(path,values[round(start*16000):round(end*16000)])
                report['conversations'].append({'speaker_id':speaker,'group':group,'path':str(path),'sha256':digest(path),'start_seconds':start,'end_seconds':end,'duration_seconds':(round(end*16000)-round(start*16000))/16000,'labeled_respondent_intervals':[r for r in in_window if '<'not in r['reference']and r['reference'].strip()],'untranscribed_interviewer_intervals':[r for r in in_window if '<IVER>'in r['reference']],'whole_conversation_cer_valid':False})
        for index,row in enumerate(choose_reference_clips(rows,*windows[0])):
            for group,values in all_audio.items():
                path=FOLDER/(speaker+'-'+group+'-ref'+str(index)+'.wav');write_pcm(path,values[round(row['start']*16000):round(row['end']*16000)])
                report['clips'].append({'row_idx':speaker+'-'+group+'-'+str(index),'group':group+'-adult','speaker_id':speaker,'path':str(path),'sha256':digest(path),'reference':row['reference'],'reference_raw_transcription':row['reference'],'start_seconds':row['start'],'end_seconds':row['end'],'duration_seconds':(round(row['end']*16000)-round(row['start']*16000))/16000,'short_turn':row['end']-row['start']<1})
        print('Prepared actual adult '+speaker,flush=True)
    assert len(report['clips'])==45 and len(report['conversations'])==18
    long=next(r for r in report['mixtures']if r['speaker']=='s12m23f1'and r['group']=='office')
    sidecar={'input_type':'continuous adult Korean interviewer/respondent conversation with real office ambient mixed at global10dB; interviewer words untranscribed, no whole CER','source':'https://www.openslr.org/113/','source_file':'s12m23f1.flac','noise':'https://zenodo.org/records/1227121','noise_file':'OOFFICE/ch08.wav','license':'Private noncommercial local evaluation; Seoul CC BY-NC2.0 and conservative DEMAND CC BY-SA3.0; no audio redistribution','mixture':long}
    Path(long['path']).with_suffix('.json').write_text(json.dumps(sidecar,ensure_ascii=False,indent=2));report['long_input']=long['path'];report['ready']=True
    (FOLDER/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'ready':True,'reference_clips':45,'conversation_windows':18,'long_input':report['long_input']}),flush=True)
if __name__=='__main__':collect()
