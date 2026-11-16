import sqlite3
import datetime
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import jdatetime
import hijri_converter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8080))
ADMIN_IDS = [8818126928] 

# ====== تنظیمات ظرفیت ======
MAX_CONCURRENT_USERS = 50
active_users = {} 

CHANNELS = [
    {"name": "آکادمی سراوندی", "link": "https://t.me/akademi_saravandi", "chat_id": "@akademi_saravandi"},
    {"name": "گروه آکادمی", "link": "https://t.me/Gakademi_saravandi", "chat_id": "@Gakademi_saravandi"}
]

admin_state, user_states, temp_questions = {}, {}, {}
ROUTINES = {"arabic": "درک مطلب عربی", "gharabat": "قرابت معنایی", "samii": "سماعی"}

MORNING_MSGS = ["صبح بخیر! امروز یک صفحه سفید جدید از زندگی توست. با انرژی شروع کن.", "صبح بخیر! موفقیت از لحظه‌ای شروع می‌شه که تصمیم بگیری تغییر کنی.", "صبح بخیر! تو قوی‌تر از اون چیزی هستی که فکر می‌کنی.", "صبح بخیر! هر روز یک فرصت جدید برای بهتر شدن است.", "صبح بخیر! با لبخند شروع کن، دنیا هم به روی تو لبخند می‌زند."]
NIGHT_MSGS = ["شب بخیر! امروز هر کاری کردی، تلاشت ارزشمند بود. استراحت کن.", "شب بخیر! فردا یک روز جدید و پر از فرصت‌های تازه است.", "شب بخیر! با خیال راحت بخواب، چون امروز بهترین تلاشت رو کردی.", "شب بخیر! آرامش شب، انرژی فردا رو بهت می‌ده.", "شب بخیر! از خودت و کارهای امروزت راضی باش."]

def get_daily_message(morning=True):
    day_of_year = datetime.date.today().timetuple().tm_yday
    idx = (day_of_year - 1) % len(MORNING_MSGS)
    return MORNING_MSGS[idx] if morning else NIGHT_MSGS[idx]

def get_todays_date_info():
    today = datetime.date.today()
    j_date = jdatetime.date.fromgregorian(date=today)
    h_date = hijri_converter.Gregorian(today.year, today.month, today.day).to_hijri()
    return f"📅 شمسی: {j_date.strftime('%Y/%m/%d')}\n🌙 قمری: {h_date.year}/{h_date.month}/{h_date.day}\n🌍 میلادی: {today.strftime('%Y/%m/%d')}"

