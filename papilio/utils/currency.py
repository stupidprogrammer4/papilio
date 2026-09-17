"""Turning a quoted amount into a number you can store.

A price arrives as whatever its source felt like sending: a Persian-digit
string with thousands separators, a float, a `Decimal`. These normalise that to
one storable integer or `Decimal`, and refuse anything that is not a number
rather than silently coercing it — a price that quietly becomes `0` is worse
than a failed import.

`utils.persian` is the other half of the pair: this parses inbound text, that
formats outbound.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from papilio.utils import persian

QuotedAmount = str | int | float | Decimal
MAZANE_FACTOR = Decimal("4.331802")
TROY_OUNCE_GRAMS = Decimal("31.1034768")


def _normalize(value: QuotedAmount) -> str | None:
    """Strip a quoted string down to something `Decimal` will accept, or return
    `None` when the value was already numeric."""
    text = None
    if isinstance(value, str):
        text = persian.to_english_digits(value)
        text = text.strip().replace(",", "").replace("،", "")
    return text


def _numeric(value: QuotedAmount) -> int | float | Decimal:
    # bool is an int in Python; True as an amount is always a bug
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"non-numeric amount: {value!r}")
    return value


def round_rial(amount: int | float | Decimal) -> int:
    """Round to the nearest 10 rial — the smallest unit actually quoted."""
    rial = round(amount / 10) * 10
    return rial


def to_mazane(per_gram: int) -> int:
    """Convert a per-gram rial quote to an Iranian mazane quote."""
    return round_rial(per_gram * MAZANE_FACTOR)


def from_mazane(mazane: int) -> int:
    """Convert an Iranian mazane quote to its per-gram rial quote."""
    return round_rial(mazane / MAZANE_FACTOR)


def from_usd(amount: Decimal, usd_rial: int) -> int:
    """Convert an exact USD amount using a rial exchange rate."""
    return round_rial(amount * Decimal(usd_rial))


def with_bubble(intrinsic: int, bubble: int) -> int:
    """Apply a positive or negative market bubble to intrinsic value."""
    return round_rial(intrinsic + bubble)


def to_rial(value: QuotedAmount) -> int:
    """Parse a quoted amount into whole rial.

    Strings are parsed exactly as Decimal before rounding. Exact halfway
    values round to the even integer; native numeric inputs keep their
    precision.

    Args:
        value (QuotedAmount): A number, or a string in Persian or English
            digits.
    Returns:
        (int): The amount, rounded to the nearest whole unit.
    Raises:
        ValueError: The value does not read as a number.
    """
    number: int | float | Decimal
    text = _normalize(value)
    if text is None:
        number = _numeric(value)
    else:
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"non-numeric amount: {value!r}") from None
    rial = round(number)
    return rial


def to_decimal(value: QuotedAmount) -> Decimal:
    """Parse a quoted amount into an exact `Decimal` — use this, not `float`,
    for anything that will be summed or multiplied."""
    text = _normalize(value)
    if text is None:
        text = str(_numeric(value))
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"non-numeric amount: {value!r}") from None
    return number


def to_cent(value: QuotedAmount) -> int:
    """Parse a quoted amount into integer cents (store money as an integer)."""
    cents = round(to_decimal(value) * 100)
    return cents
