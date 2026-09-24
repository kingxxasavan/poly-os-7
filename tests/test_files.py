import tempfile
import unittest
from pathlib import Path

from polyos.core import ApiError
from polyos.files import P, FileSystem, check_name, kind_of, unique_path


class FileSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "Documents").mkdir()
        (self.home / "Documents" / "a.txt").write_text("hello")
        (self.home / ".secret").write_text("x")
        self.fs = FileSystem(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, listing):
        return sorted(e["name"] for e in listing["entries"])

    def test_list_hides_dotfiles_unless_asked(self):
        self.assertEqual(self.names(self.fs.list(str(self.home))), ["Documents"])
        self.assertEqual(self.names(self.fs.list(str(self.home), hidden=True)), [".secret", "Documents"])
        with self.assertRaises(ApiError):
            self.fs.list("relative/path")

    def test_kinds(self):
        self.assertEqual(kind_of(Path("x.png"), False)[1], "image")
        self.assertEqual(kind_of(Path("x.py"), False)[1], "code")
        self.assertEqual(kind_of(Path("x.pdf"), False)[1], "pdf")
        self.assertEqual(kind_of(Path("dir"), True)[1], "folder")
        self.assertEqual(kind_of(Path("x.unknownext"), False)[1], "file")

    def test_names_and_unique_paths(self):
        for bad in ("", "  ", ".", "..", "a/b", "x" * 300):
            with self.assertRaises(ApiError):
                check_name(bad)
        docs = self.home / "Documents"
        self.assertEqual(unique_path(docs, "a.txt").name, "a (2).txt")
        (docs / "b.tar.gz").write_text("")
        self.assertEqual(unique_path(docs, "b.tar.gz").name, "b (2).tar.gz")

    def test_mkdir_rename_and_conflicts(self):
        first = self.fs.mkdir(str(self.home), "New Folder")
        second = self.fs.mkdir(str(self.home), "New Folder")
        self.assertEqual(Path(second["path"]).name, "New Folder (2)")
        renamed = self.fs.rename(first["path"], "Projects")
        self.assertTrue(Path(renamed["path"]).is_dir())
        with self.assertRaises(ApiError):
            self.fs.rename(second["path"], "Projects")

    def test_copy_move_and_self_nesting(self):
        docs = str(self.home / "Documents")
        out = self.fs.mkdir(str(self.home), "Out")["path"]
        self.fs.copy([docs + "/a.txt"], out)
        self.fs.copy([docs + "/a.txt"], out)
        self.assertEqual(self.names(self.fs.list(out)), ["a (2).txt", "a.txt"])
        self.fs.move([docs], out)
        self.assertFalse((self.home / "Documents").exists())
        self.assertTrue((Path(out) / "Documents" / "a.txt").exists())
        with self.assertRaises(ApiError):
            self.fs.copy([out], out + "/Documents")

    def test_trash_restore_and_empty(self):
        target = self.home / "Documents" / "a.txt"
        self.assertEqual(self.fs.trash_paths([str(target)]), 1)
        self.assertFalse(target.exists())
        listing = self.fs.trash_list()
        self.assertEqual(len(listing["entries"]), 1)
        item = listing["entries"][0]
        self.assertEqual(item["origin"], P(target))
        self.assertEqual(self.fs.restore([item["trashName"]]), 1)
        self.assertEqual(target.read_text(), "hello")
        self.fs.trash_paths([str(target)])
        self.assertEqual(self.fs.trash_count(), 1)
        self.assertEqual(self.fs.empty_trash(), 1)
        self.assertEqual(self.fs.trash_count(), 0)
        with self.assertRaises(ApiError):
            self.fs.trash_paths([str(self.home)])

    def test_search(self):
        (self.home / "Documents" / "deep").mkdir()
        (self.home / "Documents" / "deep" / "Report A.txt").write_text("")
        found = self.fs.search(str(self.home), "report")
        self.assertEqual([e["name"] for e in found["entries"]], ["Report A.txt"])

    def test_places_include_existing_user_dirs(self):
        ids = [p["id"] for p in self.fs.places()["places"]]
        self.assertEqual(ids[:2], ["home", "documents"])


if __name__ == "__main__":
    unittest.main()
