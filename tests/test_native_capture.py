import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS Swift compiler required')
class NativeCaptureTests(unittest.TestCase):
    def test_pending_ack_cancellation_preserves_recovery(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='solasi-capture-') as folder:
            folder = Path(folder)
            source = folder / 'AudioRecovery.swift'
            source.write_text('\n'.join((root / 'macos' / name).read_text() for name in ('AudioCapture.swift', 'AudioRecoveryFixture.swift')))
            binary = folder / 'capture-fixture'
            compiled = subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-module-cache-path', str(root / '.local-state/swift-cache'), str(source), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=12)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('stale ACK ignored; explicit stop completes', result.stdout)
