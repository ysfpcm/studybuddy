import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from studybuddy import ingest, retrieval
from studybuddy.db import connect


class RetrievalTest(unittest.TestCase):
    def test_single_letter_terms_and_stop_words(self):
        self.assertEqual(retrieval._terms("How do I use C++?"), ["use", "c"])
        self.assertEqual(retrieval._terms("How do I?"), [])

    def check_single_letter_search(self, use_fts):
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            for course in ("programming", "other"):
                material = courses / course / "material"
                material.mkdir(parents=True)
                (material / "lesson.txt").write_text("C++ pointers store memory addresses.", encoding="utf-8")
            material = courses / "statistics" / "material"
            material.mkdir(parents=True)
            (material / "lesson.txt").write_text("R vectors hold statistical data.", encoding="utf-8")

            with closing(connect(":memory:")) as conn:
                if use_fts and not conn.fts:
                    self.skipTest("SQLite FTS5 is unavailable")
                conn.fts = use_fts
                for course in ("programming", "other", "statistics"):
                    ingest.index_course(conn, courses, course)
                hits = retrieval.search(conn, "programming", "C++")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["source"], "material/lesson.txt")
                self.assertIn("C++ pointers", hits[0]["text"])
                self.assertIn("R vectors", retrieval.search(conn, "statistics", "R")[0]["text"])
                self.assertEqual(retrieval.search(conn, "missing", "C++"), [])
                self.assertEqual(retrieval.search(conn, "programming", "How do I?"), [])

    def test_single_letter_search_with_fts(self):
        self.check_single_letter_search(use_fts=True)

    def test_single_letter_search_with_fallback(self):
        self.check_single_letter_search(use_fts=False)


if __name__ == "__main__":
    unittest.main()
