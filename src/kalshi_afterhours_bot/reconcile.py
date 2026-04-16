from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import BookSide, RestingOrderState


@dataclass
class DesiredOrder:
    """
    One desired resting order for one market side.

    If quantity <= 0, the planner will interpret that as:
    'this side should have no resting order.'
    """
    market_ticker: str
    side: BookSide
    price: int
    quantity: float


@dataclass
class PlannedAction:
    """
    One reconciliation action.

    action_type values:
    - KEEP
    - PLACE
    - AMEND
    - CANCEL
    """
    action_type: str
    market_ticker: str
    side: Optional[BookSide]
    order_id: Optional[str]
    price: Optional[int]
    quantity: Optional[float]
    reason: str


def _same_order(order: RestingOrderState, desired: DesiredOrder) -> bool:
    """Return True if the resting order already matches the desired state."""
    return (
        order.side == desired.side
        and order.price == desired.price
        and abs(order.quantity - desired.quantity) < 1e-9
    )


def _pick_canonical_order(
    orders: list[RestingOrderState],
    desired: DesiredOrder,
) -> Optional[RestingOrderState]:
    """
    Pick the one resting order we keep/amend if multiple exist on a side.

    Better policy:
    1. Prefer the order already closest to the desired price.
    2. Break ties by smallest quantity difference from target.
    3. Break remaining ties by largest quantity.

    Why:
    This minimizes unnecessary churn and tends to preserve the order that already
    looks most like the target state.
    """
    if not orders:
        return None

    def score(order: RestingOrderState):
        return (
            abs(order.price - desired.price),
            abs(order.quantity - desired.quantity),
            -order.quantity,
        )

    return min(orders, key=score)


def plan_side_reconciliation(
    market_ticker: str,
    side: BookSide,
    existing_orders: list[RestingOrderState],
    desired_order: Optional[DesiredOrder],
) -> list[PlannedAction]:
    """
    Reconcile one market-side.

    Rules:
    - You only ever want one resting order per side.
    - If desired_order is None or quantity <= 0, cancel all existing orders on that side.
    - If there are no existing orders and a desired order exists, place one.
    - If exactly one existing order matches desired, keep it.
    - If exactly one exists but differs, amend it.
    - If multiple exist, choose one canonical order to keep/amend and cancel the rest.
    """
    actions: list[PlannedAction] = []

    side_orders = [o for o in existing_orders if o.side == side]

    if desired_order is None or desired_order.quantity <= 0:
        for order in side_orders:
            actions.append(
                PlannedAction(
                    action_type="CANCEL",
                    market_ticker=market_ticker,
                    side=side,
                    order_id=order.order_id,
                    price=order.price,
                    quantity=order.quantity,
                    reason="no_desired_order_for_side",
                )
            )
        return actions

    if not side_orders:
        actions.append(
            PlannedAction(
                action_type="PLACE",
                market_ticker=market_ticker,
                side=side,
                order_id=None,
                price=desired_order.price,
                quantity=desired_order.quantity,
                reason="missing_resting_order",
            )
        )
        return actions

    canonical = _pick_canonical_order(side_orders, desired_order)
    extras = [o for o in side_orders if o.order_id != canonical.order_id]

    if _same_order(canonical, desired_order):
        actions.append(
            PlannedAction(
                action_type="KEEP",
                market_ticker=market_ticker,
                side=side,
                order_id=canonical.order_id,
                price=canonical.price,
                quantity=canonical.quantity,
                reason="already_matches_target",
            )
        )
    else:
        actions.append(
            PlannedAction(
                action_type="AMEND",
                market_ticker=market_ticker,
                side=side,
                order_id=canonical.order_id,
                price=desired_order.price,
                quantity=desired_order.quantity,
                reason="resting_order_differs_from_target",
            )
        )

    for order in extras:
        actions.append(
            PlannedAction(
                action_type="CANCEL",
                market_ticker=market_ticker,
                side=side,
                order_id=order.order_id,
                price=order.price,
                quantity=order.quantity,
                reason="duplicate_order_same_side",
            )
        )

    return actions


def plan_market_reconciliation(
    market_ticker: str,
    existing_orders: list[RestingOrderState],
    desired_yes: Optional[DesiredOrder],
    desired_no: Optional[DesiredOrder],
) -> list[PlannedAction]:
    """
    Reconcile both YES and NO sides for one market.
    """
    actions: list[PlannedAction] = []
    actions.extend(
        plan_side_reconciliation(
            market_ticker=market_ticker,
            side=BookSide.YES,
            existing_orders=existing_orders,
            desired_order=desired_yes,
        )
    )
    actions.extend(
        plan_side_reconciliation(
            market_ticker=market_ticker,
            side=BookSide.NO,
            existing_orders=existing_orders,
            desired_order=desired_no,
        )
    )
    return actions


def plan_skip_market_cancellations(
    market_ticker: str,
    existing_orders: list[RestingOrderState],
) -> list[PlannedAction]:
    """
    If a market is ineligible for the session, all resting orders in that market
    should be canceled.
    """
    actions: list[PlannedAction] = []
    for order in existing_orders:
        actions.append(
            PlannedAction(
                action_type="CANCEL",
                market_ticker=market_ticker,
                side=order.side,
                order_id=order.order_id,
                price=order.price,
                quantity=order.quantity,
                reason="market_ineligible_for_session",
            )
        )
    return actions