"""Invoice storage in SQLite, with numbered migrations applied in name order."""

import sqlite3
from pathlib import Path
from typing import Any

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration the database has not seen; return the names applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for script in sorted(MIGRATIONS.glob("*.sql")):
        if script.name in done:
            continue
        conn.executescript(script.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (script.name,))
        conn.commit()
        applied.append(script.name)
    return applied


def save_invoice(conn: sqlite3.Connection, order_id: str, total_cents: int, tenant: str) -> None:
    conn.execute(
        "INSERT INTO invoices (order_id, total_cents, tenant) VALUES (?, ?, ?)",
        (order_id, total_cents, tenant),
    )
    conn.commit()


def load_invoice(conn: sqlite3.Connection, order_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
    return dict(row) if row else None
