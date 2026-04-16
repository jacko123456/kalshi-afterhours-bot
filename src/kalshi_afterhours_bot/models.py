from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SideMode(str, Enum):
    """Which side(s) the strategy actively quotes overnight."""

    BOTH = "both"
    YES_ONLY = "yes_only"
    NO_ONLY = "no_only"


class InventoryMode(str, Enum):
    """How the strategy sizes the opposing side relative to inventory."""

    FIXED_OPPOSITE_SIZE = "fixed_opposite_size"
    OFFSET_OPPOSITE_BY_INVENTORY = "offset_opposite_by_inventory"


class BookSide(str, Enum):
    """Book side label used throughout the bot."""

    YES = "yes"
    NO = "no"


class SessionPhase(str, Enum):
    """High-level session state for scheduler and engine logic."""

    PRE_CAPTURE = "pre_capture"
    CAPTURE_WINDOW = "capture_window"
    OVERNIGHT_REPRICE = "overnight_reprice"
    DAYTIME_FLATTEN = "daytime_flatten"


@dataclass(slots=True)
class BookLevel:
    """One visible price level on a YES or NO bid ladder.

    Prices are stored as discrete integer ticks for deterministic comparisons.
    Right now that means integer cents, but keeping the field generic lets us
    adapt later if Kalshi introduces fractional increments.
    """

    price: int
    quantity: float


@dataclass(slots=True)
class ReferenceQuote:
    """Frozen 3:55 PM reference quote for one market side."""

    price: Optional[int]
    quantity: Optional[float]


@dataclass(slots=True)
class MarketReferenceSnapshot:
    """Reference snapshot for a single market in the event."""

    market_ticker: str
    yes: ReferenceQuote
    no: ReferenceQuote
    timestamp: datetime
    eligible: bool
    reason: Optional[str] = None


@dataclass(slots=True)
class MarketPosition:
    """Current net exchange position for one market.

    `side` is the side Kalshi reports as the current net position.
    `quantity` is the magnitude of that position.

    Example:
    - side=yes, quantity=120 => long 120 YES
    - side=no, quantity=40   => long 40 NO
    - side=None, quantity=0  => flat
    """

    market_ticker: str
    side: Optional[BookSide]
    quantity: float
    avg_entry_price: Optional[int] = None

    def normalized_yes_inventory(self) -> float:
        """Return the net inventory measured in YES-space.

        Positive means long YES.
        Negative means long NO.
        """
        if self.side is None or self.quantity == 0:
            return 0.0
        return self.quantity if self.side == BookSide.YES else -self.quantity


@dataclass(slots=True)
class RestingOrderState:
    """One currently open resting order on the exchange."""

    order_id: str
    market_ticker: str
    side: BookSide
    price: int
    quantity: float


@dataclass(slots=True)
class TargetOrder:
    """Desired order state after the current decision cycle."""

    market_ticker: str
    side: BookSide
    desired_price: int
    desired_quantity: float
    reason: str


@dataclass(slots=True)
class OrderDecision:
    """Final reconcile decision for one market side."""

    market_ticker: str
    side: BookSide
    action: str
    details: str


@dataclass(slots=True)
class CycleSummary:
    """Persisted summary of one engine cycle."""

    timestamp: datetime
    phase: SessionPhase
    decisions: list[OrderDecision] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
