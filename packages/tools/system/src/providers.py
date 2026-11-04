"""Tool source abstraction shipped with the native tool index."""
from abc import ABC, abstractmethod

from .descriptor import ToolDescriptor


class ToolProvider(ABC):
    """One source of native tool descriptors."""

    name: str = "?"

    @abstractmethod
    async def discover(self) -> list[ToolDescriptor]:
        """List this source's currently available tools."""

    async def lazy_load(self, tool_name: str) -> ToolDescriptor | None:
        """Resolve one unindexed tool on demand; default: unsupported."""
        return None

    def label_of(self, descriptor: ToolDescriptor) -> str:
        """Display label for this provider's tool in UI/logs."""
        return self.name


class BuiltinToolProvider(ToolProvider):
    """Tools registered by host code (sandbox bash/python, skill, ...)."""

    name = "builtin"

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.name] = descriptor

    def unregister(self, names) -> None:
        for name in names:
            self._tools.pop(name, None)

    def descriptors(self) -> list[ToolDescriptor]:
        return list(self._tools.values())

    async def discover(self) -> list[ToolDescriptor]:
        return self.descriptors()

    async def lazy_load(self, tool_name: str) -> ToolDescriptor | None:
        return self._tools.get(tool_name)
