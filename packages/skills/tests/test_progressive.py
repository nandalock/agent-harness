"""Discovery never returns instructions; entry and reference reads are explicit."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_platform_skills import SkillRegistry, SkillScope, SkillSource, SkillError
from agent_platform_skills_filesystem import FilesystemSkillProvider, default_sources


class ProgressiveSkillTests(unittest.TestCase):
    def setUp(self):
        self.scope = SkillScope(1, "test", frozenset({"skill"}))
        self.registry = SkillRegistry()
        with patch.dict("os.environ", {"SKILL_SOURCES": "[]"}):
            self.sources = default_sources()
        self.registry.register_provider(FilesystemSkillProvider(self.sources))

    def test_catalog_stops_at_frontmatter_without_reading_or_hashing_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "demo.md").write_text("---\nname: demo\ndescription: Summary\n---\nPRIVATE BODY", encoding="utf-8")
            provider = FilesystemSkillProvider([SkillSource("local", root)])
            real_open = Path.open

            @contextmanager
            def header_only(path, *args, **kwargs):
                with real_open(path, *args, **kwargs) as reader:
                    class HeaderReader:
                        def readline(self):
                            return reader.readline()
                        def __iter__(self):
                            return self
                        def __next__(self):
                            return next(reader)
                        def read(self):
                            raise AssertionError("Discovery tried to read the body")
                    yield HeaderReader()

            with patch.object(Path, "open", header_only), patch("agent_platform_skills.document.hashlib.sha256", side_effect=AssertionError("Discovery hashed the body")):
                entries = provider.list(self.scope)
            self.assertEqual([s.name for s in entries], ["demo"])
            self.assertFalse(hasattr(entries[0], "content"))
            self.assertFalse(hasattr(entries[0], "content_hash"))

    def test_overleaf_entry_does_not_open_references_and_resource_reads_only_requested_file(self):
        opened = []
        real_open = Path.open

        def track(path, *args, **kwargs):
            opened.append(path.resolve())
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", track):
            entries = self.registry.list(self.scope)
            self.assertEqual([e.name for e in entries], ["overleaf", "skill-installer"])
            self.assertTrue(all(not hasattr(e, "content") for e in entries))
            loaded = self.registry.load("overleaf", self.scope)
            self.assertIn("references/comments.md", loaded["text"])
            self.assertIn("当前声明的工具尚未就绪", loaded["text"])
            self.assertFalse(any("references" in path.parts for path in opened))
            opened.clear()
            resource = self.registry.load("overleaf", self.scope, "references/comments.md")
        refs = [path.name for path in opened if "references" in path.parts]
        self.assertEqual(refs, ["comments.md"])
        self.assertIn("Overleaf comments", resource["text"])
        self.assertNotIn("references/compilation.md", resource["text"])

    def test_references_cannot_escape_entry_directory_or_bypass_disabled_binding(self):
        with self.assertRaisesRegex(SkillError, "技能资源路径"):
            self.registry.load("overleaf", self.scope, "../../../../NOTICE.md")
        with self.assertRaisesRegex(SkillError, "未启用"):
            self.registry.load("overleaf", replace(self.scope, enabled_names=()), "references/comments.md")
        self.assertIsNone(self.registry.get("comments", self.scope))

    def test_all_legacy_names_keep_saved_bindings_working_with_one_canonical_entry(self):
        source = next(source for source in self.sources if source.name == "overleaf-rt")
        for name in (*source.aliases["overleaf"], "@package/overleaf-rt", "overleaf-rt:overleaf"):
            with self.subTest(name=name):
                scope = replace(self.scope, enabled_names=(name,))
                self.assertEqual([s.key for s in self.registry.list(scope)], ["overleaf-rt:overleaf"])
                self.assertEqual(self.registry.get("overleaf", scope).name, "overleaf")


if __name__ == "__main__":
    unittest.main()
