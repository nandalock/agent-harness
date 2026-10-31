"""Typed service access and owned plugin effects; implementations live in runtime."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from .models import PluginSpec, ServiceRef

T = TypeVar("T")
ConfigT = TypeVar("ConfigT", bound=BaseModel)
CleanupCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class ServiceKey(Generic[T]):
    """Invariant typed handle; import the canonical key from its contract package.

    Equal references identify the same service. T is a static contract, not a
    runtime signature validator; a host must also validate provider behavior.
    """

    ref: ServiceRef


class Registration(Protocol):
    """Owned effect handle. aclose() is idempotent and awaitably releases it.

    A stale handle must never remove a newer registration of the same name.
    Cancelling a close must not leave cleanup running after owner shutdown.
    """

    async def aclose(self) -> None: ...


class PluginContext(Protocol):
    """One plugin instance's restricted service resolver and cleanup owner.

    Only declared dependencies may be resolved and declared services published.
    Registration is owned by this context; setup failure rolls it back. Close
    revokes new work, drains active work, and unwinds effects in reverse order,
    attempting every cleanup even when one fails. It never deletes user data.
    """

    @property
    def instance_id(self) -> str: ...

    @property
    def spec(self) -> PluginSpec: ...

    def require(self, key: ServiceKey[T]) -> T:
        """Resolve a ready declared dependency, or raise ServiceUnavailableError."""
        ...

    def get(self, key: ServiceKey[T]) -> T | None:
        """Read a declared optional dependency. Absence alone returns None."""
        ...

    def provide(self, key: ServiceKey[T], service: T) -> Registration:
        """Publish a declared service and track its withdrawal automatically."""
        ...

    def track(self, registration: Registration) -> Registration:
        """Adopt an externally created registration into this instance's lifetime."""
        ...

    def on_dispose(self, callback: CleanupCallback, *, label: str) -> Registration:
        """Track a sync or async finalizer with an actionable diagnostic label."""
        ...


class Plugin(Protocol[ConfigT]):
    """An entry point exports a no-argument plugin class; host instantiates it.

    One instance is an assembly/lifecycle unit: it may publish services and
    register zero or many tools. Tool count and executor count are independent
    of plugin identity; every effect must be owned by its PluginContext.

    The host matches entry name to spec.name, checks SDK compatibility, validates
    config with config_model and resolves dependencies before calling setup.
    Importing a plugin must not register services or start background work.
    CancelledError propagates; teardown is performed through the owned context.
    """

    @property
    def spec(self) -> PluginSpec: ...

    @property
    def config_model(self) -> type[ConfigT]: ...

    async def setup(self, ctx: PluginContext, config: ConfigT) -> None: ...
