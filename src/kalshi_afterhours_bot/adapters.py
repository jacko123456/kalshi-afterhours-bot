from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import BookLevel, BookSide, MarketPosition, RestingOrderState


@dataclass(slots=True)
class MarketSnapshot:
    market_ticker: str
    yes_levels: list[BookLevel]
    no_levels: list[BookLevel]


class ExchangeAdapter(ABC):
    """Abstract interface between strategy logic and the exchange/client library.

    Only this interface should know how to fetch books, positions, and orders from
    `pykalshi`. The rest of the code stays pure and testable.
    """

    @abstractmethod
    def list_event_market_tickers(self, series_ticker: str, event_ticker: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_market_snapshot(self, market_ticker: str) -> MarketSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_market_position(self, market_ticker: str) -> MarketPosition:
        raise NotImplementedError

    @abstractmethod
    def get_resting_orders(self, market_ticker: str) -> list[RestingOrderState]:
        raise NotImplementedError

    @abstractmethod
    def place_resting_order(self, market_ticker: str, side: BookSide, price: int, quantity: float) -> str:
        raise NotImplementedError

    @abstractmethod
    def modify_resting_order(self, order_id: str, new_price: int, new_quantity: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError


class DryRunAdapter(ExchangeAdapter):
    """A no-op adapter used while validating logic.

    You can subclass this or replace its data sources with fixtures if you want to
    unit-test cycle decisions without touching Kalshi.
    """

    def __init__(self) -> None:
        self.snapshots: dict[str, MarketSnapshot] = {}
        self.positions: dict[str, MarketPosition] = {}
        self.orders: dict[str, list[RestingOrderState]] = {}

    def list_event_market_tickers(self, series_ticker: str, event_ticker: str) -> list[str]:
        return sorted(self.snapshots.keys())

    def get_market_snapshot(self, market_ticker: str) -> MarketSnapshot:
        return self.snapshots[market_ticker]

    def get_market_position(self, market_ticker: str) -> MarketPosition:
        return self.positions.get(
            market_ticker,
            MarketPosition(market_ticker=market_ticker, side=None, quantity=0.0, avg_entry_price=None),
        )

    def get_resting_orders(self, market_ticker: str) -> list[RestingOrderState]:
        return list(self.orders.get(market_ticker, []))

    def place_resting_order(self, market_ticker: str, side: BookSide, price: int, quantity: float) -> str:
        order_id = f"dryrun-{market_ticker}-{side.value}-{price}-{quantity}"
        return order_id

    def modify_resting_order(self, order_id: str, new_price: int, new_quantity: float) -> None:
        return None

    def cancel_order(self, order_id: str) -> None:
        return None


class PykalshiAdapter(ExchangeAdapter):
    """Skeleton adapter for wiring the strategy to your installed `pykalshi`.

    Important:
    This file is intentionally conservative. The core strategy logic is fully
    implemented elsewhere, but exchange-side method wiring should be verified
    against the exact `pykalshi` version installed in your environment before
    sending live orders.
    """

    def __init__(self, client) -> None:
        self.client = client

    def list_event_market_tickers(self, series_ticker: str, event_ticker: str) -> list[str]:
        markets_df = self.client.get_markets(
            series_ticker=series_ticker,
            event_ticker=event_ticker,
            fetch_all=True,
        ).to_dataframe()
        return markets_df["ticker"].tolist()

    def get_market_snapshot(self, market_ticker: str) -> MarketSnapshot:
        market = self.client.get_market(market_ticker)
        ob_df = market.get_orderbook().to_dataframe()

        yes_levels = []
        no_levels = []

        if "side" in ob_df.columns:
            yes_df = ob_df[ob_df["side"] == "yes"].copy()
            no_df = ob_df[ob_df["side"] == "no"].copy()
            yes_df = yes_df.sort_values("price_dollars", ascending=False)
            no_df = no_df.sort_values("price_dollars", ascending=False)

            for _, row in yes_df.iterrows():
                yes_levels.append(
                    BookLevel(
                        price=int(round(float(row["price_dollars"]) * 100)),
                        quantity=float(row["quantity_fp"]),
                    )
                )
            for _, row in no_df.iterrows():
                no_levels.append(
                    BookLevel(
                        price=int(round(float(row["price_dollars"]) * 100)),
                        quantity=float(row["quantity_fp"]),
                    )
                )
        else:
            raise ValueError(
                "Orderbook DataFrame did not include 'side'. Confirm your installed pykalshi orderbook schema."
            )

        return MarketSnapshot(market_ticker=market_ticker, yes_levels=yes_levels, no_levels=no_levels)

    def get_market_position(self, market_ticker: str) -> MarketPosition:
        # You should verify the exact positions dataframe columns in your environment.
        positions_df = self.client.portfolio.get_positions().to_dataframe()
        rows = positions_df[positions_df["ticker"] == market_ticker]
        if rows.empty:
            return MarketPosition(market_ticker=market_ticker, side=None, quantity=0.0, avg_entry_price=None)

        row = rows.iloc[0]
        side_value = str(row.get("side", "")).lower() if row.get("side") is not None else None
        side = BookSide(side_value) if side_value in {"yes", "no"} else None
        quantity = float(row.get("count_fp", row.get("quantity_fp", row.get("count", 0.0))))
        avg_entry_raw = row.get("avg_price", row.get("avg_price_dollars", None))
        avg_entry_price = None
        if avg_entry_raw is not None:
            avg_entry_price = int(round(float(avg_entry_raw) * 100)) if float(avg_entry_raw) <= 1.0 else int(round(float(avg_entry_raw)))

        return MarketPosition(
            market_ticker=market_ticker,
            side=side,
            quantity=quantity,
            avg_entry_price=avg_entry_price,
        )

    def get_resting_orders(self, market_ticker: str) -> list[RestingOrderState]:
        # You should verify the exact order dataframe columns in your environment.
        orders_df = self.client.portfolio.get_orders().to_dataframe()
        rows = orders_df[orders_df["ticker"] == market_ticker]
        resting_orders: list[RestingOrderState] = []
        for _, row in rows.iterrows():
            status = str(row.get("status", "")).lower()
            if status and status != "resting":
                continue
            side_value = str(row.get("side", "")).lower()
            if side_value not in {"yes", "no"}:
                continue
            order_id = str(row.get("order_id", row.get("id", "")))
            price = row.get("yes_price", row.get("price", row.get("price_dollars", None)))
            if price is None:
                continue
            price_int = int(round(float(price) * 100)) if float(price) <= 1.0 else int(round(float(price)))
            quantity = float(row.get("remaining_count_fp", row.get("count_fp", row.get("remaining_count", 0.0))))
            resting_orders.append(
                RestingOrderState(
                    order_id=order_id,
                    market_ticker=market_ticker,
                    side=BookSide(side_value),
                    price=price_int,
                    quantity=quantity,
                )
            )
        return resting_orders

    def place_resting_order(self, market_ticker: str, side: BookSide, price: int, quantity: float) -> str:
        raise NotImplementedError(
            "Wire this method to client.portfolio.place_order(...) after confirming your installed pykalshi signature."
        )

    def modify_resting_order(self, order_id: str, new_price: int, new_quantity: float) -> None:
        raise NotImplementedError(
            "Wire this method to the pykalshi Order.modify(...) path after confirming quantity amendment semantics."
        )

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError(
            "Wire this method to order.cancel() or the equivalent order lookup path in your installed pykalshi version."
        )
