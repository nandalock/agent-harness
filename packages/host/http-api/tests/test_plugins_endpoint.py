from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class Catalog:
    def list(self):
        return [
            {"id": "http-api", "name": "agent-platform.http-api", "version": "0.1.0"},
            {"id": "workflow", "name": "agent-platform.workflow", "version": "0.1.0"},
        ]


def test_plugins_endpoint_lists_started_instances():
    client = TestClient(create_app(plugin_catalog=Catalog()))
    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert response.json() == {"plugins": Catalog().list()}


def test_plugins_endpoint_is_unavailable_without_catalog():
    client = TestClient(create_app())
    response = client.get("/api/plugins")
    assert response.status_code == 503
