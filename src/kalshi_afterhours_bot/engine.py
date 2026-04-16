from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .adapters import ExchangeAdapter
from .executor import ExecutionResult, execute_planned_actions
from .inventory import overnight_target_sizes
from .market_data import overnight_target_price
from .models import BookSide, InventoryMode, SideMode
from .reconcile import (
    DesiredOrder,
    PlannedAction,
    plan_market_reconciliation,
    plan_skip_market_cancellations,
)
from .reference import build_market_reference_snapshot


@dataclass
class OvernightCycleConfig:
    """
    Config required to run one overnight cycle.

    Keep this small and explicit so one cycle is easy to reason about.
    """
    series_ticker: str
    event_ticker: str
    reference_mm_min_size: float
    follow_min_size: float
    passive_floor_price: int
    tick_size: int
    target_contracts_per_order: float
    side_mode: SideMode
    inventory_mode: InventoryMode
    timezone_name: str = "America/New_York"


@dataclass
class MarketCycleResult:
    """
    Full per-market output of one overnight cycle.

    This is useful for:
    - debugging
    - persistence
    - log summaries
    """
    market_ticker: str
    eligible: bool
    reason: str | None
    planned_actions: list[PlannedAction]
    execution_results: list[ExecutionResult]


@dataclass
class OvernightCycleResult:
    """
    Result of running one full overnight cycle across the event.
    """
    timestamp: datetime
    event_ticker: str
    market_results: list[MarketCycleResult]

    @property
    def total_actions(self) -> int:
        return sum(len(m.planned_actions) for m in self.market_results)


def run_single_overnight_cycle(
    adapter: ExchangeAdapter,
    config: OvernightCycleConfig,
    dry_run: bool = True,
) -> OvernightCycleResult:
    """
    Run one full overnight cycle for one event.

    This function does the full sequence:
    - enumerate markets
    - build reference eligibility
    - fetch positions and resting orders
    - compute desired orders
    - reconcile current vs desired
    - execute planned actions (dry-run or live)

    Important:
    This function is for the overnight session only.
    Daytime flattening is intentionally excluded for now because weighted-average
    entry price is not yet wired.
    """
    timestamp = datetime.now(ZoneInfo(config.timezone_name))

    market_results: list[MarketCycleResult] = []

    market_tickers = adapter.list_event_market_tickers(
        series_ticker=config.series_ticker,
        event_ticker=config.event_ticker,
    )

    for market_ticker in market_tickers:
        snapshot = adapter.get_market_snapshot(market_ticker)
        position = adapter.get_market_position(market_ticker)
        resting_orders = adapter.get_resting_orders(market_ticker)

        ref = build_market_reference_snapshot(
            market_ticker=market_ticker,
            yes_levels=snapshot.yes_levels,
            no_levels=snapshot.no_levels,
            minimum_size=config.reference_mm_min_size,
            timestamp=timestamp,
        )

        if not ref.eligible:
            planned_actions = plan_skip_market_cancellations(
                market_ticker=market_ticker,
                existing_orders=resting_orders,
            )
            execution_results = execute_planned_actions(
                adapter=adapter,
                actions=planned_actions,
                dry_run=dry_run,
            )
            market_results.append(
                MarketCycleResult(
                    market_ticker=market_ticker,
                    eligible=False,
                    reason=ref.reason,
                    planned_actions=planned_actions,
                    execution_results=execution_results,
                )
            )
            continue

        target_sizes = overnight_target_sizes(
            side_mode=config.side_mode,
            inventory_mode=config.inventory_mode,
            target_contracts_per_order=config.target_contracts_per_order,
            position=position,
        )

        yes_target_price = overnight_target_price(
            side=BookSide.YES,
            same_side_levels=snapshot.yes_levels,
            opposing_side_levels=snapshot.no_levels,
            follow_min_size=config.follow_min_size,
            reference_cap=ref.yes.price,
            passive_floor_price=config.passive_floor_price,
            tick_size=config.tick_size,
        )

        no_target_price = overnight_target_price(
            side=BookSide.NO,
            same_side_levels=snapshot.no_levels,
            opposing_side_levels=snapshot.yes_levels,
            follow_min_size=config.follow_min_size,
            reference_cap=ref.no.price,
            passive_floor_price=config.passive_floor_price,
            tick_size=config.tick_size,
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

        planned_actions = plan_market_reconciliation(
            market_ticker=market_ticker,
            existing_orders=resting_orders,
            desired_yes=desired_yes,
            desired_no=desired_no,
        )

        execution_results = execute_planned_actions(
            adapter=adapter,
            actions=planned_actions,
            dry_run=dry_run,
        )

        market_results.append(
            MarketCycleResult(
                market_ticker=market_ticker,
                eligible=True,
                reason=None,
                planned_actions=planned_actions,
                execution_results=execution_results,
            )
        )

    return OvernightCycleResult(
        timestamp=timestamp,
        event_ticker=config.event_ticker,
        market_results=market_results,
    )