import sqlite3
from typing import Optional, Tuple

DB_NAME = "data/pages.db"

def init_db() -> None:
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, title TEXT , content TEXT , status_code INTEGER, crawled_at INTEGER)"
        )

def read_row(url: str) -> Optional[Tuple[str, str, str, int, int]]:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT url, title, content, status_code, crawled_at FROM pages WHERE url = ?", (url,))
        row = cursor.fetchone()
        return row
    
if __name__ == "__main__":
    init_db()
    data = read_row("https://example.com")
    if data:
        print(f"Read: {data}")
    else:
        print("No row found.")