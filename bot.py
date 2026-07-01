# -*- coding: utf-8 -*-
import json, logging, os
from datetime import datetime, time, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from quotes import get_daily_quote

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))
TIMEZONE  = pytz.timezone("Asia/Tehran")
DATA_FILE  = "data.json"
CHARTS_DIR = "charts"
os.makedirs(CHARTS_DIR, exist_ok=True)

REQUIRED_CHANNELS = [
    {"username": "@mohammad_yarmahmoudi",   "title": "کانال اصلی همیار"},
    {"username": "@soal_javab_yarmahmoudi", "title": "کانال سوال و جواب"},
    {"username": "@natayej_yarmahmoudi",    "title": "کانال نتایج"},
]

GRADES = ["ششم", "هفتم", "هشتم", "نهم", "دهم", "یازدهم", "کنکوری"]

STUDY_HOURS_OPTIONS = list(range(0, 13))
QUESTIONS_OPTIONS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 150]
ASK_HOURS, ASK_QUESTIONS = 1, 2

# بازه مجاز عکس صبحانه: ۵:۳۰ تا ۸:۰۰
BREAKFAST_START_H, BREAKFAST_START_M = 5, 30
BREAKFAST_END_H,   BREAKFAST_END_M   = 8, 0

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── داده ──
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"students": {}, "daily_records": {}, "pending": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_today(): return datetime.now(TIMEZONE).strftime("%Y-%m-%d")
def get_now():   return datetime.now(TIMEZONE)
def get_day_index():
    return (get_now() - datetime(2024,1,1,tzinfo=TIMEZONE)).days

