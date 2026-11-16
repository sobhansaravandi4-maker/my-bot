import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = 8818126928 # آیدی عددی خودت

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.full_name
    
    if uid == ADMIN_ID:
        await update.message.reply_text("سلام ادمین! ربات آماده است. ✅")
        return

    await update.message.reply_text("⏳ درخواست شما برای ادمین ارسال شد.")
    
    kb = [[InlineKeyboardButton("✅ تایید", callback_data=f"approve_{uid}")]]
    await context.bot.send_message(ADMIN_ID, f"👤 درخواست جدید:\nنام: {name}\nآیدی: `{uid}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID: return
    uid = int(q.data.replace("approve_", ""))
    await q.edit_message_text("✅ تایید شد.")
    await context.bot.send_message(uid, "🎉 دسترسی شما تایید شد! /start بزنید.")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(approve, pattern="^approve_"))
app.run_polling()
