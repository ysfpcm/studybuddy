import shutil
import subprocess
import unittest
from pathlib import Path


class ExtensionReaderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for extension tests")
    def test_distinct_frames_are_preserved(self):
        script = Path(__file__).with_suffix(".js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for extension tests")
    def test_following_cancels_pending_work(self):
        script = Path(__file__).with_name("test_extension_following.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
