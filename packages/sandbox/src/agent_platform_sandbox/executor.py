"""Sandbox tool executor — confine, spawn, classify.

The executor is host-neutral: it consumes ``ToolContext.sandbox_policy`` and an
optional ``approval.v1`` service, then emits domain events through
``ToolContext.event_sink``. It has no DB or MCP dependency.
"""
import asyncio
import logging
from typing import Any

from agent_platform_plugin_sdk import ApprovalRequest
from agent_platform_tool_system.context import ToolContext
from agent_platform_tool_system.descriptor import SandboxToolConfig, ToolDescriptor
from agent_platform_tool_system.events import (
    APPROVAL_REQUEST,
    SANDBOX_ESCALATION,
    ToolEvent,
)
from agent_platform_tool_system.runtime import ToolExecutor

from .classify import classify_outcome
from .errors import SandboxUnavailableError
from .escalation import (
    EscalationDenied,
    EscalationError,
    EscalationInvalid,
    approve_escalation,
    escalation_hint_marker,
    sandbox_denial_marker,
)
from .policy import resolve_policy
from .provider import SandboxProvider
from .vocabulary import SandboxExecutionPolicy, SandboxPolicy

logger = logging.getLogger(__name__)

#: 单次执行返回给模型的最大字符数（stdout / stderr 各自）。
MAX_OUTPUT_CHARS = 8000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（输出被截断，共 {len(text)} 字符）"


def build_sandbox_argv(cfg: SandboxToolConfig, args: dict) -> list[str]:
    """按 runtime 构造沙箱内的原始 argv。

    Raises:
        ValueError: 缺少必需参数或 runtime 未知。
    """
    if cfg.runtime == "shell":
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("shell 工具需要非空字符串参数 command")
        return ["bash", "-c", command]
    if cfg.runtime == "python":
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("python 工具需要非空字符串参数 code")
        return ["python", "-c", code]
    raise ValueError(f"未知沙箱 runtime: {cfg.runtime!r}（可选 shell / python）")


