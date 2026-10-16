import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS Swift compiler required')
class NativeBridgeMemoryTests(unittest.TestCase):
    def test_small_ack_reads_do_not_accumulate_buffers(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='solasi-bridge-memory-') as folder:
            folder = Path(folder)
            worker = folder / 'worker.py'
            worker.write_text('''import json, os, struct, sys
os.setpgid(0, 0)
def send(value):
    value.update(version=1, body_length=0)
    header=json.dumps(value, separators=(',', ':')).encode()
    sys.stdout.buffer.write(struct.pack('>I', len(header))+header)
    sys.stdout.buffer.flush()
send(dict(id='worker', event='ready', process_group=os.getpid()))
while prefix:=sys.stdin.buffer.read(4):
    header=json.loads(sys.stdin.buffer.read(struct.unpack('>I', prefix)[0]))
    sys.stdin.buffer.read(header['body_length'])
    if header['op']=='shutdown': break
    send(dict(id=header['id'], event='complete', payload=dict(type='ack', seq=header['seq'], frame_count=4096)))
''')
            binary = folder / 'memory-fixture'
            compiled = subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(root / '.local-state/swift-cache'), str(root / 'macos/WorkerBridge.swift'), str(root / 'macos/WorkerMemoryFixture.swift'), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary), sys.executable, str(worker)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Worker read memory baseline', result.stdout)
