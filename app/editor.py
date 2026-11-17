from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.editor_state import campaign_view as campaign_view
from app.editor_state import commit, load_campaign, load_stream, stream_view
from app.errors import DomainError, RemoteError
from app.keitaro import KeitaroClient
from app.models import Campaign, Offer, Stream, StreamOffer
from app.publication import publish_stream as publish_stream
from app.snapshots import snapshot
from app.weights import distribute


def sync_campaign(session: Session, client: KeitaroClient, campaign_id: int) -> dict[str, Any]:
    campaign = load_campaign(session, campaign_id)
    if campaign and any(stream.dirty or stream.pending is not None for stream in campaign.streams):
        raise DomainError(
            "Есть неопубликованные изменения. Сначала Publish или Cancel; при неизвестном результате — сверка через Publish.",
            409,
            "dirty_sync",
        )
    remote = client.get(f"campaigns/{campaign_id}")
    flows = client.get(f"campaigns/{campaign_id}/streams")
    if (
        not isinstance(remote, dict)
        or remote.get("id") != campaign_id
        or not isinstance(remote.get("name"), str)
        or not isinstance(flows, list)
        or not isinstance(remote.get("domain", ""), str)
        or not isinstance(remote.get("alias", ""), str)
    ):
        raise RemoteError("Keitaro вернул неожиданный формат кампании.")
    incoming = []
    seen = set()
    for flow in flows:
        if (
            not isinstance(flow, dict)
            or type(flow.get("id")) is not int
            or flow["id"] <= 0
            or flow["id"] in seen
            or not isinstance(flow.get("name"), str)
            or type(flow.get("position", 0)) is not int
            or flow.get("campaign_id", campaign_id) != campaign_id
        ):
            raise RemoteError("Keitaro вернул некорректный список потоков.")
        seen.add(flow["id"])
        if flow.get("state") != "deleted":
            incoming.append((flow, snapshot(flow)))
    offer_ids = {o["offer_id"] for _, snap in incoming for o in snap["offers"]}
    catalog = client.get("offers") if offer_ids else []
    if not isinstance(catalog, list) or any(
        not isinstance(o, dict)
        or type(o.get("id")) is not int
        or not isinstance(o.get("name"), str)
        for o in catalog
    ):
        raise RemoteError("Keitaro вернул неожиданный справочник офферов.")
    names = {o["id"]: o["name"] for o in catalog}
    occupied = session.execute(
        select(Stream.id, Stream.campaign_id).where(Stream.id.in_(seen))
    ).all()
    if any(owner_id != campaign_id for _, owner_id in occupied):
        raise RemoteError("Keitaro вернул ID потока другой кампании.")
    offers = {o.id: o for o in session.scalars(select(Offer).where(Offer.id.in_(offer_ids)))}
    for oid in offer_ids:
        if oid not in offers:
            offers[oid] = Offer(id=oid, name=names.get(oid, f"Оффер #{oid} (недоступен)"))
            session.add(offers[oid])
        elif oid in names:
            offers[oid].name = names[oid]

    if campaign is None:
        campaign = Campaign(id=campaign_id, name=remote["name"], streams=[])
        session.add(campaign)
    campaign.name = remote["name"]
    campaign.state = remote.get("state", "active")
    campaign.tracking_url = remote.get("domain", "").rstrip("/") + "/" + remote.get("alias", "")
    known = {stream.id: stream for stream in campaign.streams}
    present = set()
    for flow, snap in incoming:
        stream_id = flow["id"]
        present.add(stream_id)
        stream = known.get(stream_id)
        if stream is None:
            stream = Stream(id=stream_id, name=flow["name"], revision=0, offers=[])
            campaign.streams.append(stream)
        stream.name = flow["name"]
        stream.position = flow.get("position", 0)
        stream.schema_name = snap["schema"]
        stream.baseline = snap
        stream.pending = None
        stream.missing = stream.dirty = False
        stream.notice = ""
        stream.revision += 1
        rows = {row.offer_id: row for row in stream.offers}
        # Keep local row order; append new associations in the API's original order.
        entries = {o["offer_id"]: o for o in snap["offers"]}
        for entry in flow.get("offers", []):
            oid = entry["offer_id"]
            row = rows.get(oid)
            if row is None:
                row = StreamOffer(
                    offer_id=oid,
                    offer=offers[oid],
                    position=max((r.position for r in stream.offers), default=-1) + 1,
                )
                stream.offers.append(row)
            active = entry.get("state", "active") == "active"
            share = entry["share"] if active else 0
            if active and row.published_pin is not None and share != row.published_pin:
                row.published_pin = None
                stream.notice = "Закрепление снято: вес изменён непосредственно в Keitaro."
            row.active = row.published_active = active
            row.share = row.published_share = share
            row.pin = row.published_pin
            row.ever_published = True
        for oid, row in rows.items():
            if oid not in entries:
                row.active = row.published_active = False
                row.share = row.published_share = 0
                row.pin = row.published_pin
    for stream_id, stream in known.items():
        if stream_id not in present:
            stream.missing = True
            stream.notice = "Поток удалён или недоступен в Keitaro. Локальный архив сохранён."
            stream.revision += 1
            for row in stream.offers:
                row.active = row.published_active = False
                row.share = row.published_share = 0
    campaign.synced_at = datetime.now(UTC).replace(tzinfo=None)
    commit(session)
    return campaign_view(session, campaign_id)


