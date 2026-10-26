"""The default implementation must satisfy the SDK's shared tools.v1 suite."""
import unittest

from agent_platform_plugin_sdk.testing import verify_tools_service
from agent_platform_tools_default import ToolsDefaultService


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_contract_suite_passes(self):
        async def factory(scope):
            return ToolsDefaultService()

        passed = await verify_tools_service(factory)
        self.assertEqual(
            passed,
            (
                "execution_context",
                "visibility_and_lookup",
                "registration_ownership",
                "cancellation",
                "deadline",
                "tool_timeout",
                "shutdown",
            ),
        )

    async def test_closed_service_rejects_new_work(self):
        service = ToolsDefaultService()
        await service.aclose()
        await service.aclose()
        from agent_platform_plugin_sdk import ServiceClosedError, ToolDescriptor

        with self.assertRaises(ServiceClosedError):
            service.register_tool(
                ToolDescriptor(name="x", executor="x", description="x")
            )


if __name__ == "__main__":
    unittest.main()
