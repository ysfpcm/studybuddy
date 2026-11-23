import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from studybuddy import ingest, retrieval
from studybuddy.db import connect


class RetrievalTest(unittest.TestCase):
    def test_split_preserves_whitespace_in_chunks(self):
        source = '    if ready:\n\tprint("two  spaces")\n\n\n    return result\n' * 3
        chunks = ingest.split(source, size=50, overlap=10)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 50 for chunk in chunks))
        self.assertEqual(chunks[0] + "".join(chunk[10:] for chunk in chunks[1:]), source)
        self.assertEqual(ingest.split(" \n\t"), [])

    def test_reindex_repairs_legacy_whitespace_and_then_skips_unchanged_files(self):
        source = 'def route():\n    message = "two  spaces"\n    if message:\n        return message'
        for use_fts in (False, True):
            with self.subTest(use_fts=use_fts), tempfile.TemporaryDirectory() as directory:
                courses = Path(directory)
                material = courses / "programming" / "material"
                material.mkdir(parents=True)
                lesson = material / "lesson.py"
                lesson.write_text(source, encoding="utf-8")
                with closing(connect(":memory:")) as conn:
                    if use_fts and not conn.fts:
                        continue
                    conn.fts = use_fts
                    with patch.object(ingest, "split", return_value=["def route():\n message = two spaces"]):
                        ingest.index_course(conn, courses, "programming")
                    conn.execute("UPDATE files SET sha=?", (ingest._sha(lesson),))
                    conn.commit()

                    stats = ingest.index_course(conn, courses, "programming")
                    self.assertEqual(stats["updated"], 1)
                    self.assertEqual(retrieval.search(conn, "programming", "route")[0]["text"], source)
                    self.assertEqual(ingest.index_course(conn, courses, "programming")["skipped"], 1)

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

    def test_single_letter_search_ignores_embedded_letters(self):
        with tempfile.TemporaryDirectory() as directory:
            courses = Path(directory)
            material = courses / "programming" / "material"
            material.mkdir(parents=True)
            for number in range(6):
                (material / f"a-network-{number}.txt").write_text(
                    "Routers forward packets across networks.", encoding="utf-8")
            (material / "z-cpp.txt").write_text("C++ pointers store memory addresses.", encoding="utf-8")
            (material / "z-c.txt").write_text("The language is C.", encoding="utf-8")
            (material / "z-r.txt").write_text("R vectors hold statistical data.", encoding="utf-8")

            with closing(connect(":memory:")) as conn:
                ingest.index_course(conn, courses, "programming")
                fts_available = conn.fts
                for use_fts in (False, True):
                    if use_fts and not fts_available:
                        continue
                    with self.subTest(use_fts=use_fts):
                        conn.fts = use_fts
                        self.assertEqual({hit["source"] for hit in retrieval.search(conn, "programming", "C++")},
                                         {"material/z-cpp.txt", "material/z-c.txt"})
                        self.assertEqual([hit["source"] for hit in retrieval.search(conn, "programming", "R")],
                                         ["material/z-r.txt"])
                        self.assertEqual(retrieval.search(conn, "programming", "C++ pointers", k=1)[0]["source"],
                                         "material/z-cpp.txt")


if __name__ == "__main__":
    unittest.main()
