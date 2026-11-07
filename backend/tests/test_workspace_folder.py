"""Workspace folder creation by name (the showDirectoryPicker selection landing point)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from agent_platform_http_api.routes import workspace


class BrowseLocalTests(unittest.TestCase):
    def test_lists_only_directories_with_absolute_paths_and_crumbs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "alpha").mkdir()
            (root / ".hidden").mkdir()
            (root / "note.txt").write_text("x", encoding="utf-8")
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
                listing = workspace._browse_local(str(root))
            names = [entry["name"] for entry in listing["entries"]]
            self.assertEqual(names, [".hidden", "alpha"])
            self.assertEqual(listing["mode"], "local")
            self.assertEqual([c["label"] for c in listing["crumbs"]][-1], str(root))
            self.assertTrue(all(Path(e["path"]).is_absolute() for e in listing["entries"]))
            self.assertIsNone(listing["folder"])

    def test_mkdir_creates_child_and_rejects_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
                result = workspace.api_browse_mkdir({"path": str(root), "name": "child"})
                self.assertTrue((root / "child").is_dir())
                self.assertEqual(result["entry"]["name"], "child")
                with self.assertRaises(HTTPException) as error:
                    workspace.api_browse_mkdir({"path": str(root), "name": "child"})
                self.assertEqual(error.exception.status_code, 409)

    def test_mkdir_rejects_path_separators(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
                with self.assertRaises(HTTPException) as error:
                    workspace.api_browse_mkdir({"path": str(root), "name": "../escape"})
                self.assertEqual(error.exception.status_code, 400)
