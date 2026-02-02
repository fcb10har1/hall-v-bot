from telegram import Update, InputFile, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler
)
from dotenv import load_dotenv
import os
from database import (
    init_db,
    add_pending_user,
    get_pending_users,
    approve_user,
    reject_user,
    is_registered,
    remove_user,
    get_registered_users
)
from booking import init_booking_db, booking_conv, view_bookings, approve_booking_cmd, reject_booking_cmd, get_daily_bookings, get_all_daily_bookings
import pandas as pd
import io
from functools import wraps
import sqlite3
from datetime import datetime, timedelta

# States
ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)

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
    """Get all bookings (approved, pending, rejected) for a given date (default: today)"""
    if date is None:
        date = datetime.utcnow().date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, name, equipment, duration, status FROM bookings WHERE date=? ORDER BY id",
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

def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id == ADMIN_ID:
            return await func(update, context, *args, **kwargs)
        with sqlite3.connect("hall5.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM pending_users WHERE user_id = ?", (user_id,))
            is_pending = cursor.fetchone() is not None
        print(f"[LOG] User {user_id} - Admin={ADMIN_ID}, Registered={is_registered(user_id)}, Pending={is_pending}")
        if not is_registered(user_id):
            if update.message:
                if is_pending:
                    await update.message.reply_text("❌ Your registration is pending approval. Please wait.")
                else:
                    await update.message.reply_text("❌ You must register first using /register.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1779704544"))

init_db()
init_booking_db()

async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("register", "Register yourself in the bot"),
        BotCommand("cancel", "Cancel registration"),
        BotCommand("help", "List all available commands"),
        BotCommand("food", "Find supper and food options"),
        BotCommand("groups", "View Hall 5 group links"),
        BotCommand("pending", "Admin: View pending registrations"),
        BotCommand("approve", "Admin: Approve a pending user"),
        BotCommand("reject", "Admin: Reject a pending user"),
        BotCommand("remove", "Admin: Remove a registered user"),
        BotCommand("export", "Admin: Export registered users"),
        BotCommand("export_pending", "Admin: Export pending users"),
        BotCommand("book", "Request to book sports equipment"),
        BotCommand("booking_pending", "Admin: View pending bookings"),
        BotCommand("booking_approve", "Admin: Approve a booking"),
        BotCommand("booking_reject", "Admin: Reject a booking"),
        BotCommand("committees", "Committees in Hall V"),
        BotCommand("daily_bookings", "Admin: View today's approved bookings"),
        BotCommand("all_daily_bookings", "Admin: View all today's bookings (all statuses)")
    ]
    await application.bot.set_my_commands(commands)

ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*WASSUP FIVERS !! 🎉*\n"
        "Welcome to your personal Fiver buddy to aid you in your journey in HALL V !! 🌟\n"
        "- To register please use `/register` 📅\n",
        parse_mode="Markdown"
    )

async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_registered(user_id):
        await update.message.reply_text("✅ You are already registered.")
        return ConversationHandler.END
    await update.message.reply_text("👋 Hi! What's your full name?")
    return ASK_NAME

