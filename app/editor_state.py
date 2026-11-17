from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.errors import DomainError
from app.models import Campaign, Stream, StreamOffer


def editable(stream: Stream) -> bool:
    return not stream.missing and stream.schema_name == "landings" and bool(stream.offers)


def stream_view(stream: Stream) -> dict[str, Any]:
    offers = [
        {
            "offer_id": row.offer_id,
            "name": row.offer.name,
            "active": row.active,
            "archived": not row.active,
            "share": row.share,
            "pin": row.pin,
            "published_active": row.published_active,
            "ever_published": row.ever_published,
        }
        for row in sorted(stream.offers, key=lambda row: row.position)
    ]
    return {
        "id": stream.id,
        "name": stream.name,
        "revision": stream.revision,
        "dirty": stream.dirty,
        "missing": stream.missing,
        "pending": stream.pending is not None,
        "notice": stream.notice,
        "editable": editable(stream),
        "offers": offers,
        "total": sum(row.share for row in stream.offers if row.active),
        "active_count": sum(row.active for row in stream.offers),
    }


def load_campaign(session: Session, campaign_id: int) -> Campaign | None:
    return session.get(
        Campaign,
        campaign_id,
        populate_existing=True,
        options=[
            selectinload(Campaign.streams).selectinload(Stream.offers).joinedload(StreamOffer.offer)
        ],
    )


def campaign_view(session: Session, campaign_id: int) -> dict[str, Any]:
    campaign = load_campaign(session, campaign_id)
    if campaign is None:
        raise DomainError(
            "Кампания ещё не загружена. Нажмите «Загрузить потоки».", 404, "not_imported"
        )
    return {
        "id": campaign.id,
        "name": campaign.name,
        "state": campaign.state,
        "tracking_url": campaign.tracking_url,
        "synced_at": campaign.synced_at.isoformat() if campaign.synced_at else None,
        "streams": [
            stream_view(s) for s in sorted(campaign.streams, key=lambda s: (s.position, s.id))
        ],
    }


def load_stream(
    session: Session,
    stream_id: int,
    revision: int,
    *,
    allow_pending: bool = False,
    require_editable: bool = True,
) -> Stream:
    stream = session.get(
        Stream,
        stream_id,
        populate_existing=True,
        options=[selectinload(Stream.offers).joinedload(StreamOffer.offer)],
    )
    if stream is None:
        raise DomainError("Поток не загружен.", 404, "stream_missing")
    if type(revision) is not int or revision != stream.revision:
        raise DomainError("Данные изменились. Обновите локальное состояние.", 409, "stale_revision")
    if stream.pending is not None and not allow_pending:
        raise DomainError(
            "Результат публикации неизвестен. Нажмите Publish для сверки перед изменениями.",
            409,
            "publication_pending",
        )
    if require_editable and not editable(stream):
        raise DomainError("Этот поток недоступен для редактирования офферов.")
    return stream


def commit(session: Session) -> None:
    try:
        session.commit()
    except StaleDataError:
        session.rollback()
        raise DomainError(
            "Данные изменились параллельно. Обновите локальное состояние.", 409, "stale_revision"
        ) from None
    except IntegrityError:
        session.rollback()
        raise DomainError(
            "Состояние привязок изменилось параллельно. Загрузите актуальные данные.",
            409,
            "state_conflict",
        ) from None
