"""Parsing a quoted price — the point where a bad string must fail loudly
rather than become a zero."""

from decimal import Decimal, localcontext

import pytest

from papilio.utils import currency as cu


@pytest.mark.parametrize(
    "value, expected",
    [
        ("۱۲۳٬۴۵۶".replace("٬", ","), 123456),  # persian digits, separator
        ("1,234,500", 1234500),
        ("  2500  ", 2500),
        (2500, 2500),
        (Decimal("2500.4"), 2500),
    ],
)
def test_a_quoted_amount_parses_to_whole_rial(value, expected) -> None:
    assert cu.to_rial(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("9007199254740993", 9007199254740993),
        ("9223372036854775807", 9223372036854775807),
        ("-9007199254740993", -9007199254740993),
        (" ۹,۰۰۷,۱۹۹,۲۵۴,۷۴۰,۹۹۳ ", 9007199254740993),
        ("۹،۰۰۷،۱۹۹،۲۵۴،۷۴۰،۹۹۳", 9007199254740993),
        ("9.007199254740993e15", 9007199254740993),
        ("1.49999999999999999", 1),
        ("2.50000000000000001", 3),
        ("-1.49999999999999999", -1),
        ("-2.50000000000000001", -3),
        ("2.5", 2),
        ("3.5", 4),
        ("-2.5", -2),
        ("-3.5", -4),
    ],
)
def test_rial_text_retains_precision_before_rounding(value, expected) -> None:
    assert cu.to_rial(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (9007199254740993, 9007199254740993),
        (9007199254740992.0, 9007199254740992),
        (2.5, 2),
        (3.5, 4),
        (-2.5, -2),
        (Decimal("9007199254740993"), 9007199254740993),
        (Decimal("2.50000000000000001"), 3),
    ],
)
def test_native_rial_numbers_keep_their_rounding(value, expected) -> None:
    assert cu.to_rial(value) == expected


def test_rial_text_precision_does_not_depend_on_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 6
        assert cu.to_rial("9007199254740993") == 9007199254740993
        assert cu.to_rial("2.50000000000000001") == 3


def test_an_exact_amount_stays_exact_as_decimal() -> None:
    assert cu.to_decimal("1,234.56") == Decimal("1234.56")


def test_money_can_be_stored_as_integer_cents() -> None:
    assert cu.to_cent("12.346") == 1235
    # an exact half goes to the even neighbour (Python's round), so a long run
    # of ties does not drift upwards
    assert cu.to_cent("12.345") == 1234


def test_rounding_lands_on_the_smallest_quoted_unit() -> None:
    assert cu.round_rial(1234) == 1230
    assert cu.round_rial(1236) == 1240


def test_gold_and_exchange_rate_conversions_use_rial_rounding() -> None:
    assert cu.from_mazane(cu.to_mazane(10_000_000)) == 10_000_000
    assert cu.from_usd(Decimal("2.5"), 600_000) == 1_500_000
    assert cu.with_bubble(10_000_000, -125_000) == 9_875_000


@pytest.mark.parametrize("value", ["", "n/a", "12abc", None, True, object()])
def test_a_non_numeric_amount_raises_instead_of_becoming_zero(value) -> None:
    with pytest.raises(ValueError):
        cu.to_rial(value)
