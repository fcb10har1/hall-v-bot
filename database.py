import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "/tmp/hall5.db")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            block TEXT NOT NULL,
            room TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS registered_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            block TEXT NOT NULL,
            room TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        conn.commit()


def add_pending_user(user_id: int, name: str, block: str, room: str):
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        INSERT OR REPLACE INTO pending_users (user_id, name, block, room, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, block, room, created_at))
        conn.commit()


def get_pending_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users ORDER BY created_at ASC")
        return c.fetchall()


def approve_user(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if not row:
            return False

        c.execute("""
        INSERT OR REPLACE INTO registered_users (user_id, name, block, room, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, row)

        c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))
        conn.commit()
        return True


def reject_user(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))
        conn.commit()


def is_registered(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM registered_users WHERE user_id=?", (user_id,))
        return c.fetchone() is not None


def remove_user(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM registered_users WHERE user_id=?", (user_id,))
        conn.commit()


def get_registered_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, name, block, room, created_at FROM registered_users ORDER BY created_at ASC")
        return c.fetchall()
