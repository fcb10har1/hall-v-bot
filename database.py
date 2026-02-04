import os
import sqlite3
from datetime import datetime
import psycopg2
from psycopg2 import sql

# Check if using PostgreSQL (Railway) or SQLite (local)
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

DB_PATH = os.getenv("DB_PATH", "/tmp/hall5.db") if not USE_POSTGRES else None


def get_db_connection():
    """Get database connection - PostgreSQL for Railway, SQLite for local"""
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    else:
        return sqlite3.connect(DB_PATH)


def init_db():
    """Initialize database tables"""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        
        c.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            user_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            block TEXT NOT NULL,
            room TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        
        c.execute("""
        CREATE TABLE IF NOT EXISTS registered_users (
            user_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            block TEXT NOT NULL,
            room TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        
        conn.commit()
        conn.close()
    else:
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
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("""
        INSERT INTO pending_users (user_id, name, block, room, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name, block=EXCLUDED.block, room=EXCLUDED.room, created_at=EXCLUDED.created_at
        """, (user_id, name, block, room, created_at))
        conn.commit()
        conn.close()
    else:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
            INSERT OR REPLACE INTO pending_users (user_id, name, block, room, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, (user_id, name, block, room, created_at))
            conn.commit()


def get_pending_users():
    conn = get_db_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users ORDER BY created_at ASC")
    else:
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users ORDER BY created_at ASC")
    results = c.fetchall()
    conn.close()
    return results


def approve_user(user_id: int) -> bool:
    conn = get_db_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users WHERE user_id=%s", (user_id,))
    else:
        c.execute("SELECT user_id, name, block, room, created_at FROM pending_users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False

    if USE_POSTGRES:
        c.execute("""
        INSERT INTO registered_users (user_id, name, block, room, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """, row)
        c.execute("DELETE FROM pending_users WHERE user_id=%s", (user_id,))
    else:
        c.execute("""
        INSERT OR REPLACE INTO registered_users (user_id, name, block, room, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, row)
        c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def reject_user(user_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("DELETE FROM pending_users WHERE user_id=%s", (user_id,))
    else:
        c.execute("DELETE FROM pending_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def is_registered(user_id: int) -> bool:
    conn = get_db_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("SELECT 1 FROM registered_users WHERE user_id=%s", (user_id,))
    else:
        c.execute("SELECT 1 FROM registered_users WHERE user_id=?", (user_id,))
    result = c.fetchone() is not None
    conn.close()
    return result


def remove_user(user_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("DELETE FROM registered_users WHERE user_id=%s", (user_id,))
    else:
        c.execute("DELETE FROM registered_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_registered_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, name, block, room, created_at FROM registered_users ORDER BY created_at ASC")
    results = c.fetchall()
    conn.close()
    return results
