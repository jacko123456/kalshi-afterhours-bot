from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter
from kalshi_afterhours_bot.engine import OvernightCycleConfig, run_single_overnight_cycle
from kalshi_afterhours_bot.models import InventoryMode, SideMode


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    config = OvernightCycleConfig(
        series_ticker="KXINXY",
        event_ticker="KXINXY-26DEC31H1600",
        reference_mm_min_size=100_000,
        follow_min_size=250,
        passive_floor_price=1,
        tick_size=1,
        target_contracts_per_order=1000,
        side_mode=SideMode.BOTH,
        inventory_mode=InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY,
        timezone_name="America/New_York",
    )

    result = run_single_overnight_cycle(
        adapter=adapter,
        config=config,
        dry_run=True,
    )

    print("\n=== OVERNIGHT CYCLE RESULT ===")
    print("Timestamp:", result.timestamp)
    print("Event ticker:", result.event_ticker)
    print("Total markets:", len(result.market_results))
    print("Total planned actions:", result.total_actions)

    print("\n=== FIRST 8 MARKET RESULTS ===")
    for market_result in result.market_results[:8]:
        print("\n" + "=" * 100)
        print("Market:", market_result.market_ticker)
        print("Eligible:", market_result.eligible)
        print("Reason:", market_result.reason)
        print("Planned actions:")
        for action in market_result.planned_actions:
            print("  ", action)
        print("Execution results:")
        for execution in market_result.execution_results:
            print("  ", execution)


if __name__ == "__main__":
    main()