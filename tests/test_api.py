import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def api(tracker, sessions):
    engine_url = str(sessions.kw["bind"].url)
    application = create_app(
        Settings(database_url=engine_url, keitaro_api_key="unused", allowed_hosts=["testserver"]),
        tracker.client,
    )
    with TestClient(application, headers={"Content-Type": "application/json"}) as client:
        yield client


def test_health_catalogs_and_search(api):
    assert api.get("/api/health").json()["status"] == "ok"
    assert api.get("/api/catalogs").json()["domains"][0]["id"] == 1
    assert api.get("/api/offers", params={"q": "12"}).json()[0]["id"] == 12
    assert api.get("/api/campaigns", params={"q": "existing"}).json()[0]["id"] == 100
    assert api.get("/api/campaigns", params={"q": "no-match"}).json() == []


def test_editor_http_flow_and_revision(api):
    assert api.get("/api/campaigns/100").status_code == 404
    initial = api.post("/api/campaigns/100/sync").json()
    stream = initial["streams"][1]
    changed = api.post(
        "/api/streams/201/offers", json={"offer_id": 12, "revision": stream["revision"]}
    )
    assert changed.status_code == 200
    revision = changed.json()["revision"]
    assert (
        api.post("/api/streams/201/cancel", json={"revision": stream["revision"]}).status_code
        == 409
    )
    assert api.post("/api/campaigns/100/sync").status_code == 409
    assert (
        api.post("/api/streams/201/publish", json={"revision": revision}).json()["dirty"] is False
    )
    data = api.get("/api/campaigns/100").json()["streams"][1]
    assert data["active_count"] == 3


def test_create_idempotency_and_operation_status(api):
    body = {
        "name": "demo",
        "countries": ["AU"],
        "offer_id": 10,
        "domain_id": 1,
        "group_id": 2,
        "traffic_source_id": 3,
    }
    headers = {"Idempotency-Key": "http-create-key-1"}
    result = api.post("/api/campaigns", json=body, headers=headers)
    assert result.status_code == 201
    again = api.post("/api/campaigns", json=body, headers=headers)
    assert again.json()["campaign_id"] == result.json()["campaign_id"]
    operation = api.get("/api/operations/http-create-key-1").json()
    assert operation["phase"] == "complete"
    assert api.get("/api/operations/nonexistent").status_code == 404


def test_validation_errors_and_safe_integration_error(api, tracker):
    result = api.post("/api/campaigns", json={"name": "bad"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "validation_error"
    tracker.fail_status["GET offers"] = 401
    result = api.get("/api/offers", params={"q": "12"})
    assert result.status_code == 502
    assert "fake-test-key" not in result.text


def test_cross_origin_write_and_dns_rebinding_are_rejected(api):
    response = api.post("/api/campaigns/100/sync", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403
    assert api.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    assert (
        api.post("/api/campaigns/100/sync", headers={"Origin": "http://testserver"}).status_code
        == 200
    )


def test_pin_requires_integer_and_no_extra_fields_are_accepted(api):
    stream = api.post("/api/campaigns/100/sync").json()["streams"][1]
    for value in [True, 1.5, -1, 101]:
        response = api.patch(
            "/api/streams/201/offers/10",
            json={"action": "pin", "pin": value, "revision": stream["revision"]},
        )
        assert response.status_code == 422


def test_zero_pin_and_extra_fields(api):
    stream = api.post("/api/campaigns/100/sync").json()["streams"][1]
    response = api.patch(
        "/api/streams/201/offers/10",
        json={"action": "pin", "pin": 0, "revision": stream["revision"]},
    )
    assert response.status_code == 200
    assert response.json()["offers"][0]["pin"] == 0
    assert response.json()["offers"][0]["active"] is True
    assert (
        api.post(
            "/api/streams/201/cancel", json={"revision": response.json()["revision"], "force": True}
        ).status_code
        == 422
    )


def test_non_json_writes_and_cross_site_without_origin_rejected(api, tracker):
    for headers, status in [
        ({"Content-Type": "text/plain"}, 415),
        ({"Content-Type": "application/x-www-form-urlencoded"}, 415),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Origin": "null"}, 403),
    ]:
        assert api.post("/api/campaigns/100/sync", headers=headers).status_code == status
    assert tracker.calls == []


def test_http_drafts_archive_cancel_and_external_conflict(api, tracker):
    stream = api.post("/api/campaigns/100/sync").json()["streams"][1]
    changed = api.patch(
        "/api/streams/201/offers/10", json={"action": "remove", "revision": stream["revision"]}
    ).json()
    assert changed["offers"][0]["archived"] and changed["offers"][0]["share"] == 0
    assert len(tracker.streams[201]["offers"]) == 2
    cancelled = api.post("/api/streams/201/cancel", json={"revision": changed["revision"]}).json()
    assert cancelled["offers"][0]["active"] and not cancelled["dirty"]
    changed = api.post(
        "/api/streams/201/offers", json={"offer_id": 12, "revision": cancelled["revision"]}
    ).json()
    tracker.streams[201]["offers"][0]["share"] = 60
    conflict = api.post("/api/streams/201/publish", json={"revision": changed["revision"]})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "remote_conflict"
    assert api.get("/api/campaigns/100").json()["streams"][1]["dirty"]


def test_http_pending_reconciliation_never_repeats_write(api, tracker):
    stream = api.post("/api/campaigns/100/sync").json()["streams"][1]
    changed = api.post(
        "/api/streams/201/offers", json={"offer_id": 12, "revision": stream["revision"]}
    ).json()
    tracker.timeout_before.add("PUT streams/201")
    assert (
        api.post("/api/streams/201/publish", json={"revision": changed["revision"]}).status_code
        == 502
    )
    pending = api.get("/api/campaigns/100").json()["streams"][1]
    assert pending["pending"]
    assert (
        api.post("/api/streams/201/cancel", json={"revision": pending["revision"]}).status_code
        == 409
    )
    assert (
        api.post("/api/streams/201/publish", json={"revision": pending["revision"]}).status_code
        == 502
    )
    assert len([c for c in tracker.calls if c[:2] == ("PUT", "streams/201")]) == 1


def test_static_files_and_openapi_are_available_without_secrets(api):
    response = api.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "test_tsybizov_" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    for path in ["/static/app.js", "/static/style.css", "/openapi.json"]:
        result = api.get(path)
        assert result.status_code == 200
        assert "fake-test-key" not in result.text


def test_validation_does_not_echo_supplied_secret(api):
    response = api.post(
        "/api/streams/201/offers", json={"offer_id": "sensitive-input", "revision": 1}
    )
    assert response.status_code == 422
    assert "sensitive-input" not in response.text
