# Интерфейс и приёмка — план реализации

> Исполнитель: `superpowers:executing-plans`. Спецификация: [../spec.md](../spec.md).

**Цель:** использовать все сценарии через браузер и воспроизвести запуск по README.
**Архитектура:** JSON API + статическая страница с того же origin.
**Стек:** FastAPI, vanilla JavaScript, CSS, Playwright для проверки.

## Задачи

- [x] D1. `tests/test_api.py`: TestClient, DI, ошибки, revision, идемпотентность,
  поиск, формы и health; unsafe origins отклоняются. RED → GREEN.
- [x] D2. `app/main.py`: `create_app(settings=None, client=None)`; маршруты из
  общего плана, отдельная Session на запрос, безопасные JSON-ошибки.
  Ревизии защищены в сервисах и БД; общий RLock не нужен. Pin принимает 0..100;
  нулевая активная доля не отображается как архивная строка.
- [x] D3. `app/static/index.html`, `app.js`, `style.css`: слева создание/выбор,
  справа рабочие потоки. Палитра white #fff, navy #18384b, blue #126899,
  slate #526978, amber #fff4cc, archive #f0f3f5. Системная sans-serif,
  табличные цифры; жёлтый означает draft, серый — архив; текстовые статусы.
  Без внешних шрифтов/CDN, анимаций и декоративной статистики.
- [x] D4. `tests/browser/`: Playwright проверяет создание, выбор, поиск,
  Add/Cancel, Remove/Publish, Restore, pin, перезагрузку и сообщения ошибок
  на локальном fake API. Проверить desktop/mobile и отсутствие console errors.
- [x] D5. `tests/test_http_live.py`: opt-in HTTP-вызовы приложения, только собственный
  prefix, actual ID-флаги, сравнение удалённых payload, ограниченный внешний remove.
  Сохранить ID/результаты без ключа и без посещения tracking URL.
- [x] D6. README + `.env.example`, полный pytest, ruff, migration check,
  live smoke, секрет-скан, независимое итоговое review.

**Приёмка:** VT5–VT7; `verification.md` содержит команды, результаты, AC и ограничения.
**Запуск:** `uv sync --frozen --extra dev`, `uv run alembic upgrade head`,
`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`.

Результат D1–D5: 12 API-тестов, 8 браузерных сценариев (desktop 1440×1000 и
mobile 390×844), полный набор с RUN_BROWSER=1 — 127 passed / 2 skipped.
HTTP live — 1 passed, кампания #213040, выключена в finally.

Ruling: отдельный scripts/live_smoke.py заменён opt-in pytest HTTP-сценарием,
поскольку пользователь исключил дополнительный CLI. Сервисы вызываются через
TestClient с реальным KeitaroClient, БД временная; tracking URL не открывается.

Ruling: при отказе Sync из-за dirty открывается локальная версия выбранной
кампании с уведомлением. Это позволяет вернуться к черновику другой кампании,
сохраняя запрет на его затирание.

Ruling: внешние CDN не используются; контракт API доступен в /openapi.json.
/docs и /redoc отключены, чтобы не отдавать неработающий UI при self-only CSP.
