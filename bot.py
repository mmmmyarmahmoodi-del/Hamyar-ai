# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime, time, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytz

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, Update
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters,
)
from quotes import get_daily_quote

# ==================== تنظیمات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "123456789"))
TIMEZONE  = pytz.timezone("Asia/Tehran")

DATA_FILE  = "data.json"
CHARTS_DIR = "charts"
os.makedirs(CHARTS_DIR, exist_ok=True)

BREAKFAST_DEADLINE = 8   # قبل از ساعت ۸ = به موقع
REPORT_DEADLINE_H  = 0   # بعد از ۱۲ شب = دیر (ساعت ۰ تا ۶ = دیر)

STUDY_HOURS_OPTIONS = list(range(0, 13))
QUESTIONS_OPTIONS   = [0, 10, 20, 30, 40, 50]

REQUIRED_CHANNELS = [
    {"username": "@mohammad_yarmahmoudi",   "title": "کانال اصلی همیار"},
    {"username": "@soal_javab_yarmahmoudi", "title": "کانال سوال و جواب"},
    {"username": "@natayej_yarmahmoudi",    "title": "کانال نتایج"},
]

# States
REG_NAME = 1
ASK_HOURS, ASK_QUESTIONS = 2, 3

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
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


# ==================== منو ====================
def main_menu():
    kb = [[
        KeyboardButton("📸 ارسال عکس صبحانه"),
        KeyboardButton("📝 ارسال گزارش شب"),
    ]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, persistent=True)


# ==================== چک عضویت ====================
async def check_membership(user_id: int, bot) -> list:
    not_member = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch["username"], user_id)
            if m.status in ("left", "kicked", "banned"):
                not_member.append(ch)
        except Exception as e:
            logger.warning(f"چک عضویت {ch['username']}: {e}")
    return not_member

def join_keyboard():
    btns = [
        [InlineKeyboardButton(f"📢 {ch['title']}", url=f"https://t.me/{ch['username'].lstrip('@')}")]
        for ch in REQUIRED_CHANNELS
    ]
    btns.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return InlineKeyboardMarkup(btns)

async def send_join_msg(message, not_joined):
    ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
    text = (
        "برای استفاده از ربات همیار باید عضو کانال‌های زیر بشی:\n\n"
        f"{ch_list}\n\n"
        "بعد از عضویت دکمه «✅ عضو شدم» رو بزن."
    )
    await message.reply_text(text, reply_markup=join_keyboard())


