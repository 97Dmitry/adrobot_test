import hashlib
import json
import re
import uuid

from sqlalchemy.orm import Session

from app.errors import DomainError, RemoteError
from app.keitaro import KeitaroClient
from app.models import Campaign, CreationOperation
from app.schemas import CreateCampaign


def _details(op: CreationOperation) -> dict:
    return {"operation_key": op.key, "campaign_id": op.campaign_id, "phase": op.phase}


def _find_created(client, op):
    matches = [c for c in client.campaigns() if c.get("alias") == op.alias]
    if len(matches) == 1:
        op.campaign_id = matches[0]["id"]


def _verify_streams(client, op, request):
    flows = client.get(f"campaigns/{op.campaign_id}/streams")
    if (
        not isinstance(flows, list)
        or len(flows) != 2
        or any(
            not isinstance(flow, dict) or type(flow.get("position")) is not int for flow in flows
        )
    ):
        raise RemoteError("Не подтверждено создание двух потоков. Кампания оставлена выключенной.")
    geo, fallback = sorted(flows, key=lambda flow: flow["position"])
    filters = geo.get("filters")
    country = (
        filters[0]
        if isinstance(filters, list) and len(filters) == 1 and isinstance(filters[0], dict)
        else {}
    )
    codes = country.get("payload")
    url = geo.get("action_payload")
    offers = fallback.get("offers")
    expected = [{"offer_id": request.offer_id, "share": 100, "state": "active"}]
    actual = (
        [
            {
                k: offer.get(k, "active" if k == "state" else None)
                for k in ("offer_id", "share", "state")
            }
            for offer in offers
        ]
        if isinstance(offers, list) and all(isinstance(offer, dict) for offer in offers)
        else None
    )
    if not (
        geo.get("schema") == "redirect"
        and geo.get("action_type") == "http"
        and isinstance(url, str)
        and url.rstrip("/") == "https://google.com"
        and geo.get("type") == "regular"
        and geo.get("state", "active") == "active"
        and country.get("name") == "country"
        and country.get("mode") == "accept"
        and isinstance(codes, list)
        and all(isinstance(code, str) for code in codes)
        and set(codes) == set(request.countries)
        and fallback.get("schema") == "landings"
        and fallback.get("type") == "default"
        and fallback.get("state", "active") == "active"
        and fallback.get("landings", []) == []
        and fallback.get("filters", []) == []
        and actual == expected
    ):
        raise RemoteError(
            "Настройки потоков не совпали с запросом. Кампания оставлена выключенной."
        )


def _finish(session, client, op):
    remote = client.get(f"campaigns/{op.campaign_id}")
    if remote.get("state") != "active":
        raise RemoteError("Кампания создана, но включение не подтверждено.")
    campaign = session.get(Campaign, op.campaign_id)
    if campaign is None:
        campaign = Campaign(id=op.campaign_id, name=remote["name"])
        session.add(campaign)
    campaign.state = remote["state"]
    campaign.tracking_url = (
        remote.get("domain", "").rstrip("/") + "/" + remote.get("alias", op.alias)
    )
    op.phase = "complete"
    op.error = ""
    op.result = {**_details(op), "name": campaign.name, "tracking_url": campaign.tracking_url}
    session.commit()
    return op.result


def create_campaign(
    session: Session, client: KeitaroClient, request: CreateCampaign, key: str
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        raise DomainError("Idempotency-Key: ожидается 8–100 букв, цифр, дефисов или подчёркиваний.")
    payload = request.model_dump()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = session.get(CreationOperation, key)
    if existing:
        if existing.fingerprint != fingerprint:
            raise DomainError(
                "Этот ключ операции уже использован с другими параметрами.",
                409,
                "idempotency_conflict",
            )
        if existing.phase == "complete":
            return existing.result
        try:
            if existing.campaign_id is None:
                _find_created(client, existing)
                session.commit()
            if existing.campaign_id and existing.phase.startswith("activate"):
                return _finish(session, client, existing)
        except RemoteError:
            session.commit()
        raise DomainError(
            "Создание уже выполнялось. Требуется сверка в Keitaro; повторное создание не отправлено. "
            + existing.error,
            409,
            "creation_incomplete",
            _details(existing),
        )

    client.offer(request.offer_id)
    catalogs = client.catalogs()
    for collection, field, label in [
        ("domains", "domain_id", "домен"),
        ("groups", "group_id", "группа кампаний"),
        ("traffic_sources", "traffic_source_id", "источник"),
    ]:
        if not any(
            int(x["id"]) == payload[field] and x.get("state") != "deleted"
            for x in catalogs[collection]
        ):
            raise DomainError(f"Выбранный {label} не найден в Keitaro.")

    op = CreationOperation(
        key=key,
        fingerprint=fingerprint,
        request=payload,
        alias="tsibizov_" + uuid.uuid4().hex[:20],
        phase="campaign_pending",
    )
    session.add(op)
    session.commit()  # Durable before the first remote side effect.
    try:
        remote = client.post(
            "campaigns",
            {
                "name": request.name,
                "alias": op.alias,
                "type": "position",
                "state": "disabled",
                "domain_id": request.domain_id,
                "group_id": request.group_id,
                "traffic_source_id": request.traffic_source_id,
            },
        )
        if not isinstance(remote, dict) or not isinstance(remote.get("id"), int):
            raise RemoteError("Не получен ID созданной кампании.", uncertain=True)
        op.campaign_id = remote["id"]
        op.phase = "geo_pending"
        session.commit()
        client.post(
            "streams",
            {
                "campaign_id": op.campaign_id,
                "name": "Geo → Google",
                "schema": "redirect",
                "type": "regular",
                "position": 1,
                "state": "active",
                "action_type": "http",
                "action_payload": "https://google.com/",
                "collect_clicks": True,
                "filters": [{"name": "country", "mode": "accept", "payload": request.countries}],
            },
        )
        op.phase = "offers_pending"
        session.commit()
        client.post(
            "streams",
            {
                "campaign_id": op.campaign_id,
                "name": "Offers",
                "schema": "landings",
                "type": "default",
                "position": 2,
                "state": "active",
                "action_type": "http",
                "collect_clicks": True,
                "landings": [],
                "offers": [{"offer_id": request.offer_id, "share": 100, "state": "active"}],
            },
        )
        _verify_streams(client, op, request)
        op.phase = "activate_pending"
        session.commit()
        try:
            client.put(f"campaigns/{op.campaign_id}", {"state": "active"})
        except RemoteError as error:
            if not error.uncertain:
                raise
            # The write may have applied: read back instead of repeating it.
        return _finish(session, client, op)
    except RemoteError as error:
        phase = op.phase
        if op.campaign_id is None and error.uncertain:
            try:
                _find_created(client, op)
            except RemoteError:
                pass
        op.phase = phase + (
            "_unknown" if error.uncertain or phase == "activate_pending" else "_failed"
        )
        op.error = error.message
        session.commit()
        raise DomainError(
            "Создание не завершено. "
            + error.message
            + " Проверьте состояние кампании в Keitaro перед новой попыткой.",
            502,
            "creation_incomplete",
            _details(op),
        ) from None
