import tempfile
import unittest
from pathlib import Path

from studybuddy import page


class PageCleaningTest(unittest.TestCase):
    def test_distinct_paragraphs_with_shared_prefix_are_read_and_saved(self):
        prefix = "A network connects devices and transmits data. " * 10
        first = prefix + "Switches forward frames."
        second = prefix + "Routers forward packets."
        page.clear()
        self.addCleanup(page.clear)
        page.set_page("https://example.test/lesson", "Networking", "\n\n".join([first, first, second]))

        self.assertEqual(page.read()["text"], first + "\n\n" + second)
        with tempfile.TemporaryDirectory() as directory:
            saved, _ = page.save_to_course(Path(directory), "networking")
            self.assertIn(first + "\n\n" + second, saved.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
