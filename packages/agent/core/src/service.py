"""One factory and one active-run table per plugin runtime."""
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceClosedError, ServiceKey, ServiceUnavailableError

EventSink = Callable[[dict], Awaitable[None]]
NEXT_STEP = "next-step"
NEXT_TURN = "next-turn"


class RunConflict(RuntimeError):
    def __init__(self, session_id: str):
        super().__init__(f"会话 {session_id} 上已有一轮正在运行")
        self.session_id = session_id


class RunHandle(Protocol):
    def followup(self, text: str) -> str: ...
    def steer(self, text: str) -> str: ...
    def inject(self, text: str) -> str: ...
    def cancel(self, cause: str = ..., *, keep_inbox: bool = ...) -> None: ...


class Agent(RunHandle, Protocol):
    async def when_idle(self) -> None: ...
    def answer_text(self) -> str: ...


class AgentFactory(Protocol):
    def create(self, **options: Any) -> Agent: ...


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}

    def register(self, session_id: str, handle: RunHandle) -> None:
        if session_id in self._runs:
            raise RunConflict(session_id)
        self._runs[session_id] = handle

    def get(self, session_id: str) -> RunHandle | None:
        return self._runs.get(session_id)

    def unregister(self, session_id: str) -> None:
        self._runs.pop(session_id, None)

    def active(self) -> list[str]:
        return list(self._runs)


async def _drain(task: asyncio.Task) -> Any:
    """Finish cleanup even if its caller receives another cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError()
    return result


class _OwnedAgent:
    """Revokes input before stopping the underlying driver during unload."""
    def __init__(self, agent: Agent, registration: "_FactoryRegistration"):
        self.agent = agent
        self.registration = registration
        self.accepting = True

    def _send(self, method: str, text: str) -> str:
        service = self.registration.service
        if not self.accepting or service._closed or service._factory is not self.registration:
            raise ServiceClosedError("agent run is disposed")
        return getattr(self.agent, method)(text)

    def followup(self, text: str) -> str:
        return self._send("followup", text)

    def steer(self, text: str) -> str:
        return self._send("steer", text)

    def inject(self, text: str) -> str:
        return self._send("inject", text)

    def cancel(self, cause: str = "cancelled", *, keep_inbox: bool = False) -> None:
        self.agent.cancel(cause, keep_inbox=keep_inbox)

    def revoke(self, cause: str) -> None:
        self.accepting = False
        self.cancel(cause)

    async def when_idle(self) -> None:
        await self.agent.when_idle()

    def answer_text(self) -> str:
        return self.agent.answer_text()


class _FactoryRegistration:
    def __init__(self, service: "AgentService", factory: AgentFactory):
        self.service = service
        self.factory = factory
        self.closing: asyncio.Task | None = None

    async def aclose(self) -> None:
        if self.closing is None:
            if self.service._factory is self:
                self.service._factory = None  # Revoke creation before the first await.
            self.closing = asyncio.create_task(self.service._stop(self))
        await _drain(self.closing)


class AgentService(RunRegistry):
    """Scopes keep the session occupied through host checkpoint/listener cleanup."""
    def __init__(self) -> None:
        super().__init__()
        self._factory: _FactoryRegistration | None = None
        self._scopes: dict[str, tuple[_FactoryRegistration, _OwnedAgent, asyncio.Event]] = {}
        self._closed = False

    def register_factory(self, factory: AgentFactory) -> _FactoryRegistration:
        if self._closed:
            raise ServiceClosedError("agent service is closed")
        if self._factory is not None or self._scopes:
            raise RuntimeError("an agent factory is already active or draining")
        self._factory = _FactoryRegistration(self, factory)
        return self._factory

    @asynccontextmanager
    async def open(self, **options: Any) -> AsyncIterator[Agent]:
        if self._closed:
            raise ServiceClosedError("agent service is closed")
        registration = self._factory
        if registration is None:
            raise ServiceUnavailableError(ServiceKey("agent.loop"))
        session_id = options["session"].header.id
        if session_id in self._runs:
            raise RunConflict(session_id)
        agent = _OwnedAgent(registration.factory.create(**options), registration)
        released = asyncio.Event()
        self.register(session_id, agent)
        self._scopes[session_id] = (registration, agent, released)
        try:
            yield agent
        finally:
            async def cleanup():
                try:
                    agent.revoke("agent scope disposed")
                    try:
                        await agent.when_idle()
                    except asyncio.CancelledError:
                        pass  # The driver's facts have already been settled.
                finally:
                    self._scopes.pop(session_id, None)
                    self.unregister(session_id)
                    released.set()
            await _drain(asyncio.create_task(cleanup()))

    async def _stop(self, registration: _FactoryRegistration) -> None:
        scopes = [scope for scope in self._scopes.values() if scope[0] is registration]
        for _, agent, _ in scopes:
            agent.revoke("agent loop plugin unloaded")
        # Scope owners finish their driver and host persistence before releasing.
        await asyncio.gather(*(released.wait() for _, _, released in scopes))

    async def aclose(self) -> None:
        self._closed = True
        registrations = {scope[0] for scope in self._scopes.values()}
        if self._factory is not None:
            registrations.add(self._factory)
        await asyncio.gather(*(registration.aclose() for registration in registrations))


AGENT_RUNS: ServiceKey[AgentService] = ServiceKey("agent.runs")
