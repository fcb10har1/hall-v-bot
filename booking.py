import os
from datetime import datetime, date as dt_date
from typing import List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def _get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Add it in Railway Variables.")
    # sslmode=require is needed on most hosted Postgres (incl. Railway)
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_booking_db():
    """Create bookings table if it doesn't exist."""
    with _get_conn() as conn:
        with conn.cursor() as c:
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
        conn.commit()


def add_booking(user_id: int, name: str, equipment: str, date: str, duration: str) -> int:
    """
    date: 'YYYY-MM-DD' string
    returns booking id
    """
    with _get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO bookings (user_id, name, equipment, date, duration, status, created_at)
                VALUES (%s, %s, %s, %s::date, %s, 'pending', NOW())
                RETURNING id;
                """,
                (user_id, name, equipment, date, duration),
            )
            booking_id = c.fetchone()[0]
        conn.commit()
        return int(booking_id)


def get_pending_bookings():
    """
    Returns list of tuples matching your previous ordering:
    (id, user_id, name, equipment, date, duration, status, created_at)
    """
    with _get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT id, user_id, name, equipment, date::text, duration, status, created_at::text
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
    with _get_conn() as conn:
        with conn.cursor() as c:
            # lock the row to avoid race condition
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=%s FOR UPDATE;",
                (booking_id,),
            )
            row = c.fetchone()
            if not row:
                return None

            user_id, status = row
            if status != "pending":
                return None

            c.execute(
                "UPDATE bookings SET status='approved' WHERE id=%s;",
                (booking_id,),
            )
        conn.commit()
        return int(user_id)


def reject_booking_db(booking_id: int) -> Optional[int]:
    """
    Rejects only if pending. Returns user_id if success, else None.
    """
    with _get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                "SELECT user_id, status FROM bookings WHERE id=%s FOR UPDATE;",
                (booking_id,),
            )
            row = c.fetchone()
            if not row:
                return None

            user_id, status = row
            if status != "pending":
                return None

            c.execute(
                "UPDATE bookings SET status='rejected' WHERE id=%s;",
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
    with _get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, date::text
                FROM bookings
                WHERE date = %s::date AND status='approved'
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
    with _get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT id, user_id, name, equipment, duration, status, date::text
                FROM bookings
                WHERE date = %s::date
                ORDER BY created_at ASC;
                """,
                (today,),
            )
            return c.fetchall()