class SandboxExecutor(ToolExecutor):
    """沙箱工具执行器：``descriptor.sandbox`` 决定 argv 形状，策略来自 ToolContext。"""

    def __init__(
        self,
        provider: SandboxProvider | None = None,
        approval: Any | None = None,
    ) -> None:
        # provider 缺省时在执行时从装配层取（避免装配顺序耦合）
        self._provider = provider
        #: approval.v1 host service; ``None`` falls back to context.approval.
        self._approval = approval

    # ── 升权 ──

    def _approval_channel(self, context: ToolContext | None) -> Any | None:
        if self._approval is not None:
            return self._approval
        return context.approval if context is not None else None

    @staticmethod
    def _can_ask_human(approval: Any | None) -> bool:
        if approval is None:
            return False
        available = getattr(approval, "available", None)
        return available if isinstance(available, bool) else True

    async def _apply_escalation(
        self,
        descriptor: ToolDescriptor,
        args: dict,
        policy: SandboxExecutionPolicy,
        context: ToolContext | None,
    ) -> tuple[SandboxExecutionPolicy, EscalationError | None]:
        """走完整条升权链，把结果落到策略上。"""
        approval = self._approval_channel(context)
        try:
            target = await approve_escalation(
                args,
                current=policy.mode,
                approval=approval,
                agent=context.agent_id if context is not None else None,
                tool_name=descriptor.name,
                tool_call_id=context.tool_call_id if context is not None else None,
                on_request=lambda req: self._emit_approval_request(
                    context, descriptor.name, req
                ),
            )
        except EscalationInvalid as e:
            await self._emit_escalation(
                context, descriptor.name, policy.mode, target=None, error=e
            )
            raise
        except EscalationDenied as e:
            await self._emit_escalation(
                context, descriptor.name, policy.mode, target=None, error=e
            )
            return policy, e

        if target is None:
            return policy, None

        await self._emit_escalation(
            context, descriptor.name, policy.mode, target=target, error=None
        )
        wider = resolve_policy(
            workspace_root=policy.workspace_root,
            session_id=policy.session_id,
            explicit_mode=target,
            read_roots=policy.read_roots,
        )
        return wider, None

    @staticmethod
    async def _emit_approval_request(
        context: ToolContext | None,
        tool_name: str,
        req: ApprovalRequest,
    ) -> None:
        if context is None:
            return
        sink = context.event_sink
        if sink is None:
            return
        try:
            await sink.emit(
                ToolEvent(
                    type=APPROVAL_REQUEST,
                    tool_name=tool_name,
                    session_id=context.session_id,
                    trace_id=context.trace_id,
                    data={
                        "approval_id": req.approval_id,
                        "tool_call_id": req.tool_call_id,
                        "reason": req.reason,
                        "metadata": req.metadata,
                    },
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"approval.request 发送失败（不影响执行）: {tool_name}: {e}")

    @staticmethod
    async def _emit_escalation(
        context: ToolContext | None,
        tool_name: str,
        from_mode: str,
        *,
        target: str | None,
        error: EscalationError | None,
    ) -> None:
        if context is None:
            return
        sink = context.event_sink
        if sink is None:
            return
        try:
            await sink.emit(
                ToolEvent(
                    type=SANDBOX_ESCALATION,
                    tool_name=tool_name,
                    session_id=context.session_id,
                    trace_id=context.trace_id,
                    data={
                        "from": from_mode,
                        "requested": target
                        or (error.requested if error is not None else None),
                        "to": target,
                        "granted": target is not None,
                        "reason": "granted"
                        if target is not None
                        else (error.reason if error else "denied"),
                        "justification": error.justification
                        if error is not None
                        else "",
                        "approval_id": error.approval_id
                        if error is not None
                        else None,
                    },
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"sandbox.escalation 发送失败（不影响执行）: {tool_name}: {e}")

    async def execute(
        self,
        descriptor: ToolDescriptor,
        args: dict,
        context: ToolContext | None = None,
    ) -> dict:
        cfg = descriptor.sandbox
        if cfg is None:
            return {"error": f"沙箱工具缺少 SandboxToolConfig: {descriptor.name}"}

        policy = context.sandbox_policy if context is not None else None
        if policy is None:
            return {
                "error": f"沙箱策略缺失，拒绝执行 {descriptor.name}（沙箱未装配？）"
            }

        try:
            argv = build_sandbox_argv(cfg, args)
        except ValueError as e:
            return {"error": str(e)}

        try:
            policy, escalation = await self._apply_escalation(
                descriptor, args, policy, context
            )
        except EscalationInvalid as e:
            return {
                "error": str(e),
                "sandbox": {"mode": policy.mode, "escalation_invalid": e.reason},
            }

        confined = None
        if policy.mode == "danger-full-access":
            final_argv = argv
        else:
            provider = self._provider or get_sandbox_provider()
            if provider is None:
                return {"error": f"没有可用的沙箱后端，拒绝执行 {descriptor.name}"}
            try:
                confined = provider.confine(
                    argv,
                    SandboxPolicy(
                        mode=policy.mode,
                        workspace_root=policy.workspace_root,
                        session_id=policy.session_id,
                        read_roots=policy.read_roots,
                        write_roots=policy.write_roots,
                    ),
                )
            except SandboxUnavailableError as e:
                return {"error": str(e), "sandbox": {"unavailable": True}}
            final_argv = confined.argv

        try:
            proc = await asyncio.create_subprocess_exec(
                *final_argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError) as e:
            return {"error": f"沙箱 runner 不可执行: {e}"}

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=cfg.timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"沙箱执行超时（>{cfg.timeout_s:.0f}s），已取消"}
        except asyncio.CancelledError:
            proc.kill()
            raise

        stdout_full = stdout_b.decode("utf-8", errors="replace")
        stderr_full = stderr_b.decode("utf-8", errors="replace")
        result: dict = {
            "tool": descriptor.name,
            "exit_code": proc.returncode,
            "stdout": _truncate(stdout_full),
            "stderr": _truncate(stderr_full),
        }

        if confined is not None:
            outcome = classify_outcome(proc.returncode, stderr_full, confined)
            result["sandbox"] = {
                "mode": policy.mode,
                "enforcement": confined.enforcement,
                "outcome": outcome,
            }
            if outcome == "denied":
                result["notice"] = sandbox_denial_marker(policy.mode)
                if escalation is not None:
                    result["notice"] += (
                        f"\n[sandbox: escalation refused ({escalation.reason})"
                        " — do not retry this command as-is]"
                    )
                else:
                    hint = escalation_hint_marker(
                        policy.mode,
                        can_ask_human=self._can_ask_human(
                            self._approval_channel(context)
                        ),
                    )
                    if hint:
                        result["notice"] = f"{result['notice']}\n{hint}"
            elif outcome == "runner_failed":
                result["notice"] = (
                    "沙箱基础设施故障：命令未执行，请勿重试同一命令。"
                )
        return result


def get_sandbox_provider() -> SandboxProvider | None:
    """装配层 provider（延迟导入，避免执行器与装配层互相依赖）。"""
    from .runtime import get_sandbox_provider as _get

    return _get()
