"""Gateway 领域错误 — 与 HTTP/SSE/WebSocket 无关

由通道层（API adapter）翻译成通道错误，Gateway 不直接产生 HTTPException。
对齐 DSH：Gateway 错误携带稳定 code（如 session/agent-busy），协议层负责映射。

已使用：InvalidGatewayContext / AgentNotFound / **AgentBusy**（run ownership 落地后由
chat() 抛）/ **NoActiveRun**（运行中输入投递时该会话没有在跑的轮次）。
仍预留：SessionNotFound（冷会话恢复策略启用后使用）。
"""
from typing import Optional


class GatewayError(Exception):
    code = "gateway/error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidGatewayContext(GatewayError):
    """RequestContext 缺失运行必需字段（tenant_id / agent_key 为空等）"""
    code = "gateway/invalid-context"


class AgentNotFound(GatewayError):
    """目标 agent 不在注册表中（key 不存在）"""
    code = "gateway/agent-not-found"


class SessionNotFound(GatewayError):
    """session_id 对应 Session 不存在（预留：冷会话恢复策略启用后使用）"""
    code = "session/not-found"


class AgentBusy(GatewayError):
    """同一 Session 正被另一个 run 驱动（同 session 单飞：第二个请求应改投运行中输入）"""
    code = "session/agent-busy"


class NoActiveRun(GatewayError):
    """该会话没有正在跑的轮次 —— 投递运行中输入时无处可投。

    不是错误用法：客户端拿着「发送中」的状态来投是对的，只是这一轮刚巧已经收口了。
    给客户端的动作是「按新消息发」（/chat/stream），不是重试。
    """
    code = "session/no-active-run"
