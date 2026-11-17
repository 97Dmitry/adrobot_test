from typing import Any

from sqlalchemy.orm import Session

from app.editor_state import commit, load_stream, stream_view
from app.errors import DomainError, RemoteError
from app.keitaro import KeitaroClient
from app.models import Stream
from app.snapshots import snapshot


def _read(session: Session, client: KeitaroClient, stream: Stream) -> dict[str, Any]:
    try:
        return snapshot(client.get(f"streams/{stream.id}"))
    except RemoteError as error:
        if error.remote_status == 404:
            stream.missing = True
            stream.pending = None
            stream.notice = "Поток удалён или недоступен в Keitaro. Локальный архив сохранён."
            stream.revision += 1
            commit(session)
            raise DomainError(stream.notice, 409, "remote_stream_missing") from None
        raise


def _clear_pending(session: Session, stream: Stream) -> None:
    stream.pending = None
    stream.revision += 1
    commit(session)


def _finalize(session: Session, stream: Stream, target: dict[str, Any]) -> dict[str, Any]:
    stream_id = stream.id
    for row in stream.offers:
        row.published_active, row.published_share, row.published_pin = (
            row.active,
            row.share,
            row.pin,
        )
        row.ever_published = row.ever_published or row.active
    stream.baseline = target
    stream.pending = None
    stream.dirty = False
    stream.notice = "Опубликовано в Keitaro."
    stream.revision += 1
    try:
        commit(session)
    except DomainError as error:
        if error.code != "stale_revision":
            raise
        current = session.get(Stream, stream_id, populate_existing=True)
        if current is None or current.pending is not None or current.baseline != target:
            raise
        # Another read-back may already have confirmed this same intent.
        return stream_view(current)
    return stream_view(stream)


def _conflict(session: Session, stream: Stream, *, clear_pending: bool) -> None:
    if clear_pending and stream.pending is not None:
        _clear_pending(session, stream)
    raise DomainError(
        "Поток изменён в Keitaro. Черновик сохранён. После завершения сверки отмените черновик и загрузите актуальные потоки.",
        409,
        "remote_conflict",
    )


def _save_unknown(
    session: Session, stream: Stream, target: dict[str, Any], confirmed: bool
) -> None:
    stream.pending = {"target": target, "phase": "unknown", "confirmed": confirmed}
    stream.revision += 1
    commit(session)


def publish_stream(
    session: Session, client: KeitaroClient, stream_id: int, revision: int
) -> dict[str, Any]:
    stream = load_stream(session, stream_id, revision, allow_pending=True)
    if not stream.dirty and stream.pending is None:
        return stream_view(stream)
    active = [row for row in sorted(stream.offers, key=lambda row: row.position) if row.active]
    if not active or sum(row.share for row in active) != 100:
        raise DomainError("Для публикации нужен хотя бы один активный оффер с суммой весов 100%.")
    target = snapshot(
        {
            "schema": stream.schema_name,
            "offers": [
                {"offer_id": row.offer_id, "share": row.share, "state": "active"} for row in active
            ],
        }
    )
    remote = _read(session, client, stream)
    if (
        stream.pending is not None
        and remote == stream.pending["target"]
        and (remote != stream.baseline or stream.pending.get("confirmed") is True)
    ):
        return _finalize(session, stream, remote)
    if stream.pending is not None:
        confirmed = stream.pending.get("confirmed") is True
        if remote != stream.baseline or confirmed:
            _conflict(session, stream, clear_pending=confirmed)
        raise DomainError(
            "Результат предыдущей записи не подтверждён. Прежние веса не доказывают завершение PUT; требуется сверка в Keitaro. Повторная запись не отправлена.",
            409 if stream.pending.get("phase") == "sending" else 502,
            "publication_in_progress"
            if stream.pending.get("phase") == "sending"
            else "publication_pending",
        )
    if remote != stream.baseline:
        _conflict(session, stream, clear_pending=False)
    for row in active:
        client.offer(row.offer_id)
    if stream.pending is None and target == remote:
        # Pin policy is local: unchanged remote shares need no PUT or sending intent.
        return _finalize(session, stream, target)
    stream.pending = {"target": target, "phase": "sending"}
    stream.revision += 1
    commit(session)  # Revision claim and intent are durable before PUT.
    confirmed = False
    try:
        response = client.put(f"streams/{stream.id}", {"offers": target["offers"]})
    except RemoteError as error:
        if not error.uncertain:
            _clear_pending(session, stream)
            raise
        # An uncertain write is read back below, never automatically repeated.
    else:
        try:
            confirmed = snapshot(response) == target
        except RemoteError:
            pass
    try:
        actual = _read(session, client, stream)
    except RemoteError:
        _save_unknown(session, stream, target, confirmed)
        raise DomainError(
            "Результат публикации пока неизвестен. Черновик сохранён; нажмите Publish для сверки после восстановления связи.",
            502,
            "publication_pending",
        ) from None
    if actual == target:
        return _finalize(session, stream, actual)
    if confirmed:
        # A validated PUT reply proves completion; a differing GET is an external conflict.
        _conflict(session, stream, clear_pending=True)
    _save_unknown(session, stream, target, confirmed=False)
    if actual != stream.baseline:
        _conflict(session, stream, clear_pending=False)
    raise DomainError(
        "Результат записи неизвестен: чтение прежних весов не доказывает завершение PUT. Черновик заблокирован до подтверждения результата; требуется сверка в Keitaro.",
        502,
        "publication_pending",
    )
