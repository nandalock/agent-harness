"""Public configuration/data boundaries, without importing the application."""
import json
import unittest

from pydantic import ValidationError

from agent_platform_plugin_sdk import (
    TOOLS, ExecutionScope,
    ServiceKey, ServiceUnavailableError,
    ToolCall, ToolContext, ToolDescriptor, ToolError, ToolResult,
)


class ServiceKeyTests(unittest.TestCase):
    def test_service_keys_use_cordis_identity_and_exact_versions(self):
        from minidsh_cordis import ServiceKey as CordisKey

        self.assertIs(ServiceKey, CordisKey)
        for version in (0, -1, True, "1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                ServiceKey("tools", version=version)
        self.assertEqual(str(TOOLS), "tools.v1")
        self.assertNotEqual(TOOLS, ServiceKey("tools", version=2))
        self.assertEqual(TOOLS, ServiceKey("tools"))
        self.assertEqual(ServiceUnavailableError(TOOLS).service, TOOLS)


class ToolsDataTests(unittest.TestCase):
    def test_execution_context_requires_explicit_visibility_and_trusted_identity(self):
        scope = ExecutionScope(tenant_id=7, agent_key="assistant")
        with self.assertRaises(ValidationError):
            ToolContext(scope=scope)
        context = ToolContext(scope=scope, visible_tool_names=frozenset())
        self.assertFalse(context.visible_tool_names)
        call = ToolCall(call_id="c1", name="echo", arguments={"tenant_id": 999})
        self.assertEqual(context.scope.tenant_id, 7)
        self.assertEqual(call.arguments["tenant_id"], 999)
        for tenant in (0, -1, True, "7"):
            with self.subTest(tenant=tenant), self.assertRaises(ValidationError):
                ExecutionScope(tenant_id=tenant, agent_key="assistant")

    def test_host_context_is_opaque_and_excluded_from_the_wire(self):
        scope = ExecutionScope(tenant_id=7, agent_key="assistant")
        payload = {"sandbox_policy": "workspace-write"}
        context = ToolContext(
            scope=scope,
            visible_tool_names=frozenset({"echo"}),
            host_context=payload,
        )
        self.assertIs(context.host_context, payload)
        self.assertNotIn("host_context", context.model_dump())
        self.assertNotIn("host_context", context.model_dump_json())

    def test_result_preserves_partial_data_and_rejects_ambiguous_errors(self):
        result = ToolResult(status="error", error=ToolError(code="compile.failed", message="Compilation failed"),
                            data={"completed": ["read", "edit"]})
        self.assertEqual(ToolResult.model_validate_json(result.model_dump_json()), result)
        with self.assertRaises(ValidationError):
            ToolResult(status="error")
        with self.assertRaises(ValidationError):
            ToolResult(error=ToolError(code="failed", message="Failed"))

    def test_wire_fields_and_limits_are_validated(self):
        for value in ({"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
                      {"execution_mode": "serial"}, {"input_schema": {"type": "array"}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ToolDescriptor(name="echo", executor="native", description="Echo", **value)
        with self.assertRaises(ValidationError):
            ToolCall(call_id="c1", name="echo", arguments=["not an object"])
        with self.assertRaises(ValidationError):
            ToolContext(scope=ExecutionScope(tenant_id=1, agent_key="a"), visible_tool_names=[], deadline=float("nan"))

    def test_schema_defaults_are_not_shared(self):
        first = ToolDescriptor(name="one", executor="native", description="One")
        second = ToolDescriptor(name="two", executor="native", description="Two")
        first.input_schema["required"] = ["text"]
        self.assertNotIn("required", second.input_schema)
        # Frozen fields do not imply deep JSON immutability; documented host
        # snapshots must be made before calls cross an async boundary.
        snapshot = first.model_copy(deep=True)
        first.input_schema["required"] = []
        self.assertEqual(json.loads(snapshot.model_dump_json())["input_schema"]["required"], ["text"])


if __name__ == "__main__":
    unittest.main()
