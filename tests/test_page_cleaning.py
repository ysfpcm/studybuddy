import tempfile
import unittest
from pathlib import Path

from studybuddy import page


class PageCleaningTest(unittest.TestCase):
    def test_page_hash_tracks_title_and_section_changes(self):
        page.clear()
        self.addCleanup(page.clear)
        url = "https://example.test/lesson"
        text = "A lesson about computer networks. " * 10
        first = page.set_page(url, "Lesson", text, section="1.1.1", section_title="Switches")
        unchanged = page.set_page(url + "?nonce=new", "Lesson", text,
                                  section="1.1.1", section_title="Switches")
        self.assertEqual(first["hash"], unchanged["hash"])
        next_section = page.set_page(url, "Lesson", text, section="1.1.2", section_title="Switches")
        self.assertNotEqual(first["hash"], next_section["hash"])
        renamed = page.set_page(url, "Lesson", text, section="1.1.2", section_title="Routers")
        self.assertNotEqual(next_section["hash"], renamed["hash"])
        unnumbered = page.set_page(url, "Lesson", text)
        new_title = page.set_page(url, "Updated lesson", text)
        self.assertNotEqual(unnumbered["hash"], new_title["hash"])

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

    def test_numbered_lessons_with_shared_url_remain_separate(self):
        page.clear()
        self.addCleanup(page.clear)
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            first_text = "The first lesson explains network switches. " * 10
            second_text = "The second lesson explains network routers. " * 10
            page.set_page("https://example.test/lesson?nonce=old", "Lesson", first_text,
                          section="1.1.1", section_title="Switches")
            first, _ = page.save_to_course(courses, "networking")
            page.set_page("https://example.test/lesson?nonce=new", "Lesson", second_text,
                          section="1.1.2", section_title="Routers")
            second, replaced = page.save_to_course(courses, "networking")

            self.assertEqual(replaced, [])
            self.assertIn(first_text.strip(), first.read_text(encoding="utf-8"))
            self.assertIn(second_text.strip(), second.read_text(encoding="utf-8"))

            page.set_page("https://example.test/lesson", "Lesson", first_text,
                          section="1.1.1", section_title="Network Switches")
            renamed, replaced = page.save_to_course(courses, "networking")
            self.assertEqual(replaced, [first])
            self.assertFalse(first.exists())
            self.assertTrue(renamed.exists())
            self.assertTrue(second.exists())

            page.set_page("https://example.test/lesson", "Lesson", second_text)
            unnumbered, replaced = page.save_to_course(courses, "networking")
            self.assertEqual(replaced, [])
            self.assertTrue(renamed.exists())
            self.assertTrue(second.exists())
            self.assertTrue(unnumbered.exists())

    def test_numbered_lesson_replaces_unnumbered_copy(self):
        page.clear()
        self.addCleanup(page.clear)
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            text = "A lesson about computer networks. " * 10
            page.set_page("https://example.test/lesson?nonce=old", "Lesson", text)
            old, _ = page.save_to_course(courses, "networking")
            page.set_page("https://example.test/lesson?nonce=new", "Lesson", text,
                          section="1.1.1", section_title="Switches")
            saved, replaced = page.save_to_course(courses, "networking")
            self.assertEqual(replaced, [old])
            self.assertFalse(old.exists())
            self.assertTrue(saved.exists())

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

    def test_code_paragraphs_keep_significant_punctuation_and_case(self):
        first = "Check the configured network threshold before forwarding packets: value > 100."
        second = "Check the configured network threshold before forwarding packets: value < 100."
        third = "Check the configured network threshold before forwarding packets: Value < 100."
        expected = "\n\n".join([first, second, third])
        page.clear()
        self.addCleanup(page.clear)
        page.set_page("https://example.test/lesson", "Networking", "\n\n".join([first, first, second, third]))

        self.assertEqual(page.read()["text"], expected)
        with tempfile.TemporaryDirectory() as directory:
            saved, _ = page.save_to_course(Path(directory), "networking")
            self.assertIn(expected, saved.read_text(encoding="utf-8"))

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

    def test_focus_finds_exact_numbered_heading(self):
        page.clear()
        self.addCleanup(page.clear)
        filler = "Routing moves traffic across networks. " * 600
        text = ("See 1.1.2 for routing tables.\n\n"
                "## 1.1.20 Routing introduction\n\n" + filler + "\n\n"
                "## 1.1.2 Routing tables\n\nThe requested lesson explains routing tables.\n\n" + filler)
        page.set_page("https://example.test/lesson", "Networking", text)

        for focus in ("1.1.2", "walk me through 1.1.2 routing"):
            with self.subTest(focus=focus):
                result = page.read(focus)
                self.assertGreater(result["showing_from_char"], 0)
                self.assertIn("## 1.1.2 Routing tables", result["text"])
                self.assertNotIn("## 1.1.20 Routing introduction", result["text"])

    def test_focus_finds_numbered_section_without_heading_markup(self):
        page.clear()
        self.addCleanup(page.clear)
        text = ("Network devices exchange data. " * 600 + "\n\n"
                "1.2.3\nSubnetting\nThe requested lesson explains subnets.")
        page.set_page("https://example.test/lesson", "Networking", text)

        result = page.read("1.2.3")
        self.assertGreater(result["showing_from_char"], 0)
        self.assertIn("1.2.3\nSubnetting", result["text"])

    def test_numbered_focus_does_not_match_longer_section_numbers(self):
        page.clear()
        self.addCleanup(page.clear)
        text = ("Network devices exchange data. " * 600 + "\n\n"
                "## 1.1.20 Different section\n\n## 1.1.2.3 Another section")
        page.set_page("https://example.test/lesson", "Networking", text)

        result = page.read("1.1.2")
        self.assertEqual(result["showing_from_char"], 0)
        self.assertEqual(result["text"], text[:page.TOOL_WINDOW])

    def test_missing_numbered_section_falls_back_to_keywords(self):
        page.clear()
        self.addCleanup(page.clear)
        text = ("Network devices exchange data. " * 600 + "\n\n"
                "## Wireless networks\n\nWireless access points connect devices.")
        page.set_page("https://example.test/lesson", "Networking", text)

        result = page.read("1.2.3 wireless")
        self.assertGreater(result["showing_from_char"], 0)
        self.assertIn("## Wireless networks", result["text"])


if __name__ == "__main__":
    unittest.main()
