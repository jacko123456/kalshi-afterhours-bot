from __future__ import annotations

from dataclasses import dataclass

from .adapters import ExchangeAdapter
from .reconcile import PlannedAction


@dataclass
class ExecutionResult:
    """
    Result of attempting one planned action.

    This is useful for:
    - logging
    - debugging
    - later persistence / audit trail
    """
    action: PlannedAction
    success: bool
    message: str


def execute_planned_actions(
    adapter: ExchangeAdapter,
    actions: list[PlannedAction],
    dry_run: bool = True,
) -> list[ExecutionResult]:
    """
    Execute a list of planned actions in order.

    Behavior:
    - dry_run=True:
        Do not touch the exchange. Just report what would happen.
    - dry_run=False:
        Send real cancel / amend / place instructions through the adapter.

    Important:
    - KEEP actions never hit the exchange.
    - CANCEL uses adapter.cancel_order(order_id)
    - AMEND uses adapter.modify_resting_order(order_id, new_price, new_quantity)
    - PLACE uses adapter.place_resting_order(market_ticker, side, price, quantity)
    """
    results: list[ExecutionResult] = []

    for action in actions:
        if action.action_type == "KEEP":
            results.append(
                ExecutionResult(
                    action=action,
                    success=True,
                    message="No action needed; order already matches target.",
                )
            )
            continue

        if dry_run:
            results.append(
                ExecutionResult(
                    action=action,
                    success=True,
                    message=f"DRY RUN: would {action.action_type}",
                )
            )
            continue

        try:
            if action.action_type == "CANCEL":
                if action.order_id is None:
                    raise ValueError("CANCEL action missing order_id")
                adapter.cancel_order(action.order_id)
                results.append(
                    ExecutionResult(
                        action=action,
                        success=True,
                        message="Canceled order successfully.",
                    )
                )

            elif action.action_type == "AMEND":
                if action.order_id is None:
                    raise ValueError("AMEND action missing order_id")
                if action.price is None or action.quantity is None:
                    raise ValueError("AMEND action missing price or quantity")

                adapter.modify_resting_order(
                    order_id=action.order_id,
                    new_price=action.price,
                    new_quantity=action.quantity,
                )
                results.append(
                    ExecutionResult(
                        action=action,
                        success=True,
                        message="Amended order successfully.",
                    )
                )

            elif action.action_type == "PLACE":
                if action.side is None:
                    raise ValueError("PLACE action missing side")
                if action.price is None or action.quantity is None:
                    raise ValueError("PLACE action missing price or quantity")

                new_order_id = adapter.place_resting_order(
                    market_ticker=action.market_ticker,
                    side=action.side,
                    price=action.price,
                    quantity=action.quantity,
                )
                results.append(
                    ExecutionResult(
                        action=action,
                        success=True,
                        message=f"Placed order successfully: {new_order_id}",
                    )
                )

            else:
                raise ValueError(f"Unknown action_type: {action.action_type}")

        except Exception as e:
            results.append(
                ExecutionResult(
                    action=action,
                    success=False,
                    message=f"Execution failed: {e}",
                )
            )

    return results