from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage.files import StoragePathError, write_bytes_under


class StorageFilesTests(unittest.TestCase):
    def test_write_bytes_under_writes_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_bytes_under(Path(tmpdir), "nested/file.bin", b"content")

            self.assertEqual(path.read_bytes(), b"content")
            self.assertEqual(path.parent.name, "nested")

    def test_write_bytes_under_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(StoragePathError):
                write_bytes_under(Path(tmpdir), "../outside.bin", b"content")


if __name__ == "__main__":
    unittest.main()
