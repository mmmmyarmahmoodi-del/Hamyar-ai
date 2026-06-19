# -*- coding: utf-8 -*-
"""
ربات مشاور تحصیلی - نسخه Railway
====================================
برای اجرا نیاز به لپ‌تاپ نیست - روی Railway اجرا می‌شه
"""

import json
import logging
import os
from datetime import datetime, time, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from quotes import get_daily_quote

# ==================== تنظیمات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID   = int(os.environ.get("ADMIN_ID", "123456789"))
TIMEZONE   = pytz.timezone("Asia/Tehran")

BREAKFAST_REMINDER_HOUR   = 8    # یادآوری صبحانه ساعت ۸
REPORT_REMINDER_HOUR      = 23   # یادآوری گزارش ساعت ۱۱ شب
MOTIVATION_HOUR           = 9    # جمله انگیزشی ساعت ۹ صبح
MOTIVATION_MINUTE         = 30

BREAKFAST_DEADLINE_HOUR   = 8    # مهلت صبحانه ساعت ۸
REPORT_DEADLINE_HOUR      = 24   # مهلت گزارش ساعت ۱۲ شب (آخر وقت)

DATA_FILE  = "data.json"
CHARTS_DIR = "charts"
os.makedirs(CHARTS_DIR, exist_ok=True)

# مرحله‌های ثبت‌نام
REG_NAME = 0

# مرحله‌های گزارش شب
ASK_HOURS, ASK_QUESTIONS = range(2)

STUDY_HOURS_OPTIONS = list(range(0, 13))          # 0 تا 12
QUESTIONS_OPTIONS   = [0, 10, 20, 30, 40, 50]     # آخری = 50+

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ==================== داده ====================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"students": {}, "daily_records": {}}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def get_now():
    return datetime.now(TIMEZONE)


def get_day_index():
    epoch = datetime(2024, 1, 1, tzinfo=TIMEZONE)
    return (get_now() - epoch).days


def is_registered(user_id: str) -> bool:
    return user_id in load_data()["students"]


# ==================== ثبت‌نام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) in data["students"]:
        await update.message.reply_text(
            f"سلام {data['students'][str(user.id)]['name']} عزیز! 😊\n\n"
            "📸 عکس صبحانه‌ات رو بفرست\n"
            "📝 برای گزارش شب دستور /report رو بزن"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "سلام! 👋 خوش اومدی.\n\n"
        "برای ثبت‌نام، لطفاً اسم و فامیلت رو بنویس:"
    )
    return REG_NAME


async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text.strip()
    user      = update.effective_user
    data      = load_data()

    if len(full_name) < 3:
        await update.message.reply_text("لطفاً اسم و فامیل کامل بنویس (حداقل ۳ حرف):")
        return REG_NAME

    data["students"][str(user.id)] = {
        "name":     full_name,
        "username": user.username or "",
        "joined":   get_today(),
    }
    save_data(data)

    await update.message.reply_text(
        f"✅ ثبت‌نام موفق!\n\n"
        f"خوش اومدی {full_name} عزیز 🎉\n\n"
        "📸 هر روز صبح قبل از ساعت ۸ عکس صبحانه‌ات رو بفرست\n"
        "📝 هر شب قبل از ۱۲ شب با /report گزارش روزانه‌ات رو بفرست\n\n"
        "موفق باشی! 🌟"
    )

    await context.bot.send_message(
        ADMIN_ID,
        f"🆕 شاگرد جدید ثبت‌نام کرد:\n"
        f"👤 نام: {full_name}\n"
        f"🆔 یوزرنیم: @{user.username or 'ندارد'}\n"
        f"🔢 آیدی: {user.id}"
    )
    return ConversationHandler.END


async def cancel_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ثبت‌نام لغو شد. هر وقت خواستی /start بزن.")
    return ConversationHandler.END


# ==================== عکس صبحانه ====================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("لطفاً اول /start رو بزن و ثبت‌نام کن.")
        return

    now   = get_now()
    today = get_today()
    name  = data["students"][str(user.id)]["name"]

    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})
    record = data["daily_records"][today][str(user.id)]

    if "breakfast" in record:
        await update.message.reply_text("✅ عکس صبحانه‌ات رو قبلاً ثبت کردم!")
        return

    on_time = now.hour < BREAKFAST_DEADLINE_HOUR
    record["breakfast"] = {
        "time":    now.strftime("%H:%M"),
        "on_time": on_time,
    }
    save_data(data)

    if on_time:
        await update.message.reply_text("به موقع فرستادی عزیزم ❤️")
        admin_status = "✅ به موقع"
    else:
        await update.message.reply_text(
            "با تاخیر فرستادی، تکرارش کنی روی کل انرژیت تاثیر بد میزاره عزیزم 🙏"
        )
        admin_status = "❌ با تاخیر"

    await context.bot.send_message(
        ADMIN_ID,
        f"📸 عکس صبحانه\n"
        f"👤 {name}\n"
        f"⏰ ساعت: {now.strftime('%H:%M')}\n"
        f"{admin_status}"
    )