def date_str(days_ago=0):
    return (get_now().date() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

# ── چک صبحانه به موقع ──
def is_breakfast_on_time(now):
    start = now.replace(hour=BREAKFAST_START_H, minute=BREAKFAST_START_M, second=0, microsecond=0)
    end   = now.replace(hour=BREAKFAST_END_H,   minute=BREAKFAST_END_M,   second=0, microsecond=0)
    return start <= now <= end

# ── منو ──
def main_menu():
    kb = [
        [KeyboardButton("📸 ارسال عکس صبحانه"), KeyboardButton("📝 ارسال گزارش شب")],
        [KeyboardButton("💬 درد و دل"), KeyboardButton("🎯 هدف هفتگی")],
        [KeyboardButton("🧮 درصد سنج"), KeyboardButton("🏅 امتیازات من")],
        [KeyboardButton("✉️ نامه به آینده"), KeyboardButton("⏰ یادم بنداز")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

# ── عضویت کانال ──
async def check_membership(user_id, bot):
    not_member = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch["username"], user_id)
            if m.status in ("left","kicked","banned"):
                not_member.append(ch)
        except Exception as e:
            logger.warning(f"چک عضویت {ch['username']}: {e}")
    return not_member

def join_keyboard():
    btns = [[InlineKeyboardButton(f"📢 {ch['title']}", url=f"https://t.me/{ch['username'].lstrip('@')}")] for ch in REQUIRED_CHANNELS]
    btns.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return InlineKeyboardMarkup(btns)

# ── انتخاب پایه ──
def grade_keyboard():
    btns = [InlineKeyboardButton(g, callback_data=f"grade_{g}") for g in GRADES]
    rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
    return InlineKeyboardMarkup(rows)

# ── چک تاخیر متوالی (۲ روز) ──
def check_late_streak(data, user_id, check_type):
    """چک می‌کنه آیا کاربر ۲ روز پشت سر هم تاخیر داشته"""
    for i in range(1, 3):
        d = date_str(i)
        rec = data["daily_records"].get(d, {}).get(user_id, {})
        item = rec.get(check_type)
        if not item or item.get("on_time", True):
            return False
    return True

# ── چک منظم بودن (۳ روز) ──
def check_consistent_streak(data, user_id):
    """چک می‌کنه آیا کاربر ۳ روز پشت سر هم هم عکس هم گزارش به موقع فرستاده"""
    for i in range(1, 4):
        d = date_str(i)
        rec = data["daily_records"].get(d, {}).get(user_id, {})
        b = rec.get("breakfast")
        r = rec.get("report")
        if not b or not r or not b.get("on_time") or not r.get("on_time"):
            return False
    return True

# ── منوی ادمین ──
def admin_menu():
    kb = [
        [KeyboardButton("📊 گزارش امروز"), KeyboardButton("👤 گزارش دانش‌آموز")],
        [KeyboardButton("🏆 رتبه‌بندی هفتگی"), KeyboardButton("📈 نمودار هفتگی")],
        [KeyboardButton("👥 لیست دانش‌آموزا"), KeyboardButton("❌ حذف دانش‌آموز")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

# ── start ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    # اگه ادمینه
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "سلام مشاور عزیز! 👋\nاز دکمه‌های پایین استفاده کن 👇",
            reply_markup=admin_menu()
        )
        return

    not_joined = await check_membership(user.id, context.bot)
    if not_joined:
        ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
        await update.message.reply_text(
            f"برای استفاده از ربات همیار باید عضو کانال‌های زیر بشی:\n\n{ch_list}\n\nبعد از عضویت دکمه «✅ عضو شدم» رو بزن.",
            reply_markup=join_keyboard()
        )
        return

    if str(user.id) in data["students"]:
        name = data["students"][str(user.id)]["name"]
        await update.message.reply_text(f"سلام {name} عزیز! 😊\nاز دکمه‌های پایین استفاده کن 👇", reply_markup=main_menu())
        return

    data["pending"][str(user.id)] = {"step": "name"}
    save_data(data)
    await update.message.reply_text("سلام! 👋 خوش اومدی.\n\nلطفاً اسم و فامیلت رو بنویس:")

# ── دریافت متن (اسم فامیل) ──
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    data = load_data()

    logger.info(f"TEXT from {user.id}: '{text}'")

    pending = data["pending"].get(str(user.id), {})

    # دکمه‌های ادمین - گزارش دانش‌آموز
    if pending.get("step") == "admin_student_report" and user.id == ADMIN_ID:
        data["pending"].pop(str(user.id), None)
        save_data(data)
        context.args = text.split()
        await cmd_student_report(update, context)
        return

    # دکمه‌های ادمین - حذف دانش‌آموز
    if pending.get("step") == "admin_remove" and user.id == ADMIN_ID:
        data["pending"].pop(str(user.id), None)
        save_data(data)
        context.args = text.split()
        await cmd_remove(update, context)
        return

    # درصد سنج - تعداد درست
    if pending.get("step") == "percent_correct":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        data["pending"][str(user.id)] = {"step": "percent_wrong", "correct": int(text)}
        save_data(data)
        await update.message.reply_text("تعداد سوالات **غلط** رو بنویس:")
        return

    # درصد سنج - تعداد غلط
    if pending.get("step") == "percent_wrong":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        correct = pending.get("correct", 0)
        wrong   = int(text)
        data["pending"][str(user.id)] = {"step": "percent_blank", "correct": correct, "wrong": wrong}
        save_data(data)
        await update.message.reply_text("تعداد سوالات **نزده** رو بنویس:")
        return

    # درصد سنج - تعداد نزده
    if pending.get("step") == "percent_blank":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        correct = pending.get("correct", 0)
        wrong   = pending.get("wrong", 0)
        blank   = int(text)
        total   = correct + wrong + blank
        data["pending"].pop(str(user.id), None)
        save_data(data)

        if total == 0:
            await update.message.reply_text("تعداد سوالات صفره! دوباره امتحان کن.", reply_markup=main_menu())
            return

        score   = correct - (wrong / 3)
        percent = (score / total) * 100

        if percent >= 70:
            emoji = "🌟"
        elif percent >= 50:
            emoji = "✅"
        elif percent >= 30:
            emoji = "⚠️"
        else:
            emoji = "❌"

        await update.message.reply_text(
            f"🧮 نتیجه درصد سنج\n\n"
            f"✅ درست: {correct}\n"
            f"❌ غلط: {wrong}\n"
            f"⬜️ نزده: {blank}\n"
            f"📊 کل: {total}\n\n"
            f"{emoji} درصد: {percent:.1f}%",
            reply_markup=main_menu()
        )
        return

    # هدف هفتگی
    if pending.get("step") == "goal":
        if len(text) < 5:
            await update.message.reply_text("هدفت رو کامل‌تر بنویس:")
            return
        data["students"][str(user.id)]["goal"]      = text
        data["students"][str(user.id)]["goal_date"] = get_today()
        data["pending"].pop(str(user.id), None)
        save_data(data)
        await update.message.reply_text(
            f"🎯 هدفت ثبت شد!\n\n«{text}»\n\n"
            "هر روز صبح یادت میندازم 💪\nبرو که میتونی! 🌟",
            reply_markup=main_menu()
        )
        return

    # درد و دل
    if pending.get("step") == "dard_del":
        data["pending"].pop(str(user.id), None)
        save_data(data)
        try:
            await update.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            update.effective_chat.id,
            "پاک شد 🍃\nسبک‌تر شدی؟ 💙",
            reply_markup=main_menu()
        )
        return

    # نامه به آینده
    if pending.get("step") == "future_letter":
        if len(text) < 5:
            await update.message.reply_text("نامه‌ات رو کامل‌تر بنویس:")
            return
        send_date = (get_now().date() + timedelta(days=30)).strftime("%Y-%m-%d")
        data["students"][str(user.id)]["future_letter"]      = text
        data["students"][str(user.id)]["future_letter_date"] = send_date
        data["pending"].pop(str(user.id), None)
        save_data(data)
        await update.message.reply_text(
            f"✉️ نامه‌ات ثبت شد!\n\n"
            f"دقیقاً یه ماه دیگه ({send_date}) تحویلت میدم 🌟",
            reply_markup=main_menu()
        )
        return

    # یادم بنداز - اسم یادآوری
    if pending.get("step") == "reminder_title":
        if len(text) < 2:
            await update.message.reply_text("اسم یادآوری رو بنویس:")
            return
        data["pending"][str(user.id)] = {"step": "reminder_day", "reminder_title": text}
        save_data(data)
        await update.message.reply_text("📅 چند روز دیگه یادآوری کنم؟", reply_markup=reminder_days_keyboard())
        return

    # ثبت اسم فامیل
    if str(user.id) not in data["students"] and pending.get("step") == "name":
        if len(text) < 3:
            await update.message.reply_text("اسم و فامیل کامل بنویس (حداقل ۳ حرف):")
            return
        data["pending"][str(user.id)] = {"step": "grade", "name": text}
        save_data(data)
        await update.message.reply_text(
            f"ممنون {text} عزیز! 🎓\n\nالان چه پایه‌ای هستی؟",
            reply_markup=grade_keyboard()
        )

# ── handler های دکمه‌های ادمین ──
async def admin_btn_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_summary(update, context)

async def admin_btn_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_ranking(update, context)

async def admin_btn_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_weekly(update, context)

async def admin_btn_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await cmd_students(update, context)

async def admin_btn_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_remove"}
    save_data(data)
    await update.message.reply_text("اسم و فامیل دانش‌آموزی که میخوای حذف کنی رو بنویس:")

async def admin_btn_student_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_student_name"}
    save_data(data)
    await update.message.reply_text("اسم و فامیل دانش‌آموز رو بنویس:")

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID: return
    text = update.message.text.strip()
    data = load_data()
    pending = data["pending"].get(str(user.id), {})

    if pending.get("step") == "admin_remove":
        data["pending"].pop(str(user.id), None)
        found_id = None
        for sid, s in data["students"].items():
            if s["name"] == text:
                found_id = sid
                break
        if not found_id:
            save_data(data)
            await update.message.reply_text(f"❌ «{text}» پیدا نشد.", reply_markup=admin_menu())
            return
        del data["students"][found_id]
        for d in data["daily_records"]:
            data["daily_records"][d].pop(found_id, None)
        save_data(data)
        await update.message.reply_text(f"✅ «{text}» حذف شد.", reply_markup=admin_menu())
        return

    if pending.get("step") == "admin_student_name":
        found_id = None
        for sid, s in data["students"].items():
            if s["name"] == text:
                found_id = sid
                break
        if not found_id:
            data["pending"].pop(str(user.id), None)
            save_data(data)
            await update.message.reply_text(f"❌ «{text}» پیدا نشد.", reply_markup=admin_menu())
            return
        data["pending"][str(user.id)] = {"step": "admin_student_period", "student_id": found_id, "student_name": text}
        save_data(data)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 هفته گذشته", callback_data="srep_week"),
            InlineKeyboardButton("🗓 ماه گذشته",  callback_data="srep_month"),
        ]])
        await update.message.reply_text(f"گزارش «{text}» رو برای چه بازه‌ای میخوای؟", reply_markup=kb)
        return

