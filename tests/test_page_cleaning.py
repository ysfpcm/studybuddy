import tempfile
import unittest
from pathlib import Path

from studybuddy import page


class PageCleaningTest(unittest.TestCase):
    def test_query_identifies_distinct_saved_lessons(self):
        page.clear()
        self.addCleanup(page.clear)
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            first_text = "The first lesson explains network switches. " * 10
            second_text = "The second lesson explains network routers. " * 10
            page.set_page("https://example.test/lesson?id=1&nonce=old", "Lesson", first_text)
            first, _ = page.save_to_course(courses, "networking")

            page.set_page("https://example.test/lesson?id=2&nonce=old", "Lesson", second_text)
            second, replaced = page.save_to_course(courses, "networking")
            self.assertNotEqual(first, second)
            self.assertEqual(replaced, [])
            self.assertIn(first_text.strip(), first.read_text(encoding="utf-8"))
            self.assertIn(second_text.strip(), second.read_text(encoding="utf-8"))

            page.set_page("https://example.test/lesson?id=1&nonce=new#top", "Lesson", first_text)
            again, replaced = page.save_to_course(courses, "networking")
            self.assertEqual(again, first)
            self.assertEqual(replaced, [])
            self.assertTrue(second.exists())

    def test_query_distinguishes_numbered_lessons(self):
        page.clear()
        self.addCleanup(page.clear)
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            text = "A lesson about computer networks. " * 10
            page.set_page("https://example.test/lesson?id=1", "Lesson", text,
                          section="1.1.1", section_title="Switches")
            first, _ = page.save_to_course(courses, "networking")
            page.set_page("https://example.test/lesson?id=2", "Lesson", text,
                          section="1.1.2", section_title="Routers")
            second, replaced = page.save_to_course(courses, "networking")
            self.assertNotEqual(first, second)
            self.assertEqual(replaced, [])
            self.assertTrue(first.exists())

    def test_old_saved_path_is_replaced_for_same_query(self):
        page.clear()
        self.addCleanup(page.clear)
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            pages = courses / "networking" / "material" / "pages"
            pages.mkdir(parents=True)
            old = pages / "legacy.md"
            old.write_text("# Lesson\n\nSource: https://example.test/lesson?id=1&nonce=old\n\nOld text",
                           encoding="utf-8")
            page.set_page("https://example.test/lesson?id=1&nonce=new", "Lesson",
                          "A lesson about computer networks. " * 10)
            saved, replaced = page.save_to_course(courses, "networking")
            self.assertEqual(replaced, [old])
            self.assertTrue(saved.exists())
            self.assertFalse(old.exists())

    def test_canonical_keeps_other_query_parameters(self):
        self.assertEqual(
            page.canonical("https://example.test/lesson/?id=1&nonce=old&view=&tag=a&tag=b#top"),
            "https://example.test/lesson?id=1&view=&tag=a&tag=b",
        )

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
