import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER") != "1", reason="Set RUN_BROWSER=1 and install Playwright Chromium"
)


@pytest.fixture
def ui_url(tracker, sessions):
    app = create_app(Settings(database_url=str(sessions.kw["bind"].url)), tracker.client)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(url + "/api/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.03)
    else:
        raise RuntimeError("Test server did not start")
    yield url
    server.should_exit = True
    worker.join(timeout=10)
    sock.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_complete_ui_flow(ui_url, tracker, monkeypatch, width, height):
    original_route = tracker.route

    def delayed_write(method, path, body, params):
        if method == "PUT" and path == "streams/201":
            time.sleep(0.2)
        return original_route(method, path, body, params)

    monkeypatch.setattr(tracker, "route", delayed_write)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Поиск по названию или ID").fill("100")
        page.get_by_role("button", name="Загрузить потоки", exact=True).click()
        stream = page.locator("#stream-201")
        expect(stream).to_be_visible()
        expect(page.locator("#stream-200")).to_contain_text("В этом потоке нет офферов")
        search = stream.get_by_role("combobox")
        search.fill("12")
        expect(stream.locator(".search-hint")).to_contain_text("Offer 12")
        stream.get_by_role("button", name="Добавить", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Не опубликован")
        expect(stream.locator("tbody tr")).to_have_count(3)
        page.reload()
        expect(stream.locator("tbody tr")).to_have_count(3)
        stream.get_by_role("button", name="Cancel", exact=True).click()
        expect(stream.locator("tbody tr")).to_have_count(2)
        first = stream.locator('[data-offer-id="10"]')
        first.get_by_role("spinbutton").fill("25")
        first.get_by_role("button", name="Pin", exact=True).click()
        stream.get_by_role("combobox").fill("12")
        stream.get_by_role("button", name="Добавить", exact=True).click()
        expect(stream.locator(".weight")).to_have_text(["25%", "38%", "37%"])
        stream.get_by_role("button", name="Publish", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Опубликован")
        first.get_by_role("button", name="Remove", exact=True).click()
        expect(first.locator(".weight")).to_have_text("0%")
        stream.get_by_role("button", name="Publish", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Опубликован")
        expect(first).to_have_class("archived")
        assert all(o["offer_id"] != 10 for o in tracker.streams[201]["offers"])
        first.get_by_role("button", name="Bring back", exact=True).click()
        expect(first.locator(".weight")).to_have_text("25%")
        stream.get_by_role("button", name="Publish", exact=True).click()
        page.get_by_role("button", name="Синхронизировать с Keitaro", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Опубликован")
        assert len(tracker.streams[201]["offers"]) == 3
        stream.get_by_role("combobox").fill("999")
        stream.get_by_role("button", name="Добавить", exact=True).click()
        expect(page.locator("#message")).to_contain_text("не найден")
        expect(stream.get_by_role("button", name="Добавить", exact=True)).to_be_enabled()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        artifacts = Path(".artifacts")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / f"editor-{width}.png"), full_page=True)
        page.get_by_label("Название", exact=True).fill("test_tsybizov_browser")
        page.get_by_label("Страны", exact=True).fill("AU, MX")
        page.get_by_label("Оффер", exact=True).fill("10")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_browser")
        expect(page.locator(".stream")).to_have_count(2)
        assert tracker.campaigns[101]["state"] == "active"
        assert errors == []
        browser.close()


def test_open_campaign_with_saved_draft(ui_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Поиск по названию или ID").fill("100")
        page.get_by_role("button", name="Загрузить потоки", exact=True).click()
        stream = page.locator("#stream-201")
        stream.get_by_role("combobox").fill("12")
        stream.get_by_role("button", name="Добавить", exact=True).click()
        expect(stream.locator("tbody tr")).to_have_count(3)
        page.get_by_label("Название", exact=True).fill("other")
        page.get_by_label("Страны", exact=True).fill("AU")
        page.get_by_label("Оффер", exact=True).fill("10")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_other")
        page.get_by_label("Поиск по названию или ID").fill("100")
        page.get_by_role("button", name="Загрузить потоки", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_existing")
        expect(stream.locator("tbody tr")).to_have_count(3)
        expect(stream.locator(".badge")).to_have_text("Не опубликован")
        browser.close()


def test_pin_zero_validation_and_keyboard_search(ui_url, tracker):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Поиск по названию или ID").fill("100")
        page.get_by_role("button", name="Загрузить потоки", exact=True).click()
        stream = page.locator("#stream-201")
        first = stream.locator('[data-offer-id="10"]')
        first.get_by_role("spinbutton").fill("101")
        first.get_by_role("button", name="Pin", exact=True).click()
        expect(page.locator("#message")).to_contain_text("100")
        expect(stream.locator(".badge")).to_have_text("Опубликован")
        first.get_by_role("spinbutton").fill("0")
        first.get_by_role("button", name="Pin", exact=True).click()
        expect(first.locator(".weight")).to_have_text("0%")
        expect(first).not_to_have_class("archived")
        stream.get_by_role("combobox").fill("12")
        expect(stream.locator(".search-hint")).to_contain_text("Offer 12")
        stream.get_by_role("combobox").press("Enter")
        expect(stream.locator("tbody tr")).to_have_count(3)
        first.get_by_role("button", name="Unpin", exact=True).click()
        expect(stream.locator(".weight")).to_have_text(["34%", "33%", "33%"])
        stream.get_by_role("button", name="Publish", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Опубликован")
        tracker.streams[201]["offers"] = [
            o for o in tracker.streams[201]["offers"] if o["offer_id"] != 12
        ]
        page.get_by_role("button", name="Синхронизировать с Keitaro", exact=True).click()
        archived = stream.locator('[data-offer-id="12"]')
        expect(archived).to_have_class("archived")
        expect(archived.get_by_role("button", name="Bring back", exact=True)).to_be_enabled()
        browser.close()


@pytest.mark.parametrize("normalization", ["country_case", "name_prefix"])
def test_lost_creation_response_reuses_key_after_reload(ui_url, tracker, normalization):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Название", exact=True).fill("lost_reply")
        page.get_by_label("Страны", exact=True).fill(
            "au" if normalization == "country_case" else "AU"
        )
        page.get_by_label("Оффер", exact=True).fill("10")

        def lose_response(route):
            route.fetch()  # Application completes creation; browser never receives the reply.
            route.abort("failed")

        page.route("**/api/campaigns", lose_response, times=1)
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#message")).to_contain_text("Нет связи")
        page.reload()
        expect(page.get_by_label("Название", exact=True)).to_have_value("lost_reply")
        if normalization == "country_case":
            page.get_by_label("Страны", exact=True).fill("AU")
        else:
            page.get_by_label("Название", exact=True).fill("test_tsybizov_lost_reply")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_lost_reply")
        assert len(tracker.campaigns) == 2
        assert len([call for call in tracker.calls if call[:2] == ("POST", "campaigns")]) == 1
        browser.close()


def test_unknown_publication_blocks_cancel_and_only_reconciles(ui_url, tracker):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Поиск по названию или ID").fill("100")
        page.get_by_role("button", name="Загрузить потоки", exact=True).click()
        stream = page.locator("#stream-201")
        stream.get_by_role("combobox").fill("12")
        stream.get_by_role("button", name="Добавить", exact=True).click()
        expect(stream.locator("tbody tr")).to_have_count(3)
        tracker.timeout_before.add("PUT streams/201")
        stream.get_by_role("button", name="Publish", exact=True).click()
        expect(stream.locator(".badge")).to_have_text("Нужна сверка")
        expect(stream.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
        expect(stream.get_by_role("button", name="Добавить", exact=True)).to_be_disabled()
        expect(stream.get_by_role("button", name="Publish", exact=True)).to_be_enabled()
        stream.get_by_role("button", name="Publish", exact=True).click()
        expect(page.locator("#message")).to_contain_text("сверка")
        expect(stream.get_by_role("button", name="Publish", exact=True)).to_be_enabled()
        assert len([call for call in tracker.calls if call[:2] == ("PUT", "streams/201")]) == 1
        browser.close()


def test_changed_creation_parameters_require_explicit_new_operation(ui_url, tracker):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(ui_url)
        expect(page.locator("#connection")).to_have_text("Keitaro подключён")
        page.get_by_label("Название", exact=True).fill("first")
        page.get_by_label("Страны", exact=True).fill("AU")
        page.get_by_label("Оффер", exact=True).fill("10")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_first")
        page.get_by_label("Название", exact=True).fill("second")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#message")).to_contain_text("Начать новую операцию")
        assert len(tracker.campaigns) == 2
        page.get_by_role("button", name="Начать новую операцию", exact=True).click()
        page.get_by_label("Название", exact=True).fill("second")
        page.get_by_role("button", name="Создать кампанию", exact=True).click()
        expect(page.locator("#campaign-title")).to_have_text("test_tsybizov_second")
        assert len(tracker.campaigns) == 3
        browser.close()
