"""Read the declarative plugin document; parsing and validation belong here, not in the SDK."""
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import PluginConfiguration

from .errors import ConfigurationError


def parse_config(document: object, *, source: str | None = None) -> PluginConfiguration:
    """Validate an already-decoded JSON/YAML document."""
    try:
        return PluginConfiguration.model_validate(document)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid plugin configuration: {exc}", source=source) from exc


def parse_yaml(text: str, *, source: str = "<yaml>") -> PluginConfiguration:
    """Parse YAML text with the safe loader and validate the document shape."""
    document = _decode_yaml(text, source)
    if not isinstance(document, Mapping):
        raise ConfigurationError("configuration must be a YAML mapping", source=source)
    return parse_config(document, source=source)


def _decode_yaml(text: str, source: str) -> object:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML: {exc}", source=source) from exc


def load_yaml_config(path: str | Path) -> PluginConfiguration:
    """Read a UTF-8 YAML file from disk and validate it."""
    return parse_yaml(_read_yaml(path), source=str(path))


def load_yaml_patch(path: str | Path) -> PluginConfiguration:
    """Read an overlay mapping or a list of per-instance patches."""
    source = str(path)
    document = _decode_yaml(_read_yaml(path), source)
    if isinstance(document, list):
        document = {"patches": document}
    return parse_config(document, source=source)


def _read_yaml(path: str | Path) -> str:
    source = str(path)
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration: {exc}", source=source) from exc
