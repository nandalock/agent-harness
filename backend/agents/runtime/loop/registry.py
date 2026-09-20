"""RunRegistry — 进程内「正在跑的那一轮」登记表（对齐 A 的会话级活动句柄）

**为什么需要它**：AgentLoop 是**请求内**现造现用的对象（AgentRuntime.reply 里的局部变量），
于是「用户在别处想看/想操控正在跑的这一轮」没有任何入口 —— 运行中输入的投递、停止按钮的
服务端入口都够不着它。本模块就是那个入口：按 session_id 找到正在驱动该会话的 loop，
把「投递一条输入」「叫停本轮」变成进程内的两次同步调用。

与 SessionStore 并列的 capability seam（都是纯内存热区，都在 main.py 装配）：

    SessionStore  —— session_id → Session（事实源）
    RunRegistry   —— session_id → 正在驱动它的活动句柄（控制面）

**同 session 单飞**：register 占用即抛 RunConflict。这不是锦上添花 —— 两个请求带同一个
session_id 时 `SessionStore.get()` 返回**同一个 Session 对象**，两个 loop 会同时往一份
Event Log 追加（`_seq` 读-改-写无锁、turn/start 交错、投影互相踩）。这是
docs/agent-loop-design.md §4 记的既有漏洞；运行中输入把它从边角变成常态，所以和它同批堵上。

**为什么是同步的**：登记/查找/投递都不 await —— 单线程事件循环里这意味着「查到了就一定是
活的」，投递不会打到一个正在收敛的轮次上（`get()` 与 `steer()` 之间没有让出点）。
"""
from typing import Protocol


class RunConflict(RuntimeError):
    """该会话已经有一轮在跑（第二个请求带同一个 session_id）。

    领域错误：由 AgentRuntime 抛出、Gateway 翻成 AgentBusy、通道层翻 409。
    """

    def __init__(self, session_id: str):
        super().__init__(f"会话 {session_id} 上已有一轮正在运行")
        self.session_id = session_id


class RunHandle(Protocol):
    """正在跑的一轮能接的动作（AgentLoop 天然满足）。

    刻意用 Protocol 而不是直接登记 AgentLoop：登记表只需要「能投递、能取消」，driver 相位、
    内部计数这些不该被外部摸到 —— 以后换一个 Loop 实现，登记表一行不用改。
    """

    def followup(self, text: str) -> str: ...
    def steer(self, text: str) -> str: ...
    def inject(self, text: str) -> str: ...
    def cancel(self, cause: str = ..., *, keep_inbox: bool = ...) -> None: ...


class RunRegistry:
    """session_id → 正在驱动它的活动句柄（一个会话一次活动）。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}

    def register(self, session_id: str, handle: RunHandle) -> None:
        """登记一次活动；已被占用即抛 RunConflict（同 session 单飞）。"""
        if session_id in self._runs:
            raise RunConflict(session_id)
        self._runs[session_id] = handle

    def get(self, session_id: str) -> RunHandle | None:
        """取正在跑的活动句柄；没有（本轮已结束 / 从未运行）返回 None。"""
        return self._runs.get(session_id)

    def unregister(self, session_id: str) -> None:
        """注销（幂等）：活动一结束就摘掉，别让下一次投递打到一个没人驱动的 loop 上。"""
        self._runs.pop(session_id, None)

    def active(self) -> list[str]:
        """当前在跑的 session_id 列表（观测用：排障时看「谁还占着会话」）。"""
        return list(self._runs)


_registry = RunRegistry()


def get_run_registry() -> RunRegistry:
    """进程级单例（与 get_session_store() 同模式）：所有 AgentRuntime 共享同一张表。"""
    return _registry
