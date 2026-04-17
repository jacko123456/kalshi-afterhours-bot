from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pykalshi import KalshiClient

from .adapters import PykalshiAdapter
from .config import load_config
from .engine import (
    OvernightCycleConfig,
    capture_reference_snapshot_for_event,
    run_single_overnight_cycle_from_saved_snapshot,
)
from .logging_utils import build_logger
from .state_store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kalshi after-hours overnight bot")

    parser.add_argument(
        "command",
        choices=["capture-reference", "run-overnight"],
        help="Which action to run",
    )

    parser.add_argument(
        "--config",
        default="config/strategy.yaml",
        help="Path to YAML strategy config",
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send order actions to Kalshi. Default is dry-run.",
    )

    return parser


def summarize_actions(result) -> tuple[int, int, dict[str, int]]:
    """
    Return:
    - eligible market count
    - skipped market count
    - action_type -> count

    This makes each cycle much easier to read quickly.
    """
    eligible_markets = 0
    skipped_markets = 0
    action_counts = {"KEEP": 0, "AMEND": 0, "CANCEL": 0, "PLACE": 0}

    for market_result in result.market_results:
        if market_result.eligible:
            eligible_markets += 1
        else:
            skipped_markets += 1

        for action in market_result.planned_actions:
            if action.action_type in action_counts:
                action_counts[action.action_type] += 1

    return eligible_markets, skipped_markets, action_counts


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)

    logger = build_logger(
        name=config.strategy_name,
        level=config.logging.level,
        log_path=config.storage.log_path,
    )

    # Safety guard:
    # --live is ignored unless config.exchange.allow_live_orders is also true.
    if args.live and not config.exchange.allow_live_orders:
        raise RuntimeError(
            "Refusing live execution because exchange.allow_live_orders is false in config."
        )

    dry_run = not args.live

    load_dotenv(config.exchange.dotenv_path)
    client = KalshiClient(demo=config.exchange.demo)
    adapter = PykalshiAdapter(client)

    state_store = StateStore(
        sqlite_path=config.storage.sqlite_path,
        snapshot_json_path=config.storage.snapshot_json_path,
    )

    cycle_config = OvernightCycleConfig(
        series_ticker=config.market.series_ticker,
        event_ticker=config.market.event_ticker,
        reference_mm_min_size=config.thresholds.reference_mm_min_size,
        follow_min_size=config.thresholds.quote_follow_min_size,
        passive_floor_price=config.quoting.passive_floor_price,
        tick_size=config.quoting.default_tick_size,
        target_contracts_per_order=config.quoting.target_contracts_per_order,
        side_mode=config.quoting.side_mode,
        inventory_mode=config.quoting.inventory_mode,
        timezone_name=config.timezone,
        market_whitelist=config.market.market_whitelist or None,
    )

    if args.command == "capture-reference":
        snapshots = capture_reference_snapshot_for_event(
            adapter=adapter,
            config=cycle_config,
            state_store=state_store,
        )

        logger.info("Captured reference snapshot")
        logger.info("Event ticker: %s", config.market.event_ticker)
        logger.info("Markets captured: %d", len(snapshots))

        eligible_count = sum(1 for s in snapshots if s.eligible)
        logger.info("Eligible markets: %d", eligible_count)

        for snapshot in snapshots:
            logger.info(
                "Reference market=%s eligible=%s yes_price=%s no_price=%s reason=%s",
                snapshot.market_ticker,
                snapshot.eligible,
                snapshot.yes.price,
                snapshot.no.price,
                snapshot.reason,
            )
        return

    if args.command == "run-overnight":
        # Refuse to run if the saved snapshot is not from today's NY trading date.
        snapshot_date = state_store.get_reference_snapshot_trading_date()
        today_ny = datetime.now(ZoneInfo(config.timezone)).date()

        if snapshot_date != today_ny:
            raise RuntimeError(
                f"Refusing to run overnight cycle because saved reference snapshot date "
                f"{snapshot_date} does not match today's NY date {today_ny}."
            )

        result = run_single_overnight_cycle_from_saved_snapshot(
            adapter=adapter,
            config=cycle_config,
            state_store=state_store,
            dry_run=dry_run,
        )

        eligible_markets, skipped_markets, action_counts = summarize_actions(result)

        logger.info("Cycle complete")
        logger.info("Timestamp: %s", result.timestamp)
        logger.info("Event ticker: %s", result.event_ticker)
        logger.info("Markets processed: %d", len(result.market_results))
        logger.info("Total planned actions: %d", result.total_actions)
        logger.info("Dry run: %s", dry_run)
        logger.info("Eligible markets: %d", eligible_markets)
        logger.info("Skipped markets: %d", skipped_markets)
        logger.info(
            "Action summary: KEEP=%d AMEND=%d CANCEL=%d PLACE=%d",
            action_counts["KEEP"],
            action_counts["AMEND"],
            action_counts["CANCEL"],
            action_counts["PLACE"],
        )

        for market_result in result.market_results:
            logger.info(
                "Market=%s eligible=%s reason=%s planned_actions=%d",
                market_result.market_ticker,
                market_result.eligible,
                market_result.reason,
                len(market_result.planned_actions),
            )
            for action in market_result.planned_actions:
                logger.info(
                    "  ACTION type=%s side=%s order_id=%s price=%s quantity=%s reason=%s",
                    action.action_type,
                    action.side.value if action.side else None,
                    action.order_id,
                    action.price,
                    action.quantity,
                    action.reason,
                )
        return


if __name__ == "__main__":
    main()