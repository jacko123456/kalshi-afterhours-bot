from __future__ import annotations

from datetime import datetime
from logging import Logger

from .adapters import ExchangeAdapter
from .config import StrategyConfig
from .inventory import flatten_target_sizes, overnight_target_sizes
from .market_data import best_filtered_bid, flatten_target_price, overnight_target_price
from .models import (
    BookSide,
    CycleSummary,
    MarketReferenceSnapshot,
    OrderDecision,
    RestingOrderState,
    SessionPhase,
    TargetOrder,
)
from .reference import build_market_reference_snapshot
from .state_store import StateStore


class StrategyEngine:
    """Main orchestration layer for the strategy.

    Read this file after reading:
    1. models.py
    2. reference.py
    3. market_data.py
    4. inventory.py

    Why this file exists:
    It combines the pure strategy modules with the exchange adapter and persistence.
    """

    def __init__(
        self,
        config: StrategyConfig,
        exchange: ExchangeAdapter,
        state_store: StateStore,
        logger: Logger,
    ) -> None:
        self.config = config
        self.exchange = exchange
        self.state_store = state_store
        self.logger = logger
        self.reference_snapshots: dict[str, MarketReferenceSnapshot] = {}

    def capture_reference_snapshot(self, now: datetime) -> list[MarketReferenceSnapshot]:
        """Capture the 3:55 PM frozen MM reference snapshot for all event markets."""
        tickers = self.exchange.list_event_market_tickers(
            series_ticker=self.config.market.series_ticker,
            event_ticker=self.config.market.event_ticker,
        )
        snapshots: list[MarketReferenceSnapshot] = []

        self.logger.info("Capturing reference snapshot for %d markets", len(tickers))
        for ticker in tickers:
            market = self.exchange.get_market_snapshot(ticker)
            snapshot = build_market_reference_snapshot(
                market_ticker=ticker,
                yes_levels=market.yes_levels,
                no_levels=market.no_levels,
                minimum_size=self.config.thresholds.reference_mm_min_size,
                timestamp=now,
            )
            snapshots.append(snapshot)
            self.reference_snapshots[ticker] = snapshot
            self.logger.info(
                "Reference | %s | eligible=%s | yes=%s | no=%s",
                ticker,
                snapshot.eligible,
                snapshot.yes.price,
                snapshot.no.price,
            )

        self.state_store.save_reference_snapshot(snapshots)
        return snapshots

    def build_overnight_targets(self) -> list[TargetOrder]:
        """Compute desired overnight orders for all eligible markets."""
        targets: list[TargetOrder] = []

        for ticker, snapshot in self.reference_snapshots.items():
            if not snapshot.eligible:
                continue

            market = self.exchange.get_market_snapshot(ticker)
            position = self.exchange.get_market_position(ticker)
            sizes = overnight_target_sizes(
                side_mode=self.config.quoting.side_mode,
                inventory_mode=self.config.quoting.inventory_mode,
                target_contracts_per_order=self.config.quoting.target_contracts_per_order,
                position=position,
            )

            if sizes[BookSide.YES] > 0:
                price = overnight_target_price(
                    side=BookSide.YES,
                    same_side_levels=market.yes_levels,
                    opposing_side_levels=market.no_levels,
                    follow_min_size=self.config.thresholds.quote_follow_min_size,
                    reference_cap=snapshot.yes.price,
                    passive_floor_price=self.config.quoting.passive_floor_price,
                    tick_size=self.config.quoting.default_tick_size,
                )
                targets.append(
                    TargetOrder(
                        market_ticker=ticker,
                        side=BookSide.YES,
                        desired_price=price,
                        desired_quantity=sizes[BookSide.YES],
                        reason="overnight_quote_yes",
                    )
                )

            if sizes[BookSide.NO] > 0:
                price = overnight_target_price(
                    side=BookSide.NO,
                    same_side_levels=market.no_levels,
                    opposing_side_levels=market.yes_levels,
                    follow_min_size=self.config.thresholds.quote_follow_min_size,
                    reference_cap=snapshot.no.price,
                    passive_floor_price=self.config.quoting.passive_floor_price,
                    tick_size=self.config.quoting.default_tick_size,
                )
                targets.append(
                    TargetOrder(
                        market_ticker=ticker,
                        side=BookSide.NO,
                        desired_price=price,
                        desired_quantity=sizes[BookSide.NO],
                        reason="overnight_quote_no",
                    )
                )

        return targets

    def build_daytime_flatten_targets(self) -> list[TargetOrder]:
        """Compute flatten-only daytime orders from live inventory."""
        targets: list[TargetOrder] = []

        for ticker, snapshot in self.reference_snapshots.items():
            if not snapshot.eligible:
                continue
            market = self.exchange.get_market_snapshot(ticker)
            position = self.exchange.get_market_position(ticker)
            sizes = flatten_target_sizes(position)

            if sizes[BookSide.YES] > 0 and position.avg_entry_price is not None:
                opposite_best = best_filtered_bid(market.no_levels, self.config.thresholds.flatten_follow_min_size)
                price = flatten_target_price(
                    opposing_best_bid=opposite_best,
                    avg_entry_price=position.avg_entry_price,
                    passive_floor_price=self.config.quoting.passive_floor_price,
                    reference_cap=snapshot.yes.price,
                )
                if price is not None:
                    targets.append(
                        TargetOrder(
                            market_ticker=ticker,
                            side=BookSide.YES,
                            desired_price=price,
                            desired_quantity=sizes[BookSide.YES],
                            reason="daytime_flatten_yes",
                        )
                    )

            if sizes[BookSide.NO] > 0 and position.avg_entry_price is not None:
                opposite_best = best_filtered_bid(market.yes_levels, self.config.thresholds.flatten_follow_min_size)
                price = flatten_target_price(
                    opposing_best_bid=opposite_best,
                    avg_entry_price=position.avg_entry_price,
                    passive_floor_price=self.config.quoting.passive_floor_price,
                    reference_cap=snapshot.no.price,
                )
                if price is not None:
                    targets.append(
                        TargetOrder(
                            market_ticker=ticker,
                            side=BookSide.NO,
                            desired_price=price,
                            desired_quantity=sizes[BookSide.NO],
                            reason="daytime_flatten_no",
                        )
                    )

        return targets

    def reconcile_market_side(
        self,
        market_ticker: str,
        side: BookSide,
        desired: TargetOrder | None,
        existing: list[RestingOrderState],
    ) -> list[OrderDecision]:
        """Turn desired state into concrete order actions.

        Current policy:
        - exactly one working order per side,
        - if there are multiple existing orders, cancel extras,
        - modify in place when possible,
        - otherwise cancel/replace.
        """
        same_side_existing = [order for order in existing if order.side == side]
        decisions: list[OrderDecision] = []

        if desired is None or desired.desired_quantity <= 0:
            for order in same_side_existing:
                decisions.append(
                    OrderDecision(
                        market_ticker=market_ticker,
                        side=side,
                        action="cancel",
                        details=f"No desired order for side; cancel existing order {order.order_id}",
                    )
                )
            return decisions

        if not same_side_existing:
            decisions.append(
                OrderDecision(
                    market_ticker=market_ticker,
                    side=side,
                    action="place",
                    details=f"Place new order at {desired.desired_price} for {desired.desired_quantity}",
                )
            )
            return decisions

        primary = same_side_existing[0]
        extras = same_side_existing[1:]
        for extra in extras:
            decisions.append(
                OrderDecision(
                    market_ticker=market_ticker,
                    side=side,
                    action="cancel",
                    details=f"Cancel extra same-side order {extra.order_id}",
                )
            )

        if primary.price == desired.desired_price and abs(primary.quantity - desired.desired_quantity) < 1e-9:
            decisions.append(
                OrderDecision(
                    market_ticker=market_ticker,
                    side=side,
                    action="keep",
                    details="Existing order already matches desired state",
                )
            )
            return decisions

        decisions.append(
            OrderDecision(
                market_ticker=market_ticker,
                side=side,
                action="modify",
                details=(
                    f"Modify {primary.order_id} from price={primary.price}, qty={primary.quantity} "
                    f"to price={desired.desired_price}, qty={desired.desired_quantity}"
                ),
            )
        )
        return decisions

    def build_cycle_summary(self, now: datetime, phase: SessionPhase) -> CycleSummary:
        """Build a dry-run cycle summary for the current phase."""
        decisions: list[OrderDecision] = []

        if phase == SessionPhase.OVERNIGHT_REPRICE:
            desired_targets = self.build_overnight_targets()
        elif phase == SessionPhase.DAYTIME_FLATTEN:
            desired_targets = self.build_daytime_flatten_targets()
        else:
            desired_targets = []

        desired_lookup = {(t.market_ticker, t.side): t for t in desired_targets}

        for ticker in self.reference_snapshots.keys():
            existing = self.exchange.get_resting_orders(ticker)
            snapshot = self.reference_snapshots[ticker]

            if not snapshot.eligible:
                for order in existing:
                    decisions.append(
                        OrderDecision(
                            market_ticker=ticker,
                            side=order.side,
                            action="cancel",
                            details=f"Market skipped for session; cancel {order.order_id}",
                        )
                    )
                continue

            for side in (BookSide.YES, BookSide.NO):
                desired = desired_lookup.get((ticker, side))
                decisions.extend(self.reconcile_market_side(ticker, side, desired, existing))

        return CycleSummary(timestamp=now, phase=phase, decisions=decisions, notes=[])
