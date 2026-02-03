import os
import io
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
from dotenv import load_dotenv
from telegram import (
    Update,
    InputFile,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from database import (
    DB_PATH,
    init_db,
    add_pending_user,
    get_pending_users,
    approve_user,
    reject_user,
    is_registered,
    remove_user,
    get_registered_users,
)

from booking import (
    init_booking_db,
    add_booking,
    get_pending_bookings,
    approve_booking_db,
    reject_booking_db,
    get_daily_bookings,
    get_all_daily_bookings,
)

# ---------------- ENV ----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1779704544"))

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

# ---------------- CONSTANTS ----------------
EQUIPMENTS = [
    "Basketball", "Soccer Ball",
    "Badminton Racket", "Shuttlecock",
    "Volleyball", "Floorball Stick",
    "Floorball Ball", "Tennis Racket",
]

# ---------------- STATES ----------------
ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)
ASK_EQUIP, ASK_DATE, ASK_DURATION = range(10, 13)


# ---------------- HELPERS ----------------
def _valid_date(text: str) -> bool:
    text = text.strip()
    if text.lower() in ("today", "tomorrow"):
        return True
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_date(text: str) -> str:
    t = text.strip().lower()
    today = datetime.utcnow().date()
    if t == "today":
        return today.isoformat()
    if t == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    return text.strip()


def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        # Admin bypass
        if user_id == ADMIN_ID:
            return await func(update, context, *args, **kwargs)

        # pending check for nicer UX
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pending_users WHERE user_id=?", (user_id,))
            is_pending = cur.fetchone() is not None

        if not is_registered(user_id):
            if update.message:
                if is_pending:
                    await update.message.reply_text("⏳ Your registration is pending admin approval. Please wait.")
                else:
                    await update.message.reply_text("❌ You must register first using /register.")
            elif update.callback_query:
                await update.callback_query.answer("❌ Register first using /register.", show_alert=True)
            return

        return await func(update, context, *args, **kwargs)

    return wrapped


# ---------------- BOT COMMANDS ----------------
async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("register", "Register yourself in the bot"),
        BotCommand("cancel", "Cancel an ongoing process"),
        BotCommand("help", "List all available commands"),
        BotCommand("food", "Find supper and food options"),
        BotCommand("groups", "View Hall 5 group links"),
        BotCommand("committees", "Committees in Hall V"),
        BotCommand("book", "Request to book sports equipment"),

        # Admin
        BotCommand("pending", "Admin: View pending registrations"),
        BotCommand("approve", "Admin: Approve a pending user"),
        BotCommand("reject", "Admin: Reject a pending user"),
        BotCommand("remove", "Admin: Remove a registered user"),
        BotCommand("export", "Admin: Export registered users"),
        BotCommand("export_pending", "Admin: Export pending users"),
        BotCommand("booking_pending", "Admin: View pending bookings"),
        BotCommand("booking_approve", "Admin: Approve a booking"),
        BotCommand("booking_reject", "Admin: Reject a booking"),
        BotCommand("daily_bookings", "Admin: View today's approved bookings"),
        BotCommand("all_daily_bookings", "Admin: View all today's bookings (all statuses)"),
    ]
    await application.bot.set_my_commands(commands)


# ---------------- BASIC ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*WASSUP FIVERS !! 🎉*\n"
        "Welcome to your personal Fiver buddy 🌟\n\n"
        "Register: `/register`\n"
        "Need help on commands you can use?: `/help`\n",
        parse_mode="Markdown",
    )


# ---------------- REGISTRATION FLOW ----------------
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_registered(user_id):
        await update.message.reply_text("✅ You are already registered.")
        return ConversationHandler.END
    await update.message.reply_text("👋 Hi! What's your full name?")
    return ASK_NAME