async def handle_student_report_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    if user.id != ADMIN_ID: return
    data    = load_data()
    pending = data["pending"].get(str(user.id), {})
    if pending.get("step") != "admin_student_period": return

    found_id = pending["student_id"]
    name     = pending["student_name"]
    period   = query.data
    data["pending"].pop(str(user.id), None)
    save_data(data)

    dates = week_dates() if period == "srep_week" else monthly_dates()
    title = f"📋 گزارش {'هفتگی' if period == 'srep_week' else 'ماهانه'} — {name}"
    sinfo = data["students"].get(found_id, {})
    msg   = f"{title}\n🎓 {sinfo.get('grade','')}\n" + "━"*25 + "\n\n"

    total_h = total_q = b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
    for d in dates:
        rec  = data["daily_records"].get(d, {}).get(found_id, {})
        b    = rec.get("breakfast"); r = rec.get("report")
        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌")
        r_st = f"✅ {r['time']} 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌"
        msg += f"📅 {d}\n   📸 {b_st}  📝 {r_st}\n"
        if b:
            if b["on_time"]: b_ok+=1
            else: b_late+=1
        else: b_miss+=1
        if r:
            total_h+=r.get("study_hours",0); total_q+=r.get("questions_solved",0)
            if r["on_time"]: r_ok+=1
            else: r_late+=1
        else: r_miss+=1

    msg += "\n" + "━"*25 + "\n"
    msg += f"📸 صبحانه: ✅{b_ok} ⚠️{b_late} ❌{b_miss}\n"
    msg += f"📝 گزارش: ✅{r_ok} ⚠️{r_late} ❌{r_miss}\n"
    msg += f"📚 کل: {total_h} ساعت | ✏️ {total_q} سوال"
    await query.edit_message_text(msg)

# ── انتخاب پایه ──
async def handle_grade_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    grade = query.data.replace("grade_", "")
    data  = load_data()

    pending = data["pending"].get(str(user.id), {})
    if pending.get("step") != "grade":
        return

    full_name = pending.get("name", user.full_name)
    data["students"][str(user.id)] = {
        "name":     full_name,
        "username": user.username or "",
        "joined":   get_today(),
        "grade":    grade,
    }
    data["pending"].pop(str(user.id), None)
    save_data(data)

    await query.edit_message_text(f"✅ ثبت‌نام موفق!\n\nخوش اومدی {full_name} عزیز 🎉\nپایه: {grade}")
    await query.message.reply_text("از دکمه‌های پایین استفاده کن 👇", reply_markup=main_menu())

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 شاگرد جدید:\n👤 {full_name}\n🎓 پایه: {grade}\n🆔 @{user.username or 'ندارد'}\n🔢 {user.id}"
        )
    except: pass

# ── دکمه چک عضویت ──
async def handle_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    not_joined = await check_membership(update.effective_user.id, context.bot)
    if not_joined:
        ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
        await query.edit_message_text(f"هنوز عضو نشدی:\n\n{ch_list}\n\nعضو شو و دوباره بزن.", reply_markup=join_keyboard())
    else:
        await query.edit_message_text("✅ عضویتت تأیید شد!\n\nحالا /start رو بزن.")

# ── درد و دل ──
async def btn_dard_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return
    data["pending"][str(user.id)] = {"step": "dard_del"}
    save_data(data)
    await update.message.reply_text(
        "هرچی دلت میخواد بگو 💙\n\n"
        "این پیامی که الان مینویسی هیچکسی بهش دسترسی نداره حتی خودم!\n"
        "با خیال راحت حرف بزن و ذهنتو خالی کن چون نوشتن همیشه جوابه 🌿\n\n"
        "بعدش که بفرستی سریع پاکش میکنم چون فکرات به اندازه کافی تو مغزت بودن،\nالان وقتشه کلا پاک بشن! 🍃"
    )

# ── درصد سنج ──
async def btn_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return
    data["pending"][str(user.id)] = {"step": "percent_correct"}
    save_data(data)
    await update.message.reply_text(
        "🧮 درصد سنج\n\n"
        "تعداد سوالات **درست** رو بنویس:"
    )

# ── هدف هفتگی ──
async def btn_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return

    student   = data["students"][str(user.id)]
    goal      = student.get("goal")
    goal_date = student.get("goal_date")

    if goal and goal_date:
        set_date    = datetime.strptime(goal_date, "%Y-%m-%d").date()
        days_passed = (get_now().date() - set_date).days
        if days_passed < 7:
            days_left = 7 - days_passed
            await update.message.reply_text(
                f"🎯 هدف هفتگی‌ات:\n\n«{goal}»\n\n"
                f"⏳ {days_left} روز تا پایان هفته مونده\nادامه بده قهرمان! 💪"
            )
            return

    data["pending"][str(user.id)] = {"step": "goal"}
    save_data(data)
    await update.message.reply_text(
        "🎯 هدف هفتگیت چیه؟\n\n"
        "یه هدف مشخص بنویس که این هفته میخوای بهش برسی:\n"
        "(مثلاً: ۵۰ سوال ریاضی حل کنم یا هر روز ۳ ساعت مطالعه داشته باشم)"
    )

