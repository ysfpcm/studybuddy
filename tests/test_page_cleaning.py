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

    def test_focus_finds_content_inside_long_paragraph(self):
        page.clear()
        self.addCleanup(page.clear)
        text = ("Network devices exchange data reliably. " * 600 +
                "Routers forward packets between subnets. " +
                "Other devices connect to the network. " * 100)
        page.set_page("https://example.test/lesson", "Networking", text)

        focused = page.read("routers")
        self.assertTrue(focused["truncated"])
        self.assertGreater(focused["showing_from_char"], 0)
        self.assertIn("Routers forward packets between subnets.", focused["text"])
        self.assertLessEqual(len(focused["text"]), page.TOOL_WINDOW)

        unmatched = page.read("wireless")
        self.assertEqual(unmatched["showing_from_char"], 0)
        self.assertEqual(unmatched["text"], text[:page.TOOL_WINDOW])


if __name__ == "__main__":
    unittest.main()
