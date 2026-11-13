import sqlite3
import datetime
import os
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ========== تنظیمات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8080))

ADMIN_IDS = [8818126928] 
CHANNELS = [
    {"name": "آکادمی سراوندی", "link": "https://t.me/akademi_saravandi", "chat_id": "@akademi_saravandi"},
]

admin_state = {}
user_states = {}
temp_questions = {}

ROUTINES = {
    "arabic": "درک مطلب عربی",
    "gharabat": "قرابت معنایی",
    "weight": "اختیار وزنی و زبانی",
    "samii": "سماعی"
}

# ========== پایگاه داده ==========
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS attempts (user_id INTEGER, routine TEXT, used_at TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, routine TEXT, q TEXT, a TEXT, b TEXT, c TEXT, d TEXT, correct TEXT, explanation TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
cur.execute("CREATE TABLE IF NOT EXISTS countdown (chat_id TEXT, target_date TEXT, channel_msg TEXT)")
conn.commit()

def is_admin(user_id):
    return user_id in ADMIN_IDS or cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()

async def check_membership(user_id, context):
    for ch in CHANNELS:
        try:
            if (await context.bot.get_chat_member(ch["chat_id"], user_id)).status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# ========== وب‌سرور برای بیدار موندن ==========
class WebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(('0.0.0.0', PORT), WebServer)
    server.serve_forever()

# ========== شمارش معکوس ==========
async def countdown_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    for chat_id, t_str, msg in cur.execute("SELECT chat_id, target_date, channel_msg FROM countdown").fetchall():
        try:
            d = (datetime.datetime.strptime(t_str, "%Y-%m-%d").date() - today).days
            if d >= 0: await context.bot.send_message(chat_id, msg.replace("{days}", str(d)))
        except Exception as e: print(e)

# ========== منوها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    admin_state.pop(uid, None)
    if not await check_membership(uid, context):
        kb = [[InlineKeyboardButton(f"📢 {ch['name']}", url=ch["link"])] for ch in CHANNELS] + [[InlineKeyboardButton("✅ تایید", callback_data="check_join")]]
        await update.message.reply_text("⚠️ عضو شوید:", reply_markup=InlineKeyboardMarkup(kb))
        return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    kb = [[InlineKeyboardButton("🌙 درک مطلب", callback_data="routine_arabic")], [InlineKeyboardButton("🌙 قرابت", callback_data="routine_gharabat")], [InlineKeyboardButton("🌙 اختیار وزنی", callback_data="routine_weight")], [InlineKeyboardButton("🌙 سماعی", callback_data="routine_samii")]]
    if is_admin(uid): kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    if update.callback_query: await update.callback_query.edit_message_text("منو:", reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text("منو:", reply_markup=InlineKeyboardMarkup(kb))

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_membership(update.callback_query.from_user.id, context):
        await update.callback_query.message.delete()
        await show_main_menu(update, context)
    else: await update.callback_query.answer("❌ عضو نیستی!", show_alert=True)

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_state.pop(update.callback_query.from_user.id, None)
    await show_main_menu(update, context)

# ========== آزمون ==========
async def routine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); uid = q.from_user.id; r = q.data.replace("routine_", "")
    row = cur.execute("SELECT used_at FROM attempts WHERE user_id=? AND routine=? ORDER BY used_at DESC LIMIT 1", (uid, r)).fetchone()
    if row and (datetime.datetime.now() - datetime.datetime.fromisoformat(row[0])) < datetime.timedelta(hours=12):
        await q.edit_message_text("⏳ ۱۲ ساعت صبر کن.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]])); return
    rows = cur.execute("SELECT id, q, a, b, c, d, correct, explanation FROM questions WHERE routine=? ORDER BY RANDOM() LIMIT 5", (r,)).fetchall()
    if not rows: await q.edit_message_text("سوالی نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]])); return
    user_states[uid] = {"r": r, "q": rows, "i": 0, "sc": 0, "ans": []}
    await ask_q(update, context, uid)

async def ask_q(update, context, uid):
    s = user_states[uid]; d = s["q"][s["i"]]
    txt = f"سوال {s['i']+1}:\n\n{d[1]}\n\nA) {d[2]}\nB) {d[3]}\nC) {d[4]}\nD) {d[5]}"
    kb = [[InlineKeyboardButton("A", callback_data="ans_A"), InlineKeyboardButton("B", callback_data="ans_B")], [InlineKeyboardButton("C", callback_data="ans_C"), InlineKeyboardButton("D", callback_data="ans_D")]]
    if update.callback_query: await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    else: await context.bot.send_message(uid, txt, reply_markup=InlineKeyboardMarkup(kb))

async def answer_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); uid = q.from_user.id
    if uid not in user_states: return
    s = user_states[uid]; d = s["q"][s["i"]]; ua = q.data.replace("ans_", "")
    if ua == d[6]: s["sc"] += 1
    s["ans"].append({"ua": ua, "cor": d[6], "ex": d[7]}); s["i"] += 1
    if s["i"] < len(s["q"]): await ask_q(update, context, uid)
    else:
        cur.execute("INSERT INTO attempts VALUES (?,?,?)", (uid, s["r"], datetime.datetime.now().isoformat())); conn.commit()
        txt = f"✅ نمره: {s['sc']} از {len(s['q'])}\n\nپاسخنامه:\n"
        for i, a in enumerate(s["ans"]): txt += f"\n{'✅' if a['ua']==a['cor'] else '❌'} {i+1}: جواب {a['cor']}\n{a['ex']}\n"
        del user_states[uid]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]]))

