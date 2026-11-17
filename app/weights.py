from app.errors import DomainError


def distribute(pins: list[int | None]) -> list[int]:
    """Keep pinned integer shares; divide the remainder in stable input order.

    None means unpinned. The caller supplies active offers only and handles
    archived rows separately. Empty input represents an empty draft, not a
    publishable flow. This function performs no I/O and does not mutate input.
    """
    if not pins:
        return []
    for pin in pins:
        if pin is not None and (type(pin) is not int or not 0 <= pin <= 100):
            raise DomainError(
                "Закреплённый вес должен быть целым числом от 0 до 100.",
                code="weight_budget",
            )

    remaining = 100 - sum(pin for pin in pins if pin is not None)
    if remaining < 0:
        raise DomainError("Сумма закреплённых весов превышает 100%.", code="weight_budget")
    free_count = pins.count(None)
    if free_count == 0:
        if remaining != 0:
            raise DomainError(
                "Все веса закреплены. Их сумма должна быть 100%; освободите закрепление или измените вес.",
                code="weight_budget",
            )
        return [pin for pin in pins if pin is not None]

    share, extra = divmod(remaining, free_count)
    result = []
    free_index = 0
    for pin in pins:
        if pin is None:
            result.append(share + int(free_index < extra))
            free_index += 1
        else:
            result.append(pin)
    return result
