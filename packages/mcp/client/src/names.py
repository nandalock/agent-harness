"""Deterministic model-facing names for MCP tools.

Tool names must be valid function names. When a raw name needs normalization or
truncation, a hash suffix keeps distinct MCP identities from collapsing.
"""
import hashlib
import re

_MAX_LENGTH = 64
_INVALID = re.compile(r"[^A-Za-z0-9_-]")


def public_tool_name(prefix: str, raw_name: str) -> str:
    joined = f"{prefix}{raw_name}"
    normalized = _INVALID.sub("_", joined)
    if normalized == joined and len(normalized) <= _MAX_LENGTH:
        return normalized
    digest = hashlib.sha256(f"{prefix}\0{raw_name}".encode("utf-8")).hexdigest()[:12]
    head = normalized[: _MAX_LENGTH - len(digest) - 1]
    return f"{head}_{digest}"
