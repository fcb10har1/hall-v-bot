from datetime import date as dt_date
from typing import Optional

from database import USE_POSTGRES, get_db_connection


def init_booking_db():
    """Create bookings table if it doesn't exist."""
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT,
                    equipment TEXT NOT NULL,
                    date DATE NOT NULL,
                    duration TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        else:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT,
                    equipment TEXT NOT NULL,
                    date TEXT NOT NULL,
                    duration TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        conn.commit()


def add_booking(user_id: int, name: str, equipment: str, date: str, duration: str) -> int:
    """
    date: 'YYYY-MM-DD' string
    returns booking id
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                """
                INSERT INTO bookings (user_id, name, equipment, date, duration, status, created_at)
                VALUES (%s, %s, %s, %s::date, %s, 'pending', NOW())
                RETURNING id;
                """,
                (user_id, name, equipment, date, duration),
            )
            booking_id = c.fetchone()[0]
        else:
            c.execute(
                """
                INSERT INTO bookings (user_id, name, equipment, date, duration, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP);
                """,
                (user_id, name, equipment, date, duration),
            )
            booking_id = c.lastrowid
        conn.commit()
        return int(booking_id)


def get_pending_bookings():
    """
    Returns list of tuples matching your previous ordering:
    (id, user_id, name, equipment, date, duration, status, created_at)
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                """
                SELECT id, user_id, name, equipment, date::text, duration, status, created_at::text
                FROM bookings
                WHERE status = 'pending'
                ORDER BY created_at ASC;
                """
            )
        else:
            c.execute(
                """
                SELECT id, user_id, name, equipment, date, duration, status, created_at
                FROM bookings
                WHERE status = 'pending'
                ORDER BY created_at ASC;
                """
            )
        return c.fetchall()


def approve_booking_db(booking_id: int) -> Optional[int]:
    """
    Approves only if pending. Returns user_id if success, else None.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=%s FOR UPDATE;",
                (booking_id,),
            )
        else:
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=?;",
                (booking_id,),
            )
        row = c.fetchone()
        if not row:
            return None

        user_id, status = row
        if status != "pending":
            return None

        if USE_POSTGRES:
            c.execute(
                "UPDATE bookings SET status='approved' WHERE id=%s;",
                (booking_id,),
            )
        else:
            c.execute(
                "UPDATE bookings SET status='approved' WHERE id=?;",
                (booking_id,),
            )
        conn.commit()
        return int(user_id)


def reject_booking_db(booking_id: int) -> Optional[int]:
    """
    Rejects only if pending. Returns user_id if success, else None.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=%s FOR UPDATE;",
                (booking_id,),
            )
        else:
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=?;",
                (booking_id,),
            )
        row = c.fetchone()
        if not row:
            return None

        user_id, status = row
        if status != "pending":
            return None

        if USE_POSTGRES:
            c.execute(
                "UPDATE bookings SET status='rejected' WHERE id=%s;",
                (booking_id,),
            )
        else:
            c.execute(
                "UPDATE bookings SET status='rejected' WHERE id=?;",
                (booking_id,),
            )
        conn.commit()
        return int(user_id)


def get_daily_bookings():
    """
    Your old function returned:
    SELECT id, user_id, name, equipment, duration, date
    for today and approved.
    """
    today = dt_date.today().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, date::text
                FROM bookings
                WHERE date = %s::date AND status='approved'
                ORDER BY created_at ASC;
                """,
                (today,),
            )
        else:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, date
                FROM bookings
                WHERE date = ? AND status='approved'
                ORDER BY created_at ASC;
                """,
                (today,),
            )
        return c.fetchall()


def get_all_daily_bookings():
    """
    Your old function returned:
    SELECT id, user_id, name, equipment, duration, status, date
    for today (all statuses)
    """
    today = dt_date.today().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, status, date::text
                FROM bookings
                WHERE date = %s::date
                ORDER BY created_at ASC;
                """,
                (today,),
            )
        else:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, status, date
                FROM bookings
                WHERE date = ?
                ORDER BY created_at ASC;
                """,
                (today,),
            )
        return c.fetchall()
