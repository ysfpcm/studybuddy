import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from studybuddy import ingest, practice
from studybuddy.db import connect


class PracticeLessonTest(unittest.TestCase):
    def test_short_saved_pages_report_insufficient_text(self):
        with tempfile.TemporaryDirectory() as directory, closing(connect(":memory:")) as conn:
            courses = Path(directory)
            pages = courses / "net101" / "material" / "pages"
            pages.mkdir(parents=True)
            for name in ("lesson.md", "1-1-1-lesson.md"):
                (pages / name).write_text("Original lesson text. " * 10, encoding="utf-8")
            ingest.index_course(conn, courses, "net101")

            with patch.object(practice.brain, "response_text", side_effect=AssertionError("unexpected model call")):
                for name in ("lesson.md", "1-1-1-lesson.md"):
                    for text in ("", "\n\n", "short lesson"):
                        for kind in ("mini", "test"):
                            with self.subTest(name=name, text=text, kind=kind):
                                (pages / name).write_text(text, encoding="utf-8")
                                with self.assertRaisesRegex(practice.PracticeError, "Not enough lesson text"):
                                    practice.start(conn, None, courses, "net101", f"material/pages/{name}",
                                                   "Networking", kind=kind)

    def test_numbered_lesson_still_creates_concepts(self):
        with tempfile.TemporaryDirectory() as directory, closing(connect(":memory:")) as conn:
            courses = Path(directory)
            pages = courses / "net101" / "material" / "pages"
            pages.mkdir(parents=True)
            (pages / "lesson.md").write_text("# 1.1.1 Networking\n\n" + "Routers forward packets. " * 10,
                                              encoding="utf-8")
            concepts = [{"name": f"Concept {number}", "objective": "Explain the concept"}
                        for number in range(3)]
            with patch.object(practice.brain, "response_text", return_value=("response", {})) as response, \
                 patch.object(practice.brain, "parse_concepts", return_value=concepts), \
                 patch.object(practice.spend, "charge_background", return_value=0):
                practice._ensure_lesson_concepts(conn, None, courses, "net101", "material/pages/lesson.md")
            self.assertEqual(response.call_count, 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM concepts WHERE course=?", ("net101",)).fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
