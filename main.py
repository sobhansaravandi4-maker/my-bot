import sqlite3
import datetime
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ========== تنظیمات ==========
# توکن اینجا نوشته نمی‌شه، Render خودش اونو به ربات می‌ده
BOT_TOKEN = os.environ.get("BOT_TOKEN", "") 
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
cur.execute("""CREATE TABLE IF NOT EXISTS attempts (
    user_id INTEGER, routine TEXT, used_at TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine TEXT, q TEXT, a TEXT, b TEXT, c TEXT, d TEXT, correct TEXT, explanation TEXT
)""")
conn.commit()

async def check_membership(user_id, context):
    for ch in CHANNELS:
        try:
            m = await context.bot.get_chat_member(ch["chat_id"], user_id)
            if m.status not in ["member", "administrator", "creator"]: return False
        except Exception: return False
    return True

# ========== منوها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    admin_state.pop(uid, None)
    if not await check_membership(uid, context):
        kb = [[InlineKeyboardButton(f"📢 {ch['name']}", url=ch["link"])] for ch in CHANNELS]
        kb.append([InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join")])
        await update.message.reply_text("⚠️ ابتدا در کانال عضو شوید:", reply_markup=InlineKeyboardMarkup(kb))
        return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🌙 درک مطلب عربی", callback_data="routine_arabic")],
        [InlineKeyboardButton("🌙 قرابت معنایی", callback_data="routine_gharabat")],
        [InlineKeyboardButton("🌙 اختیار وزنی و زبانی", callback_data="routine_weight")],
        [InlineKeyboardButton("🌙 سماعی", callback_data="routine_samii")],
    ]
    if update.effective_user.id in ADMIN_IDS:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text("یک روتین انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text("یک روتین انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_membership(q.from_user.id, context):
        await q.message.delete() 
        await show_main_menu(update, context)
    else:
        await q.answer("❌ هنوز عضو کانال نشدی!", show_alert=True)

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    admin_state.pop(q.from_user.id, None)
    await show_main_menu(update, context)

# ========== آزمون ==========
async def routine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    routine = q.data.replace("routine_", "")
    
    cur.execute("SELECT used_at FROM attempts WHERE user_id=? AND routine=? ORDER BY used_at DESC LIMIT 1", (uid, routine))
    row = cur.fetchone()
    if row:
        last = datetime.datetime.fromisoformat(row[0])
        if datetime.datetime.now() - last < datetime.timedelta(hours=12):
            remaining = 12 - (datetime.datetime.now() - last).total_seconds() / 3600
            kb = [[InlineKeyboardButton("🔙 برگشت", callback_data="back_menu")]]
            await q.edit_message_text(f"⏳ هنوز {remaining:.1f} ساعت مانده تا بتوانی دوباره این آزمون را بدهی.", reply_markup=InlineKeyboardMarkup(kb))
            return

    cur.execute("SELECT id, q, a, b, c, d, correct, explanation FROM questions WHERE routine=? ORDER BY RANDOM() LIMIT 5", (routine,))
    rows = cur.fetchall()
    if not rows:
        kb = [[InlineKeyboardButton("🔙 برگشت", callback_data="back_menu")]]
        await q.edit_message_text("هنوز سوالی برای این روتین ثبت نشده.", reply_markup=InlineKeyboardMarkup(kb))
        return

    user_states[uid] = {"routine": routine, "questions": rows, "current": 0, "score": 0, "answers": []}
    await ask_question(update, context, uid)

async def ask_question(update, context, uid):
    state = user_states[uid]
    q_data = state["questions"][state["current"]]
    q_text = f"سوال {state['current']+1} از {len(state['questions'])}:\n\n{q_data[1]}\n\nA) {q_data[2]}\nB) {q_data[3]}\nC) {q_data[4]}\nD) {q_data[5]}"
    kb = [
        [InlineKeyboardButton("A", callback_data="ans_A"), InlineKeyboardButton("B", callback_data="ans_B")],
        [InlineKeyboardButton("C", callback_data="ans_C"), InlineKeyboardButton("D", callback_data="ans_D")],
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(q_text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await context.bot.send_message(uid, q_text, reply_markup=InlineKeyboardMarkup(kb))

async def answer_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in user_states: return
    
    state = user_states[uid]
    q_data = state["questions"][state["current"]]
    user_ans = q.data.replace("ans_", "")
    
    if user_ans == q_data[6]: state["score"] += 1
    state["answers"].append({"q": q_data[1], "user_ans": user_ans, "correct": q_data[6], "explanation": q_data[7]})
    
    state["current"] += 1
    if state["current"] < len(state["questions"]):
        await ask_question(update, context, uid)
    else:
        cur.execute("INSERT INTO attempts VALUES (?,?,?)", (uid, state["routine"], datetime.datetime.now().isoformat()))
        conn.commit()
        
        res_text = f"✅ آزمون تمام شد!\n\nنمره شما: {state['score']} از {len(state['questions'])}\n\n📝 پاسخنامه تشریحی:\n"
        for i, ans in enumerate(state["answers"]):
            status = "✅" if ans["user_ans"] == ans["correct"] else "❌"
            res_text += f"\n{status} سوال {i+1}: جواب صحیح {ans['correct']}\nتوضیح: {ans['explanation']}\n"
            
        del user_states[uid]
        kb = [[InlineKeyboardButton("🔙 برگشت به منو", callback_data="back_menu")]]
        await q.edit_message_text(res_text, reply_markup=InlineKeyboardMarkup(kb))

# ========== پنل مدیریت ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id not in ADMIN_IDS: return
    admin_state.pop(q.from_user.id, None)
    
    kb = [
        [InlineKeyboardButton("➕ تست جدید (درک مطلب عربی)", callback_data="addq_arabic")],
        [InlineKeyboardButton("➕ تست جدید (قرابت معنایی)", callback_data="addq_gharabat")],
        [InlineKeyboardButton("➕ تست جدید (اختیار وزنی و زبانی)", callback_data="addq_weight")],
        [InlineKeyboardButton("➕ تست جدید (سماعی)", callback_data="addq_samii")],
        [InlineKeyboardButton("🔙 برگشت به منو", callback_data="back_menu")],
    ]
    await q.edit_message_text("⚙️ پنل مدیریت:\nیک بخش را برای افزودن تست انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id not in ADMIN_IDS: return
    
    routine = q.data.replace("addq_", "")
    admin_state[q.from_user.id] = {"routine": routine, "step": "q"}
    temp_questions[q.from_user.id] = {}
    
    kb = [[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]
    await q.edit_message_text(f"شما در حال ساخت تست برای «{ROUTINES[routine]}» هستید.\n\n📝 **مرحله ۱:**\nلطفاً **صورت سوال** را تایپ کرده و بفرستید:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in admin_state: return
    
    state = admin_state[uid]
    text = update.message.text
    step = state["step"]
    
    if step == "q":
        temp_questions[uid]["q"] = text
        state["step"] = "a"
        await update.message.reply_text("📝 **مرحله ۲:**\nگزینه **A** را بفرستید:")
    elif step == "a":
        temp_questions[uid]["a"] = text
        state["step"] = "b"
        await update.message.reply_text("📝 **مرحله ۳:**\nگزینه **B** را بفرستید:")
    elif step == "b":
        temp_questions[uid]["b"] = text
        state["step"] = "c"
        await update.message.reply_text("📝 **مرحله ۴:**\nگزینه **C** را بفرستید:")
    elif step == "c":
        temp_questions[uid]["c"] = text
        state["step"] = "d"
        await update.message.reply_text("📝 **مرحله ۵:**\nگزینه **D** را بفرستید:")
    elif step == "d":
        temp_questions[uid]["d"] = text
        state["step"] = "correct"
        kb = [
            [InlineKeyboardButton("A", callback_data="setcor_A"), InlineKeyboardButton("B", callback_data="setcor_B")],
            [InlineKeyboardButton("C", callback_data="setcor_C"), InlineKeyboardButton("D", callback_data="setcor_D")],
        ]
        await update.message.reply_text("📝 **مرحله ۶:**\nحالا روی **گزینه صحیح** کلیک کنید:", reply_markup=InlineKeyboardMarkup(kb))
    elif step == "exp":
        temp_questions[uid]["exp"] = text
        state["step"] = "confirm"
        t = temp_questions[uid]
        
        preview = (f"👀 **پیش‌نمایش تست:**\n\n"
                   f"**سوال:** {t['q']}\n\n"
                   f"A) {t['a']}\nB) {t['b']}\nC) {t['c']}\nD) {t['d']}\n\n"
                   f"✅ **گزینه صحیح:** {t['correct']}\n\n"
                   f"📝 **پاسخ تشریحی:**\n{t['exp']}")
        
        kb = [
            [InlineKeyboardButton("✅ تایید و ذخیره", callback_data="save_q")],
            [InlineKeyboardButton("❌ لغو و حذف", callback_data="admin_panel")]
        ]
        await update.message.reply_text(preview, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def set_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in admin_state: return
    
    temp_questions[uid]["correct"] = q.data.replace("setcor_", "")
    admin_state[uid]["step"] = "exp"
    
    kb = [[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]
    await q.edit_message_text("📝 **مرحله ۷:**\nحالا **پاسخنامه تشریحی** را بنویسید و بفرستید:", reply_markup=InlineKeyboardMarkup(kb))

async def save_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in admin_state or uid not in temp_questions: return
    
    t = temp_questions[uid]
    routine = admin_state[uid]["routine"]
    
    cur.execute("INSERT INTO questions (routine, q, a, b, c, d, correct, explanation) VALUES (?,?,?,?,?,?,?,?)",
                (routine, t["q"], t["a"], t["b"], t["c"], t["d"], t["correct"], t["exp"]))
    conn.commit()
    
    del admin_state[uid]
    del temp_questions[uid]
    
    kb = [[InlineKeyboardButton("🔙 برگشت به پنل", callback_data="admin_panel")]]
    await q.edit_message_text(f"✅ تست با موفقیت به «{ROUTINES[routine]}» اضافه شد!", reply_markup=InlineKeyboardMarkup(kb))

# ========== اجرا ==========
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
app.add_handler(CallbackQueryHandler(routine_click, pattern="^routine_"))
app.add_handler(CallbackQueryHandler(answer_click, pattern="^ans_"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
app.add_handler(CallbackQueryHandler(add_question_start, pattern="^addq_"))
app.add_handler(CallbackQueryHandler(set_correct, pattern="^setcor_"))
app.add_handler(CallbackQueryHandler(save_question, pattern="^save_q$"))
app.add_handler(CallbackQueryHandler(back_menu, pattern="^back_menu$"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))

app.run_polling()
