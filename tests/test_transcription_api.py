import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
from lecture_study.server import create_app
from lecture_study.config import AppConfig
from lecture_study.audio import append_pcm,get_recording
from lecture_study.transcription import range_row


class TranscriptApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(AppConfig(Path(self.temp.name),Path(self.temp.name)/"runtime",port=8765))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url="http://127.0.0.1:8765")
        origin={"Origin":"http://127.0.0.1:8765"}
        login=await self.client.post("/api/bootstrap",json={"token":self.app.state.bootstrap_token},headers=origin)
        self.headers={**origin,"X-Session-Token":login.json()["csrf_token"]}
        saved=await self.client.post("/api/sessions",json={"kind":"lecture","title":"녹음 테스트"},headers=self.headers)
        self.sid=saved.json()["id"]
        start=await self.client.post("/api/sessions/"+self.sid+"/audio/start",json={"sample_rate":48000,'transcription_mode':'realtime'},headers=self.headers)
        self.rid=start.json()["recording_id"]
        append_pcm(self.app.state.db,self.rid,0,0,48000,bytes([255,31])*48000)

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks): task.cancel()
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        await self.client.aclose();self.app.state.db.close();self.temp.cleanup()

    async def test_stop_polling_final_job_and_idempotent_retry(self):
        with patch("lecture_study.transcription.transcribe_range",new=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"확정"}])):
            stopped=await self.client.post("/api/recordings/"+self.rid+"/stop",json={},headers=self.headers)
            self.assertEqual(stopped.status_code,200,stopped.text)
            await asyncio.gather(*self.app.state.tasks)
            event=await self.client.get("/api/sessions/"+self.sid+"/events")
            self.assertEqual(event.json()["transcripts"][0]["text"],"확정")
            job=await self.client.get("/api/jobs/"+stopped.json()["id"])
            self.assertEqual(job.json()["status"],"done")
            again=await self.client.post("/api/recordings/"+self.rid+"/stop",json={},headers=self.headers)
            self.assertEqual(again.json()["id"],job.json()["id"])
            await asyncio.gather(*self.app.state.tasks)
            self.assertEqual(len((await self.client.get("/api/sessions/"+self.sid+"/events")).json()["transcripts"]),1)

    async def test_cancel_transcription_preserves_raw_and_allows_retry(self):
        started=asyncio.Event()
        async def blocked(*args,**kwargs):
            started.set();await asyncio.Event().wait()
        with patch("lecture_study.transcription.transcribe_range",new=blocked):
            stopped=await self.client.post("/api/recordings/"+self.rid+"/stop",json={},headers=self.headers)
            await asyncio.wait_for(started.wait(),2)
            cancelled=await self.client.post("/api/jobs/"+stopped.json()["id"]+"/cancel",headers=self.headers)
            self.assertEqual(cancelled.json()["status"],"cancelled")
        self.assertEqual(get_recording(self.app.state.db,self.rid)["stored_frames"],48000)
        with patch("lecture_study.transcription.transcribe_range",new=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"복구"}])):
            retried=await self.client.post("/api/jobs/"+stopped.json()["id"]+"/retry",headers=self.headers)
            self.assertEqual(retried.status_code,200,retried.text)
            await asyncio.gather(*self.app.state.tasks)
            self.assertEqual(len((await self.client.get("/api/sessions/"+self.sid+"/events")).json()["transcripts"]),1)

    async def test_range_audio_and_delete_confirmation(self):
        response=await self.client.get("/api/recordings/"+self.rid+"/audio",headers={"Range":"bytes=44-63"})
        self.assertEqual(response.status_code,206,response.text[:100])
        self.assertEqual(response.content,bytes([255,31])*10)
        denied=await self.client.delete("/api/sessions/"+self.sid)
        self.assertEqual(denied.status_code,403)
        denied=await self.client.request("DELETE","/api/sessions/"+self.sid,headers=self.headers,json={"confirmed":False})
        self.assertEqual(denied.status_code,422,denied.text)
        deleted=await self.client.request("DELETE","/api/sessions/"+self.sid,headers=self.headers,json={"confirmed":True})
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual((await self.client.get("/api/sessions/"+self.sid)).status_code,404)

    async def test_audio_delete_cancels_pending_asr(self):
        started=asyncio.Event()
        async def blocked(*args,**kwargs):
            started.set();await asyncio.Event().wait()
        with patch("lecture_study.transcription.transcribe_range",new=blocked):
            stopped=await self.client.post("/api/recordings/"+self.rid+"/stop",json={},headers=self.headers)
            await asyncio.wait_for(started.wait(),2)
            response=await self.client.request("DELETE","/api/sessions/"+self.sid+"/audio",json={"confirmed":True},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            job=await self.client.get("/api/jobs/"+stopped.json()["id"])
            self.assertEqual(job.json()["status"],"cancelled")

    async def test_stop_preempts_unfinished_preview_and_runs_final_without_new_packets(self):
        import json,struct
        started=asyncio.Event();cancelled=asyncio.Event();incoming=asyncio.Queue()
        async def decoder(*args,preview=False,**kwargs):
            if preview:
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
            return [{'start_ms':0,'end_ms':3000,'text':'확정 우선'}]
        incoming.put_nowait({'type':'websocket.connect'})
        incoming.put_nowait({'type':'websocket.receive','text':json.dumps({'recording_id':self.rid,'sample_rate':48000,'channels':1,'format':'pcm_s16le','csrf_token':self.app.state.csrf})})
        for seq in range(1,10):incoming.put_nowait({'type':'websocket.receive','bytes':struct.pack('<QQI',seq,seq*48000,48000)+bytes([255,31])*48000})
        async def send(message):pass
        scope={'type':'websocket','asgi':{'version':'3.0'},'scheme':'ws','path':'/api/sessions/'+self.sid+'/audio','raw_path':b'/','query_string':b'','root_path':'','headers':[(b'host',b'127.0.0.1:8765'),(b'origin',b'http://127.0.0.1:8765'),(b'cookie',(self.app.state.cookie_name+'='+self.app.state.cookie).encode())],'client':('127.0.0.1',1000),'server':('127.0.0.1',8765),'subprotocols':[]}
        with patch('lecture_study.transcription.transcribe_range',new=decoder):
            socket=asyncio.create_task(self.app(scope,incoming.get,send))
            try:
                await asyncio.wait_for(started.wait(),2)
                stopped=await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
                await asyncio.wait_for(cancelled.wait(),.5)
                await asyncio.wait_for(asyncio.gather(*self.app.state.tasks),2)
                job=(await self.client.get('/api/jobs/'+stopped.json()['id'])).json()
                self.assertEqual(job['status'],'done')
                event=(await self.client.get('/api/sessions/'+self.sid+'/events')).json()
                self.assertEqual([t['text'] for t in event['transcripts']],['확정 우선'])
            finally:
                incoming.put_nowait({'type':'websocket.disconnect','code':1000})
                await asyncio.wait_for(socket,2)

    async def test_new_pcm_does_not_cancel_an_already_preempted_preview_again(self):
        import json,struct
        started=asyncio.Event();terminating=asyncio.Event();release=asyncio.Event();incoming=asyncio.Queue();acks=asyncio.Queue()
        async def decoder(*args,preview=False,**kwargs):
            if preview:
                started.set()
                try:await asyncio.Event().wait()
                finally:terminating.set();await release.wait()
            return [{'start_ms':0,'end_ms':500,'text':'확정'}]
        incoming.put_nowait({'type':'websocket.connect'})
        incoming.put_nowait({'type':'websocket.receive','text':json.dumps({'recording_id':self.rid,'sample_rate':48000,'channels':1,'format':'pcm_s16le','csrf_token':self.app.state.csrf})})
        def packet(seq):incoming.put_nowait({'type':'websocket.receive','bytes':struct.pack('<QQI',seq,seq*48000,48000)+bytes([255,31])*48000})
        for seq in range(1,10):packet(seq)
        async def send(message):
            if message['type']=='websocket.send':
                body=json.loads(message['text'])
                if body.get('type')=='ack':acks.put_nowait(body['seq'])
        scope={'type':'websocket','asgi':{'version':'3.0'},'scheme':'ws','path':'/api/sessions/'+self.sid+'/audio','raw_path':b'/','query_string':b'','root_path':'','headers':[(b'host',b'127.0.0.1:8765'),(b'origin',b'http://127.0.0.1:8765'),(b'cookie',(self.app.state.cookie_name+'='+self.app.state.cookie).encode())],'client':('127.0.0.1',1000),'server':('127.0.0.1',8765),'subprotocols':[]}
        with patch('lecture_study.transcription.transcribe_range',new=decoder):
            socket=asyncio.create_task(self.app(scope,incoming.get,send))
            try:
                await asyncio.wait_for(started.wait(),2)
                for seq in range(10,30):packet(seq)
                await asyncio.wait_for(terminating.wait(),2);preview=self.app.state.active_asr[0]
                packet(30)
                while await asyncio.wait_for(acks.get(),2)!=30:pass
                self.assertEqual(preview.cancelling(),1)
                release.set()
                stopped=await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
                await asyncio.wait_for(asyncio.gather(*self.app.state.tasks),2)
                self.assertEqual((await self.client.get('/api/jobs/'+stopped.json()['id'])).json()['status'],'done')
            finally:
                release.set();incoming.put_nowait({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(socket,2)