async def ask_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    reply_keyboard = [["Purple", "Orange"], ["Green", "Blue"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🏢 Which block are you from?", reply_markup=markup)
    return ASK_BLOCK


async def ask_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["block"] = update.message.text.strip()
    await update.message.reply_text("🏠 What's your room number? (e.g. 28-04-543)")
    return ASK_ROOM


async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = context.user_data.get("name", "").strip()
    block = context.user_data.get("block", "").strip()
    room = update.message.text.strip()

    add_pending_user(user_id, name, block, room)

    await update.message.reply_text("✅ Registration request sent! Await admin approval.")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🚨 *New registration request*\n"
            f"Name: {name}\n"
            f"Block: {block}\n"
            f"Room: {room}\n"
            f"User ID: `{user_id}`\n\n"
            f"/approve {user_id}  or  /reject {user_id}"
        ),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
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
    users = get_pending_users()
    if not users:
        await update.message.reply_text("✅ No pending users.")
        return
    msg = "*Pending Registrations:*\n"
    for u in users:
        msg += f"- {u[1]} ({u[2]} Block, Room {u[3]}) — `{u[0]}`\n"
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
    await context.bot.send_message(chat_id=user_id, text="⚠️ You have been removed. Contact admin.")


@restricted
async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_registered_users()
    if not users:
        await update.message.reply_text("⚠️ No registered users found.")
        return
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room", "Created At"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    await context.bot.send_document(
        chat_id=update.effective_user.id,
        document=InputFile(output, filename="registered_users.xlsx"),
    )


@restricted
async def export_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_pending_users()
    if not users:
        await update.message.reply_text("⚠️ No pending users found.")
        return
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room", "Created At"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    await context.bot.send_document(
        chat_id=update.effective_user.id,
        document=InputFile(output, filename="pending_users.xlsx"),
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (
        "*Commands:*\n"
        "`/start`\n"
        "`/register`\n"
        "`/book`\n"
        "`/food`\n"
        "`/groups`\n"
        "`/committees`\n"
    )
    if uid == ADMIN_ID:
        text += (
            "\n*Admin:*\n"
            "`/pending`\n"
            "`/approve <user_id>`\n"
            "`/reject <user_id>`\n"
            "`/remove <user_id>`\n"
            "`/export`\n"
            "`/export_pending`\n"
            "`/booking_pending`\n"
            "`/booking_approve <booking_id>`\n"
            "`/booking_reject <booking_id>`\n"
            "`/daily_bookings`\n"
            "`/all_daily_bookings`\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- FOOD ----------------
# ✅ FIX: decorators must NOT be placed on variables
CANTEEN_MENUS = {
    "canteen_1": {
        "name": "🏫 Canteen 1",
        "food": ["Chicken Rice", "Fried Noodles", "Laksa", "Roti Prata", "Vegetable Soup"],
    },
    "canteen_2": {
        "name": "🏫 Canteen 2",
        "food": ["Fish & Chips", "Chicken Cutlet", "Fried Rice", "Mixed Vegetables", "Satay Skewers"],
    },
    "canteen_4": {
        "name": "🏫 Canteen 4",
        "food": ["Bee Hoon", "Chicken Wings", "Grilled Fish", "Stir Fried Greens", "Spring Rolls"],
    },
    "crespion": {
        "name": "☕ Crespion",
        "food": ["Crepes (Sweet & Savoury)", "Coffee Drinks", "Pastries", "Smoothie Bowls", "Desserts"],
    },
    "south_spine": {
        "name": "🍽️ South Spine",
        "food": ["International Cuisine", "Asian Fusion", "Vegetarian Options", "Burgers & Sandwiches", "Desserts & Beverages"],
    },
}


@restricted
async def food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🍜 Supper Spots Nearby", callback_data="supper_nearby")],
        [InlineKeyboardButton("🍛 Food Places Near Hall", callback_data="food_near_hall")],
        [InlineKeyboardButton("🔗 Supper Channels to Join", callback_data="supper_channels")],
        [InlineKeyboardButton("🍔 Popular Hall 5 GrabFood", callback_data="grab_options")],
    ]
    await update.message.reply_text("🍽 What are you looking for?", reply_markup=InlineKeyboardMarkup(keyboard))


