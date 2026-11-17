"""Explicitly enabled integration acceptance against the shared test account."""

import json
import os
import uuid

import pytest

from app.config import Settings
from app.creator import create_campaign
from app.editor import cancel_stream, edit_offer, publish_stream, sync_campaign
from app.errors import DomainError
from app.keitaro import KeitaroClient
from app.schemas import PREFIX, CreateCampaign

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_KEITARO_LIVE") != "1",
    reason="Requires explicit RUN_KEITARO_LIVE=1 and test-account credentials",
)


def test_live_editor_acceptance(sessions):
    settings = Settings()
    created = None
    report = {"checks": []}
    with KeitaroClient(
        settings.keitaro_url, settings.keitaro_api_key.get_secret_value(), settings.keitaro_timeout
    ) as client:
        catalogs = client.catalogs()
        offers = client.search_offers("", limit=3)
        assert len(offers) == 3, "Live acceptance needs three existing offers"
        a, b, c = [offer["id"] for offer in offers]
        group = next(
            (group for group in catalogs["groups"] if group["name"] == "FORTESTS"),
            catalogs["groups"][0],
        )
        source = next(
            (source for source in catalogs["traffic_sources"] if source["name"] == "FORTESTS"),
            catalogs["traffic_sources"][0],
        )
        operation = "editor-live-" + uuid.uuid4().hex
        request = CreateCampaign(
            name="editor_smoke_" + uuid.uuid4().hex[:10],
            countries=["AU"],
            offer_id=a,
            domain_id=catalogs["domains"][0]["id"],
            group_id=group["id"],
            traffic_source_id=source["id"],
        )
        try:
            with sessions() as db:
                try:
                    created = create_campaign(db, client, request, operation)
                except DomainError as error:
                    if error.details.get("campaign_id") is not None:
                        created = {"campaign_id": error.details["campaign_id"]}
                    raise
                campaign = sync_campaign(db, client, created["campaign_id"])
                stream = next(s for s in campaign["streams"] if s["editable"])
                sid = stream["id"]
                report.update(
                    campaign_id=campaign["id"],
                    name=campaign["name"],
                    stream_id=sid,
                    offer_ids=[a, b, c],
                )
                # Each remote write below is limited to the campaign created by this run.
                assert campaign["name"] == request.name and campaign["name"].startswith(PREFIX)
                assert client.get(f"streams/{sid}")["campaign_id"] == campaign["id"]

                stream = edit_offer(db, client, sid, stream["revision"], b, "add")
                stream = cancel_stream(db, sid, stream["revision"])
                assert [o["offer_id"] for o in stream["offers"]] == [a]
                assert len(client.get(f"streams/{sid}")["offers"]) == 1
                report["checks"].append("add_cancel")

                stream = edit_offer(db, client, sid, stream["revision"], b, "add")
                stream = edit_offer(db, client, sid, stream["revision"], c, "add")
                stream = edit_offer(db, client, sid, stream["revision"], a, "pin", 25)
                stream = publish_stream(db, client, sid, stream["revision"])
                actual = {o["offer_id"]: o["share"] for o in client.get(f"streams/{sid}")["offers"]}
                assert actual == {a: 25, b: 38, c: 37}
                report["checks"].append("add_pin_publish")

                stream = edit_offer(db, client, sid, stream["revision"], b, "remove")
                stream = publish_stream(db, client, sid, stream["revision"])
                assert next(o for o in stream["offers"] if o["offer_id"] == b)["archived"]
                assert b not in {o["offer_id"] for o in client.get(f"streams/{sid}")["offers"]}
                stream = edit_offer(db, client, sid, stream["revision"], b, "restore")
                stream = publish_stream(db, client, sid, stream["revision"])
                report["checks"].append("remove_restore_publish")

                stream = edit_offer(db, client, sid, stream["revision"], c, "pin", 0)
                stream = publish_stream(db, client, sid, stream["revision"])
                assert {
                    o["offer_id"]: o["share"] for o in client.get(f"streams/{sid}")["offers"]
                } == {a: 25, b: 75, c: 0}
                report["checks"].append("zero_pin_publish")

                client.put(
                    f"streams/{sid}",
                    {
                        "offers": [
                            {"offer_id": a, "share": 100, "state": "active"},
                            {"offer_id": c, "share": 0, "state": "active"},
                        ]
                    },
                )
                stream = next(
                    s
                    for s in sync_campaign(db, client, campaign["id"])["streams"]
                    if s["id"] == sid
                )
                assert next(o for o in stream["offers"] if o["offer_id"] == b)["archived"]
                assert next(o for o in stream["offers"] if o["offer_id"] == a)["pin"] is None
                stream = edit_offer(db, client, sid, stream["revision"], b, "restore")
                stream = publish_stream(db, client, sid, stream["revision"])
                assert stream["total"] == 100 and not stream["dirty"]
                report["checks"].append("external_remove_sync_restore")
        finally:
            if created is not None:
                cid = created["campaign_id"]
                remote = client.get(f"campaigns/{cid}")
                assert remote["name"] == request.name and remote["name"].startswith(PREFIX)
                client.put(f"campaigns/{cid}", {"state": "disabled"})
                report["final_state"] = client.get(f"campaigns/{cid}")["state"]
                assert report["final_state"] == "disabled"
                print(json.dumps(report, ensure_ascii=False))
