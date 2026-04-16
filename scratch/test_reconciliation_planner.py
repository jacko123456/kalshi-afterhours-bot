from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter
from kalshi_afterhours_bot.inventory import overnight_target_sizes
from kalshi_afterhours_bot.market_data import overnight_target_price
from kalshi_afterhours_bot.models import BookSide, InventoryMode, SideMode
from kalshi_afterhours_bot.reconcile import (
    DesiredOrder,
    plan_market_reconciliation,
    plan_skip_market_cancellations,
)
from kalshi_afterhours_bot.reference import build_market_reference_snapshot


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    series_ticker = "KXINXY"
    event_ticker = "KXINXY-26DEC31H1600"

    reference_mm_min_size = 100_000
    follow_min_size = 250
    passive_floor_price = 1
    tick_size = 1
    target_contracts_per_order = 1000
    side_mode = SideMode.BOTH
    inventory_mode = InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY

    timestamp = datetime.now(ZoneInfo("America/New_York"))

    # Pick a few representative markets from your dry run
    market_tickers = [
        "KXINXY-26DEC31H1600-T4000",  # existing YES, needs NO placement
        "KXINXY-26DEC31H1600-B8300",  # duplicate YES orders
        "KXINXY-26DEC31H1600-B7700",  # multiple YES orders + inventory offset
        "KXINXY-26DEC31H1600-B8900",  # skipped market
    ]

    for market_ticker in market_tickers:
        snapshot = adapter.get_market_snapshot(market_ticker)
        position = adapter.get_market_position(market_ticker)
        resting_orders = adapter.get_resting_orders(market_ticker)

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
        print("Reference:", ref)
        print("Position:", position)
        print("Existing resting orders:", resting_orders)

        if not ref.eligible:
            actions = plan_skip_market_cancellations(
                market_ticker=market_ticker,
                existing_orders=resting_orders,
            )
            print("\nPLANNED ACTIONS (SKIP MARKET):")
            for action in actions:
                print(action)
            continue

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

        desired_yes = None
        if target_sizes[BookSide.YES] > 0:
            desired_yes = DesiredOrder(
                market_ticker=market_ticker,
                side=BookSide.YES,
                price=yes_target_price,
                quantity=target_sizes[BookSide.YES],
            )

        desired_no = None
        if target_sizes[BookSide.NO] > 0:
            desired_no = DesiredOrder(
                market_ticker=market_ticker,
                side=BookSide.NO,
                price=no_target_price,
                quantity=target_sizes[BookSide.NO],
            )

        actions = plan_market_reconciliation(
            market_ticker=market_ticker,
            existing_orders=resting_orders,
            desired_yes=desired_yes,
            desired_no=desired_no,
        )

        print("\nDESIRED YES:", desired_yes)
        print("DESIRED NO:", desired_no)

        print("\nPLANNED ACTIONS:")
        for action in actions:
            print(action)


if __name__ == "__main__":
    main()