@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # show canteen selector
    if query.data == "food_near_hall":
        keyboard = [
            [InlineKeyboardButton("🏫 Canteen 1", callback_data="canteen_1"),
             InlineKeyboardButton("🏫 Canteen 2", callback_data="canteen_2")],
            [InlineKeyboardButton("🏫 Canteen 4", callback_data="canteen_4"),
             InlineKeyboardButton("☕ Crespion", callback_data="crespion")],
            [InlineKeyboardButton("🍽️ South Spine", callback_data="south_spine")],
        ]
        await query.edit_message_text("🍽 Select a canteen to explore:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # show canteen food list
    if query.data in CANTEEN_MENUS:
        canteen = CANTEEN_MENUS[query.data]
        food_list = "\n".join([f"• {f}" for f in canteen["food"]])
        message = f"{canteen['name']}\n\n📋 *Food Options:*\n{food_list}"
        await query.edit_message_text(message, parse_mode="Markdown")
        return

    responses = {
        "supper_nearby": (
            "🍜 *Supper Spots Nearby:*\n\n"
            "• [Extension](https://maps.app.goo.gl/56sPvRMdJPujKLzb7)\n"
            "• [Nearby Prata Shop](https://maps.app.goo.gl/d3A4HLFudtiPQQKP6)"
        ),
        "supper_channels": (
            "🔗 *Supper Telegram Channels:*\n\n"
            "• [GigabiteNTU](https://t.me/GigabiteNTU)\n"
            "• [DingoNTU](https://t.me/dingontu)\n"
            "• [UrMomsCooking](https://t.me/urmomscooking)\n"
            "• [NomAtNTU](https://t.me/NomAtNTU)\n"
            "• [AnAcaiAffairXNTU](https://t.me/AnAcaiAffairXNTU)"
        ),
        "grab_options": (
            "🍔 *Popular GrabFood Options:*\n\n"
            "• McDonald's Jurong West\n"
            "• Bai Li Xiang\n"
            "• Kimly Dim Sum"
        ),
        "JCRC": "JCRC info...",
        "TYH": "TYH info...",
        "HAVOC": "HAVOC info...",
        "HAPZ": "HAPZ info...",
        "Quindance": "Quindance info...",
        "Quinstical Productions": "Quinstical Productions info...",
        "Vikings": "Vikings info...",
        "Jamband": "Jamband info...",
    }

    if query.data in responses:
        await query.edit_message_text(responses[query.data], parse_mode="Markdown")


@restricted
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Put your group links here.", parse_mode="Markdown")


async def show_committees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("JCRC", callback_data="JCRC"), InlineKeyboardButton("TYH", callback_data="TYH")],
        [InlineKeyboardButton("HAVOC", callback_data="HAVOC"), InlineKeyboardButton("HAPZ", callback_data="HAPZ")],
        [InlineKeyboardButton("Quindance", callback_data="Quindance"),
         InlineKeyboardButton("Quinstical Productions", callback_data="Quinstical Productions")],
        [InlineKeyboardButton("Vikings", callback_data="Vikings"), InlineKeyboardButton("Jamband", callback_data="Jamband")],
    ]
    await update.message.reply_text("Select a committee:", reply_markup=InlineKeyboardMarkup(keyboard))


# ---------------- BOOKING FLOW ----------------
@restricted
async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [EQUIPMENTS[i:i + 2] for i in range(0, len(EQUIPMENTS), 2)]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Which equipment would you like to book?", reply_markup=markup)
    return ASK_EQUIP


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["equipment"] = update.message.text.strip()
    await update.message.reply_text("Booking date (YYYY-MM-DD) or 'today'/'tomorrow':")
    return ASK_DATE


