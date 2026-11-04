"""Runtime enable/disable control owned by the sandbox plugin.

The plugin registers ``bash``/``python`` only while the capability is enabled;
the host API calls :func:`set_sandbox_enabled`, and no tool is left visible in
the model's tool list when disabled.
"""
import logging
from typing import Any

from agent_platform_plugin_sdk import (
    Registration,
    SettingsService,
    ToolDescriptor,
    ToolsService,
)

logger = logging.getLogger(__name__)

SETTINGS_NAMESPACE = "sandbox"


class SandboxToolControl:
    def __init__(
        self,
        tools: ToolsService,
        settings: SettingsService,
        descriptors: dict[str, ToolDescriptor],
        track: Any,
    ) -> None:
        self._tools = tools
        self._settings = settings
        self._descriptors = descriptors
        self._track = track
        self._registrations: dict[str, Registration] = {}
        self._enabled = True
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def load(self) -> None:
        try:
            values = await self._settings.get(SETTINGS_NAMESPACE)
            self._enabled = bool(values.get("enabled", True))
        except Exception as exc:  # noqa: BLE001
            # Capability visibility defaults to on; execution still fails closed.
            logger.warning("读取沙箱开关失败，按启用处理: %s", exc)
            self._enabled = True
        await self._apply()

    async def set_enabled(self, enabled: bool) -> None:
        await self._settings.set(SETTINGS_NAMESPACE, {"enabled": enabled})
        self._enabled = enabled
        await self._apply()
        logger.info("沙箱能力已%s", "启用" if enabled else "停用")

    async def _apply(self) -> None:
        if self._closed:
            return
        if self._enabled:
            for name, descriptor in self._descriptors.items():
                if name in self._registrations:
                    continue
                registration = self._tools.register_tool(descriptor)
                self._track(registration)
                self._registrations[name] = registration
        else:
            for name in list(self._registrations):
                registration = self._registrations.pop(name)
                try:
                    await registration.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("注销沙箱工具 %s 失败: %s", name, exc)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for name in list(self._registrations):
            registration = self._registrations.pop(name)
            try:
                await registration.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("注销沙箱工具 %s 失败: %s", name, exc)
        global _control
        if _control is self:
            _control = None


_control: SandboxToolControl | None = None


def set_sandbox_control(control: SandboxToolControl | None) -> None:
    global _control
    _control = control


def get_sandbox_control() -> SandboxToolControl | None:
    return _control


def is_sandbox_enabled() -> bool:
    control = get_sandbox_control()
    return True if control is None else control.enabled


async def set_sandbox_enabled(enabled: bool) -> None:
    control = get_sandbox_control()
    if control is None:
        raise RuntimeError("沙箱工具插件未装配")
    await control.set_enabled(enabled)
