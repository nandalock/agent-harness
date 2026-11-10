"""Typed identities for services shared by plugins."""

from dataclasses import dataclass
import re
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceKey(Generic[T]):
    name: str
    version: int = 1

    def __post_init__(self) -> None:
        if (not isinstance(self.name, str)
                or len(self.name) > 128
                or re.fullmatch(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", self.name) is None
                or type(self.version) is not int or self.version < 1):
            raise ValueError("a service key needs an identifier and a positive integer version")

    def __str__(self) -> str:
        return f"{self.name}.v{self.version}"
