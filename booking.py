import sqlite3
from datetime import datetime, timedelta
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
)

# States
ASK_EQUIP, ASK_DATE, ASK_DURATION = range(3)

EQUIPMENTS = [
    "Badminton equipment",
    "Basketball",
    "Football",
    "Touch rugby ball",
    "Volleyball",
    "Frisbee",
    "Softball equipment"
]

DB_PATH = "hall5.db"

# Database helpers
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
            duration TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()

def add_booking(user_id: int, name: str, equipment: str, date: str, duration: str):
    created = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO bookings (user_id, name, equipment, date, duration, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, name, equipment, date, duration, created)
        )
        conn.commit()
        return c.lastrowid

def get_pending_bookings():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, user_id, name, equipment, date, duration, created_at FROM bookings WHERE status = 'pending' ORDER BY created_at")
        return c.fetchall()

def get_daily_bookings(date: str = None):
    """Get all approved bookings for a given date (default: today)"""
    if date is None:
        date = datetime.utcnow().date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, name, equipment, duration FROM bookings WHERE status='approved' AND date=? ORDER BY id",
            (date,)
        )
        return c.fetchall()

def get_all_daily_bookings(date: str = None):
    """Get all bookings (pending, approved, rejected) for a given date (default: today)"""
    if date is None:
        date = datetime.utcnow().date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, name, equipment, duration, status FROM bookings WHERE date=? ORDER BY status DESC, id",
            (date,)
        )
        return c.fetchall()

def approve_booking_db(booking_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE bookings SET status='approved' WHERE id=? AND status='pending'", (booking_id,))
        conn.commit()
        return c.rowcount > 0

def reject_booking_db(booking_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE bookings SET status='rejected' WHERE id=? AND status='pending'", (booking_id,))
        conn.commit()
        return c.rowcount > 0

def get_user_bookings(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, equipment, date, duration, status FROM bookings WHERE user_id=? ORDER BY created_at DESC", (user_id,))
        return c.fetchall()

# Validation helpers
def _valid_date(text: str):
    text = text.strip()
    if text.lower() in ("today", "tomorrow"):
        return True
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def _normalize_date(text: str):
    t = text.strip().lower()
    if t == "today":
        return datetime.utcnow().date().isoformat()
    if t == "tomorrow":
        return (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    return text

# Conversation handlers
async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [EQUIPMENTS[i:i+2] for i in range(0, len(EQUIPMENTS), 2)]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Which equipment would you like to book?", reply_markup=markup)
    return ASK_EQUIP

async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["equipment"] = update.message.text
    await update.message.reply_text("Please provide the booking date (YYYY-MM-DD) or 'today' / 'tomorrow':")
    return ASK_DATE

async def ask_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if not _valid_date(txt):
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD or 'today' / 'tomorrow'. Try again.")
        return ASK_DATE
    context.user_data["date"] = _normalize_date(txt.strip())
    await update.message.reply_text("How long do you need it for? (e.g. 2 hours / half day)")
    return ASK_DURATION

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    duration = update.message.text.strip()
    context.user_data["duration"] = duration
    user = update.effective_user
    name = user.full_name or ""
    equipment = context.user_data.get("equipment")
    date = context.user_data.get("date")
    booking_id = add_booking(user.id, name, equipment, date, duration)
    await update.message.reply_text(f"✅ Booking request submitted (ID: {booking_id}). Await admin approval.")
    try:
        from main import ADMIN_ID
        admin_id = ADMIN_ID
        await context.bot.send_message(
            chat_id=admin_id,
            text=(f"📢 New equipment booking request (ID: {booking_id})\n"
                  f"User: {name} (ID: {user.id})\n"
                  f"Equipment: {equipment}\n"
                  f"Date: {date}\n"
                  f"Duration: {duration}\n\n"
                  f"/booking_approve {booking_id}  — approve\n"
                  f"/booking_reject {booking_id}  — reject")
        )
    except Exception:
        pass
    return ConversationHandler.END

async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Booking cancelled.")
    return ConversationHandler.END

# Admin commands
async def view_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from main import ADMIN_ID
    except Exception:
        await update.message.reply_text("Admin not configured.")
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    pending = get_pending_bookings()
    if not pending:
        await update.message.reply_text("✅ No pending bookings.")
        return
    msg = "*Pending Bookings:*\n"
    for b in pending:
        msg += f"- ID {b[0]}: {b[2] or 'Unknown'} (UID {b[1]}) — {b[3]} on {b[4]} ({b[5]})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def approve_booking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from main import ADMIN_ID
    except Exception:
        await update.message.reply_text("Admin not configured.")
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        booking_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /booking_approve <booking_id>")
        return
    if approve_booking_db(booking_id):
        await update.message.reply_text(f"✅ Approved booking {booking_id}.")
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM bookings WHERE id=?", (booking_id,))
            row = c.fetchone()
            if row:
                await context.bot.send_message(chat_id=row[0], text=f"✅ Your booking (ID {booking_id}) has been approved.")
    else:
        await update.message.reply_text("❌ Booking not found or already processed.")

async def reject_booking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from main import ADMIN_ID
    except Exception:
        await update.message.reply_text("Admin not configured.")
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        booking_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /booking_reject <booking_id>")
        return
    if reject_booking_db(booking_id):
        await update.message.reply_text(f"❌ Rejected booking {booking_id}.")
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM bookings WHERE id=?", (booking_id,))
            row = c.fetchone()
            if row:
                await context.bot.send_message(chat_id=row[0], text=f"❌ Your booking (ID {booking_id}) has been rejected.")
    else:
        await update.message.reply_text("❌ Booking not found or already processed.")

# ConversationHandler to register from main.py
booking_conv = ConversationHandler(
    entry_points=[CommandHandler("book", start_booking)],
    states={
        ASK_EQUIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
        ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
        ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)],
    },
    fallbacks=[CommandHandler("cancel", cancel_booking)],
)