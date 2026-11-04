import asyncio
import unittest

from backend.services.chat.live import LiveRun, LiveRunConflict, LiveRunRegistry


def _run(**overrides) -> LiveRun:
    values = dict(
        session_id="s1", tenant_id=1, agent_key="default",
        conversation_id=7, agent_name="默认智能体", question="hi",
    )
    values.update(overrides)
    return LiveRun(**values)


class LiveRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_reaches_every_subscriber(self):
        run = _run()
        first, second = run.subscribe(), run.subscribe()
        run.publish({"type": "traj/open", "node": {"id": "n1"}})
        self.assertEqual((await first.get())["type"], "traj/open")
        self.assertEqual((await second.get())["type"], "traj/open")
        run.unsubscribe(first)
        run.publish({"type": "usage", "step": 1})
        self.assertEqual((await second.get())["type"], "usage")
        self.assertTrue(first.empty())

    async def test_snapshot_contains_nodes_usage_and_pending_approvals(self):
        run = _run()
        run.set_snapshot(lambda: {"nodes": [{"id": "n1"}], "usage": [{"step": 1}]})
        run.publish({
            "type": "approval.request", "tool": "bash",
            "data": {"approval_id": "a1", "reason": "need write", "metadata": {"to": "workspace-write"}},
        })
        snapshot = run.snapshot()
        self.assertEqual(snapshot["nodes"], [{"id": "n1"}])
        self.assertEqual(snapshot["usage"], [{"step": 1}])
        self.assertEqual(snapshot["pending_approvals"][0]["tool"], "bash")

        run.publish({"type": "sandbox.escalation", "data": {"approval_id": "a1"}})
        self.assertEqual(run.snapshot()["pending_approvals"], [])

    async def test_granted_escalation_clears_stale_pending_card(self):
        run = _run()
        run.publish({
            "type": "approval.request", "tool": "bash",
            "data": {"approval_id": "a2", "reason": "need write"},
        })
        run.publish({"type": "sandbox.escalation", "data": {"granted": True, "approval_id": None}})
        self.assertEqual(run.snapshot()["pending_approvals"], [])

    async def test_finish_wakes_blocked_subscribers(self):
        run = _run()
        queue = run.subscribe()
        run.publish({"type": "done", "answer": "ok"})
        run.finish()
        self.assertEqual((await queue.get())["type"], "done")
        self.assertIsNone(await queue.get())
        self.assertTrue(run.done)

    async def test_cancel_only_sets_the_signal(self):
        run = _run()
        self.assertFalse(run.cancel_event.is_set())
        run.cancel()
        self.assertTrue(run.cancel_event.is_set())


class LiveRunRegistryTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_rejects_a_second_run_for_the_same_session(self):
        registry = LiveRunRegistry()
        run = registry.start(**dict(
            session_id="s1", tenant_id=1, agent_key="default",
            conversation_id=7, agent_name="默认智能体", question="hi",
        ))
        with self.assertRaises(LiveRunConflict):
            registry.start(**dict(
                session_id="s1", tenant_id=1, agent_key="default",
                conversation_id=7, agent_name="默认智能体", question="again",
            ))
        registry.finish(run)
        self.assertIsNone(registry.get("s1"))

    async def test_finish_does_not_remove_a_newer_run(self):
        registry = LiveRunRegistry()
        old = registry.start(**dict(
            session_id="s1", tenant_id=1, agent_key="default",
            conversation_id=7, agent_name="默认智能体", question="hi",
        ))
        registry.finish(old)
        new = registry.start(**dict(
            session_id="s1", tenant_id=1, agent_key="default",
            conversation_id=7, agent_name="默认智能体", question="next",
        ))
        registry.finish(old)
        self.assertIs(registry.get("s1"), new)


if __name__ == "__main__":
    unittest.main()
