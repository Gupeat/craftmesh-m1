"""极简 JSON 文档存储：给 M2 / B / C / 验收等扩展模块用。

M1 的主订单仍走 store.py 的关系表；扩展模块以「命名空间 + 文档」的形式落库，
每个模块各自一个 SQLite 文件，互不干扰，也便于单独重置演示数据。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class JsonStore:
    def __init__(self, db_path: str | Path, namespace: str):
        self.db_path = Path(db_path)
        self.namespace = namespace
        self.lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS docs (
                    coll TEXT NOT NULL,
                    id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    doc TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (coll, id)
                )
                """
            )

    def put(self, coll: str, doc_id: str, payload: dict[str, Any], updated_at: str = "") -> None:
        from datetime import datetime, timezone

        stamp = updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        body = json.dumps(payload, ensure_ascii=False)
        with self.lock, self._connect() as con:
            row = con.execute(
                "SELECT seq FROM docs WHERE coll = ? AND id = ?", (coll, doc_id)
            ).fetchone()
            if row is None:
                seq = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM docs WHERE coll = ?", (coll,)
                ).fetchone()[0]
                con.execute(
                    "INSERT INTO docs (coll, id, seq, doc, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (coll, doc_id, seq, body, stamp),
                )
            else:
                con.execute(
                    "UPDATE docs SET doc = ?, updated_at = ? WHERE coll = ? AND id = ?",
                    (body, stamp, coll, doc_id),
                )

    def get(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as con:
            row = con.execute(
                "SELECT doc FROM docs WHERE coll = ? AND id = ?", (coll, doc_id)
            ).fetchone()
        return json.loads(row["doc"]) if row else None

    def list(self, coll: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.lock, self._connect() as con:
            rows = con.execute(
                "SELECT doc FROM docs WHERE coll = ? ORDER BY seq ASC LIMIT ?", (coll, limit)
            ).fetchall()
        return [json.loads(r["doc"]) for r in rows]

    def count(self, coll: str) -> int:
        with self.lock, self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM docs WHERE coll = ?", (coll,)).fetchone()[0])

    def delete(self, coll: str, doc_id: str) -> None:
        with self.lock, self._connect() as con:
            con.execute("DELETE FROM docs WHERE coll = ? AND id = ?", (coll, doc_id))

    def reset(self) -> None:
        with self.lock, self._connect() as con:
            con.execute("DELETE FROM docs")


def new_id(prefix: str) -> str:
    import secrets

    return f"{prefix}-{secrets.token_hex(4)}"
