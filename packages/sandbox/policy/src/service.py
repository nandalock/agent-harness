"""Bind the provider to a Session's sandbox-mode projection."""
from agent_platform_sandbox.runtime import session_policy
from agent_platform_session_projection import project_sandbox_mode


class SandboxPolicyService:
    def __init__(self, provider) -> None:
        self._provider = provider

    def policy(self, session):
        header = session.header
        policy = session_policy(
            self._provider,
            header.id,
            header.cwd,
            session_override=project_sandbox_mode(session.events),
        )
        if policy is not None and header.cwd is None:
            header.cwd = policy.workspace_root
        return policy