# ==================== گزارش شب ====================
def hours_keyboard():
    btns = [InlineKeyboardButton(str(h), callback_data=f"h_{h}") for h in STUDY_HOURS_OPTIONS]
    rows = [btns[i:i+4] for i in range(0, len(btns), 4)]
    return InlineKeyboardMarkup(rows)


def questions_keyboard():
    btns = []
    for q in QUESTIONS_OPTIONS:
        label = f"{q}+" if q == QUESTIONS_OPTIONS[-1] else str(q)
        btns.append(InlineKeyboardButton(label, callback_data=f"q_{q}"))
    rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
    return InlineKeyboardMarkup(rows)


async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("لطفاً اول /start رو بزن و ثبت‌نام کن.")
        return ConversationHandler.END

    now   = get_now()
    # بعد از ۱۲ شب ثبت نمی‌شه
    if now.hour == 0 and now.minute > 0 or now.hour > 0 and now.hour < 6:
        await update.message.reply_text("تاخیر داشتیا ثبت نشد.")
        return ConversationHandler.END

    today  = get_today()
    record = data["daily_records"].get(today, {}).get(str(user.id), {})
    if "report" in record:
        await update.message.reply_text("✅ گزارش امشبت رو قبلاً ثبت کردم!")
        return ConversationHandler.END

    await update.message.reply_text(
        "📚 چند ساعت امروز مطالعه کردی؟",
        reply_markup=hours_keyboard()
    )
    return ASK_HOURS


async def got_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["hours"] = int(query.data.split("_")[1])
    await query.edit_message_text(f"📚 {context.user_data['hours']} ساعت ثبت شد.")
    await query.message.reply_text("✏️ چند تا سوال حل کردی؟", reply_markup=questions_keyboard())
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

    q_label = f"{questions}+" if questions == QUESTIONS_OPTIONS[-1] else str(questions)

    # چک مهلت ۱۲ شب
    # ساعت ۲۳ به بعد تا ۲۴ = on_time، بعد از نیمه شب = دیر
    on_time = not (now.hour >= 0 and now.hour < 6)  # بین نیمه شب تا ۶ صبح = دیر

    if not on_time:
        await query.edit_message_text("تاخیر داشتیا ثبت نشد.")
        return ConversationHandler.END

    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})
    data["daily_records"][today][str(user.id)]["report"] = {
        "time":             now.strftime("%H:%M"),
        "on_time":          True,
        "study_hours":      hours,
        "questions_solved": questions,
    }
    save_data(data)

    await query.edit_message_text(f"✏️ {q_label} سوال ثبت شد.")
    await query.message.reply_text("خداقوت عزیزم❤️ ما حواسمون به تلاشت هست")

    await context.bot.send_message(
        ADMIN_ID,
        f"📝 گزارش شب\n"
        f"👤 {name}\n"
        f"📚 {hours} ساعت | ✏️ {q_label} سوال\n"
        f"⏰ {now.strftime('%H:%M')}"
    )
    return ConversationHandler.END


async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("گزارش لغو شد. هر وقت خواستی /report بزن.")
    return ConversationHandler.END


# ==================== جاب‌های زمان‌بندی ====================
async def job_breakfast_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    for sid in data["students"]:
        try:
            await context.bot.send_message(int(sid), "عکس صبحانتو فرستادی واسه پشتیبانت عزیزم؟🍳")
        except Exception as e:
            logger.warning(f"یادآوری صبحانه به {sid} ناموفق: {e}")


async def job_report_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    for sid in data["students"]:
        try:
            await context.bot.send_message(int(sid), "گزارش کار فراموش نشه قهرمان😍")
        except Exception as e:
            logger.warning(f"یادآوری گزارش به {sid} ناموفق: {e}")


async def job_motivation(context: ContextTypes.DEFAULT_TYPE):
    data  = load_data()
    quote = get_daily_quote(get_day_index())
    for sid in data["students"]:
        try:
            await context.bot.send_message(int(sid), quote)
        except Exception as e:
            logger.warning(f"جمله انگیزشی به {sid} ناموفق: {e}")


# ==================== دستورات ادمین ====================
def week_dates():
    today = get_now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]


def weekly_totals(data):
    dates  = week_dates()
    result = {}
    for sid, sinfo in data["students"].items():
        h = q = 0
        for d in dates:
            rep = data["daily_records"].get(d, {}).get(sid, {}).get("report")
            if rep:
                h += rep.get("study_hours", 0)
                q += rep.get("questions_solved", 0)
        result[sid] = {"name": sinfo["name"], "hours": h, "questions": q}
    return result