class WebServer(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is alive!")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self, format, *args): pass
def run_web_server(): HTTPServer(('0.0.0.0', PORT), WebServer).serve_forever()

conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS attempts (user_id INTEGER, routine TEXT, used_at TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, routine TEXT, q TEXT, a TEXT, b TEXT, c TEXT, d TEXT, correct TEXT, explanation TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, perms TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS countdown (chat_id TEXT, target_date TEXT, channel_msg TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS join_channels (name TEXT, link TEXT, chat_id TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, name TEXT)") 
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)") 
conn.commit()

if cur.execute("SELECT COUNT(*) FROM join_channels").fetchone()[0] == 0:
    for ch in CHANNELS: cur.execute("INSERT INTO join_channels VALUES (?, ?, ?)", (ch["name"], ch["link"], ch["chat_id"]))
    conn.commit()
if cur.execute("SELECT COUNT(*) FROM settings WHERE key='auto_msg'").fetchone()[0] == 0:
    cur.execute("INSERT INTO settings VALUES ('auto_msg', 'on')")
    conn.commit()

def get_join_channels(): return cur.execute("SELECT name, link, chat_id FROM join_channels").fetchall()
def is_admin(user_id): return user_id in ADMIN_IDS or cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None
def get_all_admins(): return list(set([ADMIN_IDS[0]] + [r[0] for r in cur.execute("SELECT user_id FROM admins").fetchall()]))
def get_user_status(user_id):
    row = cur.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else "none"
def has_perm(user_id, perm):
    if user_id in ADMIN_IDS: return True
    row = cur.execute("SELECT perms FROM admins WHERE user_id=?", (user_id,)).fetchone()
    return row and row[0] and perm in row[0].split(",")
def is_auto_msg_on(): return cur.execute("SELECT value FROM settings WHERE key='auto_msg'").fetchone()[0] == "on"

async def check_membership(user_id, context):
    for name, link, chat_id in get_join_channels():
        try:
            if (await context.bot.get_chat_member(chat_id, user_id)).status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

def clean_inactive_users():
    while True:
        now = time.time()
        to_remove = [uid for uid, start_t in active_users.items() if now - start_t > 600]
        for uid in to_remove: del active_users[uid]
        time.sleep(60)

async def send_morning(context: ContextTypes.DEFAULT_TYPE):
    if not is_auto_msg_on(): return
    msg = get_daily_message(True) + "\n\n" + get_todays_date_info()
    for name, link, chat_id in get_join_channels():
        try: await context.bot.send_message(chat_id=chat_id, text=msg)
        except: pass
    for row in cur.execute("SELECT user_id FROM users WHERE status='approved'").fetchall():
        try: await context.bot.send_message(row[0], msg)
        except: pass

async def send_night(context: ContextTypes.DEFAULT_TYPE):
    if not is_auto_msg_on(): return
    msg = get_daily_message(False) + "\n\n" + get_todays_date_info()
    for name, link, chat_id in get_join_channels():
        try: await context.bot.send_message(chat_id=chat_id, text=msg)
        except: pass
    for row in cur.execute("SELECT user_id FROM users WHERE status='approved'").fetchall():
        try: await context.bot.send_message(row[0], msg)
        except: pass

async def countdown_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    for chat_id, t_str, msg in cur.execute("SELECT chat_id, target_date, channel_msg FROM countdown").fetchall():
        try:
            d = (datetime.datetime.strptime(t_str, "%Y-%m-%d").date() - today).days
            if d >= 0: await context.bot.send_message(chat_id, msg.replace("{days}", str(d)))
        except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; admin_state.pop(uid, None)
    if is_admin(uid): await show_main_menu(update, context); return
    if not await check_membership(uid, context):
        kb = [[InlineKeyboardButton(f"📢 {ch[0]}", url=ch[1])] for ch in get_join_channels()] + [[InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")]]
        await update.message.reply_text("⚠️ ابتدا در کانال و گروه زیر عضو شوید:", reply_markup=InlineKeyboardMarkup(kb)); return
    status = get_user_status(uid)
    if status == "approved": await show_main_menu(update, context)
    elif status == "pending": await update.message.reply_text("⏳ درخواست شما قبلاً ارسال شده. منتظر تایید باشید.")
    else: await update.message.reply_text("⚠️ برای ارسال درخواست، روی /start بزنید.")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    kb = [[InlineKeyboardButton("🌙 درک مطلب", callback_data="routine_arabic")], [InlineKeyboardButton("🌙 قرابت", callback_data="routine_gharabat")], [InlineKeyboardButton("🌙 سماعی", callback_data="routine_samii")]]
    if is_admin(uid): kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    if update.callback_query: await update.callback_query.edit_message_text("یک روتین انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text("یک روتین انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id
    if await check_membership(uid, context):
        await q.message.delete(); status = get_user_status(uid)
        if status == "approved": await show_main_menu(update, context); return
        if status == "pending": await q.message.reply_text("⏳ درخواست شما در انتظار تایید است."); return
        cur.execute("INSERT OR REPLACE INTO users VALUES (?, 'pending', ?)", (uid, q.from_user.full_name)); conn.commit()
        await q.message.reply_text("✅ درخواست شما ارسال شد. منتظر تایید ادمین باشید.")
        kb = [[InlineKeyboardButton("✅ تایید", callback_data=f"approve_{uid}"), InlineKeyboardButton("❌ رد", callback_data=f"reject_{uid}")]]
        for adm in get_all_admins():
            try: await context.bot.send_message(adm, f"👤 درخواست جدید:\nنام: {q.from_user.full_name}\nآیدی: `{uid}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            except: pass
    else: await q.answer("❌ هنوز عضو نشدی!", show_alert=True)

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_state.pop(update.callback_query.from_user.id, None); await show_main_menu(update, context)

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_students"): return
    action, uid = q.data.split("_"); uid = int(uid)
    if action == "approve":
        cur.execute("UPDATE users SET status='approved' WHERE user_id=?", (uid,)); conn.commit()
        await q.edit_message_text("✅ تایید شد.")
        try: await context.bot.send_message(uid, "🎉 دسترسی شما تایید شد! /start بزنید.")
        except: pass
    elif action == "reject":
        cur.execute("UPDATE users SET status='none' WHERE user_id=?", (uid,)); conn.commit()
        await q.edit_message_text("❌ رد شد.")

async def routine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); uid = q.from_user.id; r = q.data.replace("routine_", "")
    if not is_admin(uid) and get_user_status(uid) != "approved": await q.answer("⏳ تایید نشدی!", show_alert=True); return
    
    clean_inactive_users()
    if not is_admin(uid) and uid not in active_users:
        if len(active_users) >= MAX_CONCURRENT_USERS:
            await q.answer("⚠️ ظرفیت ربات در حال حاضر تکمیل است. لطفاً چند دقیقه دیگر مراجعه کنید.", show_alert=True); return
        active_users[uid] = time.time()

    row = cur.execute("SELECT used_at FROM attempts WHERE user_id=? AND routine=? ORDER BY used_at DESC LIMIT 1", (uid, r)).fetchone()
    if row and (datetime.datetime.now() - datetime.datetime.fromisoformat(row[0])) < datetime.timedelta(hours=12):
        await q.edit_message_text("⏳ ۱۲ ساعت صبر کن.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]]))
        if uid in active_users: del active_users[uid]
        return
    rows = cur.execute("SELECT id, q, a, b, c, d, correct, explanation FROM questions WHERE routine=? ORDER BY RANDOM() LIMIT 5", (r,)).fetchall()
    if not rows: 
        await q.edit_message_text("سوالی نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]]))
        if uid in active_users: del active_users[uid]
        return
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
        if uid in active_users: del active_users[uid]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back_menu")]]))

# ====== پنل مدیریت ======
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    admin_state.pop(q.from_user.id, None)
    uid = q.from_user.id
    kb = []
    if has_perm(uid, "manage_tests"):
        kb.extend([[InlineKeyboardButton("➕ تست جدید (درک مطلب)", callback_data="addq_arabic")], [InlineKeyboardButton("➕ تست جدید (قرابت معنایی)", callback_data="addq_gharabat")], [InlineKeyboardButton("➕ تست جدید (سماعی)", callback_data="addq_samii")], [InlineKeyboardButton("📋 حذف تست‌ها", callback_data="manage_q")]])
    if has_perm(uid, "manage_admins"): kb.append([InlineKeyboardButton("👤 مدیریت ادمین‌ها", callback_data="manage_admins")])
    if has_perm(uid, "manage_students"): kb.append([InlineKeyboardButton("🎓 مدیریت دانش‌آموزان", callback_data="manage_users")])
    if has_perm(uid, "manage_channels"): kb.append([InlineKeyboardButton("🔗 مدیریت کانال‌ها", callback_data="manage_join")])
    if has_perm(uid, "manage_broadcast"):
        status = "روشن ✅" if is_auto_msg_on() else "خاموش ❌"
        kb.append([InlineKeyboardButton(f"📢 ارسال خودکار صبح/شب: {status}", callback_data="toggle_auto_msg")])
    if has_perm(uid, "manage_countdown"): kb.append([InlineKeyboardButton("⏱ شمارش معکوس", callback_data="set_countdown")])
    kb.append([InlineKeyboardButton("🔙", callback_data="back_menu")])
    await q.edit_message_text("⚙️ پنل مدیریت:", reply_markup=InlineKeyboardMarkup(kb))

async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_admins"): return
    kb = [[InlineKeyboardButton("➕ افزودن ادمین", callback_data="add_admin")], [InlineKeyboardButton("📋 لیست ادمین‌ها", callback_data="list_admins")], [InlineKeyboardButton("🔙", callback_data="admin_panel")]]
    await q.edit_message_text("مدیریت ادمین‌ها:", reply_markup=InlineKeyboardMarkup(kb))

async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_state[update.callback_query.from_user.id] = {"step": "add_admin_id"}
    await update.callback_query.edit_message_text("آیدی عددی ادمین جدید را بفرستید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_admins")]]))

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    admins = cur.execute("SELECT user_id FROM admins").fetchall()
    if not admins: await q.edit_message_text("هیچ ادمین اضافه‌ای وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_admins")]])); return
    kb = [[InlineKeyboardButton(f"⚙️ تنظیمات ادمین {a[0]}", callback_data=f"edit_admin_{a[0]}")] for a in admins] + [[InlineKeyboardButton("🔙", callback_data="manage_admins")]]
    await q.edit_message_text("لیست ادمین‌ها:", reply_markup=InlineKeyboardMarkup(kb))

