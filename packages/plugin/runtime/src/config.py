"""Read the declarative plugin document; parsing and validation belong here, not in the SDK."""
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from agent_platform_plugin_sdk import PluginConfiguration

from .errors import ConfigurationError


def parse_config(document: object, *, source: str | None = None) -> PluginConfiguration:
    """Validate an already-decoded JSON/YAML document."""
    try:
        return PluginConfiguration.model_validate(document)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid plugin configuration: {exc}", source=source) from exc


def parse_yaml(text: str, *, source: str = "<yaml>") -> PluginConfiguration:
    """Parse YAML text with the safe loader and validate the document shape."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML: {exc}", source=source) from exc
    if not isinstance(document, Mapping):
        raise ConfigurationError("configuration must be a YAML mapping", source=source)
    return parse_config(document, source=source)


def load_yaml_config(path: str | Path) -> PluginConfiguration:
    """Read a UTF-8 YAML file from disk and validate it."""
    source = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration: {exc}", source=source) from exc
    return parse_yaml(text, source=source)