# ── نامه به آینده ──
async def btn_future_letter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return
    data["pending"][str(user.id)] = {"step": "future_letter"}
    save_data(data)
    await update.message.reply_text(
        "✉️ نامه به آینده\n\n"
        "به یک ماه آینده خودت یه نامه بده و دقیقاً همون موقع تحویلش بگیر!\n\n"
        "نامه‌ات رو بنویس 👇"
    )

# ── امتیازات من ──
async def btn_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return

    b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
    for i in range(30):
        d   = date_str(i)
        rec = data["daily_records"].get(d, {}).get(str(user.id), {})
        b   = rec.get("breakfast")
        r   = rec.get("report")
        if b:
            if b["on_time"]: b_ok += 1
            else: b_late += 1
        else: b_miss += 1
        if r:
            if r["on_time"]: r_ok += 1
            else: r_late += 1
        else: r_miss += 1

    total_score = (b_ok * 2) + (r_ok * 2) - b_late - r_late
    if total_score >= 100:  rank = "🏆 افسانه‌ای"
    elif total_score >= 70: rank = "🌟 عالی"
    elif total_score >= 40: rank = "✅ خوب"
    elif total_score >= 20: rank = "⚠️ متوسط"
    else:                   rank = "❌ نیاز به تلاش بیشتر"

    await update.message.reply_text(
        f"🏅 امتیازات من (۳۰ روز اخیر)\n\n"
        f"📸 صبحانه:\n"
        f"   ✅ به موقع: {b_ok} روز\n"
        f"   ⚠️ با تاخیر: {b_late} روز\n"
        f"   ❌ نفرستاده: {b_miss} روز\n\n"
        f"📝 گزارش شب:\n"
        f"   ✅ به موقع: {r_ok} روز\n"
        f"   ⚠️ با تاخیر: {r_late} روز\n"
        f"   ❌ نفرستاده: {r_miss} روز\n\n"
        f"🎯 امتیاز کل: {total_score}\n"
        f"{rank}",
        reply_markup=main_menu()
    )

# ── یادم بنداز ──
async def btn_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return
    data["pending"][str(user.id)] = {"step": "reminder_title"}
    save_data(data)
    await update.message.reply_text(
        "⏰ یادم بنداز\n\n"
        "اسم یادآوری رو بنویس:\n"
        "(مثلاً: مطالعه شیمی، تکلیف ریاضی)"
    )

def reminder_days_keyboard():
    days = ["فردا", "۲ روز دیگه", "۳ روز دیگه", "یه هفته دیگه"]
    btns = [InlineKeyboardButton(d, callback_data=f"rday_{i}") for i, d in enumerate(days)]
    return InlineKeyboardMarkup([btns[:2], btns[2:]])

def reminder_hours_keyboard():
    hours = ["۷ صبح", "۹ صبح", "۱۲ ظهر", "۳ بعدازظهر", "۶ عصر", "۹ شب"]
    btns  = [InlineKeyboardButton(h, callback_data=f"rhour_{i}") for i, h in enumerate(hours)]
    return InlineKeyboardMarkup([btns[:3], btns[3:]])

REMINDER_DAYS  = [1, 2, 3, 7]
REMINDER_HOURS = [7, 9, 12, 15, 18, 21]

async def handle_reminder_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    data  = load_data()
    idx   = int(query.data.split("_")[1])
    data["pending"][str(user.id)]["days"] = REMINDER_DAYS[idx]
    save_data(data)
    await query.edit_message_text("⏰ چه ساعتی یادآوری کنم؟", reply_markup=reminder_hours_keyboard())

async def handle_reminder_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user    = update.effective_user
    data    = load_data()
    pending = data["pending"].get(str(user.id), {})
    idx     = int(query.data.split("_")[1])
    hour    = REMINDER_HOURS[idx]
    title   = pending.get("reminder_title", "یادآوری")
    days    = pending.get("days", 1)
    remind_date = (get_now().date() + timedelta(days=days)).strftime("%Y-%m-%d")

    data["students"][str(user.id)].setdefault("reminders", []).append({
        "title": title, "date": remind_date, "hour": hour, "done": False,
    })
    data["pending"].pop(str(user.id), None)
    save_data(data)

    days_labels = ["فردا", "۲ روز دیگه", "۳ روز دیگه", "یه هفته دیگه"]
    await query.edit_message_text(
        f"✅ یادآوری ثبت شد!\n\n📌 {title}\n📅 {days_labels[REMINDER_DAYS.index(days)]} ساعت {hour}:00"
    )

# ── جاب یادآوری‌ها ──
async def job_check_reminders(context: ContextTypes.DEFAULT_TYPE):
    data    = load_data()
    now     = get_now()
    today   = get_today()
    changed = False
    for sid, sinfo in data["students"].items():
        for rem in sinfo.get("reminders", []):
            if rem["done"]: continue
            if rem["date"] == today and now.hour >= rem["hour"]:
                try:
                    await context.bot.send_message(int(sid), f"⏰ یادآوری: {rem['title']}")
                    rem["done"] = True
                    changed = True
                except Exception as e:
                    logger.warning(f"یادآوری {sid}: {e}")
    if changed: save_data(data)

