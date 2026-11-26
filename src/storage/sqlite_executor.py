"""Thread-sicherer lokaler SQLite-Executor als Zero-Config-Standard-Backend."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.config.constants import SQLITE_BUSY_TIMEOUT_MS
from src.domain.exceptions import StorageError
from src.storage.executor import StatementResult


class SqliteExecutor:
    """Kapselt lokale SQLite-Datenbankzugriffe mit WAL-Modus und Parameterisierung."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")

    @property
    def backend_name(self) -> str:
        return f"SQLite ({self._db_path.as_posix()})"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> StatementResult:
        with self._lock:
            try:
                cursor = self._conn.execute(sql, tuple(params))
                rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
                affected = cursor.rowcount if cursor.rowcount >= 0 else 0
                self._conn.commit()
                return StatementResult(rows=rows, affected_rows=affected)
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise StorageError(f"SQLite-Fehler: {exc}") from exc

    def execute_batch(
        self,
        statements: Sequence[tuple[str, Sequence[Any]]],
    ) -> list[StatementResult]:
        if not statements:
            return []
        results: list[StatementResult] = []
        with self._lock:
            try:
                for sql, params in statements:
                    cursor = self._conn.execute(sql, tuple(params))
                    rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
                    affected = cursor.rowcount if cursor.rowcount >= 0 else 0
                    results.append(StatementResult(rows=rows, affected_rows=affected))
                self._conn.commit()
                return results
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise StorageError(f"SQLite-Batch-Fehler: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            self._conn.close()
