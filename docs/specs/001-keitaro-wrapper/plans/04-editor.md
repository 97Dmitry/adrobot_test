# Редактор — план реализации

> Исполнитель: `superpowers:executing-plans`. Спецификация: [../spec.md](../spec.md).

**Цель:** US2/US3 и внешняя синхронизация закреплений AC4.7.
**Архитектура:** baseline и draft в StreamOffer, снимок API и durable intent в Stream.
**Стек:** SQLAlchemy, чистый алгоритм весов, клиент основы.

## Задачи

- [ ] E1. `tests/test_editor.py`: импорт всех потоков, no-offer passthrough,
  неизвестное поле, внешний remove/add, пустой внешний поток, удалённый поток,
  сохранение/снятие pin. `uv run pytest tests/test_editor.py -q`: RED → GREEN.
- [ ] E2. `app/editor.py`: `sync_campaign(session, client, campaign_id)` и
  `campaign_view(session, campaign_id)`; импорт без перерасчёта, архив вместо delete.
- [ ] E3. Тесты Add/Remove/Restore/Pin/Unpin, ошибки без частичных изменений,
  Cancel новой привязки, сохранение архива, новая сессия и stale revision.
- [ ] E4. `edit_offer(session, client, stream_id, revision, offer_id, action, pin)`;
  `cancel_stream(...)`; dirty сравнивает baseline/draft и закрепления.
  Диапазон pin — 0..100; нулевой вес активной строки не делает её архивной.
  В `distribute` передаются только активные строки в стабильном порядке.
- [ ] E5. Тесты Publish: только offers в PUT, конфликт не пишет, пустой набор
  запрещён, timeout до/после применения, повтор после локального сбоя,
  неизвестный исход блокирует редактирование/Cancel до сверки.
- [ ] E6. `publish_stream(session, client, stream_id, revision)` сохраняет intent
  до PUT; сверяет snapshot; читает результат, завершает baseline либо сохраняет
  состояние сверки. Сверка по baseline/target, без слепого повторного PUT.

**Вход:** модели/клиент F и `distribute` W. **Выход:** сервисы для API/UI.
**Приёмка:** VT2/VT4; каждый тест использует новую временную SQLite и fake Keitaro.
