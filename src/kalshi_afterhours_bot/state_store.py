from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import MarketReferenceSnapshot, ReferenceQuote


class StateStore:
    """
    Persistence layer for the bot.

    Current responsibilities:
    - save frozen reference snapshots to JSON
    - load frozen reference snapshots from JSON
    - optionally store simple cycle / exception logs in SQLite

    Why this design:
    - the 3:55 PM reference snapshot must survive process restarts
    - overnight runs must load the saved snapshot instead of rebuilding from
      the current live book
    - JSON is easy to inspect manually
    - SQLite is useful for lightweight audit logging
    """

    def __init__(self, sqlite_path: str, snapshot_json_path: str) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.snapshot_json_path = Path(snapshot_json_path)

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_json_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.sqlite_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_logs (
                    ts TEXT NOT NULL,
                    event_ticker TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    total_markets INTEGER NOT NULL,
                    total_actions INTEGER NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exceptions (
                    ts TEXT NOT NULL,
                    context TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Frozen reference snapshot persistence
    # -------------------------------------------------------------------------

    def save_reference_snapshot(self, snapshots: list[MarketReferenceSnapshot]) -> None:
        """
        Save the full event reference snapshot to JSON.

        The saved structure is a list of per-market snapshots.
        Timestamps are converted to ISO strings for portability.
        """
        payload = []

        for snapshot in snapshots:
            row = asdict(snapshot)
            row["timestamp"] = snapshot.timestamp.isoformat()
            payload.append(row)

        with open(self.snapshot_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def load_reference_snapshot(self) -> dict[str, MarketReferenceSnapshot]:
        """
        Load the frozen event reference snapshot from JSON.

        Returns:
            dict keyed by market_ticker -> MarketReferenceSnapshot

        Why dict:
            the engine needs fast lookup by market ticker during overnight cycles.
        """
        if not self.snapshot_json_path.exists():
            raise FileNotFoundError(
                f"Reference snapshot file not found: {self.snapshot_json_path}"
            )

        with open(self.snapshot_json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        snapshots: dict[str, MarketReferenceSnapshot] = {}

        for row in payload:
            snapshot = MarketReferenceSnapshot(
                market_ticker=row["market_ticker"],
                yes=ReferenceQuote(
                    price=row["yes"]["price"],
                    quantity=row["yes"]["quantity"],
                ),
                no=ReferenceQuote(
                    price=row["no"]["price"],
                    quantity=row["no"]["quantity"],
                ),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                eligible=row["eligible"],
                reason=row["reason"],
            )
            snapshots[snapshot.market_ticker] = snapshot

        return snapshots

    # -------------------------------------------------------------------------
    # Lightweight cycle / exception logging
    # -------------------------------------------------------------------------

    def save_cycle_log(
        self,
        ts: datetime,
        event_ticker: str,
        dry_run: bool,
        total_markets: int,
        total_actions: int,
        notes: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cycle_logs (ts, event_ticker, dry_run, total_markets, total_actions, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts.isoformat(),
                    event_ticker,
                    1 if dry_run else 0,
                    total_markets,
                    total_actions,
                    notes,
                ),
            )
            conn.commit()

    def save_exception(self, context: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO exceptions (ts, context, message) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), context, message),
            )
            conn.commit()