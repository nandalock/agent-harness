import tempfile
import unittest
from pathlib import Path

from agent_platform_plugin_runtime import (
    ConfigurationError,
    load_yaml_config,
    parse_config,
    parse_yaml,
)

VALID = """
version: 1
plugins:
  - id: tools
    name: test.tools
  - id: echo
    name: test.echo
    disabled: false
    config:
      prefix: "收到："
"""


class ConfigurationTests(unittest.TestCase):
    def test_yaml_document_becomes_a_validated_configuration(self):
        config = parse_yaml(VALID)
        self.assertEqual([entry.id for entry in config.plugins], ["tools", "echo"])
        self.assertEqual(config.plugins[1].config, {"prefix": "收到："})
        self.assertFalse(config.plugins[1].disabled)

    def test_yaml_file_is_read_as_utf8_and_reports_its_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.yaml"
            path.write_text(VALID, encoding="utf-8")
            config = load_yaml_config(path)
            self.assertEqual(config.plugins[1].name, "test.echo")

            broken = Path(directory) / "broken.yaml"
            broken.write_text("version: [1", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as raised:
                load_yaml_config(broken)
            self.assertEqual(raised.exception.code, "plugin_runtime.config")
            self.assertIn(str(broken), str(raised.exception))

    def test_missing_file_is_a_configuration_error(self):
        with self.assertRaises(ConfigurationError) as raised:
            load_yaml_config("definitely-not-here.yaml")
        self.assertEqual(raised.exception.code, "plugin_runtime.config")

    def test_non_mapping_documents_are_rejected(self):
        for text in ("", "[]", "- id: echo", "just a string"):
            with self.subTest(text=text), self.assertRaises(ConfigurationError):
                parse_yaml(text)

    def test_invalid_document_shape_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            parse_yaml("version: 2")
        with self.assertRaises(ConfigurationError):
            parse_config({"version": True})
        with self.assertRaises(ConfigurationError):
            parse_config({"version": 1, "plugins": [{"id": "Bad Id", "name": "test.echo"}]})
        with self.assertRaises(ConfigurationError):
            parse_config({"version": 1, "plugins": [
                {"id": "echo", "name": "test.echo", "config": {"callback": object()}}
            ]})

    def test_configuration_instance_is_accepted_directly(self):
        config = parse_config({"version": 1, "plugins": []})
        self.assertEqual(config.plugins, ())


if __name__ == "__main__":
    unittest.main()
