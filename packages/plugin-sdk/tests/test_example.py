"""An independently authored plugin can configure and use only SDK contracts."""
import importlib.util
from pathlib import Path
import sys
import unittest

from pydantic import ValidationError

from agent_platform_plugin_sdk import TOOLS, ToolCall, ToolContext, ensure_sdk_compatible
from test_contract import MemoryTools
from agent_platform_plugin_sdk import ExecutionScope


class ExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_entry_config_and_owned_registration_work_without_backend(self):
        path = Path(__file__).resolve().parents[1] / "examples/tool_plugin.py"
        module_spec = importlib.util.spec_from_file_location("sdk_echo_example", path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        try:
            module_spec.loader.exec_module(module)
            plugin = module.EchoPlugin()
            ensure_sdk_compatible(plugin.spec)
            config = plugin.config_model.model_validate({"prefix": "收到："})
            with self.assertRaises(ValidationError):
                plugin.config_model.model_validate({"prefix": "", "unrecognized": True})
            scope = ExecutionScope(tenant_id=7, agent_key="assistant")
            tools = MemoryTools(scope)
            self.assertEqual(await tools.list_for_agent(scope), [])

            class Context:
                def __init__(self):
                    self.owned = []
                def require(self, key):
                    if key != TOOLS:
                        raise AssertionError("unexpected dependency")
                    return tools
                def track(self, registration):
                    self.owned.append(registration)
                    return registration

            context = Context()
            try:
                await plugin.setup(context, config)
                result = await tools.execute(ToolCall(call_id="1", name="echo", arguments={"text": "hello"}),
                                             ToolContext(scope=scope, visible_tool_names={"echo"}))
                self.assertEqual(result.data, {"text": "收到：hello"})
                for registration in reversed(context.owned):
                    await registration.aclose()
                self.assertEqual(await tools.list_for_agent(scope), [])
                self.assertEqual(len(context.owned), 2)
            finally:
                await tools.aclose()
        finally:
            sys.modules.pop(module_spec.name, None)


if __name__ == "__main__":
    unittest.main()
