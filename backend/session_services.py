"""Resolve session services from the active plugin runtime.

This is the legacy HTTP layer's accessor. Runtime/plugin code receives the same
instances through ``ctx.require``; no global fallback instance exists.
"""
from agent_platform_plugin_sdk import ServiceUnavailableError
from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE
from agent_platform_session_recovery import SESSION_RECOVERY
from agent_platform_session_title import SESSION_TITLE


def _require(key):
    from backend.plugin_host import get_plugin_host

    host = get_plugin_host()
    if host is None:
        raise ServiceUnavailableError(key.ref)
    return host.runtime.require(key)


def store():
    return _require(SESSIONS)


def persistence():
    return _require(SESSION_PERSISTENCE)


def recovery():
    return _require(SESSION_RECOVERY)


def title():
    return _require(SESSION_TITLE)