# ========== پنل مدیریت ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    admin_state.pop(q.from_user.id, None)
    kb = [
        [InlineKeyboardButton("➕ تست جدید (درک مطلب)", callback_data="addq_arabic")],
        [InlineKeyboardButton("➕ تست جدید (قرابت معنایی)", callback_data="addq_gharabat")],
        [InlineKeyboardButton("➕ تست جدید (اختیار وزنی)", callback_data="addq_weight")],
        [InlineKeyboardButton("➕ تست جدید (سماعی)", callback_data="addq_samii")],
        [InlineKeyboardButton("📋 حذف تست‌ها", callback_data="manage_q")],
        [InlineKeyboardButton("👤 افزودن ادمین", callback_data="add_admin")],
        [InlineKeyboardButton("⏱ شمارش معکوس", callback_data="set_countdown")],
        [InlineKeyboardButton("🔙", callback_data="back_menu")]
    ]
    await q.edit_message_text("⚙️ پنل مدیریت:", reply_markup=InlineKeyboardMarkup(kb))

async def manage_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton("درک مطلب", callback_data="delq_arabic"), InlineKeyboardButton("قرابت", callback_data="delq_gharabat")], [InlineKeyboardButton("وزنی", callback_data="delq_weight"), InlineKeyboardButton("سماعی", callback_data="delq_samii")], [InlineKeyboardButton("🔙", callback_data="admin_panel")]]
    await q.edit_message_text("بخش:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_q_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); r = q.data.replace("delq_", ""); rows = cur.execute("SELECT id, q FROM questions WHERE routine=?", (r,)).fetchall()
    if not rows: await q.edit_message_text("خالیه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_q")]])); return
    kb = [[InlineKeyboardButton(f"❌ {i}", callback_data=f"del_q_{i}")] for i, t in rows[:10]] + [[InlineKeyboardButton("🔙", callback_data="manage_q")]]
    await q.edit_message_text("لیست تست‌ها:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); cur.execute("DELETE FROM questions WHERE id=?", (int(q.data.replace("del_q_", "")),)); conn.commit()
    await q.edit_message_text("✅ حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_q")]]))

