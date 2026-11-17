import pytest
from pydantic import ValidationError

from app.creator import create_campaign
from app.errors import DomainError
from app.models import Campaign, CreationOperation
from app.schemas import CreateCampaign


def request(**changes):
    return CreateCampaign(
        **{
            "name": "demo",
            "countries": ["au", "MX", "AU"],
            "offer_id": 10,
            "domain_id": 1,
            "group_id": 2,
            "traffic_source_id": 3,
            **changes,
        }
    )


def test_creates_disabled_then_configured_campaign(db, tracker):
    result = create_campaign(db, tracker.client, request(), "create-key-1")
    campaign = tracker.campaigns[result["campaign_id"]]
    assert campaign["name"] == "test_tsybizov_demo"
    assert campaign["state"] == "active"
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (1, 2, 3)
    calls = [c for c in tracker.calls if c[0] != "GET"]
    assert [(c[0], c[1]) for c in calls] == [
        ("POST", "campaigns"),
        ("POST", "streams"),
        ("POST", "streams"),
        ("PUT", f"campaigns/{campaign['id']}"),
    ]
    assert calls[0][2]["state"] == "disabled"
    geo, fallback = calls[1][2], calls[2][2]
    assert geo["schema"] == "redirect"
    assert geo["action_type"] == "http"
    assert geo["action_payload"] == "https://google.com/"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert geo["type"] == "regular" and geo["position"] == 1
    assert fallback["type"] == "default" and fallback["position"] == 2
    assert fallback["offers"] == [{"offer_id": 10, "share": 100, "state": "active"}]
    assert db.get(Campaign, campaign["id"])
    assert result["tracking_url"].startswith("https://tracking.example/")


@pytest.mark.parametrize(
    "changes",
    [
        {"countries": ["XX"]},
        {"countries": []},
        {"name": "test_tsybizov_"},
        {"offer_id": 0},
        {"countries": ["AUS"]},
    ],
)
def test_invalid_form(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_campaign_name_preserves_corrected_prefix():
    assert request(name="test_tsybizov_demo").name == "test_tsybizov_demo"


@pytest.mark.parametrize(
    "changes",
    [{"offer_id": 999}, {"domain_id": 999}, {"group_id": 999}, {"traffic_source_id": 999}],
)
def test_invalid_remote_reference_prevents_writes(db, tracker, changes):
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(**changes), "invalid-key-1")
    assert not any(method != "GET" for method, *_ in tracker.calls)


def test_idempotency_key_reuses_result_and_rejects_other_payload(db, tracker):
    first = create_campaign(db, tracker.client, request(), "create-key-1")
    count = len(tracker.calls)
    assert create_campaign(db, tracker.client, request(), "create-key-1") == first
    assert len(tracker.calls) == count
    with pytest.raises(DomainError) as error:
        create_campaign(db, tracker.client, request(name="other"), "create-key-1")
    assert error.value.status == 409


def test_partial_failure_leaves_disabled_campaign_and_does_not_retry(db, tracker):
    tracker.fail_stream_number = 2
    with pytest.raises(DomainError) as error:
        create_campaign(db, tracker.client, request(), "partial-key-1")
    op = db.get(CreationOperation, "partial-key-1")
    assert op.campaign_id is not None
    assert tracker.campaigns[op.campaign_id]["state"] == "disabled"
    assert error.value.details["campaign_id"] == op.campaign_id
    writes = len([c for c in tracker.calls if c[0] != "GET"])
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(), "partial-key-1")
    assert len([c for c in tracker.calls if c[0] != "GET"]) == writes


def test_lost_campaign_response_is_reconciled_by_alias_without_second_post(db, tracker):
    tracker.timeout_after.add("POST campaigns")
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(), "lost-key-1")
    op = db.get(CreationOperation, "lost-key-1")
    assert op.campaign_id is not None
    assert tracker.campaigns[op.campaign_id]["state"] == "disabled"
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(), "lost-key-1")
    assert sum(c[0:2] == ("POST", "campaigns") for c in tracker.calls) == 1


def test_lost_activation_response_reads_actual_state(db, tracker):
    tracker.timeout_after.add("PUT campaigns/101")
    result = create_campaign(db, tracker.client, request(), "activation-key-1")
    assert result["phase"] == "complete"
    assert tracker.campaigns[result["campaign_id"]]["state"] == "active"


def test_stream_configuration_is_verified_before_activation(db, tracker):
    original = tracker.client.post

    def ignore_url(path, body):
        result = original(path, body)
        if path == "streams" and body["schema"] == "redirect":
            tracker.streams[result["id"]]["action_payload"] = ""
        return result

    tracker.client.post = ignore_url
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(), "verify-key-1")
    assert tracker.campaigns[101]["state"] == "disabled"


def test_unavailable_read_after_activation_is_unknown(db, tracker):
    tracker.timeout_after.add("PUT campaigns/101")
    tracker.timeout_before.add("GET campaigns/101")
    with pytest.raises(DomainError):
        create_campaign(db, tracker.client, request(), "unknown-key-1")
    assert db.get(CreationOperation, "unknown-key-1").phase.endswith("_unknown")


@pytest.mark.parametrize("change", ["extra_filter", "landing", "null_url", "null_filters"])
def test_unexpected_readback_is_a_controlled_failure(db, tracker, change):
    original = tracker.client.post

    def altered(path, body):
        result = original(path, body)
        if path == "streams":
            flow = tracker.streams[result["id"]]
            if body["schema"] == "redirect":
                if change == "extra_filter":
                    flow["filters"].append(
                        {"name": "device_type", "mode": "accept", "payload": ["mobile"]}
                    )
                elif change == "null_url":
                    flow["action_payload"] = None
                elif change == "null_filters":
                    flow["filters"] = None
            elif change == "landing":
                flow["landings"] = [{"landing_id": 88, "share": 100}]
        return result

    tracker.client.post = altered
    with pytest.raises(DomainError) as error:
        create_campaign(db, tracker.client, request(), "readback-key-1")
    op = db.get(CreationOperation, "readback-key-1")
    assert op.campaign_id == 101 and op.phase.endswith("_failed")
    assert error.value.details["campaign_id"] == 101
    assert tracker.campaigns[101]["state"] == "disabled"
    assert not any(c[0] == "PUT" for c in tracker.calls)


def test_idempotency_survives_a_new_database_session(sessions, db, tracker):
    result = create_campaign(db, tracker.client, request(), "persistent-key-1")
    calls = len(tracker.calls)
    with sessions() as fresh:
        assert create_campaign(fresh, tracker.client, request(), "persistent-key-1") == result
    assert len(tracker.calls) == calls


def test_completed_operation_without_result_does_not_return_none(db, tracker):
    create_campaign(db, tracker.client, request(), "missing-result-key-1")
    operation = db.get(CreationOperation, "missing-result-key-1")
    assert operation is not None
    operation.result = None
    db.commit()
    calls = len(tracker.calls)

    with pytest.raises(DomainError) as error:
        create_campaign(db, tracker.client, request(), "missing-result-key-1")

    assert error.value.status == 500
    assert error.value.code == "operation_corrupted"
    assert len(tracker.calls) == calls
