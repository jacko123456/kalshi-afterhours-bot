from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter
from kalshi_afterhours_bot.inventory import overnight_target_sizes
from kalshi_afterhours_bot.market_data import best_filtered_bid, overnight_target_price
from kalshi_afterhours_bot.models import BookSide, InventoryMode, SideMode
from kalshi_afterhours_bot.reference import build_market_reference_snapshot


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    series_ticker = "KXINXY"
    event_ticker = "KXINXY-26DEC31H1600"

    # Temporary hardcoded test params
    reference_mm_min_size = 100_000
    follow_min_size = 250
    passive_floor_price = 1
    tick_size = 1
    target_contracts_per_order = 1000
    side_mode = SideMode.BOTH
    inventory_mode = InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY

    timestamp = datetime.now(ZoneInfo("America/New_York"))

    print("\n=== EVENT-LEVEL DECISION DRY RUN ===")
    market_tickers = adapter.list_event_market_tickers(
        series_ticker=series_ticker,
        event_ticker=event_ticker,
    )

    for market_ticker in market_tickers:
        snapshot = adapter.get_market_snapshot(market_ticker)

        ref = build_market_reference_snapshot(
            market_ticker=market_ticker,
            yes_levels=snapshot.yes_levels,
            no_levels=snapshot.no_levels,
            minimum_size=reference_mm_min_size,
            timestamp=timestamp,
        )

        print(f"\n{'=' * 100}")
        print(market_ticker)
        print(f"{'=' * 100}")
        print("Reference snapshot:", ref)

        if not ref.eligible:
            print("Status: SKIP MARKET (missing one or both reference sides)")
            continue

        position = adapter.get_market_position(market_ticker)
        resting_orders = adapter.get_resting_orders(market_ticker)

        print("Position:", position)
        print("Resting orders:", resting_orders)

        target_sizes = overnight_target_sizes(
            side_mode=side_mode,
            inventory_mode=inventory_mode,
            target_contracts_per_order=target_contracts_per_order,
            position=position,
        )

        yes_target_price = overnight_target_price(
            side=BookSide.YES,
            same_side_levels=snapshot.yes_levels,
            opposing_side_levels=snapshot.no_levels,
            follow_min_size=follow_min_size,
            reference_cap=ref.yes.price,
            passive_floor_price=passive_floor_price,
            tick_size=tick_size,
        )

        no_target_price = overnight_target_price(
            side=BookSide.NO,
            same_side_levels=snapshot.no_levels,
            opposing_side_levels=snapshot.yes_levels,
            follow_min_size=follow_min_size,
            reference_cap=ref.no.price,
            passive_floor_price=passive_floor_price,
            tick_size=tick_size,
        )

        yes_best = best_filtered_bid(snapshot.yes_levels, follow_min_size)
        no_best = best_filtered_bid(snapshot.no_levels, follow_min_size)

        print("Filtered YES best:", yes_best)
        print("Filtered NO best:", no_best)

        print("Target YES price:", yes_target_price)
        print("Target NO price:", no_target_price)
        print("Target sizes:", target_sizes)


if __name__ == "__main__":
    main()