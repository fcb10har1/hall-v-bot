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
from functools import wraps
import sqlite3

def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        with sqlite3.connect("hall5.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM pending_users WHERE user_id = ?", (user_id,))
            is_pending = cursor.fetchone() is not None
        print(f"User {user_id} - Admin={ADMIN_ID}, Registered={is_registered(user_id)}, Pending={is_pending}")
        if user_id != ADMIN_ID and not is_registered(user_id):
            if is_pending:
                await update.message.reply_text("❌ Your registration is pending approval. Please wait.")
            else:
                await update.message.reply_text("❌ You must register first using /register.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Replace this with your Telegram user ID (check BotFather / userinfobot)
ADMIN_ID = 1779704544

init_db()

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
    ]
    await application.bot.set_my_commands(commands)


ASK_NAME, ASK_BLOCK, ASK_ROOM = range(3)


# ➡️ Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*WASSUP FIVERS !! 🎉*\n"
        "Welcome to your personal Fiver buddy to aid you in your journey in HALL V !! 🌟\n"
        "- To register please use `/register` 📅\n",
        parse_mode="Markdown"
    )


# ➡️ Register Start
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_registered(user_id):
        await update.message.reply_text("✅ You are already registered.")
        return ConversationHandler.END

    await update.message.reply_text("👋 Hi! What’s your full name?")
    return ASK_NAME

# ➡️ Ask for Block
async def ask_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text

    reply_keyboard = [["Purple", "Orange"], ["Green", "Blue"]]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "🏢 Which block are you from? Please select one:",
        reply_markup=markup
    )
    return ASK_BLOCK

# ➡️ Ask for Room
async def ask_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["block"] = update.message.text  # Corrected to save 'block'
    await update.message.reply_text("🏠 What’s your room number?")
    return ASK_ROOM


# ➡️ Save Pending User & Notify Admin
async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["name"]
    block = context.user_data["block"]
    room = update.message.text
    user_id = update.effective_user.id

    add_pending_user(user_id, name, block, room)

    await update.message.reply_text("✅ Registration request sent! Await admin approval.")

    # Notify admin
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


# ➡️ Admin: Approve User
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


# ➡️ Admin: Reject User
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


# ➡️ Admin: List Pending Users
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
        msg += f"- {user[1]}, Room {user[2]} (ID: `{user[0]}`)\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ➡️ Admin: remove current Users    
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

# ➡️ Admin: View all currently registered/pending users in excel

# helper functions
@restricted
async def export_registered_to_excel(filename="registered_users.xlsx"):
    users = get_registered_users()  # [(user_id, name, block, room)]

    if not users:
        print("No registered users found.")
        return False

    # Create a DataFrame with Block as a separate column
    df = pd.DataFrame(users, columns=["User ID", "Name", "Block", "Room"])

    df.to_excel(filename, index=False)
    print(f"Registered users saved to {filename}")
    return True

@restricted
async def export_pending_to_excel(filename="pending_users.xlsx"):
    pending_users = get_pending_users()  # [(user_id, name, block, room), ...]

    if not pending_users:
        print("No pending users found.")
        return False

    # Create a pandas DataFrame
    df = pd.DataFrame(pending_users, columns=["User ID", "Name", "Block", "Room"])

    # Export to Excel
    df.to_excel(filename, index=False)
    print(f"Pending users saved to {filename}")
    return True

# "/export"
@restricted
async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    filename = "registered_users.xlsx"
    success = export_registered_to_excel(filename)

    if not success:
        await update.message.reply_text("⚠️ No registered users found to export.")
        return

    # Send the Excel file to the admin
    with open(filename, "rb") as file:
        await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(file, filename))

# "/export_pending"
@restricted
async def export_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    filename = "pending_users.xlsx"
    success = export_pending_to_excel(filename)

    if not success:
        await update.message.reply_text("⚠️ No pending users found to export.")
        return

    # Send the Excel file to the admin
    with open(filename, "rb") as file:
        await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(file, filename))

# "/help"
@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Base help text for all users
    help_text = (
        "*Bot Commands:*\n\n"
        "👤 *For All Users:*\n"
        "`/start` — Welcome message\n"
        "`/register` — Register yourself in the bot\n"
        "`/cancel` — Cancel an ongoing registration\n"
    )

    # Add admin commands only if the user is an admin
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

# "/food" !!! need to update proper food options !!!!
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

    if query.data == "supper_nearby":
        await query.edit_message_text("🍜 Recommended Supper Spots:\n- Jurong West 505 [Route](https://www.google.com/maps/dir/?api=1&destination=1.3470,103.7035)", parse_mode="Markdown")
    elif query.data == "food_near_hall":
        await query.edit_message_text("🍛 NTU Food Near Hall:\n- North Spine Koufu [Route](https://www.google.com/maps/dir/?api=1&destination=1.3485,103.6836)", parse_mode="Markdown")
    elif query.data == "supper_channels":
        await query.edit_message_text("🔗 Supper Telegram Channels:\n- @ntusupperclub\n- @ntu_latenights")
    elif query.data == "grab_options":
        await query.edit_message_text("🍔 Popular GrabFood Picks:\n- McDonald's Jurong West\n- KFC Pioneer\n- Mr Bean NTU")

@restricted
# /groups
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "*🏛️ HALL 5 GROUP CHATS TO JOIN !*\n\n"
        "*HALL V ANNOUNCEMENTS:*\n"
        "[https://t.me/+X6aJeSaPg-JjMDI1](https://t.me/+X6aJeSaPg-JjMDI1)\n\n"

        "*BLOCK CHATS TO CONNECT WITH UR BLOCK MATES!:*\n\n"
        "*Purple Block (Block 28)💜:* [https://t.me/+YLowJE5pAI4zYWNl](https://t.me/+YLowJE5pAI4zYWNl)\n"
        "*Orange Block (Block 29)🧡:* [https://t.me/+KcGB8uMeP8ZmZTE1](https://t.me/+KcGB8uMeP8ZmZTE1)\n"
        "*Blue Block (Block 30)💙:* [https://t.me/+lK95Tc_NFgc4OTBl](https://t.me/+lK95Tc_NFgc4OTBl)\n"
        "*Green Block (Block 31)💚:* [https://t.me/+0rHuc8UPaY01ZWY1](https://t.me/+0rHuc8UPaY01ZWY1)\n\n"

        "*HALL V SPORTS FANATICS!*\n"
        "Join in for impromptu night sports sessions!:\n"
        "https://t.me/+urn2-hrYt-A2OWY1"
    )

    await update.message.reply_text(message, parse_mode="Markdown")



def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.post_init = set_bot_commands

    # Commands
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



    # Register conversation
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




