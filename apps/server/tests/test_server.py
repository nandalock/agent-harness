import unittest

from agent_platform_server import RuntimeASGIApp, app


class ServerEntryTests(unittest.TestCase):
    def test_asgi_entry_exposes_the_carrier(self):
        self.assertIsInstance(app, RuntimeASGIApp)
        self.assertTrue(callable(app))


def test_release_shell_preserves_api_errors_and_supports_spa_paths(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_platform_server.web import BrowserShell

    (tmp_path / "index.html").write_text("<title>minidsh</title>", encoding="utf-8")
    (tmp_path / "main.js").write_text("window.loaded = true;", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/plugins")
    def catalog():
        return {"plugins": []}

    app.mount("/", BrowserShell(directory=tmp_path, html=True))
    client = TestClient(app)
    headers = {"Accept": "text/html"}
    assert client.get("/dashboard/workspace", headers=headers).text == "<title>minidsh</title>"
    assert client.get("/main.js").text == "window.loaded = true;"
    assert client.get("/api/plugins").json() == {"plugins": []}
    assert client.get("/api/unknown", headers=headers).status_code == 404
    assert client.get("/assets/missing.js", headers=headers).status_code == 404
