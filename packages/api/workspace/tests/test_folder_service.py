"""Workspace folder creation tests for the controller service."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform_api_workspace.service import (
    WorkspaceService,
    _BrowseRoot,
    _local_project_path,
)
from agent_platform_rpc_gateway import RpcError

import agent_platform_api_workspace.service as workspace


def _ensure(name: str):
    return asyncio.run(WorkspaceService(None, None, None).ensure_folder(name))


class FolderByNameInDeploymentRootTests(unittest.TestCase):
    def test_creates_then_reopens_the_same_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {"SANDBOX_WORKSPACE_ROOT": str(root)}, clear=False), \
                    patch.object(workspace, "_browse_roots", return_value=[]):
                first = _ensure("proj")
                second = _ensure("proj")
            self.assertEqual(first["folder"], "proj")
            self.assertTrue(first["writable"])
            self.assertTrue((root / "proj").is_dir())
            self.assertEqual(second["path"], first["path"])

    def test_rejects_names_with_path_separators(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {"SANDBOX_WORKSPACE_ROOT": str(root)}, clear=False), \
                    patch.object(workspace, "_browse_roots", return_value=[]):
                for name in ("../escape", "a/b", "a\\b", "", ".", ".."):
                    with self.assertRaises(RpcError) as error:
                        _ensure(name)
                    self.assertEqual(error.exception.code, "workspace/invalid-name")

    def test_refuses_to_replace_a_file_with_the_same_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "proj").write_text("not a directory", encoding="utf-8")
            with patch.dict(os.environ, {"SANDBOX_WORKSPACE_ROOT": str(root)}, clear=False), \
                    patch.object(workspace, "_browse_roots", return_value=[]):
                with self.assertRaises(RpcError) as error:
                    _ensure("proj")
            self.assertEqual(error.exception.code, "workspace/name-conflict")


class FolderByNameInBrowseRootsTests(unittest.TestCase):
    def test_write_root_wins_and_value_is_translated(self):
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory).resolve()
            host = "D:/jk/Nexus"
            root = _BrowseRoot("Nexus", host, container, True)
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "docker"}, clear=True), \
                    patch.object(workspace, "_browse_roots", return_value=[root]), \
                    patch.object(workspace, "_write_roots", return_value=(host,)):
                choice = _ensure("proj")
            self.assertTrue((container / "proj").is_dir())
            self.assertEqual(choice["folder"], "Nexus/proj")
            self.assertEqual(choice["host_path"], "D:/jk/Nexus/proj")
            self.assertTrue(choice["writable"])

    def test_local_backend_creates_in_host_path_not_container_path(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Path(directory).resolve()
            container = host / "unmounted-container-path"
            root = _BrowseRoot("work", str(host), container, True)
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True), \
                    patch.object(workspace, "_browse_roots", return_value=[root]), \
                    patch.object(workspace, "_write_roots", return_value=(str(host),)):
                choice = _ensure("proj")
            self.assertTrue((host / "proj").is_dir())
            self.assertFalse(container.exists())
            self.assertEqual(choice["folder"], "work/proj")

    def test_unusable_write_root_falls_back_to_the_next_root(self):
        with tempfile.TemporaryDirectory() as directory:
            read_container = Path(directory).resolve()
            missing_write = read_container / "does-not-exist"
            write_root = _BrowseRoot("write", "D:/jk/write", missing_write, True)
            read_root = _BrowseRoot("read", "D:/jk/read", read_container, False)
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "docker"}, clear=True), \
                    patch.object(workspace, "_browse_roots", return_value=[write_root, read_root]), \
                    patch.object(workspace, "_write_roots", return_value=("D:/jk/write",)):
                choice = _ensure("proj")
            self.assertTrue((read_container / "proj").is_dir())
            self.assertEqual(choice["folder"], "read/proj")
            self.assertFalse(choice["writable"])

    def test_existing_file_in_root_is_reported_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory).resolve()
            (container / "proj").write_text("file", encoding="utf-8")
            root = _BrowseRoot("work", "D:/jk/work", container, True)
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "docker"}, clear=True), \
                    patch.object(workspace, "_browse_roots", return_value=[root]):
                with self.assertRaises(RpcError) as error:
                    _ensure("proj")
            self.assertEqual(error.exception.code, "workspace/name-conflict")


class LocalProjectPathTests(unittest.TestCase):
    def test_accepts_absolute_directory_and_creates_missing_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "my-project"
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
                resolved = _local_project_path(str(target))
            self.assertEqual(resolved, target)
            self.assertTrue(target.is_dir())

    def test_rejects_relative_path_and_non_local_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "p"
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
                with self.assertRaises(RpcError) as error:
                    _local_project_path("relative/path")
                self.assertEqual(error.exception.code, "workspace/invalid-path")
            with patch.dict(os.environ, {"SANDBOX_BACKEND": "docker"}, clear=True):
                with self.assertRaises(RpcError) as error:
                    _local_project_path(str(target))
                self.assertEqual(error.exception.code, "workspace/unsupported")

    def test_rejects_filesystem_root(self):
        with patch.dict(os.environ, {"SANDBOX_BACKEND": "local"}, clear=True):
            with self.assertRaises(RpcError) as error:
                _local_project_path(str(Path.cwd().anchor))
            self.assertEqual(error.exception.code, "workspace/invalid-path")


if __name__ == "__main__":
    unittest.main()
