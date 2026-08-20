from __future__ import annotations

import sqlite3
from os import PathLike
from typing import Any


class ClosingSQLiteConnection(sqlite3.Connection):
    """sqlite3 connection whose context manager also closes the handle.

    The standard sqlite3.Connection context manager commits or rolls back a
    transaction, but it does not close the connection. On Windows that leaves
    temporary database files locked until garbage collection, which made NEXA's
    test databases impossible to remove reliably on Python 3.14.
    """

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool | None:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def connect_sqlite(database: str | bytes | PathLike[str] | PathLike[bytes]) -> ClosingSQLiteConnection:
    """Open a transaction-aware SQLite connection that closes on context exit."""

    connection = sqlite3.connect(database, factory=ClosingSQLiteConnection)
    connection.row_factory = sqlite3.Row
    return connection
