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
import pandas as pd
import tempfile
from functools import wraps
import sqlite3

# ---------------- Restriction Decorator ----------------
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        with sqlite3.connect("hall5.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM pending_users WHERE user_id = ?", (user_id,))
            is_pending = cursor.fetchone() is not None
        print(f"[LOG] User {user_id} - Admin={ADMIN_ID}, Registered={is_registered(user_id)}, Pending={is_pending}")

        if user_id != ADMIN_ID and not is_registered(user_id):
            if update.message:
                if is_pending:
                    await update.message.reply_text("❌ Your registration is pending approval. Please wait.")
                else:
                    await update.message.reply_text("❌ You must register first using /register.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ---------------- Load environment ----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 1779704544

init_db()

# ---------------- Bot Commands ----------------
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
        BotCommand("export_pending", "Admin: Export pending users")
        #BotCommand("committees", "Committees in Hall V")
        #BotCommand("bookings", "Make bookings to borrow Sports Items")
        #BotCommand("upcoming_events", "Find out about upcoming Fiver Events!")
        #BotCommand("Vstop", "Event Feedback, Lost&Found, Fault reporting, Q&A, Security Matters")
    ]
    await application.bot.set_my_commands(commands)

ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)

# ---------------- User Commands ----------------
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
    await update.message.reply_text("👋 Hi! What’s your full name?")
    return ASK_NAME

async def ask_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    reply_keyboard = [["Purple", "Orange"], ["Green", "Blue"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🏢 Which block are you from? Please select one:", reply_markup=markup)
    return ASK_BLOCK

async def ask_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["block"] = update.message.text
    await update.message.reply_text("🏠 What’s your room number? (e.g. 28-04-543)")
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
        text=(
            f"🚨 *New registration request*\n"
            f"Name: {name}\nBlock: {block}\nRoom: {room}\nUser ID: `{user_id}`\n\n"
            f"/approve {user_id} or /reject {user_id}"
        ),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Registration cancelled.")
    return ConversationHandler.END



# ---------------- Admin Commands ----------------
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

# Remove async from these helpers and keep them synchronous
def export_registered_to_excel(filename="registered_users.xlsx"):
    users = get_registered_users()
    if not users:
        return False
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])
    df.to_excel(filename, index=False)
    return True


def export_pending_to_excel(filename="pending_users.xlsx"):
    users = get_pending_users()
    if not users:
        return False
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])
    df.to_excel(filename, index=False)
    return True


# Keep these command handlers async with @restricted
@restricted
async def export(update, context):
    users = get_registered_users()
    if not users:
        await update.message.reply_text("⚠️ No registered users found to export.")
        return

    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])

    # Use a temporary file
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        df.to_excel(tmp.name, index=False)
        tmp.seek(0)  # rewind file
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=InputFile(tmp.name, filename="registered_users.xlsx")
        )


@restricted
async def export_pending(update, context):
    users = get_pending_users()
    if not users:
        await update.message.reply_text("⚠️ No pending users found to export.")
        return

    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])

    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        df.to_excel(tmp.name, index=False)
        tmp.seek(0)
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=InputFile(tmp.name, filename="pending_users.xlsx")
        )

# ---------------- Misc Commands ----------------
@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    help_text = (
        "*Bot Commands:*\n\n"
        "👤 *For All Users:*\n"
        "`/start` — Welcome message\n"
        "`/register` — Register yourself in the bot\n"
        "`/cancel` — Cancel an ongoing registration\n"
    )
    if user_id == ADMIN_ID:
        help_text += (
            "\n🔑 *Admin Commands:*\n"
            "`/approve <user_id>` — Approve a pending registration\n"
            "`/reject <user_id>` — Reject a pending registration\n"
            "`/pending` — View list of pending registrations\n"
            "`/remove <user_id>` — Remove a registered user\n"
            "`/export` — Export all registered users to Excel\n"
            "`/export_pending` — Export all pending registrations to Excel\n"
        )
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
        "grab_options": "🍔 Popular GrabFood Picks:\n- McDonald's Jurong West\n- Bai Li Xiang\n- Kimly Dim Sum"
    }
    if query.data in responses:
        await query.edit_message_text(responses[query.data], parse_mode="Markdown")

@restricted
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "*🏛️ HALL 5 GROUP CHATS TO JOIN !*\n\n"
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
        "[Recreational Games](https://linktr.ee/HALLVREC)"
    )
    await update.message.reply_text(message, parse_mode="Markdown")

#committees (working on it)
async def committees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    responses = {
        "JCRC": "🍜 Recommended Supper Spots:\n- Extension [Route](https://maps.app.goo.gl/rZB82rqL4fhewZnL9)\n- Prata Shop nearby [Route](https://maps.app.goo.gl/qYPhyT6M5kUbgKYP8)",
        "TYH": "🍛 NTU Food Near Hall:\n- Canteen 4\n- Canteen 2\n- Canteen 1\n- Crespion\n- South Spine",
        "HAVOC": "🔗 Supper Telegram Channels:\n- https://t.me/GigabiteNTU\n- https://t.me/dingontu\n- https://t.me/urmomscooking\n- https://t.me/NomAtNTU\n- https://t.me/AnAcaiAffairXNTU",
        "HAPZ": "🍔 Popular GrabFood Picks:\n- McDonald's Jurong West\n- Bai Li Xiang\n- Kimly Dim Sum",
        "Quindance": "Hall V's talented group of dancers!",
        "Quinstical Productions": "Our very own inhouse production crew!",
        "Vikings": "HALL V Cheer !",
        "Jamband": "Jam band",
    }
    if query.data in responses:
        await query.edit_message_text(responses[query.data], parse_mode="Markdown")

#booking

#upcoming_events

#Vstop
# ---------------- Main ----------------
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
