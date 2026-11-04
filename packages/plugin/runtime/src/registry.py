"""One runtime scope's service table with caller-owned, stale-safe registrations."""
from dataclasses import dataclass
from typing import Any

from agent_platform_plugin_sdk import (
    RegistrationConflictError,
    ServiceKey,
    ServiceRef,
)

from .errors import LifecycleError


@dataclass
class _Slot:
    token: object
    service: object
    owner: str


class ServiceRegistration:
    """A handle whose close only removes the registration that created it."""

    def __init__(self, registry: "ServiceRegistry", ref: ServiceRef, token: object) -> None:
        self._registry = registry
        self._ref = ref
        self._token = token
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._registry._remove(self._ref, self._token)


class ServiceRegistry:
    """Services for one host scope; host services are borrowed, not owned."""

    def __init__(self, host_services: dict[ServiceKey[Any], Any] | None = None) -> None:
        self._slots: dict[ServiceRef, _Slot] = {}
        for key, service in (host_services or {}).items():
            if key.ref in self._slots:
                raise RegistrationConflictError(
                    f"the host provides duplicate service {key.ref}"
                )
            self._slots[key.ref] = _Slot(object(), service, "<host>")

    def lookup(self, ref: ServiceRef) -> object | None:
        slot = self._slots.get(ref)
        return slot.service if slot is not None else None

    def provide(self, ref: ServiceRef, service: object, *, owner: str) -> ServiceRegistration:
        if service is None:
            raise LifecycleError(f"service {ref} must not be None")
        existing = self._slots.get(ref)
        if existing is not None:
            raise RegistrationConflictError(
                f"service {ref} is already provided by {existing.owner!r}"
            )
        token = object()
        self._slots[ref] = _Slot(token, service, owner)
        return ServiceRegistration(self, ref, token)

    def _remove(self, ref: ServiceRef, token: object) -> None:
        slot = self._slots.get(ref)
        if slot is not None and slot.token is token:
            del self._slots[ref]

    def refs(self) -> frozenset[ServiceRef]:
        return frozenset(self._slots)
