"""
Teaching example: tests for python_engine/db.py (C1).

This is a WORKED EXAMPLE so you can learn pytest's mechanics. Read every comment.
C1 was already written, so these are "tests after the fact." From C2 onward you write the
test FIRST (Red), then the code (Green) — that's TDD, and you'll do it yourself.

Run it from the project ROOT (where you can see python_engine/ and tests/):

    python -m pytest -v

  - `python -m pytest`  runs pytest and puts the current folder on the import path, so
    `from python_engine.db import ...` resolves.
  - `-v`  = verbose: prints each test name and pass/fail.
"""

import sqlite3

import pytest

# We import the functions under test. Because we run pytest from the project root and
# python_engine has an __init__.py, it's importable as a package.
from python_engine.db import init_db, read_row


# ---------------------------------------------------------------------------
# FIXTURE — reusable setup shared by multiple tests.
# ---------------------------------------------------------------------------
# A fixture is a function pytest runs BEFORE a test that "requests" it (by naming it as
# a parameter). It's how you arrange a clean, isolated world for each test.
#
# The PROBLEM this solves: db.py has a hard-coded `DB_NAME = "data/pages.db"`. If our tests
# hit that real file they'd (a) pollute your real data and (b) depend on each other's leftovers
# — the cardinal sin of testing. Tests must be ISOLATED and repeatable.
#
# Two built-in pytest tools fix it:
#   * `tmp_path`   — a fresh, empty temporary directory unique to each test. Auto-deleted after.
#   * `monkeypatch`— safely overrides something (here, the module's DB_NAME) FOR ONE TEST ONLY,
#                    then automatically restores it. No permanent change to your code.
#
# TEACHING NOTE (a design smell worth seeing): the only reason we need monkeypatch here is that
# db.py hard-codes its path. A more *testable* design would let each function accept an optional
# db path argument (dependency injection) — then a test could just pass `tmp_path/"x.db"` with no
# monkeypatching. Consider that refactor later as an exercise; writing tests that EXPOSE rigid
# design is one of TDD's biggest payoffs.
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point db.py at a throwaway database that lives only for this one test."""
    db_file = tmp_path / "test_pages.db"
    # Redirect the module-level constant. The db.py functions read DB_NAME at call time,
    # so overriding the module attribute makes them use our temp file.
    monkeypatch.setattr("python_engine.db.DB_NAME", str(db_file))
    return db_file


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------
# Anatomy of a test: the "AAA" pattern.
#   Arrange — set up the world (often done by the fixture).
#   Act     — call the thing you're testing.
#   Assert  — state what MUST be true. If a plain `assert` is False, the test fails.
# A test's NAME should read like a sentence describing the guarantee.

def test_init_db_creates_pages_table(temp_db):
    # Act: run the schema creation against our temp db.
    init_db()

    # Assert: open the temp db and ask SQLite what tables exist.
    # sqlite_master is SQLite's internal catalog of everything in the database.
    conn = sqlite3.connect(temp_db)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    conn.close()

    # `fetchall()` gives a list of 1-tuples like [('pages',)]. We flatten to names.
    table_names = [row[0] for row in tables]
    assert "pages" in table_names


def test_pages_table_matches_the_contract(temp_db):
    """The schema is the integration contract with the TypeScript side — lock it down."""
    init_db()

    conn = sqlite3.connect(temp_db)
    # PRAGMA table_info returns one row per column:
    #   (cid, name, type, notnull, default_value, pk)
    columns = conn.execute("PRAGMA table_info(pages)").fetchall()
    conn.close()

    column_names = [col[1] for col in columns]
    assert column_names == ["url", "title", "content", "status_code", "crawled_at"]

    # The design decision that matters most: `url` must be the PRIMARY KEY.
    # In PRAGMA table_info the last field (index 5) is the pk flag (1 if part of the PK).
    url_column = next(col for col in columns if col[1] == "url")
    assert url_column[5] == 1, "url must be the PRIMARY KEY (dedup/upsert depends on it)"


def test_init_db_is_idempotent(temp_db):
    """CREATE TABLE IF NOT EXISTS means running init_db twice must not raise."""
    init_db()
    init_db()  # second call should be a harmless no-op, not an error
    # Reaching here without an exception is the assertion. (No crash == pass.)


def test_read_row_returns_none_when_url_is_absent(temp_db):
    init_db()
    # Nothing has been inserted, so a lookup should return None (not raise, not []).
    result = read_row("https://not-crawled-yet.example.com")
    assert result is None


def test_read_row_returns_the_row_that_was_inserted(temp_db):
    """Arrange test data directly with SQL, then verify read_row reads it back correctly."""
    init_db()

    # Arrange: insert a known row straight into the temp db.
    # (db.py has no insert function yet — that's C6 — so we set up the data ourselves.)
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO pages (url, title, content, status_code, crawled_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("https://example.com", "Example", "hello world", 200, 1620000000),
    )
    conn.commit()
    conn.close()

    # Act
    row = read_row("https://example.com")

    # Assert: read_row returns the columns in schema order as a tuple.
    assert row == ("https://example.com", "Example", "hello world", 200, 1620000000)
