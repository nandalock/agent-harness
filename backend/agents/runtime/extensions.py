"""Host access to plugin-owned extensions; no process-level extension registry."""
from agent_platform_plugin_sdk import AGENT_EXTENSIONS, ServiceUnavailableError


def get_agent_extensions():
    from backend.plugin_host import get_plugin_host
    host = get_plugin_host()
    if host is None:
        raise ServiceUnavailableError(AGENT_EXTENSIONS.ref)
    return host.runtime.require(AGENT_EXTENSIONS)
