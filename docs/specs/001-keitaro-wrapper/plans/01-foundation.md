# Основа — план реализации

> Исполнитель: `superpowers:executing-plans`. Спецификация: [../spec.md](../spec.md).

**Цель:** надёжный API-клиент и схема локальных состояний.
**Архитектура:** DI клиента и сессии; HTTP ошибки без утечки ключа.
**Стек:** httpx, SQLAlchemy 2, Alembic, pydantic-settings.

## Задачи

- [ ] F1. Создать pyproject, lock, `.gitignore`, `.env.example`; Python 3.12.
- [ ] F2. `tests/test_keitaro.py`: MockTransport проверяет Api-Key/User-Agent,
  URL, 401/403/404/5xx, timeout, malformed JSON и отсутствие повторных POST.
  Запуск `uv run pytest tests/test_keitaro.py -q`: сначала RED, затем GREEN.
- [ ] F3. `app/keitaro.py`: `KeitaroClient(base_url, api_key, transport=None)`;
  get/post/put возвращают JSON или `RemoteError(status, message, uncertain)`.
  Каталоги, поиск, пагинация кампаний; mutable методы никогда не retry.
- [ ] F4. `app/models.py`: Campaign, Stream, Offer, StreamOffer, CreationOperation.
  Уникальные привязки, baseline+draft, publication intent, revision.
- [ ] F5. `migrations/env.py`, `versions/0001_initial.py`, `database.py`, `config.py`.
  `tests/test_migrations.py`: пустая временная БД, upgrade/downgrade/upgrade,
  schema совпадает с metadata. Запуск `uv run pytest tests/test_migrations.py -q`.

**Выход:** методы клиента для этапов 2/4; фабрика сессий и модели.
**Приёмка:** VT5 и ошибки клиента; отсутствие БД/секретов в tracked-наборе.
