from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter
from kalshi_afterhours_bot.market_data import (
    best_filtered_bid,
    overnight_target_price,
)
from kalshi_afterhours_bot.inventory import (
    overnight_target_sizes,
    flatten_target_sizes,
)
from kalshi_afterhours_bot.models import (
    BookSide,
    InventoryMode,
    SideMode,
)


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    market_ticker = "KXINXY-26DEC31H1600-T9000"
    snapshot = adapter.get_market_snapshot(market_ticker)
    position = adapter.get_market_position(market_ticker)

    print("\n=== SNAPSHOT ===")
    print(snapshot)

    print("\n=== POSITION ===")
    print(position)

    yes_best = best_filtered_bid(snapshot.yes_levels, minimum_size=250)
    no_best = best_filtered_bid(snapshot.no_levels, minimum_size=250)

    print("\n=== EFFECTIVE BEST BIDS (ignoring size < 250) ===")
    print("YES effective best:", yes_best)
    print("NO effective best:", no_best)

    print("\n=== OVERNIGHT TARGET PRICES ===")
    yes_target = overnight_target_price(
        side=BookSide.YES,
        same_side_levels=snapshot.yes_levels,
        opposing_side_levels=snapshot.no_levels,
        follow_min_size=250,
        reference_cap=1,          # frozen 3:55 YES MM reference for this market
        passive_floor_price=1,
        tick_size=1,
    )
    print("YES target:", yes_target)

    no_target = overnight_target_price(
        side=BookSide.NO,
        same_side_levels=snapshot.no_levels,
        opposing_side_levels=snapshot.yes_levels,
        follow_min_size=250,
        reference_cap=95,         # frozen 3:55 NO MM reference for this market
        passive_floor_price=1,
        tick_size=1,
    )
    print("NO target:", no_target)

    print("\n=== OVERNIGHT TARGET SIZES ===")
    overnight_sizes_both = overnight_target_sizes(
        side_mode=SideMode.BOTH,
        inventory_mode=InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY,
        target_contracts_per_order=1000,
        position=position,
    )
    print("Both-side mode:", overnight_sizes_both)

    overnight_sizes_yes_only = overnight_target_sizes(
        side_mode=SideMode.YES_ONLY,
        inventory_mode=InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY,
        target_contracts_per_order=1000,
        position=position,
    )
    print("YES-only mode:", overnight_sizes_yes_only)

    overnight_sizes_no_only = overnight_target_sizes(
        side_mode=SideMode.NO_ONLY,
        inventory_mode=InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY,
        target_contracts_per_order=1000,
        position=position,
    )
    print("NO-only mode:", overnight_sizes_no_only)

    print("\n=== FLATTEN TARGET SIZES ===")
    flatten_sizes = flatten_target_sizes(position)
    print(flatten_sizes)


if __name__ == "__main__":
    main()