"""Splitwise Lite: a shared expense ledger for small groups.

The domain vocabulary lives in two modules and is re-exported here:

* ``money``: currency, integer-cent ``Money``, amount parsing and formatting, and the
  ``DomainError`` base every domain exception subclasses.
* ``events``: the immutable ledger events, their ids and their allocations.
"""

from .events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    InvalidAllocation,
    InvalidEvent,
    LedgerEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
    new_id,
    ordering_key,
)
from .money import (
    MAX_CENTS,
    MINOR_UNITS,
    Currency,
    CurrencyMismatch,
    DomainError,
    InvalidAmount,
    InvalidCurrency,
    Money,
    format_amount,
    parse_amount,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_CENTS",
    "MINOR_UNITS",
    "Allocation",
    "Currency",
    "CurrencyMismatch",
    "DomainError",
    "ExpenseEvent",
    "ExpenseId",
    "GroupId",
    "InvalidAllocation",
    "InvalidAmount",
    "InvalidCurrency",
    "InvalidEvent",
    "LedgerEvent",
    "MemberId",
    "Money",
    "SettlementDecisionEvent",
    "SettlementEvent",
    "SettlementId",
    "SettlementState",
    "__version__",
    "format_amount",
    "new_id",
    "ordering_key",
    "parse_amount",
]
