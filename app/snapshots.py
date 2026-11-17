from typing import Any

from app.errors import RemoteError


def snapshot(remote: Any) -> dict[str, Any]:
    """Canonical editable fields; filters and redirect payloads remain opaque."""
    if not isinstance(remote, dict) or not isinstance(remote.get("offers", []), list):
        raise RemoteError("Keitaro вернул неожиданный формат потока.")
    offers = []
    seen = set()
    for item in remote.get("offers", []):
        if not isinstance(item, dict):
            raise RemoteError("Keitaro вернул некорректную привязку оффера.")
        offer_id = item.get("offer_id")
        share = item.get("share")
        state = item.get("state", "active")
        if (
            type(offer_id) is not int
            or offer_id <= 0
            or type(share) is not int
            or not 0 <= share <= 100
            or state not in ("active", "disabled", "deleted")
            or offer_id in seen
        ):
            raise RemoteError("Keitaro вернул дубликат оффера или некорректную привязку.")
        seen.add(offer_id)
        offers.append({"offer_id": offer_id, "share": share, "state": state})
    schema = remote.get("schema", "")
    return {
        "schema": schema if isinstance(schema, str) else "",
        "offers": sorted(offers, key=lambda item: item["offer_id"]),
    }
