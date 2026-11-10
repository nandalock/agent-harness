"""Session recovery/checkpoint plugin with runtime-scoped dependencies."""
from agent_platform_plugin_sdk import SdkModel

from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE
from agent_platform_session_title import SESSION_TITLE

from .recovery import prepare_session, recovery_status
from .services import SESSION_RECOVERY
from minidsh_cordis import Context, Plugin


class RecoveryConfig(SdkModel):
    pass


class SessionRecoveryService:
    """Recovery entry point bound to one runtime's store/persistence/title."""

    def __init__(self, store, persistence, title=None) -> None:
        self._store = store
        self._persistence = persistence
        self._title = title

    def prepare(self, session_id, **options):
        return prepare_session(
            store=self._store,
            persistence=self._persistence,
            title=self._title,
            session_id=session_id,
            **options,
        )

    @staticmethod
    def status(events, *, busy=False, last_durable_seq=None) -> dict:
        return recovery_status(events, busy=busy, last_durable_seq=last_durable_seq)


class SessionRecoveryPlugin(Plugin[RecoveryConfig]):
    name = "agent-platform.session-recovery"
    version = "0.1.0"
    provides = (SESSION_RECOVERY,)
    requires = (SESSIONS, SESSION_PERSISTENCE)
    optional = (SESSION_TITLE,)
    config_model = RecoveryConfig

    async def setup(self, ctx: Context, config: RecoveryConfig) -> None:
        ctx.provide(
            SESSION_RECOVERY,
            SessionRecoveryService(
                ctx.require(SESSIONS),
                ctx.require(SESSION_PERSISTENCE),
                ctx.get(SESSION_TITLE),
            ),
        )