# ── جاب نامه به آینده ──
async def job_check_letters(context: ContextTypes.DEFAULT_TYPE):
    data    = load_data()
    today   = get_today()
    changed = False
    for sid, sinfo in data["students"].items():
        letter      = sinfo.get("future_letter")
        letter_date = sinfo.get("future_letter_date")
        if letter and letter_date and letter_date <= today:
            try:
                await context.bot.send_message(
                    int(sid),
                    f"✉️ نامه‌ای که یه ماه پیش به خودت نوشتی:\n\n«{letter}»\n\nچطوری؟ به اهدافت رسیدی؟ 🌟"
                )
                data["students"][sid].pop("future_letter", None)
                data["students"][sid].pop("future_letter_date", None)
                changed = True
            except Exception as e:
                logger.warning(f"نامه به آینده {sid}: {e}")
    if changed: save_data(data)
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return

    student = data["students"][str(user.id)]
    goal      = student.get("goal")
    goal_date = student.get("goal_date")

    if goal and goal_date:
        set_date   = datetime.strptime(goal_date, "%Y-%m-%d").date()
        days_passed = (get_now().date() - set_date).days
        if days_passed < 7:
            days_left = 7 - days_passed
            await update.message.reply_text(
                f"🎯 هدف هفتگی‌ات:\n\n«{goal}»\n\n"
                f"⏳ {days_left} روز تا پایان هفته مونده\nادامه بده قهرمان! 💪"
            )
            return

    # هدف نداره یا هفته تموم شده
    data["pending"][str(user.id)] = {"step": "goal"}
    save_data(data)
    await update.message.reply_text(
        "🎯 هدف هفتگیت چیه؟\n\n"
        "یه هدف مشخص بنویس که این هفته میخوای بهش برسی:\n"
        "(مثلاً: ۵۰ سوال ریاضی حل کنم یا هر روز ۳ ساعت مطالعه داشته باشم)"
    )
async def btn_breakfast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return
    today = get_today()
    if "breakfast" in data["daily_records"].get(today, {}).get(str(user.id), {}):
        await update.message.reply_text("✅ عکس صبحانه‌ات رو قبلاً ثبت کردم!", reply_markup=main_menu())
        return
    await update.message.reply_text("📸 عکس صبحانه‌ات رو بفرست 👇", reply_markup=main_menu())

# ── عکس صبحانه ──
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return

    now   = get_now()
    today = get_today()
    name  = data["students"][str(user.id)]["name"]

    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})

    if "breakfast" in data["daily_records"][today][str(user.id)]:
        await update.message.reply_text("✅ قبلاً ثبت کردم!", reply_markup=main_menu())
        return

    on_time = is_breakfast_on_time(now)
    data["daily_records"][today][str(user.id)]["breakfast"] = {"time": now.strftime("%H:%M"), "on_time": on_time}
    save_data(data)

    if on_time:
        await update.message.reply_text("به موقع فرستادی عزیزم ❤️", reply_markup=main_menu())
        status = "✅ به موقع"
    else:
        await update.message.reply_text("با تاخیر فرستادی، تکرارش کنی روی کل انرژیت تاثیر بد میزاره عزیزم 🙏", reply_markup=main_menu())
        status = "❌ با تاخیر"

        # چک هشدار ۲ روز تاخیر متوالی
        if check_late_streak(data, str(user.id), "breakfast"):
            await update.message.reply_text("از روند اعلام بیداریت راضی نیستم گلم 🙏\nسعی کن فردا به موقع باشی 💪")

    try:
        await context.bot.send_message(ADMIN_ID, f"📸 عکس صبحانه\n👤 {name}\n⏰ {now.strftime('%H:%M')}\n{status}")
    except: pass

# ── گزارش شب ──
def hours_kb():
    btns = [InlineKeyboardButton(str(h), callback_data=f"h_{h}") for h in STUDY_HOURS_OPTIONS]
    return InlineKeyboardMarkup([btns[i:i+4] for i in range(0,len(btns),4)])

def questions_kb():
    btns = [InlineKeyboardButton(f"+150" if q==QUESTIONS_OPTIONS[-1] else str(q), callback_data=f"q_{q}") for q in QUESTIONS_OPTIONS]
    return InlineKeyboardMarkup([btns[i:i+3] for i in range(0,len(btns),3)])

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return ConversationHandler.END
    now = get_now()
    if 0 < now.hour < 6:
        await update.message.reply_text("تاخیر داشتیا ثبت نشد.", reply_markup=main_menu())
        return ConversationHandler.END
    today = get_today()
    if "report" in data["daily_records"].get(today,{}).get(str(user.id),{}):
        await update.message.reply_text("✅ گزارش امشبت رو قبلاً ثبت کردم!", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text("📚 چند ساعت امروز مطالعه کردی؟", reply_markup=hours_kb())
    return ASK_HOURS

async def got_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["hours"] = int(query.data.split("_")[1])
    await query.edit_message_text(f"📚 {context.user_data['hours']} ساعت ثبت شد.")
    await query.message.reply_text("✏️ چند تا سوال حل کردی؟", reply_markup=questions_kb())
    return ASK_QUESTIONS

async def got_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    questions = int(query.data.split("_")[1])
    hours     = context.user_data.get("hours", 0)
    user      = update.effective_user
    now       = get_now()
    today     = get_today()
    data      = load_data()
    name      = data["students"][str(user.id)]["name"]
    q_label   = f"{questions}+" if questions==QUESTIONS_OPTIONS[-1] else str(questions)

    if 0 < now.hour < 6:
        await query.edit_message_text("تاخیر داشتیا ثبت نشد.")
        return ConversationHandler.END

    on_time = True
    data["daily_records"].setdefault(today,{})
    data["daily_records"][today].setdefault(str(user.id),{})
    data["daily_records"][today][str(user.id)]["report"] = {
        "time": now.strftime("%H:%M"), "on_time": on_time,
        "study_hours": hours, "questions_solved": questions,
    }
    save_data(data)

    await query.edit_message_text(f"✏️ {q_label} سوال ثبت شد.")
    await query.message.reply_text("خداقوت عزیزم❤️ ما حواسمون به تلاشت هست", reply_markup=main_menu())

    # چک هشدار ۲ روز تاخیر گزارش
    if check_late_streak(data, str(user.id), "report"):
        await query.message.reply_text("از روند گزارش فرستادنت راضی نیستم عزیزم 🙏\nسعی کن فردا به موقع باشی 💪")

    # چک تشویق ۳ روز منظم
    if check_consistent_streak(data, str(user.id)):
        await query.message.reply_text("آفرین! ۳ روز پشت سر هم منظم بودی! 🌟 به همین ادامه بده قهرمان!")

    try:
        await context.bot.send_message(ADMIN_ID, f"📝 گزارش شب\n👤 {name}\n📚 {hours} ساعت | ✏️ {q_label} سوال\n⏰ {now.strftime('%H:%M')}")
    except: pass
    return ConversationHandler.END

async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_menu())
    return ConversationHandler.END

