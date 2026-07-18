import pytest
import sqlite3
from python_engine.cache import PageCache

def test_schema_matches_contract(tmp_path):
    db_path = tmp_path / "test.db"
    cache = PageCache(db_path=str(db_path))
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute("PRAGMA table_info(pages)")
        columns = [row[1] for row in cursor.fetchall()]
    expected = ["url", "title", "content", "status_code", "crawled_at", "links_json"]
    assert columns == expected