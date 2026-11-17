# Интерфейс и приёмка — план реализации

> Исполнитель: `superpowers:executing-plans`. Спецификация: [../spec.md](../spec.md).

**Цель:** использовать все сценарии через браузер и воспроизвести запуск по README.
**Архитектура:** JSON API + статическая страница с того же origin; один worker.
**Стек:** FastAPI, vanilla JavaScript, CSS, Playwright для проверки.

## Задачи

- [ ] D1. `tests/test_api.py`: TestClient, DI, ошибки, revision, идемпотентность,
  поиск, формы и health; unsafe origins отклоняются. RED → GREEN.
- [ ] D2. `app/main.py`: `create_app(settings=None, client=None)`; маршруты из
  общего плана, один RLock для операций, безопасные JSON-ошибки.
- [ ] D3. `app/static/index.html`, `app.js`, `style.css`: слева создание/выбор,
  справа рабочие потоки. Палитра white #fff, navy #18384b, blue #126899,
  slate #526978, amber #fff4cc, archive #f0f3f5. Системная sans-serif,
  табличные цифры; жёлтый означает draft, серый — архив; текстовые статусы.
  Без внешних шрифтов/CDN, анимаций и декоративной статистики.
- [ ] D4. `tests/browser/`: Playwright проверяет создание, выбор, поиск,
  Add/Cancel, Remove/Publish, Restore, pin, перезагрузку и сообщения ошибок
  на локальном fake API. Проверить desktop/mobile и отсутствие console errors.
- [ ] D5. `scripts/live_smoke.py`: httpx-вызовы приложения, только собственный
  prefix, actual ID-флаги, сравнение удалённых payload, ограниченный внешний remove.
  Сохранить ID/результаты без ключа и без посещения tracking URL.
- [ ] D6. README + `.env.example`, полный pytest, ruff, migration check,
  live smoke, секрет-скан, независимое итоговое review.

**Приёмка:** VT5–VT7; `verification.md` содержит команды, результаты, AC и ограничения.
**Запуск:** `uv sync --frozen --extra dev`, `uv run alembic upgrade head`,
`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`.
