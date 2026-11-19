"""The shared server caches go by their Piwigo names, and old copies follow.

AlbumHierarchy.json and FileDict.json became "Piwigo AlbumHierarchy.json"
and "Piwigo FileIndex.json" in 2026-11, to sort with Piwigo Credentials.json.
A copy under its old name -- in a program's folder, beside an exe, on the
show computer -- is renamed the first time it is looked for.  Losing the file
index silently would cost a walk of every album on the server to rebuild.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import AlbumHierarchy as ah                                    # noqa: E402


class SharedNames(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.saved = ah.PARAMS_FILE
        ah.PARAMS_FILE = self.dir / "SomeProgram Params.json"

    def tearDown(self):
        ah.PARAMS_FILE = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def files(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_the_names(self):
        self.assertEqual(ah._album_hierarchy_file(), self.dir / "Piwigo AlbumHierarchy.json")
        self.assertEqual(ah._file_index_file(), self.dir / "Piwigo FileIndex.json")

    def test_an_old_copy_is_renamed_with_what_it_holds(self):
        (self.dir / "FileDict.json").write_text('{"a.jpg": []}', encoding="utf-8")
        (self.dir / "AlbumHierarchy.json").write_text('{"albums": []}', encoding="utf-8")
        self.assertEqual(ah._file_index_file().read_text(encoding="utf-8"), '{"a.jpg": []}')
        self.assertEqual(ah._album_hierarchy_file().read_text(encoding="utf-8"), '{"albums": []}')
        self.assertEqual(self.files(), ["Piwigo AlbumHierarchy.json", "Piwigo FileIndex.json"])

    def test_the_new_one_wins_if_both_are_there(self):
        (self.dir / "FileDict.json").write_text("old", encoding="utf-8")
        (self.dir / "Piwigo FileIndex.json").write_text("new", encoding="utf-8")
        self.assertEqual(ah._file_index_file().read_text(encoding="utf-8"), "new")
        self.assertEqual(self.files(), ["FileDict.json", "Piwigo FileIndex.json"])

    def test_nothing_there_is_not_an_error(self):
        self.assertFalse(ah._file_index_file().exists())
        self.assertEqual(self.files(), [])


if __name__ == "__main__":
    unittest.main()
