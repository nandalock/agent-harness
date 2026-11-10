"""Typed identities for services shared by plugins."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceKey(Generic[T]):
    name: str
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip() or self.version < 1:
            raise ValueError("a service key needs a name and a positive version")

    def __str__(self) -> str:
        return f"{self.name}.v{self.version}"
