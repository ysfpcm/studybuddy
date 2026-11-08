import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studybuddy import ingest, retrieval
from studybuddy.db import connect


class IndexingErrorsTest(unittest.TestCase):
    def test_unscannable_directory_preserves_index_until_retry(self):
        for use_fts in (True, False):
            with self.subTest(use_fts=use_fts), tempfile.TemporaryDirectory() as temp:
                courses = Path(temp) / "courses"
                material = courses / "net101" / "material"
                material.mkdir(parents=True)
                lesson = material / "lesson.txt"
                lesson.write_text("routers forward packets", encoding="utf-8")
                readable = courses / "net101" / "readable.txt"
                readable.write_text("original content", encoding="utf-8")
                conn = connect(":memory:")
                self.addCleanup(conn.close)
                if use_fts and not conn.fts:
                    continue
                conn.fts = use_fts
                ingest.index_course(conn, courses, "net101")
                readable.write_text("replacement content", encoding="utf-8")

                original_scandir = os.scandir

                def blocked_scandir(path):
                    if Path(path) == material:
                        raise PermissionError(13, "Access denied", str(path))
                    return original_scandir(path)

                with patch("os.scandir", side_effect=blocked_scandir):
                    stats = ingest.index_course(conn, courses, "net101")
                self.assertEqual(stats["removed"], 0)
                self.assertTrue(stats["errors"])
                self.assertIn("Access denied", stats["errors"][0])
                self.assertTrue(retrieval.search(conn, "net101", "routers"))
                self.assertTrue(retrieval.search(conn, "net101", "original"))
                self.assertFalse(retrieval.search(conn, "net101", "replacement"))

                lesson.unlink()
                retry = ingest.index_course(conn, courses, "net101")
                self.assertEqual(retry["removed"], 1)
                self.assertEqual(retry["updated"], 1)
                self.assertFalse(retry["errors"])
                self.assertFalse(retrieval.search(conn, "net101", "routers"))
                self.assertTrue(retrieval.search(conn, "net101", "replacement"))

    def test_missing_course_preserves_index(self):
        with tempfile.TemporaryDirectory() as temp:
            courses = Path(temp) / "courses"
            root = courses / "net101"
            root.mkdir(parents=True)
            (root / "lesson.txt").write_text("routers forward packets", encoding="utf-8")
            conn = connect(":memory:")
            self.addCleanup(conn.close)
            ingest.index_course(conn, courses, "net101")
            root.rename(courses / "offline")

            stats = ingest.index_course(conn, courses, "net101")
            self.assertEqual(stats["removed"], 0)
            self.assertTrue(stats["errors"])
            self.assertTrue(retrieval.search(conn, "net101", "routers"))

    def test_unreadable_files_do_not_abort_indexing(self):
        for use_fts in (True, False):
            with self.subTest(use_fts=use_fts), tempfile.TemporaryDirectory() as temp:
                courses = Path(temp) / "courses"
                material = courses / "net101" / "material"
                material.mkdir(parents=True)
                existing = material / "a-existing.txt"
                existing.write_text("original indexed lesson", encoding="utf-8")
                conn = connect(":memory:")
                self.addCleanup(conn.close)
                if use_fts and not conn.fts:
                    continue
                conn.fts = use_fts
                ingest.index_course(conn, courses, "net101")

                existing.write_text("replacement indexed lesson", encoding="utf-8")
                (material / "b-new.txt").write_text("new blocked lesson", encoding="utf-8")
                (material / "c-readable.txt").write_text("readable lesson", encoding="utf-8")
                original_sha = ingest._sha

                def sha_with_locked_files(path):
                    if path.name in {"a-existing.txt", "b-new.txt"}:
                        raise PermissionError("locked file")
                    return original_sha(path)

                with patch.object(ingest, "_sha", side_effect=sha_with_locked_files):
                    stats = ingest.index_course(conn, courses, "net101")

                self.assertEqual(stats["added"], 1)
                self.assertEqual(stats["updated"], 0)
                self.assertEqual(stats["errors"], [
                    "material/a-existing.txt: locked file",
                    "material/b-new.txt: locked file",
                ])
                self.assertTrue(retrieval.search(conn, "net101", "original"))
                self.assertFalse(retrieval.search(conn, "net101", "replacement"))
                self.assertTrue(retrieval.search(conn, "net101", "readable"))

                retry = ingest.index_course(conn, courses, "net101")
                self.assertEqual((retry["added"], retry["updated"], retry["errors"]), (1, 1, []))
                self.assertFalse(retrieval.search(conn, "net101", "original"))
                self.assertTrue(retrieval.search(conn, "net101", "replacement"))
                self.assertTrue(retrieval.search(conn, "net101", "blocked"))


if __name__ == "__main__":
    unittest.main()
