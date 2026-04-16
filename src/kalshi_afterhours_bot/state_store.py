from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import CycleSummary, MarketReferenceSnapshot, OrderDecision


class StateStore:
    """Persistence layer for snapshots, cycle summaries, and exceptions.

    Why SQLite:
    - very easy to inspect,
    - no external service required,
    - safe enough for a single-process bot.
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
                CREATE TABLE IF NOT EXISTS cycle_summaries (
                    ts TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    notes_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS order_decisions (
                    ts TEXT NOT NULL,
                    market_ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL
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

    def save_reference_snapshot(self, snapshots: Iterable[MarketReferenceSnapshot]) -> None:
        payload = []
        for snapshot in snapshots:
            row = asdict(snapshot)
            row["timestamp"] = snapshot.timestamp.isoformat()
            payload.append(row)
        with open(self.snapshot_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def save_cycle_summary(self, summary: CycleSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cycle_summaries (ts, phase, notes_json) VALUES (?, ?, ?)",
                (
                    summary.timestamp.isoformat(),
                    summary.phase.value,
                    json.dumps(summary.notes),
                ),
            )
            for decision in summary.decisions:
                self._insert_decision(conn, summary.timestamp, decision)
            conn.commit()

    def _insert_decision(self, conn: sqlite3.Connection, ts: datetime, decision: OrderDecision) -> None:
        conn.execute(
            "INSERT INTO order_decisions (ts, market_ticker, side, action, details) VALUES (?, ?, ?, ?, ?)",
            (ts.isoformat(), decision.market_ticker, decision.side.value, decision.action, decision.details),
        )

    def save_exception(self, context: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO exceptions (ts, context, message) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), context, message),
            )
            conn.commit()