async def edit_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = int(q.data.replace("edit_admin_", ""))
    row = cur.execute("SELECT perms FROM admins WHERE user_id=?", (uid,)).fetchone()
    perms = row[0].split(",") if row and row[0] else []
    kb = []
    for p, label in [("manage_tests", "مدیریت تست‌ها"), ("manage_admins", "مدیریت ادمین‌ها"), ("manage_students", "مدیریت دانش‌آموزان"), ("manage_channels", "مدیریت کانال‌ها"), ("manage_broadcast", "ارسال خودکار"), ("manage_countdown", "شمارش معکوس")]:
        icon = "✅" if p in perms else "❌"
        kb.append([InlineKeyboardButton(f"{icon} {label}", callback_data=f"toggle_perm_{uid}_{p}")])
    kb.append([InlineKeyboardButton("❌ حذف ادمین", callback_data=f"deladmin_{uid}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="list_admins")])
    await q.edit_message_text(f"تنظیمات ادمین {uid}:", reply_markup=InlineKeyboardMarkup(kb))

async def toggle_perm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_")
    uid, p = int(parts[2]), parts[3]
    row = cur.execute("SELECT perms FROM admins WHERE user_id=?", (uid,)).fetchone()
    perms = row[0].split(",") if row and row[0] else []
    if p in perms: perms.remove(p)
    else: perms.append(p)
    new_perms = ",".join(perms)
    cur.execute("UPDATE admins SET perms=? WHERE user_id=?", (new_perms, uid)); conn.commit()
    await edit_admin(update, context)

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = int(q.data.replace("deladmin_", ""))
    cur.execute("DELETE FROM admins WHERE user_id=?", (uid,)); conn.commit()
    await q.edit_message_text(f"✅ ادمین {uid} حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="list_admins")]]))

async def toggle_auto_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_broadcast"): return
    new_status = "off" if is_auto_msg_on() else "on"
    cur.execute("UPDATE settings SET value=? WHERE key='auto_msg'", (new_status,)); conn.commit()
    await admin_panel(update, context)

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_students"): return
    users = cur.execute("SELECT user_id, name FROM users WHERE status='approved'").fetchall()
    if not users: await q.edit_message_text("هیچ دانش‌آموزی تایید نشده.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]])); return
    kb = [[InlineKeyboardButton(f"🚫 قطع دسترسی {u[1]}", callback_data=f"deluser_{u[0]}")] for u in users] + [[InlineKeyboardButton("🔙", callback_data="admin_panel")]]
    await q.edit_message_text("لیست دانش‌آموزان:", reply_markup=InlineKeyboardMarkup(kb))

async def del_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_students"): return
    uid = int(q.data.replace("deluser_", ""))
    cur.execute("UPDATE users SET status='none' WHERE user_id=?", (uid,)); conn.commit()
    await q.edit_message_text(f"✅ دسترسی کاربر {uid} قطع شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_users")]]))

async def manage_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_channels"): return
    kb = [[InlineKeyboardButton("➕ افزودن کانال/گروه جدید", callback_data="add_join_channel")], [InlineKeyboardButton("🔙", callback_data="admin_panel")]]
    await q.edit_message_text("مدیریت کانال‌ها:", reply_markup=InlineKeyboardMarkup(kb))

async def add_join_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_perm(update.callback_query.from_user.id, "manage_channels"): return
    admin_state[update.callback_query.from_user.id] = {"step": "join_name"}
    await update.callback_query.edit_message_text("۱. اسم دکمه:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_panel")]]))

