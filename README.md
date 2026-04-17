# Kalshi After-Hours Market Making Bot

## Overview

This bot runs an after-hours market-making strategy on Kalshi binary markets.

Core idea:
- Capture large market-maker quotes at ~3:55 PM ET
- Freeze them as a reference snapshot
- Quote passively after hours based on that snapshot
- Maintain inventory-balanced positions

---

## Architecture

Modules:

adapters.py
- Connects to Kalshi
- Fetches orderbooks, positions, orders
- Sends place/amend/cancel requests

reference.py
- Extracts large quotes from book
- Determines if a market is eligible

market_data.py
- Computes target prices
- Handles tick improvement, caps, non-crossing

inventory.py
- Computes target sizes
- Applies inventory offset logic

reconcile.py
- Compares desired vs existing orders
- Outputs actions: KEEP / AMEND / CANCEL / PLACE

executor.py
- Executes actions (dry-run or live)

engine.py
- Runs full cycle across all markets

state_store.py
- Saves snapshots and logs

main.py
- CLI entry point

---

## Setup

Clone repo and install:

git clone https://github.com/jacko123456/kalshi-afterhours-bot.git
cd kalshi-afterhours-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Create .env file:

KALSHI_EMAIL=your_email
KALSHI_PASSWORD=your_password

---

## Running

Activate environment:

source .venv/bin/activate

---

Capture reference (around 3:55 PM ET):

PYTHONPATH=src python -m kalshi_afterhours_bot.main capture-reference --config config/strategy.yaml

This saves:
data/reference_snapshot.json

---

Run overnight cycle (after ~4:05 PM ET):

PYTHONPATH=src python -m kalshi_afterhours_bot.main run-overnight --config config/strategy.yaml

---

Enable live trading (ONLY when ready):

In config:

exchange:
  dry_run: false
  allow_live_orders: true

Then run:

PYTHONPATH=src python -m kalshi_afterhours_bot.main run-overnight --config config/strategy.yaml --live

---

## Strategy Logic

Reference:
- First level with size >= threshold
- Must exist on both YES and NO sides

Pricing:
- Follow best bid above min size
- Improve by 1 tick
- Cap at reference price
- Never cross (price + opposite >= 100)

Inventory:
- Base size per side
- Offset opposite side by current position

Reconciliation:
- One order per side
- Keep / amend / cancel / place as needed

---

## Config

config/strategy.yaml controls everything.

Key fields:

market:
  series_ticker
  event_ticker
  market_whitelist

quoting:
  side_mode
  inventory_mode
  target_contracts_per_order

thresholds:
  reference_mm_min_size
  quote_follow_min_size

exchange:
  dry_run
  allow_live_orders

---

## Safety

- Dry-run default
- Explicit live flag required
- Whitelist limits exposure
- Non-crossing logic prevents taking liquidity

---

## Testing

Use scratch scripts:

python scratch/test_adapter_live.py
python scratch/test_strategy_logic.py
python scratch/test_reconciliation_planner.py
python scratch/test_executor_dry_run.py
python scratch/test_engine_overnight_cycle.py

---

## Daily Workflow

1. Before 3:55 PM
   - verify config

2. At ~3:55 PM
   - capture reference

3. After ~4:05 PM
   - run overnight cycle

---

## Status

Working:
- Full strategy pipeline
- Dry-run execution
- Order reconciliation

Not yet:
- automated scheduler loop
- daytime flattening
- production deployment

---

## Disclaimer

Use dry-run extensively before trading live.
This system can lose money.