"""Opt-in acceptance through HTTP routes; never targets an existing campaign."""

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.keitaro import KeitaroClient
from app.main import create_app
from app.schemas import PREFIX

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HTTP_LIVE") != "1",
    reason="Requires RUN_HTTP_LIVE=1 and test-account credentials",
)


def test_live_http_acceptance(sessions):
    settings = Settings(database_url=str(sessions.kw["bind"].url), allowed_hosts=["testserver"])
    report = {"checks": []}
    cid = None
    name = PREFIX + "http_smoke_" + uuid.uuid4().hex[:10]
    key = "http-live-" + uuid.uuid4().hex
    with (
        KeitaroClient(
            settings.keitaro_url,
            settings.keitaro_api_key.get_secret_value(),
            settings.keitaro_timeout,
        ) as remote,
        TestClient(
            create_app(settings, remote), headers={"Content-Type": "application/json"}
        ) as api,
    ):

        def ok(response, status=200):
            assert response.status_code == status, response.json()
            return response.json()

        try:
            catalogs = ok(api.get("/api/catalogs"))
            offers = ok(api.get("/api/offers"))[:3]
            assert len(offers) == 3
            a, b, c = [row["id"] for row in offers]
            body = {
                "name": name,
                "countries": ["AU", "MX"],
                "offer_id": a,
                "domain_id": catalogs["domains"][0]["id"],
                "group_id": next(
                    (x for x in catalogs["groups"] if x["name"] == "FORTESTS"),
                    catalogs["groups"][0],
                )["id"],
                "traffic_source_id": next(
                    (x for x in catalogs["traffic_sources"] if x["name"] == "FORTESTS"),
                    catalogs["traffic_sources"][0],
                )["id"],
            }
            response = api.post("/api/campaigns", json=body, headers={"Idempotency-Key": key})
            if response.status_code != 201:
                cid = response.json().get("error", {}).get("details", {}).get("campaign_id")
            result = ok(response, 201)
            cid = result["campaign_id"]
            assert (
                ok(api.post("/api/campaigns", json=body, headers={"Idempotency-Key": key}), 201)[
                    "campaign_id"
                ]
                == cid
            )
            campaign = ok(api.post(f"/api/campaigns/{cid}/sync"))
            assert campaign["name"] == name and name.startswith(PREFIX)
            assert len(campaign["streams"]) == 2
            stream = next(s for s in campaign["streams"] if s["editable"])
            sid = stream["id"]
            assert remote.get(f"streams/{sid}")["campaign_id"] == cid
            geo_before = remote.get(
                f"streams/{next(s['id'] for s in campaign['streams'] if not s['editable'])}"
            )
            report.update(campaign_id=cid, name=name, stream_id=sid, offer_ids=[a, b, c])
            report["checks"].append("create_idempotency_two_streams")

            def action(action_name, oid=None, pin=None):
                nonlocal stream
                data = {"revision": stream["revision"]}
                if action_name == "add":
                    response = api.post(
                        f"/api/streams/{sid}/offers", json={**data, "offer_id": oid}
                    )
                elif action_name in {"cancel", "publish"}:
                    response = api.post(f"/api/streams/{sid}/{action_name}", json=data)
                else:
                    data["action"] = action_name
                    if pin is not None:
                        data["pin"] = pin
                    response = api.patch(f"/api/streams/{sid}/offers/{oid}", json=data)
                stream = ok(response)

            action("add", b)
            action("cancel")
            assert len(stream["offers"]) == 1
            assert len(remote.get(f"streams/{sid}")["offers"]) == 1
            report["checks"].append("add_cancel")
            action("add", b)
            action("add", c)
            action("pin", a, 25)
            action("publish")
            assert {o["offer_id"]: o["share"] for o in remote.get(f"streams/{sid}")["offers"]} == {
                a: 25,
                b: 38,
                c: 37,
            }
            action("remove", b)
            action("publish")
            assert b not in {o["offer_id"] for o in remote.get(f"streams/{sid}")["offers"]}
            assert next(o for o in stream["offers"] if o["offer_id"] == b)["archived"]
            action("restore", b)
            action("publish")
            report["checks"].append("pin_remove_restore_publish")
            remote.put(
                f"streams/{sid}",
                {
                    "offers": [
                        {"offer_id": a, "share": 25, "state": "active"},
                        {"offer_id": c, "share": 75, "state": "active"},
                    ]
                },
            )
            stream = next(
                s for s in ok(api.post(f"/api/campaigns/{cid}/sync"))["streams"] if s["id"] == sid
            )
            assert next(o for o in stream["offers"] if o["offer_id"] == b)["archived"]
            action("restore", b)
            action("publish")
            assert not stream["dirty"] and stream["total"] == 100
            assert remote.get(f"streams/{geo_before['id']}") == geo_before
            report["checks"].append("external_remove_sync_restore_geo_unchanged")
        finally:
            if cid is not None:
                actual = remote.get(f"campaigns/{cid}")
                assert actual["name"] == name and name.startswith(PREFIX)
                remote.put(f"campaigns/{cid}", {"state": "disabled"})
                report["final_state"] = remote.get(f"campaigns/{cid}")["state"]
                assert report["final_state"] == "disabled"
                print(json.dumps(report, ensure_ascii=False))
