"""Per-run view of the originating plugin context and host-supplied model client."""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_platform_llm import LlmClient
from agent_platform_plugin_sdk import APPROVAL, TOOLS, ApprovalService, PluginContext, ToolsService
from agent_platform_tools_default import TOOL_CATALOG, ToolCatalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopContext:
    """Resolve capabilities from the plugin's existing service table at use time.

    Each run gets its own model client and policy resolver. Shared services and
    their lifetime still belong to plugin_ctx; this creates no second registry.
    """

    plugin_ctx: PluginContext
    llm: LlmClient
    sandbox_policy_factory: Callable[[], Any] | None = None

    @property
    def tools(self) -> ToolsService:
        return self.plugin_ctx.require(TOOLS)

    @property
    def tool_catalog(self) -> ToolCatalog:
        return self.plugin_ctx.require(TOOL_CATALOG)

    @property
    def approval(self) -> ApprovalService:
        return self.plugin_ctx.require(APPROVAL)

    @property
    def sandbox_policy(self) -> Any:
        if self.sandbox_policy_factory is None:
            return None
        try:
            return self.sandbox_policy_factory()
        except Exception:
            logger.exception("沙箱策略解析失败（沙箱工具将拒绝执行）")
            return None
