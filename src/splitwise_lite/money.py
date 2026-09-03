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
from typing import Final

__all__ = [
    "MINOR_UNITS",
    "Currency",
    "CurrencyMismatch",
    "DomainError",
    "InvalidCurrency",
    "Money",
]

MINOR_UNITS: Final[int] = 2
"""Number of decimal places every currency carries in v1.

Fixed at 2 for every currency. Parsing and formatting both read this constant, so the
two edges cannot drift apart. Zero-decimal currencies such as JPY and three-decimal
currencies such as BHD are a documented v1 limitation: the spec fixes one currency per
group and cuts multi-currency support, so no conversion table exists to hold the real
exponent.
"""

_CURRENCY_CODE_PATTERN: Final[str] = "[A-Z]{3}"
_CURRENCY_CODE_RE: Final[re.Pattern[str]] = re.compile(_CURRENCY_CODE_PATTERN)


class DomainError(Exception):
    """Base class for every domain error raised by ``splitwise_lite``.

    One base so the HTTP layer can map the whole family to a single response without
    catching bare ``Exception``. Wrong Python types raise ``TypeError`` instead: those
    are programming errors, not rejected user input.
    """


class InvalidCurrency(DomainError):
    """Raised when a currency code is not exactly three characters in ``A-Z``."""


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
