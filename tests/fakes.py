import json
from copy import deepcopy

import httpx

from app.keitaro import KeitaroClient


class FakeTracker:
    """In-memory HTTP boundary; service and SQLAlchemy code run unchanged."""

    def __init__(self):
        self.domains = [{"id": 1, "name": "tracking.example", "is_ssl": True, "state": "active"}]
        self.groups = [{"id": 2, "name": "FORTESTS", "type": "campaigns"}]
        self.sources = [{"id": 3, "name": "FORTESTS", "state": "active"}]
        self.offers = {i: {"id": i, "name": f"Offer {i}", "state": "active"} for i in range(10, 16)}
        self.campaigns = {
            100: {
                "id": 100,
                "name": "test_tsybizov_existing",
                "domain": "https://tracking.example/",
                "alias": "existing",
                "state": "active",
                "type": "position",
            }
        }
        self.streams = {
            200: {
                "id": 200,
                "campaign_id": 100,
                "name": "Geo",
                "schema": "redirect",
                "type": "regular",
                "position": 1,
                "offers": [],
                "filters": [{"unknown": {"payload": "leave intact"}}],
                "action_payload": "https://google.com/",
            },
            201: {
                "id": 201,
                "campaign_id": 100,
                "name": "Offers",
                "schema": "landings",
                "type": "default",
                "position": 2,
                "offers": [
                    {"offer_id": 10, "share": 50, "state": "active"},
                    {"offer_id": 11, "share": 50, "state": "active"},
                ],
                "landings": [{"landing_id": 88, "share": 100}],
                "filters": [{"name": "some_filter"}],
            },
        }
        self.calls = []
        self.timeout_before = set()
        self.timeout_after = set()
        self.fail_status = {}
        self.fail_stream_number = None
        self.stream_posts = 0
        self.client = KeitaroClient(
            "https://tracker.example", "fake-test-key", transport=httpx.MockTransport(self.handle)
        )

    def handle(self, request):
        path = request.url.path.removeprefix("/admin_api/v1/")
        body = json.loads(request.content) if request.content else None
        label = f"{request.method} {path}"
        self.calls.append((request.method, path, deepcopy(body)))
        if label in self.timeout_before:
            self.timeout_before.remove(label)
            raise httpx.ReadTimeout("simulated", request=request)
        if label in self.fail_status:
            return httpx.Response(self.fail_status.pop(label), json={"error": "simulated failure"})
        status, data = self.route(request.method, path, body, request.url.params)
        if label in self.timeout_after:
            self.timeout_after.remove(label)
            raise httpx.ReadTimeout("simulated lost response", request=request)
        return httpx.Response(status, json=deepcopy(data))

    def route(self, method, path, body, params):
        if method == "GET":
            catalogs = {
                "domains": self.domains,
                "groups": self.groups,
                "traffic_sources": self.sources,
            }
            if path in catalogs:
                return 200, catalogs[path]
            if path == "offers":
                return 200, list(self.offers.values())
            if path == "campaigns":
                offset = int(params.get("offset", 0))
                limit = int(params.get("limit", 100))
                return 200, list(self.campaigns.values())[offset : offset + limit]
            parts = path.split("/")
            if parts[0] == "campaigns" and len(parts) == 3:
                return 200, [s for s in self.streams.values() if s["campaign_id"] == int(parts[1])]
            collection = {
                "offers": self.offers,
                "campaigns": self.campaigns,
                "streams": self.streams,
            }.get(parts[0])
            if collection is not None and len(parts) == 2:
                item = collection.get(int(parts[1]))
                return (200, item) if item else (404, {})
        if method == "POST" and path == "campaigns":
            item = {
                **body,
                "id": max(self.campaigns, default=999) + 1,
                "domain": "https://tracking.example/",
            }
            self.campaigns[item["id"]] = item
            return 200, item
        if method == "POST" and path == "streams":
            self.stream_posts += 1
            if self.stream_posts == self.fail_stream_number:
                return 400, {"error": "simulated invalid stream"}
            item = {"offers": [], **body, "id": max(self.streams, default=299) + 1}
            self.streams[item["id"]] = item
            return 200, item
        if method == "PUT":
            parts = path.split("/")
            collection = {"campaigns": self.campaigns, "streams": self.streams}.get(parts[0])
            if collection is not None and int(parts[1]) in collection:
                item = collection[int(parts[1])]
                item.update(body)
                return 200, item
        return 404, {"error": f"unhandled {method} {path}"}
