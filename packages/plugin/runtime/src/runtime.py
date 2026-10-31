"""Host that validates the graph, sets plugins up in order, and unwinds them in reverse."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from inspect import isawaitable
from pathlib import Path
from typing import Any, TypeVar, cast

from agent_platform_plugin_sdk import (
    PluginConfiguration,
    PluginSpec,
    ServiceClosedError,
    ServiceKey,
    ServiceUnavailableError,
)

from .catalog import EntryPointCatalog, PluginCatalog
from .config import load_yaml_config, parse_config
from .context import RuntimePluginContext
from .dependencies import resolve
from .errors import LifecycleError
from .loader import LoadedPlugin, load_plugins
from .registry import ServiceRegistry

T = TypeVar("T")


class RuntimeState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"


@dataclass(frozen=True)
class LoadedPluginInfo:
    """Public metadata for one successfully started plugin instance."""

    instance_id: str
    name: str
    version: str
    spec: PluginSpec


class PluginRuntime:
    """A single host scope for declarative plugin instances.

    `start()` validates every enabled entry before calling any setup, then
    starts plugins in dependency order. A setup failure closes the failing
    context and every already-started context in reverse order before the
    original exception is re-raised. `aclose()` is idempotent and always
    attempts every cleanup, raising the failures together.

    Lifecycle calls are not safe to race with each other; a supervisor should
    serialize `start()` and `aclose()`.
    """

    def __init__(
        self,
        config: PluginConfiguration | Mapping[str, object],
        *,
        catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> None:
        self._config = (
            config
            if isinstance(config, PluginConfiguration)
            else parse_config(config)
        )
        self._catalog = catalog if catalog is not None else EntryPointCatalog()
        self._host_services = dict(host_services or {})
        self._state = RuntimeState.NEW
        self._registry: ServiceRegistry | None = None
        self._contexts: list[tuple[LoadedPlugin, RuntimePluginContext]] = []
        self._plugins: tuple[LoadedPluginInfo, ...] = ()

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> "PluginRuntime":
        return cls(
            load_yaml_config(path),
            catalog=catalog,
            host_services=host_services,
        )

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def config(self) -> PluginConfiguration:
        return self._config

    @property
    def plugins(self) -> tuple[LoadedPluginInfo, ...]:
        """Metadata for the instances started by the last successful `start()`."""
        return self._plugins

    async def start(self) -> None:
        if self._state is RuntimeState.CLOSED:
            raise ServiceClosedError("plugin runtime is closed")
        if self._state is not RuntimeState.NEW:
            raise LifecycleError(
                f"cannot start plugin runtime in state {self._state.value!r}"
            )
        self._state = RuntimeState.STARTING
        started: list[tuple[LoadedPlugin, RuntimePluginContext]] = []
        current: RuntimePluginContext | None = None
        try:
            loaded = load_plugins(self._config, self._catalog)
            plan = resolve(loaded, self._host_services)
            self._registry = ServiceRegistry(self._host_services)
            for record in plan.plugins:
                current = RuntimePluginContext(
                    record.entry.id, record.spec, self._registry
                )
                result = record.plugin.setup(current, record.config)
                if not isawaitable(result):
                    raise LifecycleError(
                        f"plugin {record.entry.id!r} setup() did not return an awaitable"
                    )
                await result
                started.append((record, current))
                current = None
            self._contexts = started
            self._plugins = tuple(
                LoadedPluginInfo(
                    instance_id=record.entry.id,
                    name=record.spec.name,
                    version=record.spec.version,
                    spec=record.spec,
                )
                for record in plan.plugins
            )
            self._state = RuntimeState.RUNNING
        except BaseException as exc:
            await self._rollback(started, current, exc)
            self._registry = None
            self._state = RuntimeState.NEW
            raise

    async def aclose(self) -> None:
        if self._state is RuntimeState.CLOSED:
            return
        if self._state is RuntimeState.STARTING:
            raise LifecycleError(
                "cannot close a plugin runtime while it is starting"
            )
        if self._state is RuntimeState.STOPPING:
            raise LifecycleError("plugin runtime is already stopping")
        self._state = RuntimeState.STOPPING
        errors: list[BaseException] = []
        for _, context in reversed(self._contexts):
            try:
                await context.aclose()
            except BaseException as exc:
                errors.append(exc)
        self._contexts.clear()
        self._registry = None
        self._state = RuntimeState.CLOSED
        if errors:
            raise BaseExceptionGroup("plugin runtime shutdown failed", errors)

    def require(self, key: ServiceKey[T]) -> T:
        """Resolve a service published by a plugin or supplied by the host."""
        if self._state is not RuntimeState.RUNNING:
            raise LifecycleError(
                f"plugin runtime is not running (state {self._state.value!r})"
            )
        if self._registry is None:
            raise LifecycleError("plugin runtime has no service registry")
        service = self._registry.lookup(key.ref)
        if service is None:
            raise ServiceUnavailableError(key.ref)
        return cast(T, service)

    async def _rollback(
        self,
        started: list[tuple[LoadedPlugin, RuntimePluginContext]],
        current: RuntimePluginContext | None,
        original: BaseException,
    ) -> None:
        failures: list[BaseException] = []
        if current is not None:
            try:
                await current.aclose()
            except BaseException as exc:
                failures.append(exc)
        for _, context in reversed(started):
            try:
                await context.aclose()
            except BaseException as exc:
                failures.append(exc)
        for failure in failures:
            original.add_note(f"plugin rollback also failed: {failure!r}")
