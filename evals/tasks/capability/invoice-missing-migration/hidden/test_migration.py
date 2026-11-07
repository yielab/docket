"""The tenant column arrives as a new migration: fresh databases and databases at 0002 both get it."""

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO / "src"))

import store  # noqa: E402

OLD = {
    "0001_create_invoices.sql": "7b11ce712a1573fc6e4c921d9a04c7628b23a15708ef056daab930cba2ad0112",
    "0002_add_status.sql": "4f7c670005bb51437f62ac033e8058c6f3dd708e06b6bda8cd49217c85c1948e",
}


def _at_0002() -> sqlite3.Connection:
    conn = store.connect()
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
    for name in OLD:
        conn.executescript((REPO / "migrations" / name).read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
    conn.execute("INSERT INTO invoices (order_id, total_cents) VALUES ('old-1', 1999)")
    conn.commit()
    return conn


def test_the_existing_migrations_were_not_edited() -> None:
    for name, digest in OLD.items():
        found = hashlib.sha256((REPO / "migrations" / name).read_bytes()).hexdigest()
        assert found == digest, name


def test_a_fresh_database_stores_the_tenant() -> None:
    conn = store.connect()
    store.migrate(conn)
    store.save_invoice(conn, "order-1", 500, "amber-2")
    assert store.load_invoice(conn, "order-1")["tenant"] == "amber-2"


def test_a_database_at_0002_upgrades_in_place_and_keeps_its_rows() -> None:
    conn = _at_0002()
    applied = store.migrate(conn)
    assert len(applied) == 1 and applied[0] > "0002", applied
    old = store.load_invoice(conn, "old-1")
    assert (old["total_cents"], old["status"], old["tenant"]) == (1999, "open", "cobalt-7")
    store.save_invoice(conn, "new-1", 700, "juniper-9")
    assert store.load_invoice(conn, "new-1")["tenant"] == "juniper-9"


def test_migrating_twice_applies_nothing_the_second_time() -> None:
    conn = store.connect()
    first = store.migrate(conn)
    assert len(first) == 3, first
    assert store.migrate(conn) == []


def test_the_visible_suite_is_green() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
