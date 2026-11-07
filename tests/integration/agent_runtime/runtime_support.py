"""Explicit runtime capabilities for plugin-runtime tests (no host fallbacks)."""
from types import SimpleNamespace

from agent_platform_agent_runtime import AgentExtensionRegistry, RuntimeService
from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import LLM, ModelConfig
from agent_platform_plugin_sdk import AGENTS
from agent_platform_sandbox.services import AGENT_SANDBOX
from agent_platform_session import SESSIONS, SessionStore
from agent_platform_session_persistence import NoopPersistence, SESSION_PERSISTENCE
from agent_platform_session_recovery import SESSION_RECOVERY, SessionRecoveryService
from agent_platform_session_title import SESSION_TITLE, SessionTitleService
from agent_platform_system_prompt import (
    RUNTIME_PROMPTS,
    SystemPrompt,
    SystemPromptService,
    register_platform_sections,
    unified_tool_provider,
)


class _NoTools:
    async def descriptors_for_agent(self, tenant_id, agent_key):
        return []

    def is_sandbox_tool(self, name):
        return False


class _StaticLlm:
    def __init__(self, client, model=None):
        self._client = client
        self._model = model or ModelConfig("fake", "m", "http://fake", "k", "provider")

    def resolve(self, config):
        return self._model

    def create_client(self, model, *, max_llm_retries):
        return self._client


class _NoSandboxPolicy:
    def policy(self, session):
        return None


class _Context:
    def __init__(self, services):
        self._services = services

    def require(self, key):
        return self._services[key.ref]

    def get(self, key):
        return self._services.get(key.ref)


def runtime_service(runs, config, *, llm=None, persistence=None, store=None):
    async def get_config(key):
        return config(key)

    store = store or SessionStore()
    persistence = persistence or NoopPersistence()
    fake_llm = llm if hasattr(llm, "resolve") else _StaticLlm(llm)
    title = SessionTitleService(store, persistence, fake_llm)
    recovery = SessionRecoveryService(store, persistence, title)
    sp = SystemPrompt()
    register_platform_sections(sp, unified_tool_provider(_NoTools()))
    services = {
        AGENTS.ref: SimpleNamespace(get_config=get_config),
        AGENT_RUNS.ref: runs,
        RUNTIME_PROMPTS.ref: SystemPromptService(sp),
        LLM.ref: fake_llm,
        AGENT_SANDBOX.ref: _NoSandboxPolicy(),
        SESSIONS.ref: store,
        SESSION_PERSISTENCE.ref: persistence,
        SESSION_RECOVERY.ref: recovery,
        SESSION_TITLE.ref: title,
    }
    service = RuntimeService(_Context(services), AgentExtensionRegistry())
    service.services = services
    return service
