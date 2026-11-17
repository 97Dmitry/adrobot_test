import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.errors import DomainError
from app.weights import distribute


@pytest.mark.parametrize(
    "pins,expected",
    [
        ([], []),
        ([None], [100]),
        ([None] * 3, [34, 33, 33]),
        ([None] * 4, [25, 25, 25, 25]),
        ([25, None, None], [25, 38, 37]),
        ([None, 25, None], [38, 25, 37]),
        ([None, 60, 15, None], [13, 60, 15, 12]),
        ([40, 60], [40, 60]),
        ([100], [100]),
        ([0, 100], [0, 100]),
        ([0, None], [0, 100]),
        ([None, 0, None], [50, 0, 50]),
        ([100, None, None], [100, 0, 0]),
        ([99, None, None], [99, 1, 0]),
        ([None] * 101, [1] * 100 + [0]),
    ],
)
def test_distribution_examples(pins, expected):
    before = pins.copy()
    assert distribute(pins) == expected
    assert pins == before


@pytest.mark.parametrize(
    "pins", [[80, 30], [25, 25], [0], [-1], [101], [True], [False], [1.5], ["25"]]
)
def test_invalid_distribution_is_rejected_without_changing_input(pins):
    before = pins.copy()
    with pytest.raises(DomainError) as error:
        distribute(pins)
    assert error.value.status == 422
    assert error.value.code == "weight_budget"
    assert pins == before


@given(st.integers(min_value=1, max_value=250))
def test_unpinned_invariants(count):
    result = distribute([None] * count)
    assert sum(result) == 100
    assert min(result) >= 0
    assert max(result) - min(result) <= 1
    assert result == sorted(result, reverse=True)


@st.composite
def valid_pins(draw):
    count = draw(st.integers(min_value=1, max_value=40))
    # At least one unpinned row can absorb the remaining budget.
    unpinned_at = draw(st.integers(min_value=0, max_value=count - 1))
    remaining = 100
    pins = []
    for index in range(count):
        if index == unpinned_at or draw(st.booleans()):
            pins.append(None)
        else:
            pin = draw(st.integers(min_value=0, max_value=remaining))
            pins.append(pin)
            remaining -= pin
    return pins


@given(valid_pins())
def test_multiple_pins_and_integer_budget_invariants(pins):
    before = pins.copy()
    result = distribute(pins)
    assert pins == before
    assert len(result) == len(pins)
    assert sum(result) == 100
    assert all(type(value) is int and 0 <= value <= 100 for value in result)
    for index, pin in enumerate(pins):
        if pin is not None:
            assert result[index] == pin
    free = [result[index] for index, pin in enumerate(pins) if pin is None]
    assert max(free) - min(free) <= 1
    assert free == sorted(free, reverse=True)
    assert distribute(pins) == result


@given(valid_pins())
def test_add_then_remove_unpinned_offer_restores_distribution(pins):
    initial = distribute(pins)
    expanded = pins + [None]
    added = distribute(expanded)
    assert sum(added) == 100
    assert all(added[i] == pin for i, pin in enumerate(pins) if pin is not None)
    assert distribute(expanded[:-1]) == initial