async def ask_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    reply_keyboard = [["Purple", "Orange"], ["Green", "Blue"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🏢 Which block are you from? Please select one:", reply_markup=markup)
    return ASK_BLOCK

async def ask_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["block"] = update.message.text
    await update.message.reply_text("🏠 What's your room number? (e.g. 28-04-543)")
    return ASK_ROOM

async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["name"]
    block = context.user_data["block"]
    room = update.message.text
    user_id = update.effective_user.id
    add_pending_user(user_id, name, block, room)
    await update.message.reply_text("✅ Registration request sent! Await admin approval.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(f"🚨 *New registration request*\n"
              f"Name: {name}\nBlock: {block}\nRoom: {room}\nUser ID: `{user_id}`\n\n"
              f"/approve {user_id} or /reject {user_id}"),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Registration cancelled.")
    return ConversationHandler.END

@restricted
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /approve <user_id>")
        return
    if approve_user(user_id):
        await update.message.reply_text(f"✅ Approved user {user_id}.")
        await context.bot.send_message(chat_id=user_id, text="✅ You are now registered!")
    else:
        await update.message.reply_text("❌ User not found in pending list.")

@restricted
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /reject <user_id>")
        return
    reject_user(user_id)
    await update.message.reply_text(f"❌ Rejected user {user_id}.")
    await context.bot.send_message(chat_id=user_id, text="❌ Your registration was rejected.")

@restricted
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    pending_users = get_pending_users()
    if not pending_users:
        await update.message.reply_text("✅ No pending users.")
        return
    msg = "*Pending Registrations:*\n"
    for user in pending_users:
        msg += f"- {user[1]}, Room {user[3]} (ID: `{user[0]}`)\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

@restricted
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /remove <user_id>")
        return
    remove_user(user_id)
    await update.message.reply_text(f"🗑️ Removed user {user_id}.")
    await context.bot.send_message(chat_id=user_id, text="⚠️ You have been removed from the bot. Please contact the admin.")

@restricted
async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_registered_users()
    if not users:
        await update.message.reply_text("⚠️ No registered users found to export.")
        return
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(output, filename="registered_users.xlsx"))

@restricted
async def export_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_pending_users()
    if not users:
        await update.message.reply_text("⚠️ No pending users found to export.")
        return
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(output, filename="pending_users.xlsx"))

@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    help_text = ("*Bot Commands:*\n\n"
                 "👤 *For All Users:*\n"
                 "`/start` — Welcome message\n"
                 "`/register` — Register yourself in the bot\n"
                 "`/cancel` — Cancel an ongoing registration\n"
                 "`/book` — Request to book sports equipment\n")
    if user_id == ADMIN_ID:
        help_text += ("\n🔑 *Admin Commands:*\n"
                      "`/approve <user_id>` — Approve a pending registration\n"
                      "`/reject <user_id>` — Reject a pending registration\n"
                      "`/pending` — View list of pending registrations\n"
                      "`/remove <user_id>` — Remove a registered user\n"
                      "`/export` — Export all registered users to Excel\n"
                      "`/export_pending` — Export all pending registrations to Excel\n"
                      "`/booking_pending` — View pending bookings\n"
                      "`/booking_approve <booking_id>` — Approve a booking\n"
                      "`/booking_reject <booking_id>` — Reject a booking\n"
                      "`/daily_bookings` — View today's approved bookings\n"
                      "`/all_daily_bookings` — View all today's bookings (all statuses)\n")
    await update.message.reply_text(help_text, parse_mode="Markdown")

