"""Splitwise Lite: a shared expense ledger for small groups.

The domain vocabulary lives in six modules and is re-exported here:

* ``money``: currency, integer-cent ``Money``, amount parsing and formatting, and the
  ``DomainError`` base every domain exception subclasses.
* ``events``: the immutable ledger events, their ids and their allocations.
* ``split``: the resolver that turns a total and a split mode into the explicit
  allocations an expense event stores.
* ``balances``: the fold that derives pairwise debts and net positions from a ledger,
  and the settlement states that decide which settlements counted.
* ``simplify``: the greedy pass that turns those net positions into suggested
  transfers, each carrying the pairwise debts it absorbed.
* ``store``: the durable, append-only SQLite store those events are written to and
  read back from, and the user, group and member records they reference.
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
from .simplify import (
    AbsorbedDebt,
    InvalidBalances,
    Transfer,
    TransferPlan,
    simplify_debts,
)
from .split import (
    InvalidSplit,
    split_by_weight,
    split_equally,
    split_exact,
)
from .store import (
    BUSY_TIMEOUT_MS,
    IN_MEMORY,
    MIN_SQLITE_VERSION,
    SCHEMA_VERSION,
    AmountTooLarge,
    CannotOpenStore,
    ConstraintViolated,
    DuplicateRecord,
    EventStore,
    Group,
    InvalidRecord,
    Member,
    RecordNotFound,
    StorageFailed,
    StoreClosed,
    StoreError,
    UnsupportedSchemaVersion,
    UnsupportedSQLiteVersion,
    User,
    UserId,
    open_store,
)

__version__ = "0.1.0"

__all__ = [
    "BUSY_TIMEOUT_MS",
    "IN_MEMORY",
    "MAX_CENTS",
    "MINOR_UNITS",
    "MIN_SQLITE_VERSION",
    "SCHEMA_VERSION",
    "AbsorbedDebt",
    "Allocation",
    "AmountTooLarge",
    "Balances",
    "CannotOpenStore",
    "ConstraintViolated",
    "Currency",
    "CurrencyMismatch",
    "DomainError",
    "DuplicateRecord",
    "EventStore",
    "ExpenseEvent",
    "ExpenseId",
    "Group",
    "GroupId",
    "InvalidAllocation",
    "InvalidAmount",
    "InvalidBalances",
    "InvalidCurrency",
    "InvalidEvent",
    "InvalidLedger",
    "InvalidRecord",
    "InvalidSplit",
    "LedgerEvent",
    "Member",
    "MemberId",
    "Money",
    "RecordNotFound",
    "SettlementDecisionEvent",
    "SettlementEvent",
    "SettlementId",
    "SettlementState",
    "StorageFailed",
    "StoreClosed",
    "StoreError",
    "Transfer",
    "TransferPlan",
    "UnsupportedSQLiteVersion",
    "UnsupportedSchemaVersion",
    "User",
    "UserId",
    "__version__",
    "derive_balances",
    "format_amount",
    "new_id",
    "open_store",
    "ordering_key",
    "parse_amount",
    "settlement_states",
    "simplify_debts",
    "split_by_weight",
    "split_equally",
    "split_exact",
]
