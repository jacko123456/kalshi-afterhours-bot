from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter
from kalshi_afterhours_bot.executor import execute_planned_actions
from kalshi_afterhours_bot.inventory import overnight_target_sizes
from kalshi_afterhours_bot.market_data import overnight_target_price
from kalshi_afterhours_bot.models import BookSide, InventoryMode, SideMode
from kalshi_afterhours_bot.reconcile import (
    DesiredOrder,
    plan_market_reconciliation,
)
from kalshi_afterhours_bot.reference import build_market_reference_snapshot


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    market_ticker = "KXINXY-26DEC31H1600-B7700"

    reference_mm_min_size = 100_000
    follow_min_size = 250
    passive_floor_price = 1
    tick_size = 1
    target_contracts_per_order = 1000
    side_mode = SideMode.BOTH
    inventory_mode = InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY
    timestamp = datetime.now(ZoneInfo("America/New_York"))

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

    print("\nREFERENCE:", ref)
    print("POSITION:", position)
    print("EXISTING ORDERS:", resting_orders)

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

    desired_yes = DesiredOrder(
        market_ticker=market_ticker,
        side=BookSide.YES,
        price=yes_target_price,
        quantity=target_sizes[BookSide.YES],
    )

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

    print("\nPLANNED ACTIONS:")
    for action in actions:
        print(action)

    results = execute_planned_actions(
        adapter=adapter,
        actions=actions,
        dry_run=True,
    )

    print("\nEXECUTION RESULTS (DRY RUN):")
    for result in results:
        print(result)


if __name__ == "__main__":
    main()