# ==================== ثبت‌نام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    not_joined = await check_membership(user.id, context.bot)
    if not_joined:
        await send_join_msg(update.message, not_joined)
        return ConversationHandler.END

    if str(user.id) in data["students"]:
        name = data["students"][str(user.id)]["name"]
        await update.message.reply_text(
            f"سلام {name} عزیز! 😊\nاز دکمه‌های پایین استفاده کن 👇",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    context.user_data["waiting_name"] = True
    await update.message.reply_text("سلام! 👋 خوش اومدی.\n\nلطفاً اسم و فامیلت رو بنویس:")
    return REG_NAME

async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text.strip()
    user = update.effective_user

    if len(full_name) < 3:
        await update.message.reply_text("اسم و فامیل کامل بنویس (حداقل ۳ حرف):")
        return REG_NAME

    data = load_data()
    data["students"][str(user.id)] = {
        "name": full_name,
        "username": user.username or "",
        "joined": get_today(),
    }
    save_data(data)

    await update.message.reply_text(
        f"✅ ثبت‌نام موفق!\n\nخوش اومدی {full_name} عزیز 🎉\n\n"
        "از دکمه‌های پایین استفاده کن 👇",
        reply_markup=main_menu()
    )
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 شاگرد جدید:\n👤 {full_name}\n🆔 @{user.username or 'ندارد'}\n🔢 {user.id}"
        )
    except Exception:
        pass
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر عمومی متن"""
    user = update.effective_user
    text = update.message.text.strip()
    data = load_data()

    logger.info(f"handle_text: user={user.id}, text={text}, waiting={context.user_data.get('waiting_name')}, registered={str(user.id) in data['students']}")

    # اگه منتظر اسم فامیله
    if str(user.id) not in data["students"]:
        if len(text) < 3:
            await update.message.reply_text("اسم و فامیل کامل بنویس (حداقل ۳ حرف):")
            return

        data["students"][str(user.id)] = {
            "name": text,
            "username": user.username or "",
            "joined": get_today(),
        }
        save_data(data)
        context.user_data["waiting_name"] = False

        logger.info(f"ثبت‌نام موفق: {text} ({user.id})")

        await update.message.reply_text(
            f"✅ ثبت‌نام موفق!\n\nخوش اومدی {text} عزیز 🎉\n\n"
            "از دکمه‌های پایین استفاده کن 👇",
            reply_markup=main_menu()
        )
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🆕 شاگرد جدید:\n👤 {text}\n🆔 @{user.username or 'ندارد'}\n🔢 {user.id}"
            )
        except Exception as e:
            logger.warning(f"خطا در ارسال به ادمین: {e}")


# ==================== عکس صبحانه ====================
async def btn_breakfast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دکمه ارسال عکس صبحانه"""
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن و ثبت‌نام کن.")
        return

    not_joined = await check_membership(user.id, context.bot)
    if not_joined:
        await send_join_msg(update.message, not_joined)
        return

    today = get_today()
    record = data["daily_records"].get(today, {}).get(str(user.id), {})
    if "breakfast" in record:
        await update.message.reply_text("✅ عکس صبحانه‌ات رو قبلاً ثبت کردم!", reply_markup=main_menu())
        return

    await update.message.reply_text("📸 عکس صبحانه‌ات رو بفرست 👇", reply_markup=main_menu())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت عکس صبحانه"""
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن و ثبت‌نام کن.")
        return

    not_joined = await check_membership(user.id, context.bot)
    if not_joined:
        await send_join_msg(update.message, not_joined)
        return

    now   = get_now()
    today = get_today()
    name  = data["students"][str(user.id)]["name"]

    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})
    record = data["daily_records"][today][str(user.id)]

    if "breakfast" in record:
        await update.message.reply_text("✅ عکس صبحانه‌ات رو قبلاً ثبت کردم!", reply_markup=main_menu())
        return

    on_time = now.hour < BREAKFAST_DEADLINE
    record["breakfast"] = {"time": now.strftime("%H:%M"), "on_time": on_time}
    save_data(data)

    if on_time:
        await update.message.reply_text("به موقع فرستادی عزیزم ❤️", reply_markup=main_menu())
        status = "✅ به موقع"
    else:
        await update.message.reply_text(
            "با تاخیر فرستادی، تکرارش کنی روی کل انرژیت تاثیر بد میزاره عزیزم 🙏",
            reply_markup=main_menu()
        )
        status = "❌ با تاخیر"

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📸 عکس صبحانه\n👤 {name}\n⏰ {now.strftime('%H:%M')}\n{status}"
        )
    except Exception:
        pass


# ==================== گزارش شب ====================
def hours_kb():
    btns = [InlineKeyboardButton(str(h), callback_data=f"h_{h}") for h in STUDY_HOURS_OPTIONS]
    return InlineKeyboardMarkup([btns[i:i+4] for i in range(0, len(btns), 4)])

def questions_kb():
    btns = []
    for q in QUESTIONS_OPTIONS:
        label = f"{q}+" if q == QUESTIONS_OPTIONS[-1] else str(q)
        btns.append(InlineKeyboardButton(label, callback_data=f"q_{q}"))
    return InlineKeyboardMarkup([btns[i:i+3] for i in range(0, len(btns), 3)])

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن و ثبت‌نام کن.")
        return ConversationHandler.END

    not_joined = await check_membership(user.id, context.bot)
    if not_joined:
        await send_join_msg(update.message, not_joined)
        return ConversationHandler.END

    now = get_now()
    if 0 < now.hour < 6:
        await update.message.reply_text("تاخیر داشتیا ثبت نشد.", reply_markup=main_menu())
        return ConversationHandler.END

    today = get_today()
    if "report" in data["daily_records"].get(today, {}).get(str(user.id), {}):
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
    q_label   = f"{questions}+" if questions == QUESTIONS_OPTIONS[-1] else str(questions)

    if 0 < now.hour < 6:
        await query.edit_message_text("تاخیر داشتیا ثبت نشد.")
        return ConversationHandler.END

    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})
    data["daily_records"][today][str(user.id)]["report"] = {
        "time": now.strftime("%H:%M"),
        "on_time": True,
        "study_hours": hours,
        "questions_solved": questions,
    }
    save_data(data)

    await query.edit_message_text(f"✏️ {q_label} سوال ثبت شد.")
    await query.message.reply_text("خداقوت عزیزم❤️ ما حواسمون به تلاشت هست", reply_markup=main_menu())

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📝 گزارش شب\n👤 {name}\n📚 {hours} ساعت | ✏️ {q_label} سوال\n⏰ {now.strftime('%H:%M')}"
        )
    except Exception:
        pass
    return ConversationHandler.END

async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_menu())
    return ConversationHandler.END


# ==================== چک عضویت (دکمه) ====================
async def handle_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    not_joined = await check_membership(update.effective_user.id, context.bot)
    if not_joined:
        ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
        await query.edit_message_text(
            f"هنوز عضو این کانال‌ها نشدی:\n\n{ch_list}\n\nعضو شو و دوباره بزن.",
            reply_markup=join_keyboard()
        )
    else:
        await query.edit_message_text("✅ عضویتت تأیید شد!\n\nحالا /start رو بزن.")


# ==================== جاب‌های زمان‌بندی ====================
async def job_breakfast_reminder(context: ContextTypes.DEFAULT_TYPE):
    for sid in load_data()["students"]:
        try:
            await context.bot.send_message(int(sid), "عکس صبحانتو فرستادی واسه پشتیبانت عزیزم؟🍳")
        except Exception as e:
            logger.warning(f"یادآوری صبحانه {sid}: {e}")

async def job_report_reminder(context: ContextTypes.DEFAULT_TYPE):
    for sid in load_data()["students"]:
        try:
            await context.bot.send_message(int(sid), "گزارش کار فراموش نشه قهرمان😍")
        except Exception as e:
            logger.warning(f"یادآوری گزارش {sid}: {e}")

async def job_motivation(context: ContextTypes.DEFAULT_TYPE):
    quote = get_daily_quote(get_day_index())
    for sid in load_data()["students"]:
        try:
            await context.bot.send_message(int(sid), quote)
        except Exception as e:
            logger.warning(f"جمله انگیزشی {sid}: {e}")


# ==================== دستورات ادمین ====================
def week_dates():
    today = get_now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

def weekly_totals(data):
    dates = week_dates()
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

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    today = get_today()
    records = data["daily_records"].get(today, {})
    msg = f"📊 گزارش امروز ({today})\n" + "━"*25 + "\n\n"
    for sid, sinfo in data["students"].items():
        rec = records.get(sid, {})
        b = rec.get("breakfast")
        r = rec.get("report")
        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌ نفرستاده")
        r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌ نفرستاده"
        msg += f"👤 {sinfo['name']}\n   📸 {b_st}\n   📝 {r_st}\n\n"
    await update.message.reply_text(msg)

async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    students = data["students"]
    if not students:
        await update.message.reply_text("هنوز کسی ثبت‌نام نکرده.")
        return
    msg = f"👥 لیست شاگردها ({len(students)} نفر)\n\n"
    for sid, s in students.items():
        msg += f"• {s['name']} | @{s.get('username','ندارد')} | از {s['joined']}\n"
    await update.message.reply_text(msg)

async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    totals = weekly_totals(data)
    if not totals:
        await update.message.reply_text("هنوز دانش‌آموزی ثبت‌نام نکرده.")
        return
    ranked = sorted(totals.values(), key=lambda t: (t["hours"], t["questions"]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    msg = "🏆 رتبه‌بندی هفتگی\n" + "━"*20 + "\n\n"
    for i, t in enumerate(ranked):
        medal = medals[i] if i < 3 else f"{i+1}."
        msg += f"{medal} {t['name']}\n   📚 {t['hours']} ساعت  |  ✏️ {t['questions']} سوال\n\n"
    await update.message.reply_text(msg)

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    totals = weekly_totals(data)
    if not totals:
        await update.message.reply_text("هنوز دانش‌آموزی ثبت‌نام نکرده.")
        return
    names     = [t["name"] for t in totals.values()]
    hours     = [t["hours"] for t in totals.values()]
    questions = [t["questions"] for t in totals.values()]
    fig, ax = plt.subplots(figsize=(max(8, len(names)*1.5), 6))
    x = range(len(names))
    w = 0.35
    b1 = ax.bar([i-w/2 for i in x], hours,     w, label="Study Hours",     color="#4CAF50", zorder=3)
    b2 = ax.bar([i+w/2 for i in x], questions, w, label="Questions Solved", color="#2196F3", zorder=3)
    for bar in b1+b2:
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.3,
                str(int(bar.get_height())), ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=25, ha="right", fontsize=10)
    ax.set_title("Weekly Report", fontsize=14, fontweight="bold")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    fig.tight_layout()
    path = os.path.join(CHARTS_DIR, "weekly.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    with open(path, "rb") as img:
        await update.message.reply_photo(img, caption="📊 نمودار هفتگی")


# ==================== اجرا ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # start
    app.add_handler(CommandHandler("start", start))

    # متن عمومی (ثبت اسم فامیل) - باید قبل از report_conv باشه
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^📝 ارسال گزارش شب$") & ~filters.Regex("^📸 ارسال عکس صبحانه$"),
        handle_text
    ))

    # گزارش شب
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

    # دکمه صبحانه
    app.add_handler(MessageHandler(filters.Regex("^📸 ارسال عکس صبحانه$"), btn_breakfast))

    # عکس
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # چک عضویت
    app.add_handler(CallbackQueryHandler(handle_check_join, pattern="^check_join$"))

    # دستورات ادمین
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("students", cmd_students))
    app.add_handler(CommandHandler("weekly",   cmd_weekly))
    app.add_handler(CommandHandler("ranking",  cmd_ranking))

    jq = app.job_queue
    jq.run_daily(job_breakfast_reminder, time=time(4,  30, tzinfo=pytz.utc), name="breakfast")
    jq.run_daily(job_report_reminder,    time=time(19, 30, tzinfo=pytz.utc), name="report_reminder")
    jq.run_daily(job_motivation,         time=time(6,  0,  tzinfo=pytz.utc), name="motivation")

    logger.info("✅ ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
