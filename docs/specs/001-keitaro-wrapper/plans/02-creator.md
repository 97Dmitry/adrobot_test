# Создаватор — план реализации

> Исполнитель: `superpowers:executing-plans`. Спецификация: [../spec.md](../spec.md).

**Цель:** AC1.1–AC1.7, подтверждённая двухпоточная кампания.
**Архитектура:** журнал операции до POST; выключенная кампания до завершения.
**Стек:** модели основы, Pydantic, httpx-клиент.

## Задачи

- [ ] C1. `tests/test_creator.py`: запрос AU/MX, prefix, неверный ISO/оффер/
  каталог, правильные payload и порядок, одинаковый key, иной payload с key,
  сбой второго потока и потерянный ответ кампании/включения.
  Запуск `uv run pytest tests/test_creator.py -q`: RED → GREEN.
- [ ] C2. `app/schemas.py`: `CreateCampaign(name, countries, offer_id,
  domain_id, group_id, traffic_source_id)`; pycountry для реальных ISO.
- [ ] C3. `app/creator.py`: `create_campaign(session, client, request, key)`.
  Проверить справочники; сохранить key/hash/alias; POST disabled campaign;
  POST regular geo redirect с country/accept; POST default offers; PUT active;
  GET-сверка и импорт. Хранить фазу/ошибку/известный campaign_id.
- [ ] C4. При timeout POST искать результат по уникальному alias, не создавать
  заново. Частичный результат возвращать с ID и фазой. Повтор завершённой
  операции возвращает тот же результат; незавершённой — статус/сверку.

**Вход:** `KeitaroClient`, Session и модели этапа 1.
**Выход:** сервис создания и Pydantic-схема для HTTP API и smoke.
**Приёмка:** VT1; отсутствие удалённых POST при ошибках валидации.
