"""Money primitives: currency, integer-cent money, and the domain exception base.

Money in this codebase is always an integer number of minor units (cents) plus a
currency tag. Floating point never touches money: there is no ``float()`` call, no
true division and no rounding of a binary float anywhere in this module. Amounts are
parsed from text at the input edge and formatted back to text only for display.

``Decimal`` is an implementation detail of parsing and formatting. It never appears in
a public field, return type or constructor argument.

This module imports nothing from the rest of the package: the dependency direction is
one way, and ``events.py`` imports from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Final

__all__ = [
    "MAX_CENTS",
    "MINOR_UNITS",
    "Currency",
    "CurrencyMismatch",
    "DomainError",
    "InvalidAmount",
    "InvalidCurrency",
    "Money",
    "parse_amount",
]

MINOR_UNITS: Final[int] = 2
"""Number of decimal places every currency carries in v1.

Fixed at 2 for every currency. Parsing and formatting both read this constant, so the
two edges cannot drift apart. Zero-decimal currencies such as JPY and three-decimal
currencies such as BHD are a documented v1 limitation: the spec fixes one currency per
group and cuts multi-currency support, so no conversion table exists to hold the real
exponent.
"""

MAX_CENTS: Final[int] = 2**63 - 1
"""Largest cent value the system stores.

