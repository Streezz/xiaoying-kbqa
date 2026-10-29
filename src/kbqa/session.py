"""多轮会话存储（SQLite）：每轮的问题和结果，以及会话级的证据账本。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .ledger import Ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    session_id TEXT NOT NULL,
    turn_no    INTEGER NOT NULL,
    question   TEXT NOT NULL,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_no)
);
CREATE TABLE IF NOT EXISTS ledgers (
    session_id TEXT PRIMARY KEY,
    data       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_no INTEGER NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class SessionStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def load(self, session_id: str) -> tuple[list[dict], Ledger]:
        rows = self.conn.execute(
            "SELECT turn_no, question, result FROM turns WHERE session_id=? ORDER BY turn_no", (session_id,)
        ).fetchall()
        turns = [{"turn_no": n, "question": q, "result": json.loads(r)} for n, q, r in rows]
        row = self.conn.execute("SELECT data FROM ledgers WHERE session_id=?", (session_id,)).fetchone()
        return turns, Ledger.from_dict(json.loads(row[0]) if row else None)

    def save(self, session_id: str, turn_no: int, question: str, result: dict, ledger: Ledger) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO turns VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_no, question, json.dumps(result, ensure_ascii=False), datetime.now().isoformat()),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO ledgers VALUES (?, ?)",
                (session_id, json.dumps(ledger.to_dict(), ensure_ascii=False)),
            )
            if result.get('confirmation'):
                self.conn.execute("INSERT INTO confirmations (session_id, turn_no, data, created_at) VALUES (?, ?, ?, ?)",
                                  (session_id, turn_no, json.dumps(result['confirmation'], ensure_ascii=False),
                                   datetime.now(timezone.utc).isoformat()))

    def confirmations(self, session_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT id, turn_no, data, created_at FROM confirmations WHERE session_id=? ORDER BY id",
                                 (session_id,)).fetchall()
        return [{'id': i, 'session_id': session_id, 'turn_no': n, 'confirmation': json.loads(d), 'created_at': at}
                for i, n, d, at in rows]

    def reset(self, session_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
            self.conn.execute("DELETE FROM ledgers WHERE session_id=?", (session_id,))