def edit_offer(
    session: Session,
    client: KeitaroClient,
    stream_id: int,
    revision: int,
    offer_id: int,
    action: str,
    pin: int | None = None,
) -> dict[str, Any]:
    stream = load_stream(session, stream_id, revision)
    rows = sorted(stream.offers, key=lambda row: row.position)
    current = next((row for row in rows if row.offer_id == offer_id), None)
    if action not in ("add", "remove", "restore", "pin", "unpin"):
        raise DomainError("Неизвестное действие над оффером.")
    if type(offer_id) is not int or offer_id <= 0:
        raise DomainError("ID оффера должен быть положительным целым числом.")
    if action == "add" and current:
        raise DomainError(
            "Оффер уже известен потоку. Для архивного используйте Bring back.",
            409,
            "duplicate_offer",
        )
    if action != "add" and current is None:
        raise DomainError("Оффер не найден в потоке.", 404, "offer_missing")
    if current and action in ("remove", "pin", "unpin") and not current.active:
        raise DomainError("Оффер находится в архиве. Сначала Bring back.")
    if current and action == "restore" and current.active:
        raise DomainError("Оффер уже активен.")
    if action == "pin" and (type(pin) is not int or not 0 <= pin <= 100):
        raise DomainError("Закреплённый вес должен быть целым числом от 0 до 100.")
    offer_data = client.offer(offer_id) if action in ("add", "restore") else None
    proposal = {row.offer_id: (row.active, row.pin) for row in rows}
    if action in ("add", "restore"):
        proposal[offer_id] = (True, current.pin if current else None)
    elif current:
        proposal[offer_id] = (
            action != "remove",
            pin if action == "pin" else None if action == "unpin" else current.pin,
        )
    active_ids = [oid for oid, (active, _) in proposal.items() if active]
    shares = dict(
        zip(active_ids, distribute([proposal[oid][1] for oid in active_ids]), strict=True)
    )
    # No ORM mutation before remote validation and a valid complete weight proposal.
    if offer_data:
        offer = session.get(Offer, offer_id)
        if offer is None:
            offer = Offer(id=offer_id, name=offer_data["name"])
            session.add(offer)
        else:
            offer.name = offer_data["name"]
        if action == "add":
            stream.offers.append(
                StreamOffer(
                    offer_id=offer_id,
                    offer=offer,
                    position=max((r.position for r in rows), default=-1) + 1,
                    published_active=False,
                    published_share=0,
                    published_pin=None,
                    ever_published=False,
                )
            )
    for row in list(stream.offers):
        row.active, row.pin = proposal[row.offer_id]
        row.share = shares.get(row.offer_id, 0)
        if not row.active and not row.ever_published:
            stream.offers.remove(row)
    stream.dirty = any(
        (row.active, row.share, row.pin)
        != (row.published_active, row.published_share, row.published_pin)
        for row in stream.offers
    )
    stream.revision += 1
    stream.notice = ""
    commit(session)
    return stream_view(stream)


def cancel_stream(session: Session, stream_id: int, revision: int) -> dict[str, Any]:
    stream = load_stream(session, stream_id, revision, require_editable=False)
    if not stream.dirty:
        return stream_view(stream)
    for row in list(stream.offers):
        if not row.ever_published:
            stream.offers.remove(row)
        else:
            row.active, row.share, row.pin = (
                row.published_active,
                row.published_share,
                row.published_pin,
            )
    stream.dirty = False
    stream.notice = "Изменения отменены."
    stream.revision += 1
    commit(session)
    return stream_view(stream)
