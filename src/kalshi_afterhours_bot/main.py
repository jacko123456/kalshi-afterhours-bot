from __future__ import annotations

import argparse

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


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)

    logger = build_logger(
        name=config.strategy_name,
        level=config.logging.level,
        log_path=config.storage.log_path,
    )

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
        result = run_single_overnight_cycle_from_saved_snapshot(
            adapter=adapter,
            config=cycle_config,
            state_store=state_store,
            dry_run=dry_run,
        )

        logger.info("Cycle complete")
        logger.info("Timestamp: %s", result.timestamp)
        logger.info("Event ticker: %s", result.event_ticker)
        logger.info("Markets processed: %d", len(result.market_results))
        logger.info("Total planned actions: %d", result.total_actions)
        logger.info("Dry run: %s", dry_run)

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