async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_state[update.callback_query.from_user.id] = {"step": "add_admin"}
    await update.callback_query.edit_message_text("آیدی عددی ادمین جدید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

async def set_countdown_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_state[update.callback_query.from_user.id] = {"step": "cd_chat"}
    await update.callback_query.edit_message_text("آیدی کانال:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in admin_state: return
    s = admin_state[uid]; step = s["step"]; t = update.message.text
    if step == "add_admin":
        try: cur.execute("INSERT OR IGNORE INTO admins VALUES (?)", (int(t),)); conn.commit(); await update.message.reply_text("✅ ادمین اضافه شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]])); del admin_state[uid]
        except: await update.message.reply_text("❌ عدد بفرست:")
    elif step == "cd_chat": s["chat_id"] = t; s["step"] = "cd_date"; await update.message.reply_text("تاریخ (YYYY-MM-DD):")
    elif step == "cd_date": s["target_date"] = t; s["step"] = "cd_msg"; await update.message.reply_text("متن (جای روزها {days}):")
    elif step == "cd_msg": cur.execute("INSERT INTO countdown VALUES (?,?,?)", (s["chat_id"], s["target_date"], t)); conn.commit(); await update.message.reply_text("✅ تنظیم شد!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]])); del admin_state[uid]
    elif step == "q": temp_questions.setdefault(uid, {})["q"] = t; s["step"] = "a"; await update.message.reply_text("گزینه A:")
    elif step == "a": temp_questions[uid]["a"] = t; s["step"] = "b"; await update.message.reply_text("گزینه B:")
    elif step == "b": temp_questions[uid]["b"] = t; s["step"] = "c"; await update.message.reply_text("گزینه C:")
    elif step == "c": temp_questions[uid]["c"] = t; s["step"] = "d"; await update.message.reply_text("گزینه D:")
    elif step == "d": temp_questions[uid]["d"] = t; s["step"] = "correct"; await update.message.reply_text("گزینه صحیح:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data="setcor_A"), InlineKeyboardButton("B", callback_data="setcor_B")], [InlineKeyboardButton("C", callback_data="setcor_C"), InlineKeyboardButton("D", callback_data="setcor_D")]]))
    elif step == "exp":
        temp_questions[uid]["exp"] = t; s["step"] = "confirm"; d = temp_questions[uid]
        await update.message.reply_text(f"پیش‌نمایش:\n{d['q']}\nA) {d['a']}\nB) {d['b']}\nC) {d['c']}\nD) {d['d']}\n✅ {d['correct']}\n📝 {d['exp']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data="save_q")], [InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; admin_state[q.from_user.id] = {"routine": q.data.replace("addq_", ""), "step": "q"}
    await q.edit_message_text("مرحله ۱: صورت سوال:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def set_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; temp_questions[q.from_user.id]["correct"] = q.data.replace("setcor_", ""); admin_state[q.from_user.id]["step"] = "exp"
    await q.edit_message_text("پاسخنامه تشریحی:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def save_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; t = temp_questions[uid]; r = admin_state[uid]["routine"]
    cur.execute("INSERT INTO questions (routine, q, a, b, c, d, correct, explanation) VALUES (?,?,?,?,?,?,?,?)", (r, t["q"], t["a"], t["b"], t["c"], t["d"], t["correct"], t["exp"])); conn.commit()
    del admin_state[uid]; del temp_questions[uid]
    await q.edit_message_text("✅ ذخیره شد!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

# ========== اجرا ==========
def main():
    # راه‌اندازی وب‌سرور در یک ترد جداگانه
    threading.Thread(target=run_web_server, daemon=True).start()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.job_queue.run_daily(countdown_job, time=datetime.time(hour=22, minute=0))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(routine_click, pattern="^routine_"))
    app.add_handler(CallbackQueryHandler(answer_click, pattern="^ans_"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(add_question_start, pattern="^addq_"))
    app.add_handler(CallbackQueryHandler(set_correct, pattern="^setcor_"))
    app.add_handler(CallbackQueryHandler(save_question, pattern="^save_q$"))
    app.add_handler(CallbackQueryHandler(back_menu, pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(manage_q, pattern="^manage_q$"))
    app.add_handler(CallbackQueryHandler(delete_q_list, pattern="^delq_"))
    app.add_handler(CallbackQueryHandler(delete_question, pattern="^del_q_"))
    app.add_handler(CallbackQueryHandler(add_admin_start, pattern="^add_admin$"))
    app.add_handler(CallbackQueryHandler(set_countdown_start, pattern="^set_countdown$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    app.run_polling()

if __name__ == "__main__":
    main()
