from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self._init()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init(self) -> None:
        with self.lock, self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    pattern_id TEXT NOT NULL,
                    pattern_name TEXT NOT NULL,
                    process TEXT NOT NULL,
                    process_label TEXT NOT NULL,
                    material TEXT NOT NULL,
                    material_label TEXT NOT NULL,
                    finish TEXT NOT NULL,
                    finish_label TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    verdict TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    order_json TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    label TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    role TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_order ON audit(order_id, id)")

    def reset(self) -> None:
        with self.lock, self._connect() as con:
            con.execute("DELETE FROM audit")
            con.execute("DELETE FROM orders")

    def insert(self, order: dict[str, Any]) -> None:
        payload = json.dumps(order, ensure_ascii=False)
        pattern = order["pattern"]
        quote = order["quote"]
        with self.lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO orders (
                    id, status, version, pattern_id, pattern_name, process, process_label,
                    material, material_label, finish, finish_label, mode, quantity,
                    verdict, amount_cents, created_at, updated_at, created_by, order_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["id"], order["status"], order["version"], pattern["id"], pattern["name"],
                    order["process"], order["processLabel"], order["material"], order["materialLabel"],
                    order["finish"], order["finishLabel"], order["mode"], order["quantity"],
                    order["verdict"], quote["amountCents"], order["createdAt"], order["updatedAt"],
                    order["createdBy"], payload,
                ),
            )

    def update(self, order: dict[str, Any]) -> None:
        payload = json.dumps(order, ensure_ascii=False)
        with self.lock, self._connect() as con:
            con.execute(
                "UPDATE orders SET status=?, version=?, updated_at=?, order_json=? WHERE id=?",
                (order["status"], order["version"], order["updatedAt"], payload, order["id"]),
            )

    def add_event(self, event: dict[str, Any]) -> None:
        with self.lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO audit (order_id, at, action, label, from_status, to_status, role, actor, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["orderId"], event["at"], event["action"], event["label"],
                    event["from"], event["to"], event["role"], event["actor"], event.get("note", ""),
                ),
            )

    def _row_to_order(self, row: sqlite3.Row, with_audit: bool = False) -> dict[str, Any]:
        order = json.loads(row["order_json"])
        if with_audit:
            order["audit"] = self.audit(row["id"])
        return order

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, self._connect() as con:
            rows = con.execute(
                "SELECT * FROM orders ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def get(self, order_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as con:
            row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_order(row, with_audit=True)

    def audit(self, order_id: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as con:
            rows = con.execute(
                "SELECT * FROM audit WHERE order_id=? ORDER BY id ASC", (order_id,)
            ).fetchall()
        return [
            {
                "at": r["at"], "action": r["action"], "label": r["label"],
                "from": r["from_status"], "to": r["to_status"], "role": r["role"],
                "actor": r["actor"], "note": r["note"],
            }
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self.lock, self._connect() as con:
            total = con.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
            open_count = con.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE status NOT IN ('settled','cancelled')"
            ).fetchone()["n"]
            passed = con.execute("SELECT COUNT(*) AS n FROM orders WHERE verdict='pass'").fetchone()["n"]
            audit_count = con.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
            recent_rows = con.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT 6"
            ).fetchall()
            status_rows = con.execute(
                "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"
            ).fetchall()
        return {
            "orders": total,
            "open": open_count,
            "passed": passed,
            "audit": audit_count,
            "byStatus": {r["status"]: r["n"] for r in status_rows},
            "recentAudit": [
                {
                    "orderId": r["order_id"], "at": r["at"], "action": r["action"],
                    "label": r["label"], "from": r["from_status"], "to": r["to_status"],
                    "role": r["role"], "actor": r["actor"], "note": r["note"],
                }
                for r in recent_rows
            ],
        }
