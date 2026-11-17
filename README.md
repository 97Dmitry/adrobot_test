# Обёртка над Keitaro

Тестовое Adrobot: создание кампаний с двумя потоками и редактор офферов.
Стек: FastAPI, SQLAlchemy 2, Alembic, SQLite; интерфейс — HTML/JavaScript.

Разработка идёт по этапам с отдельным PR и приёмкой каждого этапа.
Требования и сценарии: [spec.md](docs/specs/001-keitaro-wrapper/spec.md).
Порядок работ: [plan.md](docs/specs/001-keitaro-wrapper/plan.md).

## Текущее состояние

В этой версии доступны клиент Admin API, миграции и сервис создания кампаний.
Сервис проверяется автоматическими тестами. HTTP-маршруты, интерфейс и редактор
входят в следующие PR.

Создаватор проверяет справочники, создаёт выключенную кампанию, добавляет
гео-поток на Google и поток с оффером. Он включает кампанию только после
повторного чтения и проверки настроек обоих потоков.

## Установка и миграции

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/getting-started/installation/).
Проверенная версия uv — 0.12.22. Команды выполняются из корня проекта.

```sh
uv sync --frozen --extra dev
```

Создайте локальный `.env` из `.env.example`:

```sh
# Linux / WSL / macOS
cp .env.example .env
```

```bat
rem Windows cmd
copy .env.example .env
```

Заполните `KEITARO_URL` и `KEITARO_API_KEY`. URL — адрес вашего тестового
сервера, без `/admin_api/v1`; пример в `.env.example` указывает на сервер задания.
Ключ не нужен для локальных автоматических тестов. `.env` и файлы SQLite
исключены из Git; ключ используется только сервером.

```sh
uv run alembic upgrade head
uv run alembic current
```

Схема не создаётся автоматически при запуске. Новые миграции добавляются
отдельными версиями Alembic. `downgrade base` удаляет все таблицы приложения
и данные: используйте его только на одноразовой тестовой БД, как в тестах.

## Проверки

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check app tests migrations
uv run --extra dev ruff format --check app tests migrations
```

Тесты используют временную SQLite и `httpx.MockTransport`; реальный Keitaro
ими не изменяется. Проверяются payload и порядок действий, валидация,
частичные сбои, потерянные ответы, повторные запросы и миграции.
Результаты по критериям: [verification.md](docs/specs/001-keitaro-wrapper/verification.md).

При реальных проверках создаются только кампании `test_tsybizov_*`.
Трекинговые ссылки не открываются: настройка маршрутизации проверяется через
Admin API, а фактический редирект по IP требует отдельной проверки с нужным IP.
