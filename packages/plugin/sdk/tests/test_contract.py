"""Test-only implementations exercise the SDK's portable behavior suite."""
import asyncio
from time import monotonic
import unittest

from agent_platform_plugin_sdk import (
    TOOL_DENIED, TOOL_NOT_FOUND, TOOL_TIMEOUT, TOOL_UNAVAILABLE,
    ExecutionScope, RegistrationConflictError, ServiceClosedError,
    ToolCall, ToolContext, ToolError, ToolResult,
)
from agent_platform_plugin_sdk.testing import verify_tools_service


class Handle:
    def __init__(self, remove):
        self.remove = remove
        self.closed = False

    async def aclose(self):
        if not self.closed:
            self.closed = True
            self.remove()


class MemoryTools:
    """Fixture, not a shipped tool service or an adapter to the backend."""
    def __init__(self, scope):
        self.scope = scope
        self.tools = {}
        self.executors = {}
        self.providers = {}
        self.tasks = set()
        self.closed = False

    def _register(self, table, name, value):
        if self.closed:
            raise ServiceClosedError("fixture is closed")
        if name in table:
            raise RegistrationConflictError(name)
        token = object()
        table[name] = (token, value)
        def remove():
            if name in table and table[name][0] is token:
                del table[name]
        return Handle(remove)

    def register_tool(self, descriptor):
        return self._register(self.tools, descriptor.name, descriptor)

    def register_executor(self, name, executor):
        return self._register(self.executors, name, executor)

    def register_provider(self, provider):
        return self._register(self.providers, provider.name, provider)

    async def list_for_agent(self, scope):
        if scope != self.scope or self.closed:
            return []
        return [entry[1] for entry in self.tools.values()]

    @staticmethod
    def failed(code):
        return ToolResult(status="error", error=ToolError(code=code, message=code))

    async def execute(self, call, context):
        if self.closed:
            return self.failed(TOOL_UNAVAILABLE)
        if call.name not in context.visible_tool_names or context.scope != self.scope:
            return self.failed(TOOL_DENIED)
        if call.name not in self.tools:
            return self.failed(TOOL_NOT_FOUND)
        descriptor = self.tools[call.name][1]
        executor = self.executors[descriptor.executor][1]
        deadline = context.deadline
        if descriptor.timeout_seconds is not None:
            cap = monotonic() + descriptor.timeout_seconds
            deadline = cap if deadline is None else min(deadline, cap)
        if deadline is not None and deadline <= monotonic():
            return self.failed(TOOL_TIMEOUT)
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout_at(deadline):
                return await executor.execute(descriptor, call.arguments, context)
        except TimeoutError:
            return self.failed(TOOL_TIMEOUT)
        finally:
            self.tasks.remove(task)

    async def aclose(self):
        self.closed = True
        pending = [task for task in self.tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.tools.clear()
        self.executors.clear()
        self.providers.clear()


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_reference_fixture_passes_shared_behavior_contract(self):
        async def factory(scope):
            return MemoryTools(scope)
        passed = await verify_tools_service(factory)
        self.assertEqual(passed, ("execution_context", "visibility_and_lookup", "registration_ownership",
                                  "cancellation", "deadline", "tool_timeout", "shutdown"))

    async def test_shared_suite_rejects_an_implementation_that_ignores_visibility(self):
        class UnrestrictedTools(MemoryTools):
            async def execute(self, call, context):
                context = context.model_copy(update={"visible_tool_names": frozenset({call.name})})
                return await super().execute(call, context)
        async def factory(scope):
            return UnrestrictedTools(scope)
        with self.assertRaisesRegex(AssertionError, "visibility"):
            await verify_tools_service(factory)

    async def test_shared_suite_rejects_swallowed_cancellation(self):
        class SwallowingTools(MemoryTools):
            async def execute(self, call, context):
                try:
                    return await super().execute(call, context)
                except asyncio.CancelledError:
                    return ToolResult()
        async def factory(scope):
            return SwallowingTools(scope)
        with self.assertRaisesRegex(AssertionError, "CancelledError"):
            await verify_tools_service(factory)

    async def test_scope_and_closed_state_remain_distinct_from_registration(self):
        tools = MemoryTools(ExecutionScope(tenant_id=1, agent_key="a"))
        context = ToolContext(scope=ExecutionScope(tenant_id=2, agent_key="a"), visible_tool_names={"echo"})
        result = await tools.execute(ToolCall(call_id="1", name="echo"), context)
        self.assertEqual(result.error.code, TOOL_DENIED)
        await tools.aclose()


if __name__ == "__main__":
    unittest.main()