# ── جاب‌ها ──
async def job_breakfast_reminder(context: ContextTypes.DEFAULT_TYPE):
    for sid in load_data()["students"]:
        try: await context.bot.send_message(int(sid), "عکس صبحانتو فرستادی واسه پشتیبانت عزیزم؟🍳")
        except Exception as e: logger.warning(f"یادآوری صبحانه {sid}: {e}")

async def job_report_reminder(context: ContextTypes.DEFAULT_TYPE):
    for sid in load_data()["students"]:
        try: await context.bot.send_message(int(sid), "گزارش کار فراموش نشه قهرمان😍")
        except Exception as e: logger.warning(f"یادآوری گزارش {sid}: {e}")

async def job_goal_reminder(context: ContextTypes.DEFAULT_TYPE):
    """یادآوری هدف هفتگی ساعت ۸:۳۰ صبح"""
    data = load_data()
    today = get_now().date()
    for sid, sinfo in data["students"].items():
        goal      = sinfo.get("goal")
        goal_date = sinfo.get("goal_date")
        if not goal or not goal_date:
            continue
        set_date    = datetime.strptime(goal_date, "%Y-%m-%d").date()
        days_passed = (today - set_date).days
        if days_passed >= 7:
            # هفته تموم شده - بگو هدف جدید تعریف کن
            try:
                await context.bot.send_message(
                    int(sid),
                    "🎯 یه هفته گذشت!\n\nوقتشه یه هدف جدید برای هفته جدید تعریف کنی 💪\nدکمه «🎯 هدف هفتگی» رو بزن."
                )
            except Exception as e:
                logger.warning(f"یادآوری هدف {sid}: {e}")
            # پاک کردن هدف قدیمی
            data["students"][sid].pop("goal", None)
            data["students"][sid].pop("goal_date", None)
        else:
            days_left = 7 - days_passed
            try:
                await context.bot.send_message(
                    int(sid),
                    f"🎯 هدف هفتگیت:\n\n«{goal}»\n\n⏳ {days_left} روز مونده! ادامه بده 💪"
                )
            except Exception as e:
                logger.warning(f"یادآوری هدف {sid}: {e}")
    save_data(data)

async def job_motivation(context: ContextTypes.DEFAULT_TYPE):
    quote = get_daily_quote(get_day_index())
    for sid in load_data()["students"]:
        try: await context.bot.send_message(int(sid), quote)
        except Exception as e: logger.warning(f"انگیزشی {sid}: {e}")

# ── ادمین: گزارش روزانه ──
def week_dates():
    today = get_now().date()
    return [(today-timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6,-1,-1)]

def monthly_dates():
    today = get_now().date()
    return [(today-timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29,-1,-1)]

async def cmd_student_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("مثال: /student علی محمدی")
        return

    target_name = " ".join(context.args).strip()
    data = load_data()

    # پیدا کردن دانش‌آموز
    found_id = None
    for sid, s in data["students"].items():
        if s["name"] == target_name:
            found_id = sid
            break

    if not found_id:
        await update.message.reply_text(f"❌ دانش‌آموزی با اسم «{target_name}» پیدا نشد.")
        return

    sinfo = data["students"][found_id]
    dates = week_dates()

    msg = (
        f"📋 گزارش هفتگی\n"
        f"👤 {sinfo['name']}\n"
        f"🎓 پایه: {sinfo.get('grade', 'نامشخص')}\n"
        f"━" * 25 + "\n\n"
    )

    total_h = total_q = b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0

    for d in dates:
        rec = data["daily_records"].get(d, {}).get(found_id, {})
        b   = rec.get("breakfast")
        r   = rec.get("report")

        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌")
        r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌"

        msg += f"📅 {d}\n   📸 {b_st}\n   📝 {r_st}\n\n"

        if b:
            if b["on_time"]: b_ok += 1
            else: b_late += 1
        else: b_miss += 1

        if r:
            total_h += r.get("study_hours", 0)
            total_q += r.get("questions_solved", 0)
            if r["on_time"]: r_ok += 1
            else: r_late += 1
        else: r_miss += 1

    msg += "━" * 25 + "\n"
    msg += f"📸 صبحانه: ✅{b_ok} ⚠️{b_late} ❌{b_miss}\n"
    msg += f"📝 گزارش: ✅{r_ok} ⚠️{r_late} ❌{r_miss}\n"
    msg += f"📚 کل مطالعه: {total_h} ساعت | ✏️ {total_q} سوال"

    await update.message.reply_text(msg)
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    data = load_data()
    today = get_today()
    records = data["daily_records"].get(today, {})

    # فیلتر پایه
    students = data["students"]
    if args:
        grade_filter = args[0]
        students = {sid: s for sid, s in students.items() if s.get("grade") == grade_filter}
        title = f"📊 گزارش امروز - پایه {grade_filter} ({today})"
    else:
        title = f"📊 گزارش امروز ({today})"

    msg = title + "\n" + "━"*25 + "\n\n"
    for sid, sinfo in students.items():
        rec = records.get(sid, {})
        b = rec.get("breakfast"); r = rec.get("report")
        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌ نفرستاده")
        r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌ نفرستاده"
        grade = sinfo.get("grade", "نامشخص")
        msg += f"👤 {sinfo['name']} ({grade})\n   📸 {b_st}\n   📝 {r_st}\n\n"

    if not students:
        msg += "کسی در این پایه ثبت‌نام نکرده."
    await update.message.reply_text(msg)

