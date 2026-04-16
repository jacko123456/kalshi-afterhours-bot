from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .adapters import ExchangeAdapter
from .executor import ExecutionResult, execute_planned_actions
from .inventory import overnight_target_sizes
from .market_data import overnight_target_price
from .models import BookSide, InventoryMode, MarketReferenceSnapshot, SideMode
from .reconcile import (
    DesiredOrder,
    PlannedAction,
    plan_market_reconciliation,
    plan_skip_market_cancellations,
)
from .reference import build_market_reference_snapshot
from .state_store import StateStore


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
    market_whitelist: list[str] | None = None


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


def capture_reference_snapshot_for_event(
    adapter: ExchangeAdapter,
    config: OvernightCycleConfig,
    state_store: StateStore,
) -> list[MarketReferenceSnapshot]:
    """
    Capture the frozen 3:55 PM reference snapshot for the event and persist it.

    This is the snapshot your overnight strategy should use later after market
    makers pull their quotes.

    Important:
    - This function looks at the live book now.
    - It should be run at the intended capture time (around 3:55 PM ET).
    - It saves the result to JSON through StateStore.
    """
    timestamp = datetime.now(ZoneInfo(config.timezone_name))

    market_tickers = adapter.list_event_market_tickers(
        series_ticker=config.series_ticker,
        event_ticker=config.event_ticker,
    )

    if config.market_whitelist:
        allowed = set(config.market_whitelist)
        market_tickers = [ticker for ticker in market_tickers if ticker in allowed]

    snapshots: list[MarketReferenceSnapshot] = []

    for market_ticker in market_tickers:
        snapshot = adapter.get_market_snapshot(market_ticker)

        ref = build_market_reference_snapshot(
            market_ticker=market_ticker,
            yes_levels=snapshot.yes_levels,
            no_levels=snapshot.no_levels,
            minimum_size=config.reference_mm_min_size,
            timestamp=timestamp,
        )
        snapshots.append(ref)

    state_store.save_reference_snapshot(snapshots)
    return snapshots


def run_single_overnight_cycle_from_saved_snapshot(
    adapter: ExchangeAdapter,
    config: OvernightCycleConfig,
    state_store: StateStore,
    dry_run: bool = True,
) -> OvernightCycleResult:
    """
    Run one full overnight cycle using the previously saved frozen reference snapshot.

    This is the correct overnight behavior:
    - DO NOT rebuild reference eligibility/caps from the current book
    - load the saved 3:55 PM snapshot from disk
    - use that frozen snapshot for:
        * market eligibility
        * reference caps on YES and NO

    This is the function you should use after 4:05 PM and later.
    """
    timestamp = datetime.now(ZoneInfo(config.timezone_name))
    market_results: list[MarketCycleResult] = []

    reference_by_ticker = state_store.load_reference_snapshot()

    market_tickers = adapter.list_event_market_tickers(
        series_ticker=config.series_ticker,
        event_ticker=config.event_ticker,
    )

    if config.market_whitelist:
        allowed = set(config.market_whitelist)
        market_tickers = [ticker for ticker in market_tickers if ticker in allowed]

    for market_ticker in market_tickers:
        snapshot = adapter.get_market_snapshot(market_ticker)
        position = adapter.get_market_position(market_ticker)
        resting_orders = adapter.get_resting_orders(market_ticker)

        ref = reference_by_ticker.get(market_ticker)

        # If the market was not present in the saved snapshot, treat it as ineligible.
        if ref is None:
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
                    reason="missing_from_saved_reference_snapshot",
                    planned_actions=planned_actions,
                    execution_results=execution_results,
                )
            )
            continue

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

    result = OvernightCycleResult(
        timestamp=timestamp,
        event_ticker=config.event_ticker,
        market_results=market_results,
    )

    state_store.save_cycle_log(
        ts=result.timestamp,
        event_ticker=result.event_ticker,
        dry_run=dry_run,
        total_markets=len(result.market_results),
        total_actions=result.total_actions,
        notes="overnight_cycle_from_saved_snapshot",
    )

    return result


def run_single_overnight_cycle(
    adapter: ExchangeAdapter,
    config: OvernightCycleConfig,
    dry_run: bool = True,
) -> OvernightCycleResult:
    """
    Legacy/fallback version that rebuilds reference state from the current live book.

    This is NOT the correct production path for your strategy after 4:05 PM, because
    your strategy depends on the frozen 3:55 PM reference snapshot.

    Keep this only as a fallback utility for ad hoc testing.
    """
    timestamp = datetime.now(ZoneInfo(config.timezone_name))

    market_results: list[MarketCycleResult] = []

    market_tickers = adapter.list_event_market_tickers(
        series_ticker=config.series_ticker,
        event_ticker=config.event_ticker,
    )
    if config.market_whitelist:
        allowed = set(config.market_whitelist)
        market_tickers = [ticker for ticker in market_tickers if ticker in allowed]

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