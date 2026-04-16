# Kalshi After-Hours MM Shadow Bot

A GitHub-ready starter repository for the after-hours Kalshi strategy we specified together.

This repository is intentionally structured in two layers:

1. **Pure strategy logic**: pricing, inventory normalization, target-size calculation, and market eligibility rules.
2. **Exchange adapter layer**: the small set of methods that talk to `pykalshi`.

That split is deliberate. It makes the system easier to test, easier to debug, and much safer to extend.

---

## What this bot is designed to do

For a **single Kalshi event ticker**:

- At **3:55 PM ET**, capture a one-time market-maker reference snapshot for every market in the event.
- A market is **eligible** only if both a qualifying YES reference quote and a qualifying NO reference quote exist.
- Place initial resting orders at the exact marked reference prices.
- From **4:05 PM ET to 9:25 AM ET**, reprice periodically:
  - ignore displayed levels below a configurable threshold,
  - try to quote **one tick better** than the filtered best bid,
  - never quote above the frozen 3:55 PM reference quote,
  - never place an order that would immediately take liquidity.
- Always replenish filled quantity back to the configured target resting size.
- Optionally enlarge the **opposing side** by current inventory.
- After **9:25 AM ET**, cancel the normal overnight quote set and switch to **inventory-flattening only**.

---

## Repository layout

```text
kalshi_afterhours_bot/
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   └── strategy.example.yaml
├── data/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
└── src/
    └── kalshi_afterhours_bot/
        ├── __init__.py
        ├── config.py
        ├── logging_utils.py
        ├── models.py
        ├── reference.py
        ├── market_data.py
        ├── inventory.py
        ├── state_store.py
        ├── scheduler.py
        ├── adapters.py
        ├── engine.py
        └── main.py
```

---

## Why each file exists

### `config/strategy.example.yaml`
Human-editable strategy configuration.

Put things here that you may want to change without touching code:
- event ticker,
- side mode,
- target quantity,
- size thresholds,
- schedule frequency,
- persistence paths,
- dry-run toggle.

### `src/kalshi_afterhours_bot/models.py`
Contains the typed models and enums.

This is where the core language of the bot lives:
- side modes,
- inventory modes,
- reference quotes,
- positions,
- target orders,
- cycle results.

If the strategy changes conceptually, this file usually changes first.

### `src/kalshi_afterhours_bot/reference.py`
Contains the 3:55 PM snapshot logic.

This module answers:
- which markets are eligible,
- what the frozen YES/NO reference caps are,
- which markets must be skipped for the session.

### `src/kalshi_afterhours_bot/market_data.py`
Contains book parsing and pricing rules.

This module answers:
- what is the filtered best bid,
- what quote would be one tick better,
- whether a proposed quote would take liquidity,
- what the fallback price should be if a side is effectively empty.

### `src/kalshi_afterhours_bot/inventory.py`
Contains target-size calculations.

This is where we compute:
- normalized inventory,
- overnight target order sizes,
- daytime flattening target sizes.

### `src/kalshi_afterhours_bot/adapters.py`
Contains the exchange abstraction.

This is the only module that should know about `pykalshi` specifics.
The rest of the bot should not care whether data comes from `pykalshi`, a simulator, or fixtures.

This file currently includes:
- an abstract exchange interface,
- a dry-run adapter,
- a `PykalshiAdapter` skeleton with the exact methods you will wire to your environment.

### `src/kalshi_afterhours_bot/state_store.py`
Persistence layer.

Stores:
- the daily 3:55 snapshot in JSON,
- cycle summaries in SQLite,
- exceptions and operational events in SQLite.

### `src/kalshi_afterhours_bot/scheduler.py`
Wall-clock scheduling helpers.

This is where the bot decides:
- whether it is before capture,
- in overnight session,
- in daytime flattening mode,
- or waiting for the next scheduled run.

### `src/kalshi_afterhours_bot/engine.py`
The orchestration layer.

This is the brain of the bot. It ties together:
- config,
- exchange adapter,
- reference snapshot,
- market data,
- inventory,
- persistence,
- logging.

### `src/kalshi_afterhours_bot/main.py`
Entry point.

This is the file you run from the command line.

---

## How I want you to implement this locally

### Step 1: create a GitHub repo
Create a new private repository, then copy this whole folder into it.

Suggested repo name:

```text
kalshi-afterhours-shadow-bot
```

### Step 2: create a virtual environment
From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

If you use `uv`, that is also fine.

### Step 3: add your credentials
Copy `.env.example` to `.env` and fill in your Kalshi credentials.

### Step 4: copy the sample strategy config

```bash
cp config/strategy.example.yaml config/strategy.yaml
```

Then edit `config/strategy.yaml`.

### Step 5: start in dry-run mode
Keep `dry_run: true` until the bot’s decisions look exactly right.

### Step 6: wire `PykalshiAdapter`
Once dry-run logic looks correct, fill in the adapter methods using your installed `pykalshi` version.

This is where we should be careful, because exchange method signatures can evolve.

---

## First development milestone

Before you let this trade live, I want you to confirm that the bot can do all of the following correctly in dry-run mode:

1. Load the event market universe.
2. Capture the 3:55 PM reference snapshot.
3. Mark eligible vs skipped markets correctly.
4. Compute intended target prices for each market/side.
5. Compute intended target sizes from current positions.
6. Show which orders it would place, modify, cancel, or leave unchanged.
7. Persist a snapshot and cycle summary to disk.

Only after that should we wire live order methods.

---

## Why the architecture is set up this way

This is a trading system, so the main engineering goal is **deterministic behavior**.

That means:
- price logic should be pure and testable,
- exchange IO should be isolated,
- state should be persisted,
- every cycle should be auditable,
- nothing important should exist only in memory.

That is why this repository is not just one script.

---

## Notes on `pykalshi`

The current `pykalshi` repo exposes a `KalshiClient`, market and portfolio methods, DataFrame conversions, domain objects like `Order` and `Market`, plus websocket support and an `OrderbookManager`. The README also shows order placement via `client.portfolio.place_order(...)`, order modification via `order.modify(...)`, and position/fill/order retrieval via portfolio methods. That is why the adapter layer is shaped the way it is. citeturn799200view0turn940022search0

Kalshi’s orderbook docs also matter for this strategy. The book returns YES bids and NO bids only, because in a binary market a YES bid at price `x` is equivalent to a NO ask at `100 - x`. Their newer fixed-point documentation also notes that orderbook price and size values can be represented as strings to support subpenny pricing and fractional quantities, which is why this code keeps tick logic configurable and avoids baking in assumptions beyond the current default floor. citeturn133758search0turn133758search1

---

## Next step

The code scaffold in `src/kalshi_afterhours_bot/` is ready to read and extend. Start by opening `models.py`, `config.py`, and `engine.py` in that order.