# ── handler های دکمه‌های ادمین ──
async def admin_btn_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_summary(update, context)

async def admin_btn_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_ranking(update, context)

async def admin_btn_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_weekly(update, context)

async def admin_btn_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []
    await cmd_monthly(update, context)

async def admin_btn_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await cmd_students(update, context)

async def admin_btn_student_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_student_report"}
    save_data(data)
    await update.message.reply_text("👤 اسم و فامیل دانش‌آموز رو بنویس:")

async def admin_btn_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_remove"}
    save_data(data)
    await update.message.reply_text("❌ اسم و فامیل دانش‌آموزی که میخوای حذف کنی رو بنویس:")
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    data = load_data()
    today = get_today()
    records = data["daily_records"].get(today, {})

    students = data["students"]
    if args:
        grade_filter = args[0]
        students = {sid: s for sid, s in students.items() if s.get("grade") == grade_filter}
        title = f"📊 گزارش امروز - پایه {grade_filter} ({today})"
    else:
        title = f"📊 گزارش امروز ({today})"

    msg = title + "\n" + "━"*25 + "\n\n"
    for sid, sinfo in students.items():
        rec = records.get(sid, {})
        b = rec.get("breakfast"); r = rec.get("report")
        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌ نفرستاده")
        r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌ نفرستاده"
        grade = sinfo.get("grade", "نامشخص")
        msg += f"👤 {sinfo['name']} ({grade})\n   📸 {b_st}\n   📝 {r_st}\n\n"

    if not students:
        msg += "کسی در این پایه ثبت‌نام نکرده."
    await update.message.reply_text(msg)

async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    students = data["students"]
    if not students:
        await update.message.reply_text("هنوز کسی ثبت‌نام نکرده.")
        return

    # دسته‌بندی بر اساس پایه
    by_grade = {}
    for sid, s in students.items():
        g = s.get("grade", "نامشخص")
        by_grade.setdefault(g, []).append(s["name"])

    msg = f"👥 لیست شاگردها ({len(students)} نفر)\n\n"
    for grade in GRADES + ["نامشخص"]:
        if grade in by_grade:
            msg += f"🎓 پایه {grade} ({len(by_grade[grade])} نفر):\n"
            for name in by_grade[grade]:
                msg += f"   • {name}\n"
            msg += "\n"
    await update.message.reply_text(msg)

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("مثال: /remove علی محمدی")
        return

    target_name = " ".join(context.args).strip()
    data = load_data()
    found_id = None

    for sid, s in data["students"].items():
        if s["name"] == target_name:
            found_id = sid
            break

    if not found_id:
        await update.message.reply_text(f"❌ دانش‌آموزی با اسم «{target_name}» پیدا نشد.")
        return

    del data["students"][found_id]
    # حذف از daily_records هم
    for d in data["daily_records"]:
        data["daily_records"][d].pop(found_id, None)
    save_data(data)
    await update.message.reply_text(f"✅ «{target_name}» از سیستم حذف شد.")

async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    args = context.args
    dates = week_dates()

    students = data["students"]
    if args:
        grade_filter = args[0]
        students = {sid: s for sid, s in students.items() if s.get("grade") == grade_filter}
        title = f"🏆 رتبه‌بندی هفتگی - پایه {grade_filter}"
    else:
        title = "🏆 رتبه‌بندی هفتگی"

    totals = {}
    for sid, sinfo in students.items():
        h = q = 0
        for d in dates:
            rep = data["daily_records"].get(d,{}).get(sid,{}).get("report")
            if rep: h += rep.get("study_hours",0); q += rep.get("questions_solved",0)
        totals[sid] = {"name": sinfo["name"], "grade": sinfo.get("grade",""), "hours": h, "questions": q}

    ranked = sorted(totals.values(), key=lambda t:(t["hours"],t["questions"]), reverse=True)
    medals = ["🥇","🥈","🥉"]
    msg = title + "\n" + "━"*20 + "\n\n"
    for i,t in enumerate(ranked):
        msg += f"{medals[i] if i<3 else str(i+1)+'.'} {t['name']} ({t['grade']})\n   📚 {t['hours']} ساعت  |  ✏️ {t['questions']} سوال\n\n"
    if not ranked:
        msg += "کسی در این پایه ثبت‌نام نکرده."
    await update.message.reply_text(msg)

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    args = context.args
    dates = week_dates()

    students = data["students"]
    if args:
        grade_filter = args[0]
        students = {sid: s for sid, s in students.items() if s.get("grade") == grade_filter}
        chart_title = f"Weekly Report - Grade {grade_filter}"
    else:
        chart_title = "Weekly Report - All Students"

    totals = {}
    for sid, sinfo in students.items():
        h = q = 0
        for d in dates:
            rep = data["daily_records"].get(d,{}).get(sid,{}).get("report")
            if rep: h += rep.get("study_hours",0); q += rep.get("questions_solved",0)
        totals[sid] = {"name": sinfo["name"], "hours": h, "questions": q}

    if not totals:
        await update.message.reply_text("داده‌ای برای نمایش وجود نداره.")
        return

    names=[t["name"] for t in totals.values()]; hours=[t["hours"] for t in totals.values()]; questions=[t["questions"] for t in totals.values()]
    fig,ax = plt.subplots(figsize=(max(8,len(names)*1.5),6)); x=range(len(names)); w=0.35
    b1=ax.bar([i-w/2 for i in x],hours,w,label="Study Hours",color="#4CAF50",zorder=3)
    b2=ax.bar([i+w/2 for i in x],questions,w,label="Questions Solved",color="#2196F3",zorder=3)
    for bar in list(b1)+list(b2): ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+0.3,str(int(bar.get_height())),ha="center",va="bottom",fontsize=9)
    ax.set_xticks(list(x)); ax.set_xticklabels(names,rotation=25,ha="right",fontsize=10)
    ax.set_title(chart_title,fontsize=13,fontweight="bold"); ax.legend(); ax.grid(axis="y",linestyle="--",alpha=0.5,zorder=0)
    fig.tight_layout(); path=os.path.join(CHARTS_DIR,"weekly.png"); fig.savefig(path,dpi=150); plt.close(fig)
    with open(path,"rb") as img: await update.message.reply_photo(img, caption=f"📊 {chart_title}")

