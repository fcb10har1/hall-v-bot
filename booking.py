import sqlite3
from datetime import datetime
from database import DB_PATH


def init_booking_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT,
            equipment TEXT NOT NULL,
            date TEXT NOT NULL,
            duration TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()


def add_booking(user_id: int, name: str, equipment: str, date: str, duration: str) -> int:
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        INSERT INTO bookings (user_id, name, equipment, date, duration, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (user_id, name, equipment, date, duration, created_at))
        conn.commit()
        return c.lastrowid


def get_pending_bookings():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, user_id, name, equipment, date, duration, status, created_at
        FROM bookings
        WHERE status='pending'
        ORDER BY created_at ASC
        """)
        return c.fetchall()


def approve_booking_db(booking_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM bookings WHERE id=?", (booking_id,))
        row = c.fetchone()
        if not row:
            return None
        user_id, status = row
        if status != "pending":
            return None
        c.execute("UPDATE bookings SET status='approved' WHERE id=?", (booking_id,))
        conn.commit()
        return user_id


def reject_booking_db(booking_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM bookings WHERE id=?", (booking_id,))
        row = c.fetchone()
        if not row:
            return None
        user_id, status = row
        if status != "pending":
            return None
        c.execute("UPDATE bookings SET status='rejected' WHERE id=?", (booking_id,))
        conn.commit()
        return user_id


def get_daily_bookings():
    today = datetime.utcnow().date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, user_id, name, equipment, duration, date
        FROM bookings
        WHERE date=? AND status='approved'
        ORDER BY created_at ASC
        """, (today,))
        return c.fetchall()


def get_all_daily_bookings():
    today = datetime.utcnow().date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, user_id, name, equipment, duration, status, date
        FROM bookings
        WHERE date=?
        ORDER BY created_at ASC
        """, (today,))
        return c.fetchall()
