from typing import Any

import httpx

from app.errors import RemoteError


class KeitaroClient:
    """Admin API adapter. Writes are deliberately never retried."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 20, transport=None):
        root = base_url.rstrip("/")
        if not root.endswith("/admin_api/v1"):
            root += "/admin_api/v1"
        self._key = api_key
        self._http = httpx.Client(
            base_url=root + "/",
            headers={
                "Api-Key": api_key,
                "User-Agent": "Adrobot-Test/1.0",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._http.close()

    def _request(self, method: str, path: str, data=None, params=None) -> Any:
        if not self._key:
            raise RemoteError("Укажите KEITARO_API_KEY в .env и перезапустите приложение.")
        writing = method != "GET"
        try:
            response = self._http.request(method, path.lstrip("/"), json=data, params=params)
        except httpx.HTTPError:
            raise RemoteError(
                "Keitaro недоступен или не ответил вовремя. Проверьте соединение.",
                uncertain=writing,
            ) from None
        if not 200 <= response.status_code < 300:
            message = {
                401: "проверьте API-ключ",
                403: "доступ запрещён; проверьте права API-ключа и доступ к серверу",
                404: "объект не найден",
                402: "Admin API недоступен в редакции трекера",
            }.get(response.status_code, "сервер отклонил запрос")
            raise RemoteError(
                f"Keitaro: HTTP {response.status_code}, {message}.",
                response.status_code,
                uncertain=writing and response.status_code >= 500,
            )
        try:
            return response.json()
        except ValueError:
            raise RemoteError("Keitaro вернул некорректный JSON.", uncertain=writing) from None

    def get(self, path: str, params=None):
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict):
        return self._request("POST", path, data)

    def put(self, path: str, data: dict):
        return self._request("PUT", path, data)

    def _list(self, path: str, params=None) -> list[dict]:
        data = self.get(path, params=params)
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise RemoteError("Keitaro вернул неожиданный формат списка.")
        return data

    def catalogs(self) -> dict[str, list[dict]]:
        return {
            "domains": self._list("domains"),
            "groups": self._list("groups", {"type": "campaigns"}),
            "traffic_sources": self._list("traffic_sources"),
        }

    def campaigns(self) -> list[dict]:
        result = []
        for offset in range(0, 10000, 100):
            page = self._list("campaigns", {"limit": 100, "offset": offset})
            result.extend(page)
            if len(page) < 100:
                return result
        raise RemoteError("Слишком много кампаний для локального редактора (более 10000).")

    def search_offers(self, query: str, limit: int = 30) -> list[dict]:
        query = query.strip().casefold()
        offers = [
            item
            for item in self._list("offers")
            if item.get("state") != "deleted"
            and (not query or query in str(item["id"]) or query in item.get("name", "").casefold())
        ]
        offers.sort(key=lambda item: (str(item["id"]) != query, item["id"]))
        return [{"id": x["id"], "name": x["name"]} for x in offers[:limit]]

    def offer(self, offer_id: int) -> dict:
        try:
            data = self.get(f"offers/{offer_id}")
        except RemoteError as error:
            if error.remote_status == 404:
                from app.errors import DomainError

                raise DomainError("Оффер не найден в Keitaro.", code="offer_missing") from None
            raise
        if not isinstance(data, dict) or not isinstance(data.get("id"), int):
            raise RemoteError("Keitaro вернул неожиданный формат оффера.")
        if data.get("state") == "deleted":
            from app.errors import DomainError

            raise DomainError("Оффер удалён в Keitaro.", code="offer_missing")
        return data