async def manage_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_tests"): return
    kb = [[InlineKeyboardButton("درک مطلب", callback_data="delq_arabic"), InlineKeyboardButton("قرابت", callback_data="delq_gharabat"), InlineKeyboardButton("سماعی", callback_data="delq_samii")], [InlineKeyboardButton("🔙", callback_data="admin_panel")]]
    await q.edit_message_text("بخش:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_q_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_tests"): return
    r = q.data.replace("delq_", ""); rows = cur.execute("SELECT id, q FROM questions WHERE routine=?", (r,)).fetchall()
    if not rows: await q.edit_message_text("خالیه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_q")]])); return
    kb = [[InlineKeyboardButton(f"❌ {i}", callback_data=f"del_q_{i}")] for i, t in rows[:10]] + [[InlineKeyboardButton("🔙", callback_data="manage_q")]]
    await q.edit_message_text("لیست تست‌ها:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not has_perm(q.from_user.id, "manage_tests"): return
    cur.execute("DELETE FROM questions WHERE id=?", (int(q.data.replace("del_q_", "")),)); conn.commit()
    await q.edit_message_text("✅ حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_q")]]))

async def set_countdown_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_perm(update.callback_query.from_user.id, "manage_countdown"): return
    admin_state[update.callback_query.from_user.id] = {"step": "cd_chat"}
    await update.callback_query.edit_message_text("آیدی کانال:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not has_perm(q.from_user.id, "manage_tests"): return
    admin_state[q.from_user.id] = {"routine": q.data.replace("addq_", ""), "step": "q"}
    await q.edit_message_text("مرحله ۱: صورت سوال:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def set_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    temp_questions[q.from_user.id]["correct"] = q.data.replace("setcor_", "")
    admin_state[q.from_user.id]["step"] = "exp"
    await q.edit_message_text("پاسخنامه تشریحی:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def save_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id; t = temp_questions[uid]; r = admin_state[uid]["routine"]
    cur.execute("INSERT INTO questions (routine, q, a, b, c, d, correct, explanation) VALUES (?,?,?,?,?,?,?,?)", (r, t["q"], t["a"], t["b"], t["c"], t["d"], t["correct"], t["exp"])); conn.commit()
    del admin_state[uid]; del temp_questions[uid]
    await q.edit_message_text("✅ ذخیره شد!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in admin_state: return
    s = admin_state[uid]; step = s["step"]; t = update.message.text
    if step == "add_admin_id":
        try:
            new_id = int(t)
            s["new_admin_id"] = new_id; s["step"] = "add_admin_perms"; s["new_perms"] = []
            kb = []
            for p, label in [("manage_tests", "مدیریت تست‌ها"), ("manage_admins", "مدیریت ادمین‌ها"), ("manage_students", "مدیریت دانش‌آموزان"), ("manage_channels", "مدیریت کانال‌ها"), ("manage_broadcast", "ارسال خودکار"), ("manage_countdown", "شمارش معکوس")]:
                kb.append([InlineKeyboardButton(f"❌ {label}", callback_data=f"set_new_perm_{p}")])
            kb.append([InlineKeyboardButton("✅ ثبت ادمین", callback_data="confirm_new_admin")])
            await update.message.reply_text("دسترسی‌ها را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        except: await update.message.reply_text("❌ عدد بفرست:")
    elif step == "join_name": s["name"] = t; s["step"] = "join_link"; await update.message.reply_text("۲. لینک:")
    elif step == "join_link": s["link"] = t; s["step"] = "join_id"; await update.message.reply_text("۳. آیدی:")
    elif step == "join_id": cur.execute("INSERT INTO join_channels VALUES (?, ?, ?)", (s["name"], s["link"], t)); conn.commit(); await update.message.reply_text("✅ اضافه شد!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]])); del admin_state[uid]
    elif step == "cd_chat": s["chat_id"] = t; s["step"] = "cd_date"; await update.message.reply_text("تاریخ (YYYY-MM-DD):")
    elif step == "cd_date": s["target_date"] = t; s["step"] = "cd_msg"; await update.message.reply_text("متن (با {days}):")
    elif step == "cd_msg": cur.execute("INSERT INTO countdown VALUES (?,?,?)", (s["chat_id"], s["target_date"], t)); conn.commit(); await update.message.reply_text("✅ تنظیم شد!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]])); del admin_state[uid]
    elif step == "q": temp_questions.setdefault(uid, {})["q"] = t; s["step"] = "a"; await update.message.reply_text("گزینه A:")
    elif step == "a": temp_questions[uid]["a"] = t; s["step"] = "b"; await update.message.reply_text("گزینه B:")
    elif step == "b": temp_questions[uid]["b"] = t; s["step"] = "c"; await update.message.reply_text("گزینه C:")
    elif step == "c": temp_questions[uid]["c"] = t; s["step"] = "d"; await update.message.reply_text("گزینه D:")
    elif step == "d": temp_questions[uid]["d"] = t; s["step"] = "correct"; await update.message.reply_text("گزینه صحیح:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data="setcor_A"), InlineKeyboardButton("B", callback_data="setcor_B")], [InlineKeyboardButton("C", callback_data="setcor_C"), InlineKeyboardButton("D", callback_data="setcor_D")]]))
    elif step == "exp":
        temp_questions[uid]["exp"] = t; s["step"] = "confirm"; d = temp_questions[uid]
        await update.message.reply_text(f"پیش‌نمایش:\n{d['q']}\nA) {d['a']}\nB) {d['b']}\nC) {d['c']}\nD) {d['d']}\n✅ {d['correct']}\n📝 {d['exp']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data="save_q")], [InlineKeyboardButton("❌ لغو", callback_data="admin_panel")]]))

async def set_new_perm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in admin_state: return
    p = q.data.replace("set_new_perm_", "")
    perms = admin_state[uid]["new_perms"]
    if p in perms: perms.remove(p)
    else: perms.append(p)
    kb = []
    for perm, label in [("manage_tests", "مدیریت تست‌ها"), ("manage_admins", "مدیریت ادمین‌ها"), ("manage_students", "مدیریت دانش‌آموزان"), ("manage_channels", "مدیریت کانال‌ها"), ("manage_broadcast", "ارسال خودکار"), ("manage_countdown", "شمارش معکوس")]:
        icon = "✅" if perm in perms else "❌"
        kb.append([InlineKeyboardButton(f"{icon} {label}", callback_data=f"set_new_perm_{perm}")])
    kb.append([InlineKeyboardButton("✅ ثبت ادمین", callback_data="confirm_new_admin")])
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))

async def confirm_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if uid not in admin_state: return
    s = admin_state[uid]
    cur.execute("INSERT OR REPLACE INTO admins VALUES (?, ?)", (s["new_admin_id"], ",".join(s.get("new_perms", [])))); conn.commit()
    del admin_state[uid]
    await q.edit_message_text(f"✅ ادمین {s['new_admin_id']} اضافه شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_panel")]]))

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=clean_inactive_users, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.job_queue.run_daily(countdown_job, time=datetime.time(hour=22, minute=0))
    app.job_queue.run_daily(send_morning, time=datetime.time(hour=3, minute=30))
    app.job_queue.run_daily(send_night, time=datetime.time(hour=18, minute=30))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(approve_user, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(routine_click, pattern="^routine_"))
    app.add_handler(CallbackQueryHandler(answer_click, pattern="^ans_"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(manage_admins, pattern="^manage_admins$"))
    app.add_handler(CallbackQueryHandler(add_admin_start, pattern="^add_admin$"))
    app.add_handler(CallbackQueryHandler(list_admins, pattern="^list_admins$"))
    app.add_handler(CallbackQueryHandler(edit_admin, pattern="^edit_admin_"))
    app.add_handler(CallbackQueryHandler(toggle_perm, pattern="^toggle_perm_"))
    app.add_handler(CallbackQueryHandler(del_admin, pattern="^deladmin_"))
    app.add_handler(CallbackQueryHandler(manage_users, pattern="^manage_users$"))
    app.add_handler(CallbackQueryHandler(del_user, pattern="^deluser_"))
    app.add_handler(CallbackQueryHandler(toggle_auto_msg, pattern="^toggle_auto_msg$"))
    app.add_handler(CallbackQueryHandler(add_question_start, pattern="^addq_"))
    app.add_handler(CallbackQueryHandler(set_correct, pattern="^setcor_"))
    app.add_handler(CallbackQueryHandler(save_question, pattern="^save_q$"))
    app.add_handler(CallbackQueryHandler(back_menu, pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(manage_q, pattern="^manage_q$"))
    app.add_handler(CallbackQueryHandler(delete_q_list, pattern="^delq_"))
    app.add_handler(CallbackQueryHandler(delete_question, pattern="^del_q_"))
    app.add_handler(CallbackQueryHandler(manage_join, pattern="^manage_join$"))
    app.add_handler(CallbackQueryHandler(add_join_channel_start, pattern="^add_join_channel$"))
    app.add_handler(CallbackQueryHandler(set_countdown_start, pattern="^set_countdown$"))
    app.add_handler(CallbackQueryHandler(set_new_perm, pattern="^set_new_perm_"))
    app.add_handler(CallbackQueryHandler(confirm_new_admin, pattern="^confirm_new_admin$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
