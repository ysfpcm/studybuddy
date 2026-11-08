import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studybuddy import ingest, retrieval
from studybuddy.db import connect


class IndexingErrorsTest(unittest.TestCase):
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
