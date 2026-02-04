import os
import io
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
    get_db_connection,   # ✅ NEW: use this instead of sqlite3 + DB_PATH
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

# Support multiple admins - can be comma-separated IDs
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "1779704544")
ADMIN_IDS = set(int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip())
ADMIN_ID = next(iter(ADMIN_IDS))  # kept for backward compatibility

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_admins(bot, text: str, parse_mode: str = "Markdown"):
    """Send a message to all admins (safe if 1 fails)."""
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=aid, text=text, parse_mode=parse_mode)
        except Exception:
            pass


# ---------------- CONSTANTS ----------------
EQUIPMENTS = [
    "Basketball", "Football",
    "Badminton Items",
    "Volleyball", "Floorball items",
    "Tennis Items", "Table Tennis Items", "Frisbee", "Touch Rugby", "Softball", "Pickleball",
]

# ---------------- STATES ----------------
ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)
ASK_EQUIP, ASK_DATE, ASK_DURATION = range(10, 13)
ASK_AUNTY_LOCATION = 20
ASK_BROADCAST_MESSAGE = 30

pending_aunty_reports = {}

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
        if is_admin(user_id):
            return await func(update, context, *args, **kwargs)

        # ✅ FIX: check pending using DB-agnostic connection
        is_pending = False
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                try:
                    # Postgres: %s, SQLite: ?
                    cur.execute("SELECT 1 FROM pending_users WHERE user_id=%s", (user_id,))
                except Exception:
                    cur.execute("SELECT 1 FROM pending_users WHERE user_id=?", (user_id,))
                is_pending = cur.fetchone() is not None
        except Exception:
            # If DB is temporarily down, still block restricted actions safely
            is_pending = False

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
        BotCommand("enemyspotted", "Report Hall Aunty sighting"),

        # Admin
        BotCommand("broadcast", "Admin: Broadcast message to all users"),
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

    await notify_admins(
        context.bot,
        (
            f"🚨 *New registration request*\n"
            f"Name: {name}\n"
            f"Block: {block}\n"
            f"Room: {room}\n"
            f"User ID: `{user_id}`\n\n"
            f"/approve {user_id}  or  /reject {user_id}"
        ),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


@restricted
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
        "*👤 User Commands:*\n\n"
        "`/start` — Welcome message\n"
        "`/register` — Register yourself in the bot\n"
        "`/book` — Request to book sports equipment\n"
        "`/food` — Find supper and food options\n"
        "`/groups` — View Hall 5 group links\n"
        "`/committees` — View Hall V committees\n"
        "`/enemyspotted` — Report Hall Aunty sighting\n"
        "`/cancel` — Cancel an ongoing process\n"
    )
    if is_admin(uid):
        text += (
            "\n*🔑 Admin Commands:*\n\n"
            "*User Management:*\n"
            "`/pending` — View pending registrations\n"
            "`/approve <user_id>` — Approve a pending user\n"
            "`/reject <user_id>` — Reject a pending user\n"
            "`/remove <user_id>` — Remove a registered user\n"
            "`/export` — Export registered users to Excel\n"
            "`/export_pending` — Export pending users to Excel\n\n"
            "*Booking Management:*\n"
            "`/booking_pending` — View pending bookings\n"
            "`/booking_approve <booking_id>` — Approve a booking\n"
            "`/booking_reject <booking_id>` — Reject a booking\n"
            "`/daily_bookings` — View today's approved bookings\n"
            "`/all_daily_bookings` — View all today's bookings\n"
            "`/broadcast` — Broadcast message to all users\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- FOOD ----------------
CANTEEN_MENUS = {
    "canteen_1": {"name": "🏫 Canteen 1", "food": ["Japanese Curry Rice", "Mala", "Vietnamese Cusine", "Mixed Rice"]},
    "canteen_2": {"name": "🏫 Canteen 2", "food": ["Western", "Abang Dol", "Chicken Rice", "Mini Wok", "Pasta", "Snail Noodles", "Japanese and Korean Stall", "Caifan"]},
    "canteen_4": {"name": "🏫 Canteen 4", "food": ["Hot Pot", "Chicken Rice", "Flapjack + waffle + Drink stall"]},
    "crespion": {"name": "☕ Crespion", "food": ["Caifan", "Thai", "Dingo", "Ban Mian", "Fusion Bowl", "Indian Stall", "Mr Pasta", "Mala", "Tealer BBT", "Drink and Waffle store"]},
    "south_spine": {"name": "🍽️ South Spine", "food": ["Ban Mian", "Chicken Rice", "Drink Stall", "Caifan", "La Mian/ Xiao Long Bao", "Mala", "Rice Noodle"]},
}

COMMITTEES = {
    "JCRC": {"description": "Hall Council\n\nThe heart of Hall V, Hall Council plans major events and initiatives to make hall life vibrant, inclusive, and unforgettable.", "photo_url": "https://drive.google.com/uc?export=view&id=1Ah45TyWq6cfQX6Y7-rEj-7IeW5SXKJJP"},
    "TYH": {"description": "Twenty-One Young Hearts (TYH)\n\nHall V's community service committee planning meaningful service projects.", "photo_url": "https://drive.google.com/uc?export=view&id=1aLkv-e3MrB56yEPoT9vCcuOJktUuAkQh"},
    "HAVOC": {"description": "HAVOC (Hall Orientation Committee)\n\nRuns Hall V orientation and welcomes freshies.", "photo_url": "https://drive.google.com/uc?export=view&id=1FSa71k0UL-twfddQuufl1Z-E1P4i_47D"},
    "HAPZ": {"description": "HAPZ (Hall Anniversary Party Committee)\n\nOrganises Hall V's major celebrations like Seniors' Farewell and D&D.", "photo_url": "https://drive.google.com/uc?export=view&id=135sgG29JZu-r9WQdNKkDff_8Jf5Peztz"},
    "Quindance": {"description": "QuinDanze\n\nHall V’s dance family — all styles, all levels.", "photo_url": "https://drive.google.com/uc?export=view&id=1qNjutTjEGNpougxl-DAgnHDhiPEGf5X-"},
    "Quinstical Productions": {"description": "Quintsical Productions (QP)\n\nFilm & media crew — shoot, edit, act, create.", "photo_url": "https://drive.google.com/uc?export=view&id=1Ly9cRfUhWWajYrHZ_fpQ3bo3k746Lts7"},
    "Vikings": {"description": "Vikings\n\nHall V’s cheerleading team bringing energy to every event.", "photo_url": "https://via.placeholder.com/400x300?text=Vikings"},
    "Jamband": {"description": "Jamband\n\nHall V’s music crew — jam sessions, workshops, performances.", "photo_url": "https://drive.google.com/uc?export=view&id=1lpSij_B0fTYrbJ_jPw3ZrAkhECrKRtlC"},
    "SPOREC": {"description": "SPOREC\n\nSports & recreation committee running games and sports events.", "photo_url": "https://drive.google.com/uc?export=view&id=1hotBBzsWFm7marCS6Yp-7h_DfotSwy5X"},
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
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "*🏛️ HALL V GROUP CHATS TO JOIN!*\n\n"
        "*ANNOUNCEMENTS:*\n"
        "[Announcements](https://t.me/+wNb72ZmYBPVlYjI1)\n\n"
        "*BLOCK CHATS:*\n"
        "💜 [Purple Block (Block 28)](https://t.me/+YLowJE5pAI4zYWNl)\n"
        "🧡 [Orange Block (Block 29)](https://t.me/+KcGB8uMeP8ZmZTE1)\n"
        "💙 [Blue Block (Block 30)](https://t.me/+lK95Tc_NFgc4OTBl)\n"
        "💚 [Green Block (Block 31)](https://t.me/+0rHuc8UPaY01ZWY1)\n\n"
        "*HALL V SPORTS FANATICS:*\n"
        "[Sports Fanatics](https://t.me/+urn2-hrYt-A2OWY1)\n\n"
        "*HALL V SPORTS:*\n"
        "[Sports Activities](https://linktr.ee/HALLVSPORTS)\n\n"
        "*HALL V RECREATIONAL GAMES:*\n"
        "[Recreational Games](https://linktr.ee/HALLVREC)"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


async def show_committees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("JCRC", callback_data="JCRC"), InlineKeyboardButton("TYH", callback_data="TYH")],
        [InlineKeyboardButton("HAVOC", callback_data="HAVOC"), InlineKeyboardButton("HAPZ", callback_data="HAPZ")],
        [InlineKeyboardButton("Quindance", callback_data="Quindance"),
         InlineKeyboardButton("Quinstical Productions", callback_data="Quinstical Productions")],
        [InlineKeyboardButton("Vikings", callback_data="Vikings"), InlineKeyboardButton("Jamband", callback_data="Jamband")],
        [InlineKeyboardButton("SPOREC", callback_data="SPOREC")],
    ]
    await update.message.reply_text("Select a committee:", reply_markup=InlineKeyboardMarkup(keyboard))