@restricted
async def food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🍜 Supper Spots Nearby", callback_data="supper_nearby")],
        [InlineKeyboardButton("🍛 Food Places Near Hall", callback_data="food_near_hall")],
        [InlineKeyboardButton("🔗 Supper Channels to Join", callback_data="supper_channels")],
        [InlineKeyboardButton("🍔 Popular Hall 5 GrabFood", callback_data="grab_options")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🍽 What are you looking for?", reply_markup=reply_markup)

@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    responses = {
        "supper_nearby": "🍜 Recommended Supper Spots:\n- Extension [Route](https://maps.app.goo.gl/rZB82rqL4fhewZnL9)\n- Prata Shop nearby [Route](https://maps.app.goo.gl/qYPhyT6M5kUbgKYP8)",
        "food_near_hall": "🍛 NTU Food Near Hall:\n- Canteen 4\n- Canteen 2\n- Canteen 1\n- Crespion\n- South Spine",
        "supper_channels": "🔗 Supper Telegram Channels:\n- https://t.me/GigabiteNTU\n- https://t.me/dingontu\n- https://t.me/urmomscooking\n- https://t.me/NomAtNTU\n- https://t.me/AnAcaiAffairXNTU",
        "grab_options": "🍔 Popular GrabFood Picks:\n- McDonald's Jurong West\n- Bai Li Xiang\n- Kimly Dim Sum",
        "JCRC": "JCRC — Joint Common Room Committee. Contact the JCRC for hall-wide announcements and activities.",
        "TYH": "TYH — TYH Committee info and events.",
        "HAVOC": "HAVOC — Havoc committee updates and contact links.",
        "HAPZ": "HAPZ — HAPZ committee details.",
        "Quindance": "Quindance — Hall V's talented group of dancers!",
        "Quinstical Productions": "Quinstical Productions — Our inhouse production crew.",
        "Vikings": "Vikings — HALL V Cheer squad info.",
        "Jamband": "Jamband — Jam band group info."
    }
    if query.data in responses:
        await query.edit_message_text(responses[query.data], parse_mode="Markdown")

@restricted
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = ("*🏛️ HALL 5 GROUP CHATS TO JOIN !*\n\n"
               "*HALL V ANNOUNCEMENTS:*\n"
               "[Announcements](https://t.me/+X6aJeSaPg-JjMDI1)\n\n"
               "*BLOCK CHATS:*\n"
               "💜 [Purple Block (Block 28)](https://t.me/+YLowJE5pAI4zYWNl)\n"
               "🧡 [Orange Block (Block 29)](https://t.me/+KcGB8uMeP8ZmZTE1)\n"
               "💙 [Blue Block (Block 30)](https://t.me/+lK95Tc_NFgc4OTBl)\n"
               "💚 [Green Block (Block 31)](https://t.me/+0rHuc8UPaY01ZWY1)\n\n"
               "*HALL V SPORTS FANATICS:*\n"
               "Join in to meet and have impromptu sports sessions with likeminded people !\n"
               "[Join Sports Sessions](https://t.me/+urn2-hrYt-A2OWY1)\n\n"
               "*HALL V SPORTS:*\n"
               "Join in an array of exhilarating sports!\n"
               "[Sports Activities](https://linktr.ee/HALLVSPORTS)\n\n"
               "*HALL V RECREATIONAL GAMES:*\n"
               "Discover ur hidden talents in the many rec games available!\n"
               "[Recreational Games](https://linktr.ee/HALLVREC)")
    await update.message.reply_text(message, parse_mode="Markdown")

async def show_committees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("JCRC", callback_data="JCRC"), InlineKeyboardButton("TYH", callback_data="TYH")],
        [InlineKeyboardButton("HAVOC", callback_data="HAVOC"), InlineKeyboardButton("HAPZ", callback_data="HAPZ")],
        [InlineKeyboardButton("Quindance", callback_data="Quindance"), InlineKeyboardButton("Quinstical Productions", callback_data="Quinstical Productions")],
        [InlineKeyboardButton("Vikings", callback_data="Vikings"), InlineKeyboardButton("Jamband", callback_data="Jamband")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a committee to view details:", reply_markup=reply_markup)

async def daily_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    bookings = get_daily_bookings()
    if not bookings:
        await update.message.reply_text("✅ No approved bookings for today.")
        return
    msg = "📋 *Today's Approved Equipment Bookings:*\n\n"
    for b in bookings:
        msg += f"• ID {b[0]}: {b[2]} (UID {b[1]})\n  Equipment: {b[3]}\n  Duration: {b[4]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def all_daily_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    bookings = get_all_daily_bookings()
    if not bookings:
        await update.message.reply_text("✅ No bookings for today.")
        return
    msg = "📋 *All Today's Equipment Bookings:*\n\n"
    for b in bookings:
        status_icon = "✅" if b[5] == "approved" else "⏳" if b[5] == "pending" else "❌"
        msg += f"{status_icon} ID {b[0]}: {b[2]} (UID {b[1]})\n"
        msg += f"   Equipment: {b[3]} | Duration: {b[4]}\n"
        msg += f"   Status: {b[5]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.post_init = set_bot_commands

    # Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(CommandHandler("export_pending", export_pending))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("food", food))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("groups", groups))
    app.add_handler(CommandHandler("committees", show_committees))
    app.add_handler(CommandHandler("daily_bookings", daily_bookings))
    app.add_handler(CommandHandler("all_daily_bookings", all_daily_bookings))

    # Booking handlers (from booking.py)
    app.add_handler(booking_conv)
    app.add_handler(CommandHandler("booking_pending", view_bookings))
    app.add_handler(CommandHandler("booking_approve", approve_booking_cmd))
    app.add_handler(CommandHandler("booking_reject", reject_booking_cmd))

    # Registration Conversation
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", start_registration)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_block)],
            ASK_BLOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_room)],
            ASK_ROOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_user)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(register_conv)

    app.run_polling()

if __name__ == "__main__":
    main()
