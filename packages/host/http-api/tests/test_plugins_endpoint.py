from fastapi.testclient import TestClient

from agent_platform_http_api import create_app
from agent_platform_plugin_inventory.client import ClientModule


class Catalog:
    def clients(self):
        return (ClientModule(id="@app/plugin-workflow", rev="1234567890abcdef", inject=("@app/plugin-shell",)),)

    def script(self, client_id, revision):
        entry, = self.clients()
        if (client_id, revision) == (entry.id, entry.rev):
            return b"/* workflow browser entry */"
        return None

    def list(self):
        return [
            {"id": "http-api", "name": "agent-platform.http-api", "version": "0.1.0"},
            {"id": "workflow", "name": "agent-platform.workflow", "version": "0.1.0"},
        ]


def test_plugins_endpoint_lists_started_instances():
    client = TestClient(create_app(plugin_catalog=Catalog()))
    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert response.json()["plugins"] == Catalog().list()
    entry, = response.json()["clients"]
    assert entry["id"] == "@app/plugin-workflow"
    script = client.get(entry["url"])
    assert script.content == b"/* workflow browser entry */"
    assert script.headers["content-type"].startswith("application/javascript")
    assert client.get(entry["url"].replace("1234567890abcdef", "obsolete")).status_code == 404
    assert client.get(entry["url"].replace("plugin-workflow", "plugin-disabled")).status_code == 404


def test_plugins_endpoint_is_unavailable_without_catalog():
    client = TestClient(create_app())
    response = client.get("/api/plugins")
    assert response.status_code == 503
