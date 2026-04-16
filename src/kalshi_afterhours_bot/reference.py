from __future__ import annotations

from datetime import datetime

from .models import BookLevel, MarketReferenceSnapshot, ReferenceQuote


def first_large_level(levels: list[BookLevel], minimum_size: float) -> ReferenceQuote:
    """Return the first qualifying displayed level from best price outward.

    This matches your strategy's definition of the market-maker reference quote.
    """
    for level in levels:
        if level.quantity >= minimum_size:
            return ReferenceQuote(price=level.price, quantity=level.quantity)
    return ReferenceQuote(price=None, quantity=None)


def build_market_reference_snapshot(
    market_ticker: str,
    yes_levels: list[BookLevel],
    no_levels: list[BookLevel],
    minimum_size: float,
    timestamp: datetime,
) -> MarketReferenceSnapshot:
    """Create the frozen 3:55 PM snapshot object for one market."""
    yes_quote = first_large_level(yes_levels, minimum_size)
    no_quote = first_large_level(no_levels, minimum_size)
    eligible = yes_quote.price is not None and no_quote.price is not None
    reason = None if eligible else "missing_reference_on_one_or_both_sides"
    return MarketReferenceSnapshot(
        market_ticker=market_ticker,
        yes=yes_quote,
        no=no_quote,
        timestamp=timestamp,
        eligible=eligible,
        reason=reason,
    )
