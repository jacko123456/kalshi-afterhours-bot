from __future__ import annotations

from .models import BookLevel, BookSide


def filter_visible_levels(levels: list[BookLevel], minimum_size: float) -> list[BookLevel]:
    """Drop visible levels smaller than the configured threshold.

    Why:
    The strategy should not treat tiny displayed orders as meaningful when
    deciding where to quote.
    """
    return [level for level in levels if level.quantity >= minimum_size]


def best_filtered_bid(levels: list[BookLevel], minimum_size: float) -> BookLevel | None:
    """Return the best visible bid that survives the size filter."""
    filtered = filter_visible_levels(levels, minimum_size)
    if not filtered:
        return None
    return max(filtered, key=lambda x: x.price)


def capped_one_tick_better_price(
    best_bid: BookLevel | None,
    reference_cap: int,
    passive_floor_price: int,
    tick_size: int,
) -> int:
    """Compute the desired passive quote price before non-taking checks.

    Rule summary:
    - if a qualifying best bid exists, try to quote one tick better,
    - never go above the frozen reference cap,
    - if no qualifying bid exists, fall back to the passive floor.
    """
    if best_bid is None:
        return passive_floor_price
    return min(best_bid.price + tick_size, reference_cap)


def would_take_liquidity(
    side: BookSide,
    proposed_price: int,
    opposing_best_bid: BookLevel | None,
) -> bool:
    """Return True if the proposed quote would immediately cross into a fill.

    On Kalshi's binary book, YES and NO bids are complementary. A passive buy order
    on one side would effectively take liquidity if its price plus the opposing best
    bid is greater than or equal to 100.
    """
    if opposing_best_bid is None:
        return False
    return proposed_price + opposing_best_bid.price >= 100


def highest_non_taking_price(
    opposing_best_bid: BookLevel | None,
    reference_cap: int,
    passive_floor_price: int,
) -> int:
    """Return the highest passive price that will not cross the opposing side.

    If the opposing best bid is 63, the highest passive quote on the complementary
    side is 36, because 36 + 63 = 99 remains passive, while 37 would cross.
    """
    if opposing_best_bid is None:
        return reference_cap
    return max(passive_floor_price, min(reference_cap, 99 - opposing_best_bid.price))


def overnight_target_price(
    side: BookSide,
    same_side_levels: list[BookLevel],
    opposing_side_levels: list[BookLevel],
    follow_min_size: float,
    reference_cap: int,
    passive_floor_price: int,
    tick_size: int,
) -> int:
    """Compute the final overnight target price for one side.

    Steps:
    1. Find the filtered best bid on the same side.
    2. Try to improve by one tick, capped by the frozen reference quote.
    3. If that quote would take liquidity, back off to the highest passive price.
    """
    same_best = best_filtered_bid(same_side_levels, follow_min_size)
    opposing_best = best_filtered_bid(opposing_side_levels, follow_min_size)

    proposed = capped_one_tick_better_price(
        best_bid=same_best,
        reference_cap=reference_cap,
        passive_floor_price=passive_floor_price,
        tick_size=tick_size,
    )

    if not would_take_liquidity(side=side, proposed_price=proposed, opposing_best_bid=opposing_best):
        return proposed

    return highest_non_taking_price(
        opposing_best_bid=opposing_best,
        reference_cap=reference_cap,
        passive_floor_price=passive_floor_price,
    )


def flatten_target_price(
    opposing_best_bid: BookLevel | None,
    avg_entry_price: int,
    passive_floor_price: int,
    reference_cap: int,
) -> int | None:
    """Return the daytime flattening quote price.

    During daytime flattening mode, you only want to quote the side that offsets
    existing inventory, and only at a price that keeps the weighted average entry
    plus exit quote strictly below 100.

    If there is no acceptable passive price, return None.
    """
    if opposing_best_bid is None:
        return passive_floor_price if avg_entry_price + passive_floor_price < 100 else None

    max_profitable_price = 99 - avg_entry_price
    candidate = min(opposing_best_bid.price, reference_cap, max_profitable_price)
    if candidate < passive_floor_price:
        return None
    if avg_entry_price + candidate >= 100:
        return None
    return candidate
