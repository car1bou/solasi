"""Native protocol checks; set SOLASI_EMBEDDING_* to exercise the real model."""
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def frame(data):
    return struct.pack('>I', len(data)) + data


class EmbeddingProtocolTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang++'), 'C++ compiler required')
    def test_fragmented_newlines_and_rejected_frames_keep_boundaries(self):
        fixture = r'''
#include "EmbeddingProtocol.hpp"
#include <iostream>
int main() {
    std::string data;
    while (true) {
        auto state = solasi::read_frame(std::cin, data);
        if (state == solasi::FrameStatus::eof) return 0;
        if (state != solasi::FrameStatus::ok) {
            solasi::write_frame(std::cout, state == solasi::FrameStatus::oversize ? "oversize" : "truncated");
            return 2;
        }
        auto text = solasi::text_status(data);
        solasi::write_frame(std::cout, text == solasi::TextStatus::empty ? "empty" :
            text == solasi::TextStatus::invalid ? "invalid_utf8" : data);
    }
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'fixture.cpp'; binary = root/'fixture'
            source.write_text(fixture)
            built = subprocess.run(['clang++', '-std=c++17', '-I', str(ROOT/'macos'), str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                data = '첫 줄\n둘째 줄 🐱'.encode()
                for byte in frame(data): process.stdin.write(bytes([byte])); process.stdin.flush()
                self.assertEqual(process.stdout.read(len(frame(data))), frame(data))
                for bad, expected in [(b'', b'empty'), ('\u3000\n\t'.encode(), b'empty'), (b'\xc0\xaf', b'invalid_utf8'), (b'\xed\xa0\x80', b'invalid_utf8'), (b'\xf4\x90\x80\x80', b'invalid_utf8')]:
                    process.stdin.write(frame(bad));process.stdin.flush()
                    self.assertEqual(process.stdout.read(len(frame(expected))), frame(expected))
                process.stdin.write(frame(b'after errors'));process.stdin.flush()
                self.assertEqual(process.stdout.read(16), frame(b'after errors'))
                process.stdin.close();self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None: process.kill();process.wait()
                process.stdout.close()
            for payload, expected in [(struct.pack('>I', 100001), b'oversize'), (b'\x00\x01', b'truncated'), (struct.pack('>I', 9)+b'ab', b'truncated')]:
                with self.subTest(payload=payload):
                    result=subprocess.run([str(binary)],input=payload,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, frame(expected))

    def test_build_rejects_unverified_archive_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'engine.tar.gz';archive.write_bytes(b'not the pinned engine')
            destination=root/'output'
            result=subprocess.run([os.sys.executable,str(ROOT/'scripts/build_embedding_worker.py'),'--archive',str(archive),'--headers',str(root),'--destination',str(destination)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('SHA256',result.stderr)
            self.assertFalse(destination.exists())


@unittest.skipUnless(os.environ.get('SOLASI_EMBEDDING_WORKER'), 'set SOLASI_EMBEDDING_WORKER, SOLASI_EMBEDDING_MODEL and SOLASI_EMBEDDING_LIB for model integration')
class EmbeddingModelTests(unittest.TestCase):
    def test_korean_rank_norm_and_request_error_recovery(self):
        binary=Path(os.environ['SOLASI_EMBEDDING_WORKER']);model=Path(os.environ['SOLASI_EMBEDDING_MODEL']);libs=Path(os.environ['SOLASI_EMBEDDING_LIB'])
        def digest():
            with model.open('rb') as stream:
                value=hashlib.sha256()
                for block in iter(lambda:stream.read(1024*1024), b''):value.update(block)
                return value.hexdigest()
        before=digest()
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen([str(binary),str(model),str(libs)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
            def read_exact(count):
                data=b''
                while len(data)<count:
                    with selectors.DefaultSelector() as ready:
                        ready.register(process.stdout,selectors.EVENT_READ)
                        self.assertTrue(ready.select(60),'worker response timeout')
                    chunk=os.read(process.stdout.fileno(),count-len(data));self.assertTrue(chunk,'worker closed stdout')
                    data+=chunk
                return data
            def response():
                size=struct.unpack('>I',read_exact(4))[0];self.assertLessEqual(size,100000)
                return json.loads(read_exact(size))
            def ask(text):
                process.stdin.write(frame(text.encode()));process.stdin.flush();return response()
            try:
                ready=response();self.assertTrue(ready['ready']);self.assertEqual(ready['dim'],768)
                docs=[
                    'title: 생물학 | text: 광합성은 식물이 빛 에너지를 이용해 이산화 탄소와 물로부터 포도당을 합성하는 과정이다.',
                    'title: 앱 개발 | text: 맥북이 절전 상태에서 복귀하면 마이크의 새 입력 프레임을 기다린 뒤 녹음을 다시 시작한다.',
                    'title: 회의록 | text: 팀은 금요일까지 기획안을 검토하고 다음 주 월요일에 담당자를 결정하기로 했다.'
                ]
                vectors=[ask(text)['vector'] for text in docs]
                for vector in vectors:
                    self.assertEqual(len(vector),768);self.assertTrue(all(math.isfinite(x) for x in vector))
                    self.assertAlmostEqual(sum(x*x for x in vector),1,places=6)
                queries=['식물이 빛으로 에너지를 만드는 과정은?', '잠자기에서 깨운 뒤 녹음은 어떻게 복구하나요?', '기획안 검토와 담당자 결정 일정은?']
                for index,text in enumerate(queries):
                    vector=ask('task: search result | query: '+text)['vector']
                    self.assertEqual(len(vector),768);self.assertTrue(all(math.isfinite(x) for x in vector))
                    self.assertAlmostEqual(sum(x*x for x in vector),1,places=6)
                    scores=[sum(a*b for a,b in zip(vector,d)) for d in vectors]
                    self.assertEqual(max(range(3),key=lambda i:scores[i]),index)
                text='title: 필기 | text: 첫째 문장입니다.\n둘째 문장입니다.'
                original=ask(text)['vector']
                for text,code in [('', 'empty'), ('\u3000\n', 'empty'), ('안녕하세요. '*3000, 'context_limit')]:
                    rejected=ask(text);self.assertEqual(rejected['error']['code'],code);self.assertFalse(rejected['fatal'])
                again=ask('title: 필기 | text: 첫째 문장입니다.\n둘째 문장입니다.')['vector']
                self.assertLess(max(abs(a-b) for a,b in zip(original,again)),1e-6)
                process.stdin.write(struct.pack('>I',100001));process.stdin.flush()
                rejected=response();self.assertEqual(rejected['error']['code'],'frame_too_large');self.assertTrue(rejected['fatal'])
                self.assertNotEqual(process.wait(timeout=10),0)
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdin.close();process.stdout.close()
        self.assertEqual(digest(),before)
