from pathlib import Path
import unittest

from lecture_study import windows_instance as instance


class InstanceTests(unittest.TestCase):
    def test_handoff_payload_rejects_binary_controls_and_non_audio_urls(self):
        url='solasi://audio/'+'a'*32+'/'+'b'*32+'?start_ms=0&end_ms=1000'
        self.assertEqual(instance.decode_link((url+'\0').encode('utf-16-le')),url)
        for payload in (b'x',b'\0\0',('https://evil/\0').encode('utf-16-le'),(url+'\0evil\0').encode('utf-16-le'),b'x'*20000):
            with self.subTest(payload=payload[:20]),self.assertRaises(ValueError):instance.decode_link(payload)

    def test_instance_identity_follows_canonical_data_directory(self):
        self.assertEqual(instance.instance_key(Path('/tmp/data/../data')),instance.instance_key(Path('/tmp/data')))
        self.assertNotEqual(instance.instance_key(Path('/tmp/data')),instance.instance_key(Path('/tmp/other')))


if __name__=='__main__':unittest.main()