The bound of a signed 64-bit integer column. Parsing rejects anything above it so
no amount can overflow the store it is written to.
"""

_CURRENCY_CODE_PATTERN: Final[str] = "[A-Z]{3}"
_CURRENCY_CODE_RE: Final[re.Pattern[str]] = re.compile(_CURRENCY_CODE_PATTERN)

# Amount grammar, spelled with [0-9] rather than \d so Arabic-Indic and fullwidth
# digits are rejected instead of quietly accepted by Decimal. Both the integer and the
# fractional part are optional; parse_amount rejects the string that has neither.
_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"\$?"
    r"(?P<whole>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)?"
    r"(?:\.(?P<fraction>[0-9]*))?"
)


class DomainError(Exception):
    """Base class for every domain error raised by ``splitwise_lite``.

    One base so the HTTP layer can map the whole family to a single response without
    catching bare ``Exception``. Wrong Python types raise ``TypeError`` instead: those
    are programming errors, not rejected user input.
    """


class InvalidCurrency(DomainError):
    """Raised when a currency code is not exactly three characters in ``A-Z``."""


class InvalidAmount(DomainError):
    """Raised when a user-supplied amount string cannot be parsed exactly.

    One named type for every parse rejection, carrying the offending input in its
    message so the HTTP layer can surface it without reconstructing the reason.
    """


class CurrencyMismatch(DomainError):
    """Raised when two ``Money`` values of different currencies are combined."""


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO 4217 alpha-3 currency code, for example ``AUD``.

    Invariant: ``code`` is exactly three characters drawn from ``A-Z``. Lowercase input
    is rejected rather than coerced, so a persisted code has exactly one canonical
    form and two spellings of the same currency can never coexist in the store.
    """

    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise TypeError(
                f"currency code must be a str, got {type(self.code).__name__}"
            )
        if _CURRENCY_CODE_RE.fullmatch(self.code) is None:
            raise InvalidCurrency(
                f"currency code must be three uppercase A-Z letters: {self.code!r}"
            )

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount: integer ``cents`` tagged with a ``Currency``.

    Invariants:

    * ``cents`` is an ``int``. A ``float`` is rejected, and so is a ``bool`` even
      though ``bool`` is an ``int`` subclass, because ``Money(True, aud)`` is always a
      mistake.
    * ``cents`` may be negative or zero. Balances are signed, so the primitive has to
      carry a sign.
    * Arithmetic and ordering are same-currency only; crossing currencies raises
      ``CurrencyMismatch``.
    * Division is not exposed at all, so no caller can produce a fractional cent.
      Dividing a total across people is the split resolver's job, and it works in
      whole cents with an explicit remainder rule.

    Equality stays total: two ``Money`` values of different currencies compare unequal
    rather than raising, because ``__eq__`` and ``__hash__`` have to agree for ``Money``
    to be usable in a set or a dict key. Ordering is what raises on a mismatch.
    """

    cents: int
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.cents, bool) or not isinstance(self.cents, int):
            raise TypeError(
                f"Money cents must be an int, got {type(self.cents).__name__}: "
                f"{self.cents!r}"
            )
        if not isinstance(self.currency, Currency):
            raise TypeError(
                f"Money currency must be a Currency, got "
                f"{type(self.currency).__name__}: {self.currency!r}"
            )

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot combine {self.currency.code} and {other.currency.code}"
            )

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def __mul__(self, factor: object) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            return NotImplemented
        return Money(self.cents * factor, self.currency)

    __rmul__ = __mul__

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.cents < other.cents

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.cents <= other.cents

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.cents > other.cents

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.cents >= other.cents


def parse_amount(text: str, currency: Currency) -> Money:
    """Parse a user-typed amount into ``Money``, or raise ``InvalidAmount``.

    This is the only input edge. Every amount that enters the system passes through
    here and leaves as integer cents, so no later layer has to re-check the text.

    Accepted grammar, anchored end to end against an explicit ``[0-9]`` pattern:
    optional surrounding whitespace, an optional leading ``$``, an integer part that
    is either bare digits or digits in correct three-digit comma groups, and an
    optional ``.`` followed by at most ``MINOR_UNITS`` digits. Either the integer part
    or the fractional part may be absent, but not both, so ``"12"``, ``"12."`` and
    ``".5"`` all parse and ``"."`` does not.

    Rejected on purpose:

    * More fractional digits than the currency carries, ``"12.500"`` included. The
      parser never rounds a user's amount, so trailing zeros are not an excuse.
    * ``"12,5"`` and any other comma-as-decimal-separator spelling. The app is
      single-locale with a dot separator, and a silent reading of ``12,5`` as either
      ``12.5`` or ``125`` would be a money bug.
    * Signs. Negative amounts never come from a user in this product; negative
      ``Money`` is constructed from cents by the balance layer instead.
    * ``"1e3"``, ``"NaN"``, ``"Infinity"`` and non-ASCII digits, all of which
      ``Decimal`` accepts happily. That is why the string is validated against the
      pattern *before* any ``Decimal`` is built, and why the pattern spells out
      ``[0-9]`` rather than ``\\d``.
    * Anything whose cent value would exceed ``MAX_CENTS``, so every amount fits a
      signed 64-bit integer column.

    ``"0"`` and ``"0.00"`` parse successfully. Rejecting a zero-value expense belongs
    to the expense type, not to the parser.

    Raises:
        TypeError: if ``text`` is not a ``str`` (an ``int``, ``float`` or ``Decimal``
            has skipped the input edge) or ``currency`` is not a ``Currency``.
        InvalidAmount: for every rejected string, carrying the offending input.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"amount must be a str at the input edge, got {type(text).__name__}: "
            f"{text!r}"
        )
    if not isinstance(currency, Currency):
        raise TypeError(
            f"currency must be a Currency, got {type(currency).__name__}: {currency!r}"
        )

    match = _AMOUNT_RE.fullmatch(text.strip())
    if match is None:
        raise InvalidAmount(f"not a valid amount: {text!r}")

    whole_digits = (match["whole"] or "").replace(",", "")
    fraction_digits = match["fraction"] or ""
    if not whole_digits and not fraction_digits:
        raise InvalidAmount(f"amount has no digits: {text!r}")
    if len(fraction_digits) > MINOR_UNITS:
        raise InvalidAmount(
            f"amount has more than {MINOR_UNITS} fractional digits and would have to "
            f"be rounded: {text!r}"
        )

    cents = _to_cents(whole_digits or "0", fraction_digits or "0")
    if cents > MAX_CENTS:
        raise InvalidAmount(f"amount is too large to store: {text!r}")
    return Money(cents, currency)


def _to_cents(whole_digits: str, fraction_digits: str) -> int:
    """Scale a validated digit string to an exact integer number of cents.

    Both arguments are already known to be non-empty ASCII digit runs. The decimal
    context precision is widened to the length of the value so ``scaleb`` is exact for
    any input, however long: the overflow check upstream must see the true value, not
    a silently rounded one.
    """
    with localcontext() as context:
        context.prec = len(whole_digits) + len(fraction_digits) + MINOR_UNITS + 1
        scaled = Decimal(f"{whole_digits}.{fraction_digits}").scaleb(MINOR_UNITS)
        if scaled != scaled.to_integral_value():
            raise InvalidAmount(f"amount is not a whole number of cents: {scaled}")
        return int(scaled)
