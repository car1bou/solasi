import asyncio
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.db import create_session
from lecture_study.audio import start_recording,get_recording


class SocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=create_app(AppConfig(data_dir=Path(self.temp.name),runtime_dir=Path(self.temp.name)/"runtime",port=8765))
        self.addCleanup(self.app.state.db.close)
        self.sid=create_session(self.app.state.db,"lecture","녹음",None,None).id
        self.rid=start_recording(self.app.state.db,self.sid,48000)

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks):task.cancel()
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)

    async def socket(self,init,packets=(),origin="http://127.0.0.1:8765",sid=None,disconnect=True):
        incoming=asyncio.Queue()
        incoming.put_nowait({"type":"websocket.connect"})
        incoming.put_nowait({"type":"websocket.receive","text":json.dumps(init)})
        for packet in packets:
            incoming.put_nowait({"type":"websocket.receive","bytes":packet})
        if disconnect:incoming.put_nowait({"type":"websocket.disconnect","code":1000})
        sent=[]
        async def send(message): sent.append(message)
        scope={"type":"websocket","asgi":{"version":"3.0"},"scheme":"ws","path":"/api/sessions/"+(sid or self.sid)+"/audio",
               "raw_path":b"/","query_string":b"","root_path":"","headers":[(b"host",b"127.0.0.1:8765"),(b"origin",origin.encode()),
                (b"cookie",(self.app.state.cookie_name+"="+self.app.state.cookie).encode())],"client":("127.0.0.1",1000),"server":("127.0.0.1",8765),"subprotocols":[]}
        try: await asyncio.wait_for(self.app(scope,incoming.get,send),2)
        except Exception as exc: self.fail("WebSocket 입력이 처리되지 않았습니다: "+type(exc).__name__)
        return sent

    def init(self):
        return {"recording_id":self.rid,"sample_rate":48000,"channels":1,"format":"pcm_s16le","csrf_token":self.app.state.csrf}

    async def test_malformed_init_rejected_without_crash(self):
        for init in ([],{"csrf_token":[]},{"csrf_token":self.app.state.csrf,"recording_id":self.rid,"sample_rate":48000,"channels":True,"format":"pcm_s16le"}):
            sent=await self.socket(init)
            self.assertEqual(sent[-1]["type"],"websocket.close")
            self.assertEqual(sent[-1]["code"],1008)

    async def test_boundary_ownership_and_durable_ack(self):
        sent=await self.socket(self.init(),origin="https://attacker.example")
        self.assertEqual(sent,[{"type":"websocket.close","code":1008,"reason":""}])
        other=create_session(self.app.state.db,"meeting","다른 회의",None,None).id
        sent=await self.socket(self.init(),sid=other)
        self.assertNotIn('"type":"ready"',str(sent))
        packet=struct.pack("<QQI",0,0,12000)+bytes([1,0])*12000
        sent=await self.socket(self.init(),[packet,packet])
        bodies=[json.loads(m["text"]) for m in sent if m["type"]=="websocket.send"]
        self.assertEqual([b["type"] for b in bodies],["ready","ack","ack"])
        self.assertEqual(get_recording(self.app.state.db,self.rid)["stored_frames"],12000)
        self.assertEqual(get_recording(self.app.state.db,self.rid)["status"],"interrupted")

    async def test_disk_failure_has_no_ack(self):
        packet=struct.pack("<QQI",0,0,12000)+bytes([1,0])*12000
        with patch("lecture_study.audio.write_pcm",side_effect=OSError("disk full")):
            sent=await self.socket(self.init(),[packet])
        bodies=[json.loads(m["text"]) for m in sent if m["type"]=="websocket.send"]
        self.assertEqual([b["type"] for b in bodies],["ready","error"])
        self.assertEqual(get_recording(self.app.state.db,self.rid)["stored_frames"],0)


    async def test_disconnect_finalizes_received_tail(self):
        packet=struct.pack('<QQI',0,0,12000)+bytes([1,0])*12000
        await self.socket(self.init(),[packet])
        row=get_recording(self.app.state.db,self.rid)
        self.assertEqual(row['status'],'interrupted')
        self.assertIsNotNone(row['stop_job_id'])
        self.assertTrue(self.app.state.db.execute('SELECT 1 FROM transcript_ranges WHERE recording_id=? AND final=1',(self.rid,)).fetchone())
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)

    async def test_unexpected_disconnect_logs_code_without_credentials_or_audio(self):
        with self.assertLogs('lecture_study.server',level='WARNING')as logs:
            await self.socket(self.init(),[struct.pack('<QQI',0,0,12000)+bytes([1,0])*12000])
        text=' '.join(logs.output);self.assertIn('code=1000',text);self.assertIn(self.rid,text);self.assertNotIn(self.app.state.csrf,text);self.assertNotIn(self.app.state.cookie,text)

    async def test_second_socket_cannot_interrupt_current_owner(self):
        owner=object();self.app.state.audio_sockets[self.rid]=owner
        sent=await self.socket(self.init())
        self.assertEqual(sent[-1]['type'],'websocket.close')
        self.assertIs(self.app.state.audio_sockets.get(self.rid),owner)
        self.assertEqual(get_recording(self.app.state.db,self.rid)['status'],'recording')

    async def test_open_socket_without_pcm_expires_and_finalizes(self):
        from lecture_study import server
        with patch.object(server,'AUDIO_IDLE_SECONDS',.01,create=True):sent=await asyncio.wait_for(self.socket(self.init(),disconnect=False),1)
        bodies=[json.loads(m['text']) for m in sent if m['type']=='websocket.send']
        self.assertEqual([m['type'] for m in bodies],['ready','error'])
        self.assertIs(bodies[-1].get('recoverable'),True)
        row=get_recording(self.app.state.db,self.rid)
        self.assertEqual(row['status'],'interrupted');self.assertIsNotNone(row['stop_job_id'])
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)


    async def test_start_without_socket_expires_with_reason(self):
        import httpx
        from lecture_study import server
        other=create_session(self.app.state.db,'lecture','연결 지연',None,None).id
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://127.0.0.1:8765') as client:
            origin={'Origin':'http://127.0.0.1:8765'}
            login=await client.post('/api/bootstrap',json={'token':self.app.state.bootstrap_token},headers=origin)
            headers=origin|{'X-Session-Token':login.json()['csrf_token']}
            with patch.object(server,'AUDIO_IDLE_SECONDS',.01):
                result=await client.post('/api/sessions/'+other+'/audio/start',json={'sample_rate':48000},headers=headers)
                self.assertEqual(result.status_code,201,result.text)
                await asyncio.sleep(.03)
            row=get_recording(self.app.state.db,result.json()['recording_id'])
            self.assertEqual(row['status'],'interrupted');self.assertIn('시간 초과',row['error']);self.assertIsNotNone(row['stop_job_id'])
