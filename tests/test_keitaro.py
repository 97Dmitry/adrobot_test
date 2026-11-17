import httpx
import pytest

from app.errors import RemoteError
from app.keitaro import KeitaroClient


def test_headers_base_path_and_no_key_in_query():
    def handler(request):
        assert str(request.url) == "https://tracker.example/admin_api/v1/offers"
        assert request.headers["Api-Key"] == "test-secret"
        assert request.headers["User-Agent"] == "Adrobot-Test/1.0"
        return httpx.Response(200, json=[{"id": 7, "name": "Example", "state": "active"}])

    with KeitaroClient(
        "https://tracker.example/", "test-secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert client.get("offers")[0]["id"] == 7


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_remote_errors_are_safe_and_writes_never_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "secret=test-secret"})

    with KeitaroClient(
        "https://tracker.example", "test-secret", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(RemoteError) as error:
            client.post("campaigns", {"name": "example"})
        assert error.value.remote_status == status
        assert "test-secret" not in str(error.value)
        assert error.value.uncertain == (status >= 500)
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["get", "post", "put"])
def test_timeout_has_correct_uncertainty(method):
    def handler(request):
        raise httpx.ReadTimeout("test-secret", request=request)

    with KeitaroClient(
        "https://tracker.example", "test-secret", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(RemoteError) as error:
            getattr(client, method)("streams/1", *([] if method == "get" else [{}]))
        assert error.value.uncertain == (method != "get")
        assert "test-secret" not in str(error.value)


def test_invalid_json_and_redirect_are_errors():
    for response in [
        httpx.Response(200, text="not json"),
        httpx.Response(302, headers={"Location": "https://elsewhere.example"}),
    ]:
        with KeitaroClient(
            "https://tracker.example",
            "test-secret",
            transport=httpx.MockTransport(lambda _, result=response: result),
        ) as client:
            with pytest.raises(RemoteError):
                client.get("offers")


def test_campaign_pagination_and_offer_search():
    def handler(request):
        if request.url.path.endswith("/offers"):
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "Alpha", "state": "active"},
                    {"id": 21, "name": "Beta", "state": "active"},
                    {"id": 3, "name": "Alpha archived", "state": "deleted"},
                ],
            )
        offset = int(request.url.params.get("offset", 0))
        return httpx.Response(
            200,
            json=[
                {"id": i, "name": f"campaign {i}"} for i in range(offset, min(offset + 100, 123))
            ],
        )

    with KeitaroClient(
        "https://tracker.example", "test-secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert len(client.campaigns()) == 123
        assert [x["id"] for x in client.search_offers("21")] == [21]
        assert [x["id"] for x in client.search_offers("alpha")] == [1]


def test_missing_key_does_not_make_request():
    with KeitaroClient("https://tracker.example", "") as client:
        with pytest.raises(RemoteError, match="KEITARO_API_KEY"):
            client.get("offers")
