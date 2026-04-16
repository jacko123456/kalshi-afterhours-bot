from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from pykalshi import Action, OrderStatus, Side

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
    """
    Real exchange adapter backed by your installed `pykalshi`.

    Design goal
    -----------
    This class is the only place in the project that should know raw pykalshi
    details like DataFrame column names, Kalshi order objects, and enum types.

    Everything above this layer should think in strategy-native objects:
    - MarketSnapshot
    - MarketPosition
    - RestingOrderState
    """

    def __init__(self, client) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _price_dollars_to_int(price_dollars) -> int:
        """
        Convert a price expressed in dollars (e.g. 0.45) into integer cents (45).

        We use integer cents internally for deterministic comparisons and to avoid
        float slippage in the strategy logic.
        """
        return int(round(float(price_dollars) * 100))

    @staticmethod
    def _side_to_book_side(side_value: str) -> BookSide:
        """
        Normalize pykalshi/raw side strings into our internal BookSide enum.
        """
        side_value = str(side_value).lower()
        if side_value == "yes":
            return BookSide.YES
        if side_value == "no":
            return BookSide.NO
        raise ValueError(f"Unknown side value: {side_value}")

    def _get_order_object(self, order_id: str):
        """
        Fetch the rich pykalshi Order object by ID.

        We use this for live amend/cancel actions because the runtime object
        exposes methods like:
        - amend(...)
        - cancel()
        - decrease(...)
        """
        return self.client.portfolio.get_order(order_id)

    # -------------------------------------------------------------------------
    # Read methods
    # -------------------------------------------------------------------------

    def list_event_market_tickers(self, series_ticker: str, event_ticker: str) -> list[str]:
        """
        Return all market tickers in the configured event.

        We rely on `fetch_all=True` so we get the full event market universe.
        """
        markets_df = self.client.get_markets(
            series_ticker=series_ticker,
            event_ticker=event_ticker,
            fetch_all=True,
        ).to_dataframe()

        return markets_df["ticker"].tolist()

    def get_market_snapshot(self, market_ticker: str) -> MarketSnapshot:
        """
        Fetch the live orderbook for one market and normalize it into our
        internal MarketSnapshot representation.
        """
        market = self.client.get_market(market_ticker)
        ob_df = market.get_orderbook().to_dataframe()

        yes_levels: list[BookLevel] = []
        no_levels: list[BookLevel] = []

        yes_df = ob_df[ob_df["side"] == "yes"].copy()
        no_df = ob_df[ob_df["side"] == "no"].copy()

        yes_df = yes_df.sort_values("price_dollars", ascending=False)
        no_df = no_df.sort_values("price_dollars", ascending=False)

        for _, row in yes_df.iterrows():
            yes_levels.append(
                BookLevel(
                    price=self._price_dollars_to_int(row["price_dollars"]),
                    quantity=float(row["quantity_fp"]),
                )
            )

        for _, row in no_df.iterrows():
            no_levels.append(
                BookLevel(
                    price=self._price_dollars_to_int(row["price_dollars"]),
                    quantity=float(row["quantity_fp"]),
                )
            )

        return MarketSnapshot(
            market_ticker=market_ticker,
            yes_levels=yes_levels,
            no_levels=no_levels,
        )

    def get_market_position(self, market_ticker: str) -> MarketPosition:
        """
        Return the current net position for one market.

        Your runtime positions DataFrame has:
        - ticker
        - position_fp

        `position_fp` is already netted by Kalshi. So we interpret it as:
        - > 0 => long YES
        - < 0 => long NO
        - = 0 => flat

        We do NOT currently derive avg_entry_price here because the positions
        DataFrame does not include it. We will source weighted-average entry
        separately later for daytime flatten logic.
        """
        positions_df = self.client.portfolio.get_positions().to_dataframe()
        rows = positions_df[positions_df["ticker"] == market_ticker]

        if rows.empty:
            return MarketPosition(
                market_ticker=market_ticker,
                side=None,
                quantity=0.0,
                avg_entry_price=None,
            )

        row = rows.iloc[0]
        position_fp = float(row["position_fp"])

        if position_fp > 0:
            return MarketPosition(
                market_ticker=market_ticker,
                side=BookSide.YES,
                quantity=position_fp,
                avg_entry_price=None,
            )

        if position_fp < 0:
            return MarketPosition(
                market_ticker=market_ticker,
                side=BookSide.NO,
                quantity=abs(position_fp),
                avg_entry_price=None,
            )

        return MarketPosition(
            market_ticker=market_ticker,
            side=None,
            quantity=0.0,
            avg_entry_price=None,
        )

    def get_resting_orders(self, market_ticker: str) -> list[RestingOrderState]:
        """
        Return all currently resting orders for one market.

        Your runtime open-orders DataFrame includes:
        - order_id
        - ticker
        - status
        - side
        - yes_price_dollars
        - no_price_dollars
        - remaining_count_fp

        We normalize each row into our internal RestingOrderState.
        """
        orders_df = self.client.portfolio.get_orders(status=OrderStatus.RESTING).to_dataframe()
        rows = orders_df[orders_df["ticker"] == market_ticker]

        resting_orders: list[RestingOrderState] = []

        for _, row in rows.iterrows():
            side = self._side_to_book_side(row["side"])

            if side == BookSide.YES:
                price = self._price_dollars_to_int(row["yes_price_dollars"])
            else:
                price = self._price_dollars_to_int(row["no_price_dollars"])

            resting_orders.append(
                RestingOrderState(
                    order_id=str(row["order_id"]),
                    market_ticker=market_ticker,
                    side=side,
                    price=price,
                    quantity=float(row["remaining_count_fp"]),
                )
            )

        return resting_orders

    # -------------------------------------------------------------------------
    # Write methods
    # -------------------------------------------------------------------------

    def place_resting_order(self, market_ticker: str, side: BookSide, price: int, quantity: float) -> str:
        """
        Place a new resting BUY order on YES or NO.

        Important:
        - Strategy prices are stored internally as integer cents.
        - pykalshi expects dollar-format price fields like "0.45".
        - We are always placing BUY orders in this strategy.
        """
        market = self.client.get_market(market_ticker)
        price_dollars = f"{price / 100:.2f}"
        count_fp = str(quantity)

        if side == BookSide.YES:
            order = self.client.portfolio.place_order(
                market,
                Action.BUY,
                Side.YES,
                count_fp=count_fp,
                yes_price_dollars=price_dollars,
            )
        else:
            order = self.client.portfolio.place_order(
                market,
                Action.BUY,
                Side.NO,
                count_fp=count_fp,
                no_price_dollars=price_dollars,
            )

        return str(order.order_id)

    def modify_resting_order(self, order_id: str, new_price: int, new_quantity: float) -> None:
        """
        Amend an existing resting order in place.

        Your runtime Order object exposes `.amend(...)`, not `.modify(...)`.
        So we use the real runtime method here.

        Note:
        Depending on Kalshi/pykalshi amendment semantics, certain quantity
        increases may fail. The engine-level policy should remain:
        amend first, cancel/replace fallback if needed.
        """
        order = self._get_order_object(order_id)
        price_dollars = f"{new_price / 100:.2f}"

        if str(order.side).lower() == "yes":
            order.amend(
                yes_price_dollars=price_dollars,
                count_fp=str(new_quantity),
            )
        else:
            order.amend(
                no_price_dollars=price_dollars,
                count_fp=str(new_quantity),
            )

    def cancel_order(self, order_id: str) -> None:
        """
        Cancel an existing resting order by ID.
        """
        order = self._get_order_object(order_id)
        order.cancel()
