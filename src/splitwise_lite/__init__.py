"""Splitwise Lite: a shared expense ledger for small groups.

The domain vocabulary lives in four modules and is re-exported here:

* ``money``: currency, integer-cent ``Money``, amount parsing and formatting, and the
  ``DomainError`` base every domain exception subclasses.
* ``events``: the immutable ledger events, their ids and their allocations.
* ``split``: the resolver that turns a total and a split mode into the explicit
  allocations an expense event stores.
* ``balances``: the fold that derives pairwise debts and net positions from a ledger,
  and the settlement states that decide which settlements counted.
"""

from .balances import (
    Balances,
    InvalidLedger,
    derive_balances,
    settlement_states,
)
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
from .split import (
    InvalidSplit,
    split_by_weight,
    split_equally,
    split_exact,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_CENTS",
    "MINOR_UNITS",
    "Allocation",
    "Balances",
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
    "InvalidLedger",
    "InvalidSplit",
    "LedgerEvent",
    "MemberId",
    "Money",
    "SettlementDecisionEvent",
    "SettlementEvent",
    "SettlementId",
    "SettlementState",
    "__version__",
    "derive_balances",
    "format_amount",
    "new_id",
    "ordering_key",
    "parse_amount",
    "settlement_states",
    "split_by_weight",
    "split_equally",
    "split_exact",
]
