from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class FakeFAQ:
    def list(self, tenant_id, tag="", page=1, size=20):
        return [{"id": 1, "tenant_id": tenant_id}], 1

    def match(self, tenant_id, question, direct_threshold=0.95):
        return None


def test_faq_routes_delegate_to_the_plugin_service():
    client = TestClient(create_app(faq=FakeFAQ()))
    response = client.get("/api/faqs", headers={"X-Tenant-ID": "7"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["tenant_id"] == 7

    match = client.post(
        "/api/faqs/match",
        headers={"X-Tenant-ID": "7"},
        json={"question": "如何退货"},
    )
    assert match.status_code == 200
    assert match.json()["matched"] is False


def test_faq_routes_are_absent_without_the_plugin():
    client = TestClient(create_app())
    assert client.get("/api/faqs", headers={"X-Tenant-ID": "1"}).status_code == 404