async def ask_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if not _valid_date(txt):
        await update.message.reply_text("Invalid date. Use YYYY-MM-DD or 'today'/'tomorrow'.")
        return ASK_DATE
    context.user_data["date"] = _normalize_date(txt)
    await update.message.reply_text("How long? (e.g. 2 hours / half day)")
    return ASK_DURATION


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    duration = update.message.text.strip()
    user = update.effective_user

    equipment = context.user_data.get("equipment")
    date = context.user_data.get("date")
    name = user.full_name or ""

    booking_id = add_booking(user.id, name, equipment, date, duration)

    await update.message.reply_text(f"✅ Booking submitted (ID: {booking_id}). Await admin approval.")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📢 *New booking request* (ID: {booking_id})\n"
                f"User: {name} (`{user.id}`)\n"
                f"Equipment: {equipment}\n"
                f"Date: {date}\n"
                f"Duration: {duration}\n\n"
                f"/booking_approve {booking_id}\n"
                f"/booking_reject {booking_id}"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    return ConversationHandler.END


async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Booking cancelled.")
    return ConversationHandler.END


# ---------------- BOOKING ADMIN ----------------
async def booking_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return

    pending_list = get_pending_bookings()
    if not pending_list:
        await update.message.reply_text("✅ No pending bookings.")
        return

    msg = "*Pending Bookings:*\n"
    for b in pending_list:
        msg += f"- ID {b[0]}: {b[2] or 'Unknown'} (UID {b[1]}) — {b[3]} on {b[4]} ({b[5]})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def booking_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    try:
        booking_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /booking_approve <booking_id>")
        return

    user_id = approve_booking_db(booking_id)
    if user_id:
        await update.message.reply_text(f"✅ Approved booking {booking_id}.")
        await context.bot.send_message(chat_id=user_id, text=f"✅ Your booking (ID {booking_id}) is approved.")
    else:
        await update.message.reply_text("❌ Booking not found or already processed.")


async def booking_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    try:
        booking_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usage: /booking_reject <booking_id>")
        return

    user_id = reject_booking_db(booking_id)
    if user_id:
        await update.message.reply_text(f"❌ Rejected booking {booking_id}.")
        await context.bot.send_message(chat_id=user_id, text=f"❌ Your booking (ID {booking_id}) is rejected.")
    else:
        await update.message.reply_text("❌ Booking not found or already processed.")


async def daily_bookings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    bookings = get_daily_bookings()
    if not bookings:
        await update.message.reply_text("✅ No approved bookings today.")
        return
    msg = "📋 *Today's Approved Bookings:*\n\n"
    for b in bookings:
        msg += f"• ID {b[0]}: {b[2]} — {b[3]} ({b[4]})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def all_daily_bookings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    bookings = get_all_daily_bookings()
    if not bookings:
        await update.message.reply_text("✅ No bookings today.")
        return
    msg = "📋 *All Today's Bookings:*\n\n"
    for b in bookings:
        icon = "✅" if b[5] == "approved" else "⏳" if b[5] == "pending" else "❌"
        msg += f"{icon} ID {b[0]}: {b[2]} — {b[3]} ({b[4]}) [{b[5]}]\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


# ---------------- MAIN ----------------
def main():
    init_db()
    init_booking_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.post_init = set_bot_commands

    # basics
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # food + inline
    app.add_handler(CommandHandler("food", food))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("groups", groups))
    app.add_handler(CommandHandler("committees", show_committees))

    # registration convo
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

    # admin users
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(CommandHandler("export_pending", export_pending))

    # booking convo
    booking_conv = ConversationHandler(
        entry_points=[CommandHandler("book", start_booking)],
        states={
            ASK_EQUIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)],
        },
        fallbacks=[CommandHandler("cancel", cancel_booking)],
    )
    app.add_handler(booking_conv)

    # booking admin
    app.add_handler(CommandHandler("booking_pending", booking_pending))
    app.add_handler(CommandHandler("booking_approve", booking_approve))
    app.add_handler(CommandHandler("booking_reject", booking_reject))
    app.add_handler(CommandHandler("daily_bookings", daily_bookings_cmd))
    app.add_handler(CommandHandler("all_daily_bookings", all_daily_bookings_cmd))

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
