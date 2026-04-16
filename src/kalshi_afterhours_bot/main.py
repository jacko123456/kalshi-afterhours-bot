from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from .adapters import DryRunAdapter
from .config import load_config
from .engine import StrategyEngine
from .logging_utils import build_logger
from .models import SessionPhase
from .scheduler import ScheduleWindow, current_phase
from .state_store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kalshi after-hours shadow bot")
    parser.add_argument(
        "--config",
        default="config/strategy.yaml",
        help="Path to YAML strategy config",
    )
    parser.add_argument(
        "--capture-reference",
        action="store_true",
        help="Run the 3:55 PM reference snapshot logic immediately",
    )
    parser.add_argument(
        "--cycle",
        action="store_true",
        help="Run a single decision cycle immediately",
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
    state_store = StateStore(
        sqlite_path=config.storage.sqlite_path,
        snapshot_json_path=config.storage.snapshot_json_path,
    )

    # Start with DryRunAdapter.
    # Replace with PykalshiAdapter(client) once your environment-specific wiring is finished.
    exchange = DryRunAdapter()

    engine = StrategyEngine(
        config=config,
        exchange=exchange,
        state_store=state_store,
        logger=logger,
    )

    now = datetime.now(ZoneInfo(config.timezone))

    if args.capture_reference:
        snapshots = engine.capture_reference_snapshot(now)
        logger.info("Captured %d reference snapshots", len(snapshots))
        return

    if args.cycle:
        schedule = ScheduleWindow(
            timezone=config.timezone,
            capture_reference_time=config.schedule.capture_reference_time,
            begin_repricing_time=config.schedule.begin_repricing_time,
            end_overnight_time=config.schedule.end_overnight_time,
            reprice_every_minutes=config.schedule.reprice_every_minutes,
        )
        phase = current_phase(now, schedule)
        if phase in {SessionPhase.PRE_CAPTURE, SessionPhase.CAPTURE_WINDOW}:
            logger.info("Current phase is %s; no trading cycle executed", phase.value)
            return
        summary = engine.build_cycle_summary(now, phase)
        state_store.save_cycle_summary(summary)
        logger.info("Saved cycle summary with %d decisions", len(summary.decisions))
        for decision in summary.decisions:
            logger.info(
                "%s | %s | %s | %s",
                decision.market_ticker,
                decision.side.value,
                decision.action,
                decision.details,
            )
        return

    logger.info("Nothing requested. Use --capture-reference or --cycle.")