async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط برای مشاور.")
        return

    data    = load_data()
    totals  = weekly_totals(data)
    if not totals:
        await update.message.reply_text("هنوز دانش‌آموزی ثبت‌نام نکرده.")
        return

    ranked  = sorted(totals.values(), key=lambda t: (t["hours"], t["questions"]), reverse=True)
    medals  = ["🥇", "🥈", "🥉"]
    msg     = "🏆 رتبه‌بندی هفتگی\n" + "━" * 20 + "\n\n"
    for i, t in enumerate(ranked):
        medal = medals[i] if i < 3 else f"{i+1}."
        msg  += f"{medal} {t['name']}\n   📚 {t['hours']} ساعت  |  ✏️ {t['questions']} سوال\n\n"

    await update.message.reply_text(msg)


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط برای مشاور.")
        return

    data   = load_data()
    totals = weekly_totals(data)
    if not totals:
        await update.message.reply_text("هنوز دانش‌آموزی ثبت‌نام نکرده.")
        return

    # رسم نمودار - متن فارسی به انگلیسی ترجمه می‌شه چون matplotlib فارسی رو بدون فونت خاص نشون نمیده
    names     = [t["name"] for t in totals.values()]
    hours     = [t["hours"] for t in totals.values()]
    questions = [t["questions"] for t in totals.values()]

    fig, ax = plt.subplots(figsize=(max(8, len(names) * 1.5), 6))
    x       = range(len(names))
    w       = 0.35

    bars1 = ax.bar([i - w/2 for i in x], hours,     w, label="Study Hours",      color="#4CAF50", zorder=3)
    bars2 = ax.bar([i + w/2 for i in x], questions, w, label="Questions Solved",  color="#2196F3", zorder=3)

    # مقدار عددی روی هر میله
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                str(int(bar.get_height())), ha="center", va="bottom", fontsize=9)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                str(int(bar.get_height())), ha="center", va="bottom", fontsize=9)

    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=25, ha="right", fontsize=10)
    ax.set_title("Weekly Report", fontsize=14, fontweight="bold")
    ax.set_ylabel("Count")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    fig.tight_layout()

    path = os.path.join(CHARTS_DIR, "weekly.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)

    with open(path, "rb") as img:
        await update.message.reply_photo(
            img,
            caption="📊 نمودار هفتگی ساعت مطالعه و تعداد سوال"
        )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط برای مشاور.")
        return

    data    = load_data()
    today   = get_today()
    records = data["daily_records"].get(today, {})
    msg     = f"📊 گزارش امروز ({today})\n" + "━" * 25 + "\n\n"

    for sid, sinfo in data["students"].items():
        rec  = records.get(sid, {})
        b    = rec.get("breakfast")
        r    = rec.get("report")

        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌ نفرستاده")
        if r:
            r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}"
        else:
            r_st = "❌ نفرستاده"

        msg += f"👤 {sinfo['name']}\n   📸 {b_st}\n   📝 {r_st}\n\n"

    await update.message.reply_text(msg)


async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط برای مشاور.")
        return

    data     = load_data()
    students = data["students"]
    if not students:
        await update.message.reply_text("هنوز کسی ثبت‌نام نکرده.")
        return

    msg = f"👥 لیست شاگردها ({len(students)} نفر)\n\n"
    for sid, s in students.items():
        msg += f"• {s['name']} | @{s.get('username','ندارد')} | از {s['joined']}\n"
    await update.message.reply_text(msg)


# ==================== اجرا ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ثبت‌نام (اسم و فامیل)
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)]},
        fallbacks=[CommandHandler("cancel", cancel_reg)],
    )
    app.add_handler(reg_conv)

    # گزارش شب
    report_conv = ConversationHandler(
        entry_points=[CommandHandler("report", report_start)],
        states={
            ASK_HOURS:     [CallbackQueryHandler(got_hours,     pattern=r"^h_\d+$")],
            ASK_QUESTIONS: [CallbackQueryHandler(got_questions, pattern=r"^q_\d+$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_report)],
    )
    app.add_handler(report_conv)

    # عکس صبحانه
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # دستورات ادمین
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("students", cmd_students))
    app.add_handler(CommandHandler("weekly",   cmd_weekly))
    app.add_handler(CommandHandler("ranking",  cmd_ranking))

    # زمان‌بندی‌ها (UTC - چون Railway روی UTC کار می‌کنه، ۳.۵ ساعت از ایران عقب‌تره)
    # ساعت ۸ ایران = ۴:۳۰ UTC
    # ساعت ۱۱ شب ایران = ۱۹:۳۰ UTC
    # ساعت ۹:۳۰ ایران = ۶:۰۰ UTC
    jq = app.job_queue
    jq.run_daily(job_breakfast_reminder, time=time(4,  30, tzinfo=pytz.utc), name="breakfast")
    jq.run_daily(job_report_reminder,    time=time(19, 30, tzinfo=pytz.utc), name="report_reminder")
    jq.run_daily(job_motivation,         time=time(6,  0,  tzinfo=pytz.utc), name="motivation")

    logger.info("✅ ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