# ---------- ENEMY SPOTTED --------
@restricted
async def enemy_spotted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👀 Where is Hall Aunty? Please describe the location or area:")
    return ASK_AUNTY_LOCATION


async def aunty_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location_msg = update.message.text

    report_id = f"aunty_{user.id}_{datetime.utcnow().timestamp()}"
    pending_aunty_reports[report_id] = {
        "location": location_msg,
        "reporter_id": user.id,
        "reporter_name": user.full_name or "Unknown",
    }

    keyboard = [[
        InlineKeyboardButton("✅ Broadcast", callback_data=f"broadcast_aunty_{report_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_aunty_{report_id}"),
    ]]

    admin_msg = (
        f"🚨 *Hall Aunty Spotted!*\n\n"
        f"Reporter: {pending_aunty_reports[report_id]['reporter_name']} (ID: {user.id})\n"
        f"Location: {location_msg}"
    )

    await notify_admins(context.bot, admin_msg)
    await update.message.reply_text("✅ Report sent to admin for verification!")
    return ConversationHandler.END


async def cancel_enemy_spotted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Report cancelled.")
    return ConversationHandler.END


# ---------- BROADCAST MESSAGE --------
@restricted
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return ConversationHandler.END
    await update.message.reply_text("📢 Enter the message you want to broadcast to all users:")
    return ASK_BROADCAST_MESSAGE


