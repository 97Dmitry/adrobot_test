# Общий план реализации

> Исполнение: `superpowers:executing-plans`, последовательно в текущем checkout.
> Общая спецификация: [spec.md](spec.md). Пользователь разрешил реализацию.

**Цель:** работающий локальный редактор Keitaro с воспроизводимой проверкой ТЗ.
**Архитектура:** один FastAPI-процесс, синхронный httpx-клиент, SQLAlchemy 2,
SQLite и Alembic. Сервер отдаёт статический интерфейс и JSON API.
**Стек:** Python 3.12+, FastAPI, SQLAlchemy, Alembic, httpx, pytest, Hypothesis.

## Общие ограничения

- Имена создаваемых кампаний начинаются с `test_tsibizov_`.
- Ключ только в `.env`/окружении, никогда в браузере или tracked-файлах.
- Один worker, локальное использование, сериализация изменений одного процесса.
- Все записи Keitaro через клиент приложения, без автоматических повторов.
- Коммиты/push/PR/merge разрешены: отдельная ветка и PR на каждый этап.
  Worktree не создаётся; изменения делаются в текущем checkout.

## Этапы и зависимости

1. [Основа](plans/01-foundation.md) — конфигурация, HTTP-клиент, БД, миграции.
2. [Создаватор](plans/02-creator.md) — валидация, операция создания, два потока.
3. [Веса](plans/03-weights.md) — чистый алгоритм и проверки инвариантов.
4. [Редактор](plans/04-editor.md) — импорт, архив, черновик, конфликт и публикация.
5. [Приёмка](plans/05-delivery.md) — UI, браузер, live smoke, README, review.

Создаватор использует модели и клиент основы; редактор использует их и алгоритм
весов. Интерфейс реализуется после API, чтобы показывать реальные состояния.

## Структура и контракты

- `app/config.py`, `database.py`, `models.py`: настройки, сессии, сохранённые состояния.
- `app/keitaro.py`: `KeitaroClient.get/post/put`, каталоги, кампании, потоки, офферы.
- `app/errors.py`: ошибки домена и безопасные ошибки интеграции.
- `app/schemas.py`: входные данные Pydantic, revision и idempotency key.
- `app/creator.py`: `create_campaign(session, client, request, key)`.
- `app/weights.py`: `distribute(pins: list[int | None]) -> list[int]`.
- `app/editor.py`: import/sync, edit/cancel/publish и сериализация состояния.
- `app/main.py`: `create_app(settings=None, client=None)` для DI и тестов.
- `app/static/`: HTML, CSS и JavaScript без внешних CDN.
- `migrations/`: явные версии Alembic; schema не создаётся на старте приложения.
- `tests/`: клиент, создатель, веса, редактор, API и миграции.
- `scripts/live_smoke.py`: ограниченная проверка собственных тестовых кампаний.

Основные API: `GET /api/catalogs`, `/api/offers?q=`, `/api/campaigns?q=`,
`POST /api/campaigns` с `Idempotency-Key`, `POST /api/campaigns/{id}/sync`,
`GET /api/campaigns/{id}` (локальное состояние),
`POST /api/streams/{id}/offers`, `/cancel`, `/publish`,
`PATCH /api/streams/{id}/offers/{offer_id}` с revision и действием.

## Review focus

- Потеря ответа на POST/PUT: сохранённое намерение, сверка чтением, без слепого повтора.
- Полностью очищенный внешний поток: архив и восстановление при совместимой схеме.
- Устаревшая вкладка: revision конфликт, локальные правки не теряются.
- Закрепления исчерпали бюджет: атомарный отказ, прежние веса сохраняются.
- Неизвестные/удалённые справочники и офферы: отказ до первого удалённого POST.

## Проверка покрытия

US1/VT1 — этап 2; US4/VT3 — этап 3; US2/US3/VT2/VT4 — этап 4;
VT5 — этапы 1 и 5; VT6/VT7 — этап 5. Итоги — [verification.md](verification.md).

Все этапы проходят цикл тест → наблюдаемый отказ → реализация → успешная
проверка. Конфигурация, миграции и статическая вёрстка проверяются своими
проверками запуска и браузером. Изменения решений отражаются в progress.md.
