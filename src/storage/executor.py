"""Abstraktes Executor-Protokoll für SQLite und Turso."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StatementResult:
    """Einheitliches Ergebnis einer SQL-Abfrage."""

    rows: list[dict[str, Any]]
    affected_rows: int = 0


class SqlExecutor(Protocol):
    """Gemeinsames Interface für lokale SQLite- und Cloud-Turso-Verbindungen."""

    @property
    def backend_name(self) -> str: ...

    def execute(self, sql: str, params: Sequence[Any] = ()) -> StatementResult: ...

    def execute_batch(
        self,
        statements: Sequence[tuple[str, Sequence[Any]]],
    ) -> list[StatementResult]: ...

    def close(self) -> None: ...
