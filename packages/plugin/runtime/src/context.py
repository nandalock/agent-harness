"""The host-issued context that scopes resolution and owns one plugin's effects."""
from inspect import isawaitable
from typing import Any, TypeVar, cast

from agent_platform_plugin_sdk import (
    CleanupCallback,
    PluginSpec,
    Registration,
    ServiceClosedError,
    ServiceKey,
    ServiceRef,
    ServiceRequirement,
    ServiceUnavailableError,
)

from .errors import UndeclaredServiceError
from .registry import ServiceRegistry

T = TypeVar("T")


class _CallbackRegistration:
    """Idempotent cleanup owned by a plugin context."""

    def __init__(self, callback: CleanupCallback, label: str) -> None:
        self._callback = callback
        self._label = label
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            result = self._callback()
            if isawaitable(result):
                await result
        except BaseException as exc:
            exc.add_note(f"plugin cleanup callback {self._label!r} failed")
            raise


class RuntimePluginContext:
    """Resolve declared services and unwind every effect in reverse order.

    A closed context rejects new work. Cleanup attempts every registered effect
    even when one fails, then raises the failures together.
    """

    def __init__(self, instance_id: str, spec: PluginSpec, registry: ServiceRegistry) -> None:
        self._instance_id = instance_id
        self._spec = spec
        self._registry = registry
        self._effects: list[Registration] = []
        self._closed = False

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def spec(self) -> PluginSpec:
        return self._spec

    def require(self, key: ServiceKey[T]) -> T:
        self._ensure_open()
        requirement = self._requirement(key.ref)
        if requirement is None:
            raise UndeclaredServiceError(
                f"plugin {self.instance_id!r} did not declare a requirement for {key.ref}"
            )
        service = self._registry.lookup(key.ref)
        if service is None:
            raise ServiceUnavailableError(key.ref)
        return cast(T, service)

    def get(self, key: ServiceKey[T]) -> T | None:
        self._ensure_open()
        requirement = self._requirement(key.ref)
        if requirement is None:
            raise UndeclaredServiceError(
                f"plugin {self.instance_id!r} did not declare a requirement for {key.ref}"
            )
        service = self._registry.lookup(key.ref)
        if service is None:
            if requirement.optional:
                return None
            raise ServiceUnavailableError(key.ref)
        return cast(T, service)

    def provide(self, key: ServiceKey[T], service: T) -> Registration:
        self._ensure_open()
        if key.ref not in {ref for ref in self.spec.provides}:
            raise UndeclaredServiceError(
                f"plugin {self.instance_id!r} did not declare that it provides {key.ref}"
            )
        registration = self._registry.provide(
            key.ref, service, owner=self.instance_id
        )
        self._effects.append(registration)
        return registration

    def track(self, registration: Registration) -> Registration:
        self._ensure_open()
        self._effects.append(registration)
        return registration

    def on_dispose(self, callback: CleanupCallback, *, label: str) -> Registration:
        self._ensure_open()
        registration = _CallbackRegistration(callback, label)
        self._effects.append(registration)
        return registration

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[BaseException] = []
        for registration in reversed(self._effects):
            try:
                await registration.aclose()
            except BaseException as exc:
                errors.append(exc)
        self._effects.clear()
        if errors:
            raise BaseExceptionGroup(
                f"cleanup failed for plugin {self.instance_id!r}", errors
            )

    def _requirement(self, ref: ServiceRef) -> ServiceRequirement | None:
        for requirement in self.spec.requires:
            if requirement.service == ref:
                return requirement
        return None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ServiceClosedError(
                f"plugin context {self.instance_id!r} is closed"
            )
