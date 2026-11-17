from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event, Lock

import pytest

from app.editor import campaign_view, cancel_stream, edit_offer, publish_stream, sync_campaign
from app.errors import DomainError, RemoteError
from app.models import Offer, Stream


def load(db, tracker):
    sync_campaign(db, tracker.client, 100)
    return next(s for s in campaign_view(db, 100)["streams"] if s["id"] == 201)


def edit(db, tracker, offer_id, action, pin=None):
    return edit_offer(db, tracker.client, 201, db.get(Stream, 201).revision, offer_id, action, pin)


def publish(db, tracker):
    return publish_stream(db, tracker.client, 201, db.get(Stream, 201).revision)


def row(view, offer_id):
    return next(o for o in view["offers"] if o["offer_id"] == offer_id)


def test_import_no_offer_stream_and_preserve_weights(db, tracker):
    before = deepcopy(tracker.streams)
    view = load(db, tracker)
    assert [o["share"] for o in view["offers"]] == [50, 50]
    geo = campaign_view(db, 100)["streams"][0]
    assert geo["offers"] == [] and not geo["editable"]
    assert "filters" not in geo and "action_payload" not in geo
    assert tracker.streams == before


def test_add_cancel_and_persistence(sessions, db, tracker):
    load(db, tracker)
    view = edit(db, tracker, 12, "add")
    assert view["dirty"] and [o["share"] for o in view["offers"]] == [34, 33, 33]
    assert len(tracker.streams[201]["offers"]) == 2
    with sessions() as fresh:
        assert campaign_view(fresh, 100)["streams"][1]["dirty"]
    view = cancel_stream(db, 201, view["revision"])
    assert not view["dirty"] and len(view["offers"]) == 2
    assert db.get(Offer, 12) is not None


def test_remove_publish_archive_restore(db, tracker):
    load(db, tracker)
    view = edit(db, tracker, 10, "remove")
    assert not row(view, 10)["active"] and row(view, 10)["share"] == 0
    assert row(view, 11)["share"] == 100
    view = publish(db, tracker)
    assert not view["dirty"] and len(view["offers"]) == 2
    assert tracker.streams[201]["offers"] == [{"offer_id": 11, "share": 100, "state": "active"}]
    assert row(view, 10)["archived"]
    view = edit(db, tracker, 10, "restore")
    assert view["dirty"] and row(view, 10)["share"] == 50
    view = publish(db, tracker)
    assert not view["dirty"] and len(tracker.streams[201]["offers"]) == 2
    assert set(tracker.streams[201]) >= {"filters", "landings"}
    writes = [c for c in tracker.calls if c[0] == "PUT"]
    assert all(set(c[2]) == {"offers"} for c in writes)


def test_external_removal_including_last_can_be_restored(db, tracker):
    load(db, tracker)
    tracker.streams[201]["offers"] = []
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert view["editable"] and all(o["archived"] for o in view["offers"])
    edit(db, tracker, 10, "restore")
    publish(db, tracker)
    assert tracker.streams[201]["offers"][0]["offer_id"] == 10


def test_sync_refuses_dirty_and_missing_stream_stays_in_archive(db, tracker):
    view = load(db, tracker)
    edit(db, tracker, 12, "add")
    with pytest.raises(DomainError) as error:
        sync_campaign(db, tracker.client, 100)
    assert error.value.status == 409
    cancel_stream(db, 201, db.get(Stream, 201).revision)
    del tracker.streams[201]
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert view["missing"] and not view["editable"] and len(view["offers"]) == 2


def test_stale_revision_and_duplicate_are_atomic(db, tracker):
    view = load(db, tracker)
    edit(db, tracker, 12, "add")
    with pytest.raises(DomainError) as error:
        edit_offer(db, tracker.client, 201, view["revision"], 13, "add")
    assert error.value.status == 409
    with pytest.raises(DomainError):
        edit(db, tracker, 12, "add")
    assert len(campaign_view(db, 100)["streams"][1]["offers"]) == 3


def test_pins_cancel_and_invalid_budget_leave_original_state(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "pin", 25)
    view = edit(db, tracker, 12, "add")
    assert [o["share"] for o in view["offers"]] == [25, 38, 37]
    with pytest.raises(DomainError):
        edit(db, tracker, 11, "pin", 100)
    db.rollback()
    view = campaign_view(db, 100)["streams"][1]
    assert [o["share"] for o in view["offers"]] == [25, 38, 37]
    view = cancel_stream(db, 201, view["revision"])
    assert row(view, 10)["pin"] is None


