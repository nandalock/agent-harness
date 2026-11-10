"""Typed waterfall events. The context handles registration ownership."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from .fiber import Fiber

T = TypeVar("T")


@dataclass(frozen=True)
class EventKey(Generic[T]):
    name: str


type Handler[T] = Callable[[T], Awaitable[T] | T]


@dataclass(eq=False, slots=True)
class Listener:
    fiber: "Fiber"
    handler: Handler[Any]
    active: bool = True
