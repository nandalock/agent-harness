"""Host-service contracts stay independent from the backend implementations."""
import unittest

from agent_platform_plugin_sdk import (
    AGENTS,
    ALLOWED,
    APPROVAL,
    SETTINGS,
    ApprovalRequest,
    new_approval_id,
)


class HostContractTests(unittest.TestCase):
    def test_service_keys_are_stable_and_distinct(self):
        self.assertEqual(str(APPROVAL.ref), "approval.v1")
        self.assertEqual(str(SETTINGS.ref), "settings.v1")
        self.assertEqual(str(AGENTS.ref), "agents.v1")
        self.assertEqual(len({APPROVAL.ref, SETTINGS.ref, AGENTS.ref}), 3)

    def test_approval_request_is_domain_neutral_and_serializable(self):
        req = ApprovalRequest(
            approval_id=new_approval_id(),
            reason="need write access",
            tool_name="bash",
            tool_call_id="call-1",
            agent="agent-a",
            metadata={"to": "workspace-write"},
        )
        self.assertEqual(ALLOWED, "allowed-once")
        view = req.to_dict()
        self.assertEqual(view["tool"], "bash")
        self.assertEqual(view["agent"], "agent-a")
        self.assertEqual(view["metadata"], {"to": "workspace-write"})


if __name__ == "__main__":
    unittest.main()
