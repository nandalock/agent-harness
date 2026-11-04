"""Public configuration/data boundaries, without importing the application."""
import json
import unittest

from pydantic import ValidationError

from agent_platform_plugin_sdk import (
    TOOLS, ExecutionScope, PluginCompatibilityError, PluginConfiguration, PluginEntry,
    PluginSpec, ServiceKey, ServiceRef, ServiceRequirement, ServiceUnavailableError,
    ToolCall, ToolContext, ToolDescriptor, ToolError, ToolResult, ensure_sdk_compatible,
)


class ConfigurationTests(unittest.TestCase):
    def test_yaml_shaped_document_round_trips_without_losing_instance_identity(self):
        config = PluginConfiguration.model_validate({"version": 1, "plugins": [
            {"id": "tools", "name": "agent-platform.tools-default", "config": {}},
            {"id": "echo", "name": "example.echo", "disabled": True, "config": {"prefix": "收到："}},
        ]})
        self.assertEqual(config.plugins[0].id, "tools")
        self.assertEqual(config.plugins[0].name, "agent-platform.tools-default")
        self.assertEqual(PluginConfiguration.model_validate_json(config.model_dump_json()), config)

    def test_instances_are_unique_but_implementation_names_can_repeat(self):
        entries = [{"id": "first", "name": "example.echo"}, {"id": "second", "name": "example.echo"}]
        self.assertEqual(len(PluginConfiguration(plugins=entries).plugins), 2)
        entries[1]["id"] = "first"
        with self.assertRaises(ValidationError):
            PluginConfiguration(plugins=entries)

    def test_invalid_or_ambiguous_configuration_is_rejected(self):
        for value in ({"id": "bad id", "name": "example.echo"},
                      {"id": "echo", "name": "backend.module:Plugin"},
                      {"id": "echo", "name": "example.echo", "disabled": "false"},
                      {"id": "echo", "name": "example.echo", "extra": True},
                      {"id": "echo", "name": "example.echo", "config": {"callback": object()}},
                      {"id": "echo", "name": "example.echo", "config": {"number": float("nan")}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                PluginEntry.model_validate(value)
        for version in (2, True, "1"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                PluginConfiguration(version=version)

    def test_plugin_and_service_versions_are_independent(self):
        spec = PluginSpec(name="example.tools", version="2.4.0", provides=(TOOLS.ref,))
        ensure_sdk_compatible(spec)
        self.assertEqual(spec.version, "2.4.0")
        self.assertEqual(spec.provides[0].api_version, 1)
        incompatible = spec.model_copy(update={"sdk_api_version": 2})
        with self.assertRaises(PluginCompatibilityError) as raised:
            ensure_sdk_compatible(incompatible)
        self.assertEqual(raised.exception.code, "plugin.incompatible_sdk")
        for version in ("not-a-version", "", "1.2.3.?"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                PluginSpec(name="example.tools", version=version)

    def test_service_declarations_reject_duplicates_and_invalid_versions(self):
        requirement = ServiceRequirement(service=TOOLS.ref)
        with self.assertRaises(ValidationError):
            PluginSpec(name="example.echo", version="0.1", requires=(requirement, requirement))
        with self.assertRaises(ValidationError):
            PluginSpec(name="example.echo", version="0.1", provides=(TOOLS.ref, TOOLS.ref))
        for version in (0, -1, True, "1"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                ServiceRef(name="tools", api_version=version)
        self.assertEqual(str(TOOLS.ref), "tools.v1")
        self.assertNotEqual(TOOLS, ServiceKey(ServiceRef(name="tools", api_version=2)))
        self.assertEqual(TOOLS, ServiceKey(ServiceRef(name="tools", api_version=1)))
        self.assertEqual(ServiceUnavailableError(TOOLS.ref).service, TOOLS.ref)


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

    def test_schema_and_config_defaults_are_not_shared(self):
        first = ToolDescriptor(name="one", executor="native", description="One")
        second = ToolDescriptor(name="two", executor="native", description="Two")
        first.input_schema["required"] = ["text"]
        self.assertNotIn("required", second.input_schema)
        entry = PluginEntry(id="one", name="example.one")
        entry.config["changed"] = True
        self.assertEqual(PluginEntry(id="two", name="example.two").config, {})
        # Frozen fields do not imply deep JSON immutability; documented host
        # snapshots must be made before calls cross an async boundary.
        snapshot = first.model_copy(deep=True)
        first.input_schema["required"] = []
        self.assertEqual(json.loads(snapshot.model_dump_json())["input_schema"]["required"], ["text"])


if __name__ == "__main__":
    unittest.main()
