from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class FakeWorkflow:
    def __init__(self):
        self.saved = None

    async def list(self, tenant_id):
        return [{"id": 1, "tenant_id": tenant_id}]

    async def create(self, tenant_id, name, nodes=None, edges=None):
        return {"id": 9, "name": name}

    async def get(self, workflow_id):
        return {"id": workflow_id, "nodes": [], "edges": []}

    async def save(self, workflow_id, **fields):
        self.saved = (workflow_id, fields)

    async def delete(self, workflow_id):
        return None

    async def run(self, workflow_id, payload):
        yield {"type": "node_done", "node_id": "n1", "output": "hello"}
        yield {"type": "workflow_done", "output": "hello"}


def test_workflow_routes_delegate_to_the_service():
    service = FakeWorkflow()
    client = TestClient(create_app(workflow=service))

    assert client.get("/api/workflows?tenant_id=7").json() == {
        "items": [{"id": 1, "tenant_id": 7}],
    }
    assert client.post("/api/workflows", json={"name": "demo"}).json() == {
        "id": 9, "name": "demo",
    }
    assert client.get("/api/workflows/3").json()["id"] == 3

    saved = client.put("/api/workflows/3", json={"status": "published"})
    assert saved.status_code == 200
    assert service.saved == (3, {
        "name": None, "status": "published", "nodes": None, "edges": None,
    })

    run = client.post("/api/workflows/3/run", json={"input": "hi"})
    assert run.status_code == 200
    assert run.headers["content-type"].startswith("text/event-stream")
    assert '"type": "workflow_done"' in run.text
    assert '"output": "hello"' in run.text


def test_workflow_routes_are_absent_without_the_plugin():
    client = TestClient(create_app())
    assert client.get("/api/workflows").status_code == 404
