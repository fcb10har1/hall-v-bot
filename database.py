import os
import sqlite3
from datetime import datetime
from typing import Any, List, Optional, Tuple

import psycopg2

# ---------------- Config ----------------
DATABASE_URL = os.getenv("DATABASE_URL")  # set on Railway
USE_POSTGRES = bool(DATABASE_URL)

# IMPORTANT: keep DB_PATH ALWAYS as a string so imports don't break
DB_PATH = os.getenv("DB_PATH", "/tmp/hall5.db")


def get_db_connection():
    """
    Returns a connection object:
    - PostgreSQL if DATABASE_URL is set (Railway)
    - SQLite otherwise (local)
    """
    if USE_POSTGRES:
        # Railway hosted Postgres typically requires ssl
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    return sqlite3.connect(DB_PATH)


def init_db():
    """
    Create tables if they don't exist.
    Use better types for Postgres (TIMESTAMPTZ).
    """
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_users (
                        user_id BIGINT PRIMARY KEY,
                        name TEXT NOT NULL,
                        block TEXT NOT NULL,
                        room TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS registered_users (
                        user_id BIGINT PRIMARY KEY,
                        name TEXT NOT NULL,
                        block TEXT NOT NULL,
                        room TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            conn.commit()
    else:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    block TEXT NOT NULL,
                    room TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    block TEXT NOT NULL,
                    room TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()


def add_pending_user(user_id: int, name: str, block: str, room: str):
    """
    Upserts user into pending_users.
    """
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute(
                    """
                    INSERT INTO pending_users (user_id, name, block, room)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        block = EXCLUDED.block,
                        room = EXCLUDED.room,
                        created_at = NOW();
                    """,
                    (user_id, name, block, room),
                )
            conn.commit()
    else:
        created_at = datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT OR REPLACE INTO pending_users (user_id, name, block, room, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (user_id, name, block, room, created_at),
            )
            conn.commit()


def get_pending_users():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_id, name, block, room, created_at FROM pending_users ORDER BY created_at ASC"
        )
        return c.fetchall()


def approve_user(user_id: int) -> bool:
    """
    Move user from pending_users -> registered_users.
    """
    with get_db_connection() as conn:
        c = conn.cursor()

        if USE_POSTGRES:
            c.execute(
                "SELECT user_id, name, block, room, created_at FROM pending_users WHERE user_id=%s",
                (user_id,),
            )
        else:
            c.execute(
                "SELECT user_id, name, block, room, created_at FROM pending_users WHERE user_id=?",
                (user_id,),
            )

        row = c.fetchone()
        if not row:
            return False

        if USE_POSTGRES:
            c.execute(
                """
                INSERT INTO registered_users (user_id, name, block, room, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
                """,
                row,
            )
            c.execute("DELETE FROM pending_users WHERE user_id=%s", (user_id,))
        else:
            c.execute(
                """
                INSERT OR REPLACE INTO registered_users (user_id, name, block, room, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                row,
            )
            c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))

        conn.commit()
        return True


def reject_user(user_id: int):
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute("DELETE FROM pending_users WHERE user_id=%s", (user_id,))
        else:
            c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))
        conn.commit()


def is_registered(user_id: int) -> bool:
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute("SELECT 1 FROM registered_users WHERE user_id=%s LIMIT 1", (user_id,))
        else:
            c.execute("SELECT 1 FROM registered_users WHERE user_id=? LIMIT 1", (user_id,))
        return c.fetchone() is not None


def remove_user(user_id: int):
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute("DELETE FROM registered_users WHERE user_id=%s", (user_id,))
        else:
            c.execute("DELETE FROM registered_users WHERE user_id=?", (user_id,))
        conn.commit()


def get_registered_users():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_id, name, block, room, created_at FROM registered_users ORDER BY created_at ASC"
        )
        return c.fetchall()
