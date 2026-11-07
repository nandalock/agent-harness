from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class _Connection:
    def __init__(self):
        self.calls = []

    async def dispatch_json(self, raw, *, tenant_id, session_id=None, cancel=None):
        self.calls.append((raw, tenant_id, session_id))
        return {"jsonrpc": "2.0", "id": "x", "result": {"ok": True}}


def test_rpc_endpoint_delegates_tenant_and_session():
    connection = _Connection()
    client = TestClient(create_app(connection))
    response = client.post(
        "/api/rpc",
        json={"jsonrpc": "2.0", "id": "x", "method": "workspace.projects.list", "params": {}},
        headers={"X-Tenant-ID": "7", "X-Session-ID": "s1"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True}
    assert connection.calls[0][1:] == (7, "s1")