async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text

    users = get_registered_users()
    if not users:
        await update.message.reply_text("⚠️ No registered users to broadcast to.")
        return ConversationHandler.END

    await update.message.reply_text(f"📢 Broadcasting message to {len(users)} users...")

    sent_count = 0
    failed_count = 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=message_text, parse_mode="Markdown")
            sent_count += 1
        except Exception:
            failed_count += 1

    summary = f"✅ Broadcast complete!\n\n📬 Sent to: {sent_count} users"
    if failed_count > 0:
        summary += f"\n❌ Failed: {failed_count} users"

    await update.message.reply_text(summary)
    return ConversationHandler.END


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Broadcast cancelled.")
    return ConversationHandler.END


# ---------------- INLINE BUTTONS ----------------
@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Committee -> photo
    if query.data in COMMITTEES:
        committee = COMMITTEES[query.data]
        await query.edit_message_text("Loading committee info...")
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=committee["photo_url"],
            caption=committee["description"],
            parse_mode="Markdown",
        )
        return

    # Food menus
    if query.data in CANTEEN_MENUS:
        canteen = CANTEEN_MENUS[query.data]
        food_list = "\n".join([f"• {food}" for food in canteen["food"]])
        message = f"{canteen['name']}\n\n📋 *Food Options:*\n{food_list}"
        await query.edit_message_text(message, parse_mode="Markdown")
        return

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
            "• Kimly Dim Sum\n"
            "• Ah Long's Pancake\n"
            "• Western Food"
        ),
    }

    if query.data in responses:
        await query.edit_message_text(responses[query.data], parse_mode="Markdown")


# ---------------- MAIN ----------------
def main():
    init_db()
    init_booking_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.post_init = set_bot_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("food", food))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("groups", groups))
    app.add_handler(CommandHandler("committees", show_committees))

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

    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(CommandHandler("export_pending", export_pending))

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

    app.add_handler(CommandHandler("booking_pending", booking_pending))
    app.add_handler(CommandHandler("booking_approve", booking_approve))
    app.add_handler(CommandHandler("booking_reject", booking_reject))
    app.add_handler(CommandHandler("daily_bookings", daily_bookings_cmd))
    app.add_handler(CommandHandler("all_daily_bookings", all_daily_bookings_cmd))

    enemy_spotted_conv = ConversationHandler(
        entry_points=[CommandHandler("enemyspotted", enemy_spotted)],
        states={ASK_AUNTY_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, aunty_location_received)]},
        fallbacks=[CommandHandler("cancel", cancel_enemy_spotted)],
    )
    app.add_handler(enemy_spotted_conv)

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", start_broadcast)],
        states={ASK_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel_broadcast)],
    )
    app.add_handler(broadcast_conv)

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