async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    args = context.args
    dates = monthly_dates()

    students = data["students"]
    if args:
        grade_filter = args[0]
        students = {sid: s for sid, s in students.items() if s.get("grade") == grade_filter}
        title = f"📅 گزارش ماهانه - پایه {grade_filter}"
    else:
        title = "📅 گزارش ماهانه (۳۰ روز اخیر)"

    msg = title + "\n" + "━"*25 + "\n\n"
    for sid, sinfo in students.items():
        h = q = b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
        for d in dates:
            rec = data["daily_records"].get(d,{}).get(sid,{})
            b = rec.get("breakfast"); r = rec.get("report")
            if b:
                if b["on_time"]: b_ok+=1
                else: b_late+=1
            else: b_miss+=1
            if r:
                h += r.get("study_hours",0); q += r.get("questions_solved",0)
                if r["on_time"]: r_ok+=1
                else: r_late+=1
            else: r_miss+=1

        grade = sinfo.get("grade","")
        msg += f"👤 {sinfo['name']} ({grade})\n"
        msg += f"   📸 صبحانه: ✅{b_ok} ⚠️{b_late} ❌{b_miss}\n"
        msg += f"   📝 گزارش: ✅{r_ok} ⚠️{r_late} ❌{r_miss}\n"
        msg += f"   📚 کل مطالعه: {h} ساعت | ✏️ {q} سوال\n\n"

    if not students:
        msg += "کسی در این پایه ثبت‌نام نکرده."
    await update.message.reply_text(msg)

# ── main ──
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("student",  cmd_student_report))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("students", cmd_students))
    app.add_handler(CommandHandler("weekly",   cmd_weekly))
    app.add_handler(CommandHandler("ranking",  cmd_ranking))
    app.add_handler(CommandHandler("monthly",  cmd_monthly))
    app.add_handler(CommandHandler("remove",   cmd_remove))

    report_conv = ConversationHandler(
        entry_points=[
            CommandHandler("report", report_start),
            MessageHandler(filters.Regex("^📝 ارسال گزارش شب$"), report_start),
        ],
        states={
            ASK_HOURS:     [CallbackQueryHandler(got_hours,     pattern=r"^h_\d+$")],
            ASK_QUESTIONS: [CallbackQueryHandler(got_questions, pattern=r"^q_\d+$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_report)],
        allow_reentry=True,
    )
    app.add_handler(report_conv)

    app.add_handler(MessageHandler(filters.Regex("^📸 ارسال عکس صبحانه$"), btn_breakfast))
    app.add_handler(MessageHandler(filters.Regex("^💬 درد و دل$"), btn_dard_del))
    app.add_handler(MessageHandler(filters.Regex("^🎯 هدف هفتگی$"), btn_goal))
    app.add_handler(MessageHandler(filters.Regex("^🧮 درصد سنج$"), btn_percentage))
    app.add_handler(MessageHandler(filters.Regex("^✉️ نامه به آینده$"), btn_future_letter))
    app.add_handler(MessageHandler(filters.Regex("^🏅 امتیازات من$"), btn_score))
    app.add_handler(MessageHandler(filters.Regex("^⏰ یادم بنداز$"), btn_reminder))
    # دکمه‌های ادمین
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش امروز$"),       admin_btn_summary))
    app.add_handler(MessageHandler(filters.Regex("^👤 گزارش دانش‌آموز$"),   admin_btn_student_report))
    app.add_handler(MessageHandler(filters.Regex("^🏆 رتبه‌بندی هفتگی$"),   admin_btn_ranking))
    app.add_handler(MessageHandler(filters.Regex("^📈 نمودار هفتگی$"),      admin_btn_weekly))
    app.add_handler(MessageHandler(filters.Regex("^👥 لیست دانش‌آموزا$"),   admin_btn_students))
    app.add_handler(MessageHandler(filters.Regex("^❌ حذف دانش‌آموز$"),     admin_btn_remove))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_grade_selection,        pattern=r"^grade_"))
    app.add_handler(CallbackQueryHandler(handle_check_join,             pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(handle_reminder_day,           pattern=r"^rday_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_reminder_hour,          pattern=r"^rhour_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_student_report_period,  pattern=r"^srep_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    jq = app.job_queue
    jq.run_daily(job_breakfast_reminder, time=time(3,30,tzinfo=pytz.utc),  name="breakfast")
    jq.run_daily(job_report_reminder,    time=time(19,30,tzinfo=pytz.utc), name="report_reminder")
    jq.run_daily(job_motivation,         time=time(6,0,tzinfo=pytz.utc),   name="motivation")
    jq.run_daily(job_goal_reminder,      time=time(5,0,tzinfo=pytz.utc),   name="goal_reminder")
    jq.run_daily(job_check_letters,      time=time(5,30,tzinfo=pytz.utc),  name="letters")
    jq.run_repeating(job_check_reminders, interval=600, first=10,          name="reminders")  # هر ۱۰ دقیقه

    logger.info("✅ ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
