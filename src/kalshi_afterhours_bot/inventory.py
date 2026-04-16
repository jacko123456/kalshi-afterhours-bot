from __future__ import annotations

from .models import BookSide, InventoryMode, MarketPosition, SideMode


def overnight_target_sizes(
    side_mode: SideMode,
    inventory_mode: InventoryMode,
    target_contracts_per_order: float,
    position: MarketPosition,
) -> dict[BookSide, float]:
    """Compute desired overnight resting quantities for each side.

    Core behavior agreed on:
    - Quoted sides are always replenished back to target size.
    - Opposing side inventory adjustment depends on inventory mode.
    - In one-sided mode, the configured side stays at target and the opposing side
      can be used only as an inventory-offset order.
    """
    net_yes = position.normalized_yes_inventory()
    long_yes = max(net_yes, 0.0)
    long_no = max(-net_yes, 0.0)

    targets: dict[BookSide, float] = {BookSide.YES: 0.0, BookSide.NO: 0.0}

    if side_mode == SideMode.BOTH:
        targets[BookSide.YES] = target_contracts_per_order
        targets[BookSide.NO] = target_contracts_per_order

        if inventory_mode == InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY:
            if net_yes > 0:
                targets[BookSide.NO] += long_yes
            elif net_yes < 0:
                targets[BookSide.YES] += long_no

        return targets

    if side_mode == SideMode.YES_ONLY:
        targets[BookSide.YES] = target_contracts_per_order
        if inventory_mode == InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY:
            targets[BookSide.NO] = long_yes
        return targets

    if side_mode == SideMode.NO_ONLY:
        targets[BookSide.NO] = target_contracts_per_order
        if inventory_mode == InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY:
            targets[BookSide.YES] = long_no
        return targets

    return targets


def flatten_target_sizes(position: MarketPosition) -> dict[BookSide, float]:
    """Compute daytime flatten-only order sizes.

    Daytime mode is only for reducing inventory. If the position is long YES,
    quote NO for exactly that inventory size. If long NO, quote YES.
    """
    targets: dict[BookSide, float] = {BookSide.YES: 0.0, BookSide.NO: 0.0}
    if position.side is None or position.quantity <= 0:
        return targets

    if position.side == BookSide.YES:
        targets[BookSide.NO] = position.quantity
    elif position.side == BookSide.NO:
        targets[BookSide.YES] = position.quantity
    return targets
