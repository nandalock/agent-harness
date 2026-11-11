import tempfile
import unittest

from pydantic import ValidationError
from pathlib import Path

from minidsh_cordis_plugin_include import (
    ConfigurationError,
    PluginConfiguration,
    EntryOptions,
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


class ConfigurationModelTests(unittest.TestCase):
    def test_yaml_shaped_document_round_trips_without_losing_instance_identity(self):
        config = PluginConfiguration.model_validate({"version": 1, "plugins": [
            {"id": "tools", "name": "agent-platform.tools-default", "config": {}},
            {"id": "echo", "name": "example.echo", "disabled": True, "config": {"prefix": "收到："}},
        ]})
        self.assertEqual(config.plugins[0].id, "tools")
        self.assertEqual(config.plugins[0].name, "agent-platform.tools-default")
        self.assertEqual(PluginConfiguration.model_validate_json(config.model_dump_json()), config)

    def test_instances_are_unique_but_implementation_names_can_repeat(self):
        entries = [{"id": "first", "name": "example.echo"}, {"id": "second", "name": "example.echo"}]
        self.assertEqual(len(PluginConfiguration(plugins=entries).plugins), 2)
        entries[1]["id"] = "first"
        with self.assertRaises(ValidationError):
            PluginConfiguration(plugins=entries)

    def test_invalid_or_ambiguous_configuration_is_rejected(self):
        for value in ({"id": "bad id", "name": "example.echo"},
                      {"id": "echo", "name": "backend.module:Plugin"},
                      {"id": "echo", "name": "example.echo", "disabled": "false"},
                      {"id": "echo", "name": "example.echo", "extra": True},
                      {"id": "echo", "name": "example.echo", "config": {"callback": object()}},
                      {"id": "echo", "name": "example.echo", "config": {"number": float("nan")}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                EntryOptions.model_validate(value)
        for version in (2, True, "1"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                PluginConfiguration(version=version)

    def test_plugin_config_defaults_are_isolated(self):
        entry = EntryOptions(id="one", name="example.one")
        entry.config["changed"] = True
        self.assertEqual(EntryOptions(id="two", name="example.two").config, {})


if __name__ == "__main__":
    unittest.main()