def test_external_pin_changes_are_reported(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "pin", 25)
    publish(db, tracker)
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert row(view, 10)["pin"] == 25
    tracker.streams[201]["offers"][0]["share"] = 30
    tracker.streams[201]["offers"][1]["share"] = 70
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert row(view, 10)["pin"] is None and row(view, 10)["share"] == 30
    assert view["notice"]


def test_conflict_preserves_draft_and_never_puts(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.streams[201]["offers"] = [{"offer_id": 10, "share": 100, "state": "active"}]
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.status == 409
    assert db.get(Stream, 201).dirty
    assert not [c for c in tracker.calls if c[0] == "PUT"]


def test_empty_draft_cannot_publish_and_cancel_restores(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "remove")
    view = edit(db, tracker, 11, "remove")
    assert view["total"] == 0
    with pytest.raises(DomainError):
        publish(db, tracker)
    view = cancel_stream(db, 201, view["revision"])
    assert view["total"] == 100


def test_lost_put_response_after_apply_is_success(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.timeout_after.add("PUT streams/201")
    view = publish(db, tracker)
    assert not view["dirty"] and not view["pending"]
    assert len(tracker.streams[201]["offers"]) == 3
    assert sum(c[0:2] == ("PUT", "streams/201") for c in tracker.calls) == 1


def test_uncertain_put_blocks_edits_until_reconciliation(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.timeout_before.add("PUT streams/201")
    # The preflight GET succeeds, then the post-write GET times out.
    original = tracker.client.put

    def put(*args):
        tracker.timeout_before.add("GET streams/201")
        return original(*args)

    tracker.client.put = put
    with pytest.raises(DomainError):
        publish(db, tracker)
    assert db.get(Stream, 201).pending
    with pytest.raises(DomainError):
        edit(db, tracker, 13, "add")
    with pytest.raises(DomainError):
        cancel_stream(db, 201, db.get(Stream, 201).revision)
    tracker.client.put = original
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.code == "publication_pending"
    assert db.get(Stream, 201).pending is not None
    # A late response can still apply after the client timeout.
    tracker.streams[201]["offers"] = deepcopy(db.get(Stream, 201).pending["target"]["offers"])
    view = publish(db, tracker)
    assert not view["dirty"] and not view["pending"]


def test_publication_intent_survives_new_session(sessions, db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    original = tracker.client.put

    def lost_after_apply(*args):
        result = original(*args)
        tracker.timeout_before.add("GET streams/201")
        return result

    tracker.client.put = lost_after_apply
    with pytest.raises(DomainError):
        publish(db, tracker)
    assert db.get(Stream, 201).pending
    tracker.client.put = original
    with sessions() as fresh:
        view = publish_stream(fresh, tracker.client, 201, fresh.get(Stream, 201).revision)
        assert not view["dirty"]
    assert sum(c[0:2] == ("PUT", "streams/201") for c in tracker.calls) == 1


def test_redirect_stream_cannot_be_edited_and_deleted_offer_rejected(db, tracker):
    load(db, tracker)
    with pytest.raises(DomainError):
        edit_offer(db, tracker.client, 200, db.get(Stream, 200).revision, 12, "add")
    tracker.offers[12]["state"] = "deleted"
    with pytest.raises(DomainError):
        edit(db, tracker, 12, "add")


def test_sync_preserves_nonuniform_weights_and_external_additions(db, tracker):
    tracker.streams[201]["offers"][0]["share"] = 40
    tracker.streams[201]["offers"][1]["share"] = 60
    view = load(db, tracker)
    assert [o["share"] for o in view["offers"]] == [40, 60]
    tracker.streams[201]["offers"] = [{"offer_id": 12, "share": 100, "state": "active"}]
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert row(view, 12)["active"] and row(view, 12)["share"] == 100
    assert row(view, 10)["archived"] and row(view, 11)["archived"]
    assert not view["dirty"]


def test_zero_pin_is_active_and_unpin_creates_local_draft(db, tracker):
    load(db, tracker)
    view = edit(db, tracker, 10, "pin", 0)
    assert row(view, 10)["active"] and row(view, 10)["pin"] == 0
    assert [o["share"] for o in view["offers"]] == [0, 100]
    publish(db, tracker)
    view = edit(db, tracker, 10, "unpin")
    assert row(view, 10)["pin"] is None and view["dirty"]
    assert [o["share"] for o in view["offers"]] == [50, 50]
    view = cancel_stream(db, 201, view["revision"])
    assert row(view, 10)["pin"] == 0 and not view["dirty"]


def test_remove_unpublished_offer_drops_only_new_binding(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    view = edit(db, tracker, 12, "remove")
    assert len(view["offers"]) == 2 and not view["dirty"]
    assert db.get(Offer, 12) is not None


def test_cancel_removal_and_restore_retains_published_archive(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "pin", 25)
    publish(db, tracker)
    edit(db, tracker, 10, "remove")
    view = cancel_stream(db, 201, db.get(Stream, 201).revision)
    assert row(view, 10)["active"] and row(view, 10)["pin"] == 25
    edit(db, tracker, 10, "remove")
    publish(db, tracker)
    edit(db, tracker, 10, "restore")
    view = cancel_stream(db, 201, db.get(Stream, 201).revision)
    assert row(view, 10)["archived"] and row(view, 10)["pin"] == 25


def test_external_restore_preserves_matching_archived_pin(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "pin", 25)
    publish(db, tracker)
    tracker.streams[201]["offers"] = [{"offer_id": 11, "share": 100, "state": "active"}]
    sync_campaign(db, tracker.client, 100)
    tracker.streams[201]["offers"] = [
        {"offer_id": 10, "share": 25, "state": "active"},
        {"offer_id": 11, "share": 75, "state": "active"},
    ]
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert row(view, 10)["pin"] == 25


@pytest.mark.parametrize(
    "bad_offers",
    [
        None,
        [{"offer_id": 10, "share": 1.5}],
        [{"offer_id": True, "share": 100}],
        [{"offer_id": 10, "share": 100}, {"offer_id": 10, "share": 0}],
    ],
)
def test_malformed_sync_is_rejected_before_changing_saved_state(db, tracker, bad_offers):
    before = load(db, tracker)
    tracker.streams[200]["name"] = "Must not be saved"
    tracker.streams[201]["offers"] = bad_offers
    with pytest.raises(RemoteError):
        sync_campaign(db, tracker.client, 100)
    assert campaign_view(db, 100)["streams"][0]["name"] == "Geo"
    assert campaign_view(db, 100)["streams"][1] == before


def test_same_offer_imported_in_multiple_streams_is_one_global_offer(db, tracker):
    tracker.streams[202] = {**deepcopy(tracker.streams[201]), "id": 202, "position": 3}
    view = sync_campaign(db, tracker.client, 100)
    assert len(view["streams"]) == 3
    assert [o["offer_id"] for o in view["streams"][2]["offers"]] == [10, 11]


def test_reordering_and_other_stream_fields_do_not_cause_offer_conflict(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.streams[201]["offers"].reverse()
    tracker.streams[201]["filters"] = [{"new_filter": "preserve exactly"}]
    untouched = {
        key: deepcopy(value) for key, value in tracker.streams[201].items() if key != "offers"
    }
    publish(db, tracker)
    assert {
        key: value for key, value in tracker.streams[201].items() if key != "offers"
    } == untouched


def test_definite_put_error_keeps_draft_and_allows_cancel(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.fail_status["PUT streams/201"] = 403
    with pytest.raises(RemoteError):
        publish(db, tracker)
    stream = db.get(Stream, 201)
    assert stream.dirty and stream.pending is None
    assert not cancel_stream(db, 201, stream.revision)["dirty"]


def test_deleted_offer_at_publish_prevents_remote_write(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    tracker.offers[12]["state"] = "deleted"
    with pytest.raises(DomainError):
        publish(db, tracker)
    assert not [call for call in tracker.calls if call[0] == "PUT"]


def test_remote_missing_during_publish_can_be_cancelled_and_synced(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    del tracker.streams[201]
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.code == "remote_stream_missing"
    stream = db.get(Stream, 201)
    assert stream.missing and stream.dirty
    cancel_stream(db, 201, stream.revision)
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert view["missing"] and not view["dirty"]


def test_concurrent_edits_commit_only_one_revision(sessions, db, tracker):
    revision = load(db, tracker)["revision"]
    barrier = Barrier(2)
    original = tracker.client.offer

    def offer(offer_id):
        data = original(offer_id)
        barrier.wait(timeout=5)
        return data

    tracker.client.offer = offer

    def run(offer_id):
        with sessions() as session:
            try:
                return edit_offer(session, tracker.client, 201, revision, offer_id, "add")
            except DomainError as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [12, 13]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, DomainError) and result.code == "stale_revision"
            for result in results
        )
        == 1
    )
    view = campaign_view(db, 100)["streams"][1]
    assert view["total"] == 100 and view["active_count"] == 3 and view["dirty"]


def test_sync_does_not_overwrite_a_draft_created_while_reading(sessions, db, tracker):
    initial = load(db, tracker)
    reading, release = Event(), Event()
    original = tracker.client.get

    def get(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == "campaigns/100/streams":
            reading.set()
            assert release.wait(timeout=5)
        return result

    tracker.client.get = get

    def sync():
        with sessions() as session:
            return sync_campaign(session, tracker.client, 100)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(sync)
        try:
            assert reading.wait(timeout=5)
            edit_offer(db, tracker.client, 201, initial["revision"], 12, "add")
        finally:
            release.set()
        with pytest.raises(DomainError) as error:
            future.result(timeout=5)
        assert error.value.code == "stale_revision"
    view = campaign_view(db, 100)["streams"][1]
    assert view["dirty"] and view["active_count"] == 3 and view["total"] == 100


def test_publish_claim_detects_a_new_edit_before_put(sessions, db, tracker):
    load(db, tracker)
    initial = edit(db, tracker, 12, "add")
    reading, release = Event(), Event()
    original = tracker.client.offer

    def offer(offer_id):
        result = original(offer_id)
        if offer_id == 10:
            reading.set()
            assert release.wait(timeout=5)
        return result

    tracker.client.offer = offer

    def send():
        with sessions() as session:
            return publish_stream(session, tracker.client, 201, initial["revision"])

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send)
        try:
            assert reading.wait(timeout=5)
            edit(db, tracker, 13, "add")
        finally:
            release.set()
        with pytest.raises(DomainError) as error:
            future.result(timeout=5)
        assert error.value.code == "stale_revision"
    assert not [call for call in tracker.calls if call[0] == "PUT"]
    assert campaign_view(db, 100)["streams"][1]["active_count"] == 4


def test_pin_only_publish_does_not_resend_unchanged_remote_offers(db, tracker):
    load(db, tracker)
    edit(db, tracker, 10, "pin", 50)
    view = publish(db, tracker)
    assert not view["dirty"] and row(view, 10)["pin"] == 50
    assert not [call for call in tracker.calls if call[0] == "PUT"]


def test_two_publishers_with_one_revision_send_one_put(sessions, db, tracker):
    load(db, tracker)
    initial = edit(db, tracker, 12, "add")
    barrier, counter_lock = Barrier(2), Lock()
    count = 0
    original = tracker.client.get

    def get(path, *args, **kwargs):
        nonlocal count
        result = original(path, *args, **kwargs)
        if path == "streams/201":
            with counter_lock:
                count += 1
                preflight = count <= 2
            if preflight:
                barrier.wait(timeout=5)
        return result

    tracker.client.get = get

    def run(_):
        with sessions() as session:
            try:
                return publish_stream(session, tracker.client, 201, initial["revision"])
            except DomainError as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, DomainError) and result.code == "stale_revision"
            for result in results
        )
        == 1
    )
    assert sum(call[:2] == ("PUT", "streams/201") for call in tracker.calls) == 1
    assert not campaign_view(db, 100)["streams"][1]["dirty"]


def test_inflight_intent_does_not_allow_a_second_put(sessions, db, tracker):
    load(db, tracker)
    initial = edit(db, tracker, 12, "add")
    sending, release = Event(), Event()
    original = tracker.client.put

    def put(*args):
        sending.set()
        assert release.wait(timeout=5)
        return original(*args)

    tracker.client.put = put

    def send():
        with sessions() as session:
            return publish_stream(session, tracker.client, 201, initial["revision"])

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send)
        try:
            assert sending.wait(timeout=5)
            view = campaign_view(db, 100)["streams"][1]
            with pytest.raises(DomainError) as error:
                publish_stream(db, tracker.client, 201, view["revision"])
            assert error.value.code == "publication_in_progress"
            with pytest.raises(DomainError):
                cancel_stream(db, 201, view["revision"])
        finally:
            release.set()
        assert not future.result(timeout=5)["dirty"]
    assert sum(call[:2] == ("PUT", "streams/201") for call in tracker.calls) == 1


def test_other_readback_can_confirm_intent_before_original_response(sessions, db, tracker):
    load(db, tracker)
    initial = edit(db, tracker, 12, "add")
    confirming, release = Event(), Event()
    blocked = False
    original = tracker.client.get

    def get(path, *args, **kwargs):
        nonlocal blocked
        result = original(path, *args, **kwargs)
        if path == "streams/201" and any(c[0] == "PUT" for c in tracker.calls) and not blocked:
            blocked = True
            confirming.set()
            assert release.wait(timeout=5)
        return result

    tracker.client.get = get

    def send():
        with sessions() as session:
            return publish_stream(session, tracker.client, 201, initial["revision"])

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send)
        try:
            assert confirming.wait(timeout=5)
            view = campaign_view(db, 100)["streams"][1]
            assert not publish_stream(db, tracker.client, 201, view["revision"])["dirty"]
        finally:
            release.set()
        assert not future.result(timeout=5)["dirty"]
    assert sum(call[:2] == ("PUT", "streams/201") for call in tracker.calls) == 1


def test_unknown_publication_conflict_can_be_cancelled_and_synced(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    original = tracker.client.put

    def put(*args):
        result = original(*args)
        tracker.timeout_before.add("GET streams/201")
        return result

    tracker.client.put = put
    with pytest.raises(DomainError):
        publish(db, tracker)
    tracker.client.put = original
    tracker.streams[201]["offers"] = [{"offer_id": 13, "share": 100, "state": "active"}]
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.code == "remote_conflict"
    stream = db.get(Stream, 201)
    assert stream.dirty and stream.pending is None
    cancel_stream(db, 201, stream.revision)
    view = sync_campaign(db, tracker.client, 100)["streams"][1]
    assert row(view, 13)["active"] and row(view, 10)["archived"]


def test_read_failure_before_publish_has_no_remote_or_local_write(db, tracker):
    load(db, tracker)
    initial = edit(db, tracker, 12, "add")
    tracker.timeout_before.add("GET streams/201")
    with pytest.raises(RemoteError):
        publish(db, tracker)
    assert campaign_view(db, 100)["streams"][1] == initial
    assert not [call for call in tracker.calls if call[0] == "PUT"]


def test_late_uncertain_put_never_unlocks_or_repeats_before_confirmation(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")
    queued = []

    def delayed_put(path, body):
        queued.append(deepcopy(body))
        raise RemoteError(
            "The response was lost while the server was still working", uncertain=True
        )

    tracker.client.put = delayed_put
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.code == "publication_pending"
    for _ in range(2):
        with pytest.raises(DomainError):
            publish(db, tracker)
        with pytest.raises(DomainError):
            cancel_stream(db, 201, db.get(Stream, 201).revision)
        with pytest.raises(DomainError):
            edit(db, tracker, 13, "add")
    assert len(queued) == 1
    tracker.streams[201]["offers"] = queued[0]["offers"]
    view = publish(db, tracker)
    assert not view["pending"] and not view["dirty"]
    assert view["active_count"] == 3


def test_uncertain_write_followed_by_external_conflict_stays_blocked(db, tracker):
    load(db, tracker)
    edit(db, tracker, 12, "add")

    def uncertain_put(*_):
        raise RemoteError("uncertain write", uncertain=True)

    tracker.client.put = uncertain_put
    with pytest.raises(DomainError):
        publish(db, tracker)
    tracker.streams[201]["offers"] = [{"offer_id": 13, "share": 100, "state": "active"}]
    with pytest.raises(DomainError) as error:
        publish(db, tracker)
    assert error.value.code == "remote_conflict"
    assert db.get(Stream, 201).pending is not None
    with pytest.raises(DomainError):
        cancel_stream(db, 201, db.get(Stream, 201).revision)
