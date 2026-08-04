# -*- coding: utf-8 -*-
import json, logging, os, asyncio, tempfile, threading
import urllib.request, urllib.error
from datetime import datetime, time, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
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
INSTAGRAM_LINK = "https://www.instagram.com/mohammad.yarmahmoudi?igsh=eHVhbjM5d3A2czEw"
REFERRALS_PER_SESSION = 10   # به ازای هر ۱۰ دعوت، یک جلسه مشاوره تلفنی رایگان
BOT_USERNAME = None           # موقع اجرا پر میشه (post_init)

GRADES = ["ششم", "هفتم", "هشتم", "نهم", "دهم", "یازدهم", "کنکوری"]
STUDY_HOURS_OPTIONS = list(range(0, 13))
QUESTIONS_OPTIONS   = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 150]
ASK_HOURS, ASK_QUESTIONS = 1, 2
BREAKFAST_START_H, BREAKFAST_START_M = 5, 30
BREAKFAST_END_H,   BREAKFAST_END_M   = 8, 0
WAKE_TIME_OPTIONS = ["05:30","06:00","06:30","07:00","07:30","08:00","08:30","09:00","09:30","10:00"]
DEFAULT_WAKE_TIME = "08:00"     # اگه کسی خودش تنظیم نکرده باشه
WAKE_TIME_VALID_DAYS = 7        # تنظیم هر دانش‌آموز یک هفته معتبره
WAKE_TIME_GRACE_MINUTES = 30    # تا این مقدار بعد از ساعت انتخابی، بازم به‌موقع حساب میشه
REMINDER_DAYS  = [1, 2, 3, 7]
REMINDER_HOURS = [7, 9, 12, 15, 18, 21]
DAILY_RECORDS_RETENTION_DAYS = 30   # رکوردهای روزانه (صبحانه/گزارش) قدیمی‌تر از این تعداد روز پاک میشن

# پرسش مستقیم از استاد
TEACHER_LINK = "https://t.me/soal_javab_yarmahmoudi/4"

# چت با هوش مصنوعی (Groq)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "openai/gpt-oss-120b"
CHAT_RATE_LIMIT_PER_HOUR = 15   # حداکثر پیام چت با AI برای هر دانش‌آموز در هر ساعت

REPORT_STREAK_MESSAGES = {
    2: "امروز ۲ روزه گزارش نفرستادی نمیدونم چرا گزارش نمیدی ولی امیدوارم حالت خوب باشه و سلامت باشی ❤️ "
       "اگه مشکلی نداری سعی کن از امروز بفرستی عزیزم من اینجام که همراهت باشم وقتی هیچکس حواسش بهت نیست یادت نره 😘"
       "اگرم مشکل خاصی داری این روزا مطمئن باش همه چی بهتر میشه تو فقط غصه نخور اگه خواستی با منم میتونی حرف بزنی "
       "تو قسمت چت با من یا درد و دل😘 اگه سوال تخصصیم داری که از استاد بپرس بدون سانسور",
    4: "عزیزدلم کجایی نگرانت شدم؟",
    6: "خواهشا گزارشتو بفرست منو از نگرانی در بیار ❤️",
    8: "فقط نگران حالتم همین ...💔",
    10: "عشق من کجایی دلتنگتم زیاد ❤️‍🩹",
    15: "اگه یه کاری‌کنی که بفهمم حالت خوبه خیلی حالم بهتر میشه\nمنظورم اینه گزارش کار بفرستی 💘",
}

# توربو جادویی
TURBO_HOURS       = list(range(7, 19))   # ۷ صبح تا ۶ عصر
TURBO_SECOND_HOUR = 21                    # یادآوری دوم، ثابت، ساعت ۹ شب
TURBO_DAYS        = 7
ASK_TURBO_COUNT, ASK_TURBO_TASK, ASK_TURBO_HOUR = 3, 4, 5

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── داده ──
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"students": {}, "daily_records": {}, "pending": {}}

_SAVE_LOCK = threading.Lock()

def save_data(data):
    """نوشتن امن: اول رو یه فایل موقت کامل می‌نویسه، بعد جایگزین فایل اصلی میکنه.
    اگه وسط نوشتن ربات کرش/ری‌استارت بشه، data.json هیچ‌وقت نصفه‌نیمه یا خراب نمی‌مونه."""
    with _SAVE_LOCK:
        dir_name = os.path.dirname(os.path.abspath(DATA_FILE)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".data_tmp_", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, DATA_FILE)
        except Exception:
            try: os.remove(tmp_path)
            except Exception: pass
            raise

def get_today(): return datetime.now(TIMEZONE).strftime("%Y-%m-%d")
def get_now():   return datetime.now(TIMEZONE)
def get_day_index():
    return (get_now() - datetime(2024,1,1,tzinfo=TIMEZONE)).days

def date_str(days_ago=0):
    return (get_now().date() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def to_jalali(date_str):
    """تبدیل تاریخ میلادی به شمسی بدون کتابخونه خارجی"""
    try:
        parts = date_str.split('-')
        gy, gm, gd = int(parts[0]), int(parts[1]), int(parts[2])
        g_days = [31,28,31,30,31,30,31,31,30,31,30,31]
        j_days = [31,31,31,31,31,31,30,30,30,30,30,29]
        gy2 = gy - 1600; gm2 = gm - 1; gd2 = gd - 1
        g_day_no = 365*gy2 + (gy2+3)//4 - (gy2+99)//100 + (gy2+399)//400
        for i in range(gm2): g_day_no += g_days[i]
        if gm2 > 1 and ((gy2%4==0 and gy2%100!=0) or gy2%400==0): g_day_no += 1
        g_day_no += gd2
        j_day_no = g_day_no - 79
        j_np = j_day_no // 12053; j_day_no %= 12053
        jy = 979 + 33*j_np + 4*(j_day_no//1461); j_day_no %= 1461
        if j_day_no >= 366:
            jy += (j_day_no-1)//365; j_day_no = (j_day_no-1)%365
        jm = 12; jd = j_day_no + 1
        for i in range(11):
            if j_day_no >= j_days[i]: j_day_no -= j_days[i]
            else: jm = i+1; jd = j_day_no+1; break
        return f"{jy}/{jm:02d}/{jd:02d}"
    except Exception as e:
        logger.warning(f"خطا در تبدیل تاریخ {date_str}: {e}")
        return date_str

def get_effective_wake_time(student):
    """ساعت اعلام بیداری خودِ دانش‌آموز، اگه تنظیم کرده و هنوز معتبره؛ وگرنه ساعت پیش‌فرض."""
    wt = student.get("wake_time")
    until = student.get("wake_time_until")
    if wt and until and get_today() <= until:
        return wt
    return DEFAULT_WAKE_TIME

def wake_time_window(now, student):
    """بازه (ساعت انتخابی، پایان مهلت) رو برای امروز برمیگردونه."""
    wt = get_effective_wake_time(student)
    start = now.replace(hour=int(wt[:2]), minute=int(wt[3:]), second=0, microsecond=0)
    end = start + timedelta(minutes=WAKE_TIME_GRACE_MINUTES)
    return start, end

def is_breakfast_on_time(now, student):
    _, end = wake_time_window(now, student)
    return now <= end

def is_silent(student):
    """چک میکنه دانش‌آموز حالت «سکوت موقت» رو فعال کرده یا تو مرخصیه."""
    if student.get("silent_mode"):
        return True
    leave_until = student.get("leave_until")
    if leave_until and get_today() <= leave_until:
        return True
    return False

def week_dates():
    today = get_now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

def monthly_dates():
    today = get_now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]

def check_late_streak(data, user_id, check_type):
    for i in range(1, 3):
        d   = date_str(i)
        rec = data["daily_records"].get(d, {}).get(user_id, {})
        item = rec.get(check_type)
        if not item or item.get("on_time", True):
            return False
    return True

def check_consistent_streak(data, user_id):
    for i in range(1, 4):
        d   = date_str(i)
        rec = data["daily_records"].get(d, {}).get(user_id, {})
        b = rec.get("breakfast"); r = rec.get("report")
        if not b or not r or not b.get("on_time") or not r.get("on_time"):
            return False
    return True

def prune_old_records(data):
    """فقط رکوردهای روزانه (daily_records) قدیمی‌تر از حد مجاز رو پاک میکنه.
    به students، goal، turbo، reminders و بقیه اطلاعات دانش‌آموزا هیچ کاری نداره."""
    cutoff = (get_now().date() - timedelta(days=DAILY_RECORDS_RETENTION_DAYS)).strftime("%Y-%m-%d")
    old_dates = [d for d in data.get("daily_records", {}) if d < cutoff]
    for d in old_dates:
        del data["daily_records"][d]
    return len(old_dates)

# ── منوها ──
ONBOARDING_MESSAGE = (
    "📚 راهنمای سریع دکمه‌ها\n\n"
    "⏰ تنظیم اعلام بیداری → ساعت دلخواهتو (بین ۵:۳۰ تا ۱۰ صبح) برای اعلام بیداری انتخاب کن؛ "
    "هر روز تا نیم‌ساعت بعد از اون ساعت، عکس صبحونه‌ت رو مستقیم بفرست تا به‌موقع حساب بشه. "
    "این تنظیم یک هفته معتبره. اگه اصلاً نفرستی، بهت پیام میدم «اعلام بیداری نکردیا 😒»\n"
    "📝 ارسال گزارش شب → هر موقع تا قبل از نیمه‌شب (۰۰:۰۰) بفرست. بعد از ۰۰:۰۰ تا ۶ صبح دیگه ثبت نمیشه. "
    "اگه تا ساعت ۱۲ شب گزارش نفرستی، بهت پیام میدم «گزارشتو نفرستادیا 😏»\n"
    "🎯 هدف هفتگی → هدف این هفته‌ت رو بنویس تا هر روز صبح یادت بندازم\n"
    "🧮 درصد سنج → درصد تست‌هایی که زدی رو حساب کن\n"
    "🏅 امتیازات من → ببین تو ۳۰ روز اخیر چقدر منظم بودی\n"
    "⏰ یادم بنداز → یادآوری شخصی برای هر کاری که میخوای بساز\n"
    "✨ توربو جادویی → کارای هفته‌ت رو تعریف کن، دوبار در روز یادت میندازم\n"
    "🤖 چت با من → هر سوالی داشتی از هوش مصنوعی بپرس\n"
    "🧰 ابزارهای بیشتر → شامل «💬 درد و دل»، «🏆 رکورد های من»، «✉️ نامه به آینده»، "
    "«🎓 پرسش مستقیم از استاد»، «🌴 مرخصی» و «🎁 دریافت مشاوره رایگان»\n"
    "🔕 سکوت موقت → یادآوری‌های ربات رو موقتاً خاموش کن؛ برای روشن کردنش دوباره همین دکمه رو بزن\n"
    "📊 هر پنجشنبه شب یه خلاصه از عملکرد هفته‌ت (صبحونه و گزارش) خودکار برات میفرستم\n\n"
    "📷 پیج اینستاگرامم رو هم اگه دوست داشتی فالو کن: instagram.com/mohammad.yarmahmoudi\n\n"
    "هر وقت گیج شدی، همینجا رو دوباره بخون 🌟"
)

GUIDE_MESSAGE = (
    "📖 آموزش کامل کار با ربات\n\n"
    "⏰ تنظیم اعلام بیداری\n"
    "با این دکمه، ساعت دلخواهتو بین ۵:۳۰ تا ۱۰ صبح (نیم‌ساعت نیم‌ساعت) انتخاب کن. از فردا هر روز تا نیم‌ساعت بعد از "
    "همون ساعت، فقط کافیه عکس صبحونه‌ت رو مستقیم برام بفرستی (نیازی به زدن دکمه‌ای نیست) تا به‌موقع حساب بشه. "
    "سر همون ساعت یه یادآوری میگیری، و اگه تا نیم‌ساعت بعدش هم نفرستاده باشی، پیام «اعلام بیداری نکردیا 😒» میاد. "
    "این تنظیم یک هفته اعتبار داره، بعدش می‌تونی دوباره عوضش کنی. اگه هیچ‌وقت تنظیمش نکنی، پیش‌فرض ساعت ۸ صبحه.\n"
    "اگه مدرسه میری و خودت سرِ وقت بیدار میشی، تو همین قسمت دکمه «🏫 مدرسه میرم، بیدار میشم» رو بزن؛ از اون به بعد دیگه اصلاً "
    "ازت اعلام بیداری نمیخوام و هیچ یادآوری یا پیام هشدارآمیزی درباره‌ش برات نمیفرستم. هر وقت خواستی برگردی به حالت عادی، "
    "کافیه دوباره یه ساعت از همون دکمه «⏰ تنظیم اعلام بیداری» انتخاب کنی.\n\n"
    "📝 ارسال گزارش شب\n"
    "هر موقع تا قبل از نیمه‌شب (۰۰:۰۰) بفرست؛ بین ۰۰:۰۰ تا ۶ صبح دیگه ثبت نمیشه (خیلی دیر شده). "
    "ساعت ۱۱ شب اگه هنوز نفرستاده باشی یادآوری میگیری، ساعت ۲۳:۵۵ هم پیام «گزارشتو نفرستادیا 😏» میاد. "
    "اگه چندروز پشت سر هم گزارش ندی، پیام‌های دلسوزانه‌تری هم بهت میرسه که فراموشت نکنیم 💌\n\n"
    "🧰 ابزارهای بیشتر\n"
    "این دکمه یه زیرمنو باز میکنه شامل «💬 درد و دل»، «🏆 رکورد های من»، «✉️ نامه به آینده»، «🎓 پرسش مستقیم از استاد»، "
    "«🌴 مرخصی» و «🎁 دریافت مشاوره رایگان». برای برگشت به منوی اصلی، داخل همون زیرمنو دکمه «🔙 بازگشت به منوی اصلی» رو بزن.\n\n"
    "💬 درد و دل\n"
    "هرچی تو دلته، هر مشکل و دغدغه‌ای داری، اینجا بنویس. فقط برای خودت و مشاورت می‌مونه.\n\n"
    "🎯 هدف هفتگی\n"
    "یه هدف مشخص برای این هفته بنویس (مثلاً «تموم کردن فصل ۳ فیزیک»)؛ هر روز صبح بهت یادآوریش میکنم.\n\n"
    "🧮 درصد سنج\n"
    "تعداد سوالای درست و کل سوالا رو بگو، درصدتو حساب میکنم.\n\n"
    "🏅 امتیازات من\n"
    "خلاصه‌ی نظم و انضباطت تو ۳۰ روز اخیر (چندبار سروقت بودی، چندبار دیر کردی، چندبار جا انداختی).\n\n"
    "✉️ نامه به آینده\n"
    "یه نامه برای خودت بنویس؛ دقیقاً یک ماه دیگه همون نامه رو برات میفرستم.\n\n"
    "⏰ یادم بنداز\n"
    "برای هر کاری که میخوای (مطالعه، تکلیف، هرچی)، یه یادآوری شخصی با روز و ساعت دلخواه خودت بساز.\n\n"
    "🎓 پرسش مستقیم از استاد\n"
    "لینک مستقیم برای پرسیدن سوال از استاد رو بهت میده.\n\n"
    "✨ توربو جادویی\n"
    "بین ۱ تا ۷ تا کار که میخوای این هفته انجام بدی رو تعریف کن، یه ساعت برای یادآوری اول (بین ۷ صبح تا ۶ عصر) انتخاب کن؛ "
    "به مدت ۷ روز، هر روز دوبار (همون ساعت انتخابیت + ساعت ۹ شب) کارات رو یادت میندازم.\n\n"
    "🏆 رکورد های من\n"
    "بیشترین تستی که تو یه روز زدی و بیشترین ساعت مطالعه‌ت تو ۷ روز اخیر رو نشون میده.\n\n"
    "🤖 چت با من\n"
    "با هوش مصنوعی چت کن، هر سوالی داری بپرس. حداکثر ۱۵ پیام در ساعت میتونی بفرستی. "
    "برای خروج از چت، دکمه «🔙 پایان چت» رو بزن.\n\n"
    "🎁 دریافت مشاوره رایگان\n"
    "یه لینک دعوت اختصاصی بهت میده. هر دوستی که با اون لینک ثبت‌نام کنه، برات حساب میشه. "
    "به ازای هر ۱۰ نفر دعوت موفق، یک جلسه مشاوره تلفنی رایگان میگیری.\n\n"
    "🌴 مرخصی\n"
    "اگه مریضی یا کار داری و چند روز نمیتونی طبق روال پیش بری، این دکمه رو بزن، دلیلش رو انتخاب کن "
    "(🤒 مریض شدم یا 💼 کار دارم) و بگو چند روز (بین ۱ تا ۷ روز) میخوای مرخصی باشی. تا وقتی مرخصی‌ت تموم نشده، "
    "هیچ یادآوری یا پیامی از ربات برات نمیاد، فقط پیام‌های مشاور میرسه. بعد از تموم شدن مدتش، ربات خودکار برمیگرده به حالت عادی. "
    "اگه هم زودتر خواستی تمومش کنی، دوباره دکمه «🌴 مرخصی» رو بزن و «✅ اتمام مرخصی» رو انتخاب کن.\n\n"
    "📊 خلاصه عملکرد هفتگی\n"
    "هر پنجشنبه شب، یه خلاصه از عملکردت تو اون هفته (چند روز صبحونه و گزارش به‌موقع فرستادی، چند روز دیر کردی یا جا انداختی "
    "و امتیاز کلی هفته‌ت) رو خودکار برات میفرستم؛ نیازی نیست خودت درخواستش بدی.\n\n"
    "🔕 سکوت موقت\n"
    "اگه دلت میخواد چند روزی هیچ یادآوری و پیامی از ربات نگیری، این دکمه رو بزن. تا وقتی این حالت روشنه، هیچ پیامی "
    "(نه یادآوری صبحونه، نه یادآوری گزارش، نه پیام‌های انگیزشی و دلسوزانه، هیچی) برات نمیاد؛ فقط پیام‌هایی که خود مشاور "
    "مستقیم برات بفرسته میرسه. برای اینکه دوباره یادآوری‌ها فعال بشه، کافیه دوباره همین دکمه «🔕 سکوت موقت» رو بزنی.\n\n"
    "📢 نکته مهم\n"
    "برای استفاده از همه این امکانات، باید همیشه عضو کانال‌های اجباری ربات بمونی. اگه از یکیشون لفت بدی، "
    "دکمه‌ها موقتاً غیرفعال میشن تا دوباره عضو شی.\n\n"
    "هر وقت یادت رفت، دوباره همینجا رو بخون 🌟"
)

def referral_link(uid):
    username = BOT_USERNAME or "your_bot"
    return f"https://t.me/{username}?start=ref_{uid}"

def main_menu():
    kb = [
        [KeyboardButton("⏰ تنظیم اعلام بیداری"), KeyboardButton("📝 ارسال گزارش شب")],
        [KeyboardButton("🎯 هدف هفتگی"),          KeyboardButton("🧮 درصد سنج")],
        [KeyboardButton("🏅 امتیازات من"),         KeyboardButton("⏰ یادم بنداز")],
        [KeyboardButton("✨ توربو جادویی"),        KeyboardButton("🤖 چت با من")],
        [KeyboardButton("🧰 ابزارهای بیشتر")],
        [KeyboardButton("🔕 سکوت موقت")],
        [KeyboardButton("📖 آموزش کار با ربات")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

def more_tools_menu():
    kb = [
        [KeyboardButton("💬 درد و دل"),          KeyboardButton("🏆 رکورد های من")],
        [KeyboardButton("✉️ نامه به آینده"),      KeyboardButton("🎓 پرسش مستقیم از استاد")],
        [KeyboardButton("🌴 مرخصی"),             KeyboardButton("🎁 دریافت مشاوره رایگان")],
        [KeyboardButton("🔙 بازگشت به منوی اصلی")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

def leave_reason_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤒 مریض شدم", callback_data="leavereason_sick")],
        [InlineKeyboardButton("💼 کار دارم", callback_data="leavereason_busy")],
    ])

def leave_days_keyboard():
    btns = [InlineKeyboardButton(str(n), callback_data=f"leavedays_{n}") for n in range(1, 8)]
    return InlineKeyboardMarkup([btns[:4], btns[4:]])

def leave_end_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ اتمام مرخصی", callback_data="leaveend")]])

def chat_exit_menu():
    kb = [[KeyboardButton("🔙 پایان چت")]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

def admin_menu():
    kb = [
        [KeyboardButton("📊 گزارش امروز"),      KeyboardButton("👤 گزارش دانش‌آموز")],
        [KeyboardButton("🏆 رتبه‌بندی هفتگی"),  KeyboardButton("📈 نمودار هفتگی")],
        [KeyboardButton("👥 لیست دانش‌آموزا"),  KeyboardButton("❌ حذف دانش‌آموز")],
        [KeyboardButton("📣 پیام به همه"),       KeyboardButton("💾 بکاپ داده‌ها")],
        [KeyboardButton("😴 غیرفعال‌های هفته اخیر")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

# ── کیبوردها ──
def join_keyboard():
    btns = [[InlineKeyboardButton(f"📢 {ch['title']}", url=f"https://t.me/{ch['username'].lstrip('@')}")] for ch in REQUIRED_CHANNELS]
    btns.append([InlineKeyboardButton("📷 پیج اینستاگرام", url=INSTAGRAM_LINK)])
    btns.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return InlineKeyboardMarkup(btns)

def grade_keyboard():
    btns = [InlineKeyboardButton(g, callback_data=f"grade_{g}") for g in GRADES]
    return InlineKeyboardMarkup([btns[i:i+3] for i in range(0, len(btns), 3)])

def hours_kb():
    btns = [InlineKeyboardButton(str(h), callback_data=f"h_{h}") for h in STUDY_HOURS_OPTIONS]
    return InlineKeyboardMarkup([btns[i:i+4] for i in range(0, len(btns), 4)])

def questions_kb():
    btns = [InlineKeyboardButton("+150" if q == QUESTIONS_OPTIONS[-1] else str(q), callback_data=f"q_{q}") for q in QUESTIONS_OPTIONS]
    return InlineKeyboardMarkup([btns[i:i+3] for i in range(0, len(btns), 3)])

def reminder_days_keyboard():
    days = ["فردا", "۲ روز دیگه", "۳ روز دیگه", "یه هفته دیگه"]
    btns = [InlineKeyboardButton(d, callback_data=f"rday_{i}") for i, d in enumerate(days)]
    return InlineKeyboardMarkup([btns[:2], btns[2:]])

def reminder_hours_keyboard():
    hours = ["۷ صبح", "۹ صبح", "۱۲ ظهر", "۳ بعدازظهر", "۶ عصر", "۹ شب"]
    btns  = [InlineKeyboardButton(h, callback_data=f"rhour_{i}") for i, h in enumerate(hours)]
    return InlineKeyboardMarkup([btns[:3], btns[3:]])

def period_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 هفته گذشته", callback_data="srep_week"),
        InlineKeyboardButton("🗓 ماه گذشته",  callback_data="srep_month"),
    ]])

def teacher_link_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎓 پرسش از استاد", url=TEACHER_LINK)]])

def turbo_count_keyboard():
    btns = [InlineKeyboardButton(str(n), callback_data=f"turbocount_{n}") for n in range(1, 8)]
    return InlineKeyboardMarkup([btns[i:i+4] for i in range(0, len(btns), 4)])

TURBO_HOUR_LABELS = {
    7: "۷ صبح", 8: "۸ صبح", 9: "۹ صبح", 10: "۱۰ صبح", 11: "۱۱ صبح", 12: "۱۲ ظهر",
    13: "۱ عصر", 14: "۲ عصر", 15: "۳ عصر", 16: "۴ عصر", 17: "۵ عصر", 18: "۶ عصر",
}

def turbo_hour_keyboard():
    btns = [InlineKeyboardButton(TURBO_HOUR_LABELS[h], callback_data=f"turbohour_{h}") for h in TURBO_HOURS]
    return InlineKeyboardMarkup([btns[i:i+3] for i in range(0, len(btns), 3)])

def wake_time_keyboard():
    btns = [InlineKeyboardButton(t, callback_data=f"waketime_{t}") for t in WAKE_TIME_OPTIONS]
    rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
    rows.append([InlineKeyboardButton("🏫 مدرسه میرم، بیدار میشم", callback_data="waketime_schoolmode")])
    return InlineKeyboardMarkup(rows)

async def is_active_student(update: Update, context: ContextTypes.DEFAULT_TYPE, data, uid: str) -> bool:
    """چک میکنه کاربر ثبت‌نام کرده و هنوز عضو کانال‌هاست؛ اگه نه، پیام مناسب میفرسته و False برمیگردونه."""
    if uid not in data["students"]:
        await update.message.reply_text("اول /start بزن.")
        return False
    not_joined = await check_membership(int(uid), context.bot)
    if not_joined:
        ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
        await update.message.reply_text(
            f"برای استفاده از ربات باید عضو این کانال(ها) بشی:\n\n{ch_list}\n\nبعد از عضویت دوباره امتحان کن.",
            reply_markup=join_keyboard()
        )
        return False
    return True

# ── چک عضویت ──
_LAST_ALERT_AT = {}

async def alert_admin(bot, category: str, message: str, cooldown_minutes: int = 30):
    """پیام هشدار سیستمی به ادمین میفرسته (با ایموجی قرمز مشخص)، با فاصله زمانی تا اسپم نشه."""
    now = get_now()
    last = _LAST_ALERT_AT.get(category)
    if last and (now - last).total_seconds() < cooldown_minutes * 60:
        return
    _LAST_ALERT_AT[category] = now
    try:
        await bot.send_message(ADMIN_ID, f"🔴 هشدار سیستمی\n\n{message}")
    except Exception as e:
        logger.warning(f"ارسال هشدار سیستمی به ادمین شکست خورد: {e}")

async def check_membership(user_id, bot):
    not_member = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch["username"], user_id)
            if m.status in ("left", "kicked", "banned"):
                not_member.append(ch)
        except Exception as e:
            msg = str(e).lower()
            logger.warning(f"چک عضویت {ch['username']}: {e}")
            if any(k in msg for k in ("chat not found", "not a member", "have no rights", "not enough rights")):
                await alert_admin(
                    bot, f"channel_{ch['username']}",
                    f"چک عضویت کانال «{ch['title']}» ({ch['username']}) با خطا مواجه شد:\n{e}\n\n"
                    f"احتمالاً ربات دیگه ادمین این کانال نیست، یا یوزرنیم/آیدی کانال عوض شده. لطفاً بررسی کن."
                )
    return not_member

async def on_channel_membership_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """به محض اینکه یکی از یکی از کانال‌های اجباری لفت بده، همون لحظه بهش پیام میده."""
    cmu = update.chat_member
    if not cmu:
        return
    chat = cmu.chat
    channel = next((ch for ch in REQUIRED_CHANNELS if ch["username"].lstrip("@") == (chat.username or "")), None)
    if not channel:
        return
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    if old_status in ("member", "administrator", "creator", "restricted") and new_status in ("left", "kicked", "banned"):
        user = cmu.new_chat_member.user
        data = load_data()
        if str(user.id) not in data["students"]:
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 {channel['title']}", url=f"https://t.me/{channel['username'].lstrip('@')}")]])
        try:
            await context.bot.send_message(
                user.id,
                f"👋 دیدم از «{channel['title']}» خارج شدی!\n\n"
                f"برای اینکه بتونی همچنان از ربات استفاده کنی، لطفاً دوباره عضو شو 🙏",
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"پیام آنی خروج از کانال به {user.id}: {e}")

# ── start ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if user.id == ADMIN_ID:
        await update.message.reply_text("سلام مشاور عزیز! 👋\nاز دکمه‌های پایین استفاده کن 👇", reply_markup=admin_menu())
        return

    # ثبت لینک دعوت (اگه از طریق لینک اختصاصی یه دانش‌آموز اومده باشه)
    if context.args and str(user.id) not in data["students"]:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref_id = arg[4:]
            if ref_id.isdigit() and ref_id != str(user.id) and ref_id in data["students"]:
                data.setdefault("pending_referrals", {})[str(user.id)] = ref_id
                save_data(data)

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

# ── handle_text ──
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    data = load_data()
    pending = data["pending"].get(str(user.id), {})

    logger.info(f"TEXT from {user.id}: '{text}' step={pending.get('step')}")

    # ── ادمین ──
    if user.id == ADMIN_ID:
        if pending.get("step") == "broadcast":
            data["pending"].pop(str(user.id), None)
            save_data(data)
            success = 0; failed = 0; blocked = []
            for sid in list(data["students"].keys()):
                try:
                    await context.bot.send_message(int(sid), f"📣 پیام از مشاور:\n\n{text}", reply_markup=main_menu())
                    success += 1
                except Exception as e:
                    err = str(e).lower()
                    if "blocked" in err or "deactivated" in err or "not found" in err:
                        blocked.append(sid)
                    else:
                        failed += 1
                    logger.warning(f"broadcast به {sid}: {e}")

            # حذف کاربران بلاک‌شده از دیتابیس
            if blocked:
                data = load_data()
                for sid in blocked:
                    data["students"].pop(sid, None)
                    for d in data["daily_records"]:
                        data["daily_records"][d].pop(sid, None)
                save_data(data)

            msg = f"✅ پیام ارسال شد!\n\n✅ موفق: {success} نفر\n❌ ناموفق: {failed} نفر"
            if blocked:
                msg += f"\n🗑 حذف شده (بلاک/غیرفعال): {len(blocked)} نفر"
            await update.message.reply_text(msg, reply_markup=admin_menu())
            return

        if pending.get("step") == "admin_remove":
            data["pending"].pop(str(user.id), None)
            found_id = None
            for sid, s in data["students"].items():
                if s["name"] == text:
                    found_id = sid; break
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
                    found_id = sid; break
            if not found_id:
                data["pending"].pop(str(user.id), None)
                save_data(data)
                await update.message.reply_text(f"❌ «{text}» پیدا نشد.", reply_markup=admin_menu())
                return
            data["pending"][str(user.id)] = {"step": "admin_student_period", "student_id": found_id, "student_name": text}
            save_data(data)
            await update.message.reply_text(f"گزارش «{text}» رو برای چه بازه‌ای میخوای؟", reply_markup=period_keyboard())
            return
        return

    # ── دانش‌آموز ──
    # چت با هوش مصنوعی
    if pending.get("step") == "ai_chat":
        uid = str(user.id)
        student = data["students"].get(uid, {})
        now = get_now()
        bucket = now.strftime("%Y-%m-%d %H")
        usage = student.get("chat_usage", {})
        if usage.get("bucket") != bucket:
            usage = {"bucket": bucket, "count": 0}
        if usage["count"] >= CHAT_RATE_LIMIT_PER_HOUR:
            await update.message.reply_text(
                f"⏳ تو یک ساعت اخیر {CHAT_RATE_LIMIT_PER_HOUR} پیام فرستادی، فعلاً سقفش همینه.\n"
                f"یکم دیگه دوباره امتحان کن 🙏",
                reply_markup=chat_exit_menu()
            )
            return
        usage["count"] += 1
        student["chat_usage"] = usage
        data["students"][uid] = student
        save_data(data)

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        answer = await asyncio.to_thread(call_groq, text)
        if answer.startswith("⚠️"):
            await alert_admin(context.bot, "groq",
                "چت هوش مصنوعی (Groq) داره خطا میده و به دانش‌آموزا جواب نمیده.\n"
                "احتمالاً کلید API منقضی شده یا سقف مصرف روزانه پر شده. لاگ Railway رو چک کن.")
        await update.message.reply_text(answer, reply_markup=chat_exit_menu())
        return

    # درصد سنج
    if pending.get("step") == "percent_correct":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        data["pending"][str(user.id)] = {"step": "percent_wrong", "correct": int(text)}
        save_data(data)
        await update.message.reply_text("تعداد سوالات **غلط** رو بنویس:")
        return

    if pending.get("step") == "percent_wrong":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        data["pending"][str(user.id)] = {"step": "percent_blank", "correct": pending["correct"], "wrong": int(text)}
        save_data(data)
        await update.message.reply_text("تعداد سوالات **نزده** رو بنویس:")
        return

    if pending.get("step") == "percent_blank":
        if not text.isdigit():
            await update.message.reply_text("لطفاً یه عدد بنویس:")
            return
        correct = pending["correct"]; wrong = pending["wrong"]; blank = int(text)
        total = correct + wrong + blank
        data["pending"].pop(str(user.id), None)
        save_data(data)
        if total == 0:
            await update.message.reply_text("تعداد سوالات صفره!", reply_markup=main_menu())
            return
        percent = ((correct - wrong / 3) / total) * 100
        emoji = "🌟" if percent >= 70 else "✅" if percent >= 50 else "⚠️" if percent >= 30 else "❌"
        await update.message.reply_text(
            f"🧮 نتیجه درصد سنج\n\n✅ درست: {correct}\n❌ غلط: {wrong}\n⬜️ نزده: {blank}\n📊 کل: {total}\n\n{emoji} درصد: {percent:.1f}%",
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
        await update.message.reply_text(f"🎯 هدفت ثبت شد!\n\n«{text}»\n\nهر روز صبح یادت میندازم 💪", reply_markup=main_menu())
        return

    # درد و دل
    if pending.get("step") == "dard_del":
        data["pending"].pop(str(user.id), None)
        save_data(data)
        try: await update.message.delete()
        except: pass
        await context.bot.send_message(update.effective_chat.id, "پاک شد 🍃\nسبک‌تر شدی؟ 💙", reply_markup=more_tools_menu())
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
        await update.message.reply_text(f"✉️ نامه‌ات ثبت شد!\n\nدقیقاً یه ماه دیگه ({to_jalali(send_date)}) تحویلت میدم 🌟", reply_markup=more_tools_menu())
        return

    # یادم بنداز - اسم
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
        await update.message.reply_text(f"ممنون {text} عزیز! 🎓\n\nالان چه پایه‌ای هستی؟", reply_markup=grade_keyboard())

# ── callback ها ──
async def handle_grade_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    grade = query.data.replace("grade_", "")
    data  = load_data()
    pending = data["pending"].get(str(user.id), {})
    if pending.get("step") != "grade": return
    full_name = pending.get("name", user.full_name)
    data["students"][str(user.id)] = {"name": full_name, "username": user.username or "", "joined": get_today(), "grade": grade}
    data["pending"].pop(str(user.id), None)

    # اگه از طریق لینک دعوت اومده بود، به دعوت‌کننده اضافه کن
    ref_id = data.get("pending_referrals", {}).pop(str(user.id), None)
    if ref_id and ref_id in data["students"] and ref_id != str(user.id):
        referrer = data["students"][ref_id]
        referrals = referrer.setdefault("referrals", [])
        if str(user.id) not in referrals:
            referrals.append(str(user.id))
            count = len(referrals)
            try:
                if count % REFERRALS_PER_SESSION == 0:
                    await context.bot.send_message(
                        int(ref_id),
                        f"🎉 تبریک {referrer['name']} عزیز!\n\n"
                        f"تا الان {count} نفر رو با لینک اختصاصی خودت به ربات دعوت کردی و "
                        f"یک جلسه مشاوره تلفنی رایگان جدید برات فعال شد 📞✨\n"
                        f"مشاور باهات هماهنگ میکنه."
                    )
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"🎁 جلسه مشاوره رایگان فعال شد!\n👤 {referrer['name']} (@{referrer.get('username') or 'ندارد'} | {ref_id})\n"
                        f"👥 تعداد دعوت: {count} نفر"
                    )
                else:
                    remaining = REFERRALS_PER_SESSION - (count % REFERRALS_PER_SESSION)
                    await context.bot.send_message(
                        int(ref_id),
                        f"🎁 یه نفر با لینک دعوت تو ثبت‌نام کرد!\n"
                        f"👥 تعداد دعوت‌شده‌ها: {count} نفر\n"
                        f"🎯 {remaining} نفر دیگه تا جلسه مشاوره رایگان بعدی!"
                    )
            except Exception as e:
                logger.warning(f"اطلاع‌رسانی دعوت به {ref_id}: {e}")

    save_data(data)
    await query.edit_message_text(f"✅ ثبت‌نام موفق!\n\nخوش اومدی {full_name} عزیز 🎉\nپایه: {grade}")
    await query.message.reply_text("از دکمه‌های پایین استفاده کن 👇", reply_markup=main_menu())
    await query.message.reply_text(ONBOARDING_MESSAGE)
    try:
        await context.bot.send_message(ADMIN_ID, f"🆕 شاگرد جدید:\n👤 {full_name}\n🎓 پایه: {grade}\n🆔 @{user.username or 'ندارد'}\n🔢 {user.id}")
    except: pass

async def handle_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    not_joined = await check_membership(update.effective_user.id, context.bot)
    if not_joined:
        ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
        await query.edit_message_text(f"هنوز عضو نشدی:\n\n{ch_list}\n\nعضو شو و دوباره بزن.", reply_markup=join_keyboard())
    else:
        await query.edit_message_text("✅ عضویتت تأیید شد!\n\nحالا /start رو بزن.")

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
    data["students"][str(user.id)].setdefault("reminders", []).append({"title": title, "date": remind_date, "hour": hour, "done": False})
    data["pending"].pop(str(user.id), None)
    save_data(data)
    days_labels = ["فردا", "۲ روز دیگه", "۳ روز دیگه", "یه هفته دیگه"]
    await query.edit_message_text(f"✅ یادآوری ثبت شد!\n\n📌 {title}\n📅 {days_labels[REMINDER_DAYS.index(days)]} ساعت {hour}:00")

async def handle_student_report_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    if user.id != ADMIN_ID: return
    data    = load_data()
    pending = data["pending"].get(str(user.id), {})
    logger.info(f"srep callback: user={user.id} step={pending.get('step')} data={pending}")
    if pending.get("step") != "admin_student_period": return

    found_id = pending["student_id"]
    name     = pending["student_name"]
    period   = query.data
    data["pending"].pop(str(user.id), None)
    save_data(data)

    dates = week_dates() if period == "srep_week" else monthly_dates()
    label = "هفتگی" if period == "srep_week" else "ماهانه"
    sinfo = data["students"].get(found_id, {})
    msg   = f"📋 گزارش {label} — {name}\n🎓 {sinfo.get('grade','')}\n" + "━"*20 + "\n\n"

    total_h = total_q = b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
    for d in dates:
        rec  = data["daily_records"].get(d, {}).get(found_id, {})
        b    = rec.get("breakfast"); r = rec.get("report")
        b_st = f"✅{b['time']}" if b and b["on_time"] else (f"⚠️{b['time']}" if b else "❌")
        r_st = f"✅{r['time']} 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌"
        msg += f"📅 {to_jalali(d)}\n   📸{b_st}  📝{r_st}\n"
        if b:
            if b["on_time"]: b_ok+=1
            else: b_late+=1
        else: b_miss+=1
        if r:
            total_h+=r.get("study_hours",0); total_q+=r.get("questions_solved",0)
            if r["on_time"]: r_ok+=1
            else: r_late+=1
        else: r_miss+=1

    msg += "\n" + "━"*20 + "\n"
    msg += f"📸 صبحانه: ✅{b_ok} ⚠️{b_late} ❌{b_miss}\n"
    msg += f"📝 گزارش: ✅{r_ok} ⚠️{r_late} ❌{r_miss}\n"
    msg += f"📚 کل: {total_h} ساعت | ✏️ {total_q} سوال"
    await query.edit_message_text(msg)

# ── گزارش شب ──
async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    if not await is_active_student(update, context, data, str(user.id)):
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
    now       = get_now(); today = get_today()
    data      = load_data()
    name      = data["students"][str(user.id)]["name"]
    q_label   = "+150" if questions == QUESTIONS_OPTIONS[-1] else str(questions)
    if 0 < now.hour < 6:
        await query.edit_message_text("تاخیر داشتیا ثبت نشد.")
        return ConversationHandler.END
    data["daily_records"].setdefault(today, {})
    data["daily_records"][today].setdefault(str(user.id), {})
    data["daily_records"][today][str(user.id)]["report"] = {"time": now.strftime("%H:%M"), "on_time": True, "study_hours": hours, "questions_solved": questions}
    save_data(data)
    await query.edit_message_text(f"✏️ {q_label} سوال ثبت شد.")
    await query.message.reply_text("خداقوت عزیزم❤️ ما حواسمون به تلاشت هست", reply_markup=main_menu())
    if not is_silent(data["students"][str(user.id)]):
        if check_late_streak(data, str(user.id), "report"):
            await query.message.reply_text("از روند گزارش فرستادنت راضی نیستم عزیزم 🙏\nسعی کن فردا به موقع باشی 💪")
        if check_consistent_streak(data, str(user.id)):
            await query.message.reply_text("آفرین! ۳ روز پشت سر هم منظم بودی! 🌟 به همین ادامه بده قهرمان!")
    try:
        await context.bot.send_message(ADMIN_ID, f"📝 گزارش شب\n👤 {name}\n📚 {hours} ساعت | ✏️ {q_label} سوال\n⏰ {now.strftime('%H:%M')}")
    except: pass
    return ConversationHandler.END

async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_menu())
    return ConversationHandler.END

# ── دکمه‌های دانش‌آموز ──
async def btn_wake_time_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    student = data["students"][str(user.id)]
    current = student.get("wake_time"); until = student.get("wake_time_until")
    msg = "⏰ تنظیم اعلام بیداری\n\n"
    if student.get("wake_disabled"):
        msg += "الان حالت «🏫 مدرسه میرم، بیدار میشم» برات فعاله؛ دیگه ازت اعلام بیداری نمیخوام و پیام هشدارآمیزی هم نمیفرستم.\n\n"
    elif current and until and get_today() <= until:
        msg += f"ساعت فعلی‌ت: {current} (تا {to_jalali(until)} معتبره)\n\n"
    msg += (
        "هر روز صبح، تا نیم‌ساعت بعد از ساعتی که الان انتخاب میکنی، عکس صبحونه‌ت رو مستقیم برای من بفرست تا به‌موقع حساب بشه "
        "(نیازی نیست دوباره این دکمه رو بزنی، فقط عکس بفرست کافیه).\n"
        "این تنظیم یک هفته معتبره، بعدش دوباره میتونی عوضش کنی.\n\n"
        "اگه هم مدرسه میری و خودت سرِ وقت بیدار میشی، میتونی دکمه «🏫 مدرسه میرم، بیدار میشم» رو بزنی تا دیگه اصلاً ازت اعلام بیداری نخوام.\n\n"
        "ساعت مورد نظرتو انتخاب کن:"
    )
    await update.message.reply_text(msg, reply_markup=wake_time_keyboard())

async def got_wake_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    chosen = query.data.split("_", 1)[1]
    data = load_data()
    if str(user.id) not in data["students"]:
        await query.edit_message_text("اول /start بزن."); return
    if chosen == "schoolmode":
        data["students"][str(user.id)]["wake_disabled"] = True
        data["students"][str(user.id)].pop("wake_time", None)
        data["students"][str(user.id)].pop("wake_time_until", None)
        save_data(data)
        await query.edit_message_text(
            "🏫 باشه عزیزم!\n\nچون خودت مدرسه میری و سرِ وقت بیدار میشی، دیگه ازت اعلام بیداری نمیخوام و هیچ یادآوری یا "
            "پیام هشدارآمیزی درباره‌ش برات نمیفرستم.\n\n"
            "هر وقت خواستی دوباره فعالش کنی، کافیه دوباره از دکمه «⏰ تنظیم اعلام بیداری» یه ساعت انتخاب کنی."
        )
        return
    until = (get_now().date() + timedelta(days=WAKE_TIME_VALID_DAYS)).strftime("%Y-%m-%d")
    data["students"][str(user.id)]["wake_time"] = chosen
    data["students"][str(user.id)]["wake_time_until"] = until
    data["students"][str(user.id)]["wake_disabled"] = False
    save_data(data)
    await query.edit_message_text(
        f"✅ ثبت شد!\n\nاز فردا هر روز تا نیم‌ساعت بعد از ساعت {chosen} عکس صبحونه‌ت رو بفرست تا به‌موقع حساب بشه.\n"
        f"این تنظیم تا {to_jalali(until)} معتبره."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت فایل JSON از ادمین برای ریستور داده‌ها"""
    user = update.effective_user
    if user.id != ADMIN_ID: return
    doc = update.message.document
    if not doc.file_name.endswith(".json"):
        return
    try:
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(DATA_FILE)
        data = load_data()
        count = len(data.get("students", {}))
        await update.message.reply_text(
            f"✅ داده‌ها با موفقیت بازگردانی شد!\n"
            f"👥 تعداد دانش‌آموزان: {count} نفر",
            reply_markup=admin_menu()
        )
        logger.info(f"داده‌ها بازگردانی شد - {count} دانش‌آموز")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در بازگردانی: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if str(user.id) not in data["students"]: await update.message.reply_text("اول /start بزن."); return
    not_joined = await check_membership(user.id, context.bot)
    if not_joined: await update.message.reply_text("اول باید عضو کانال‌ها بشی.", reply_markup=join_keyboard()); return
    now = get_now(); today = get_today(); name = data["students"][str(user.id)]["name"]
    data["daily_records"].setdefault(today, {}); data["daily_records"][today].setdefault(str(user.id), {})
    if "breakfast" in data["daily_records"][today][str(user.id)]:
        await update.message.reply_text("✅ قبلاً ثبت کردم!", reply_markup=main_menu()); return
    on_time = is_breakfast_on_time(now, data["students"][str(user.id)])
    data["daily_records"][today][str(user.id)]["breakfast"] = {"time": now.strftime("%H:%M"), "on_time": on_time}
    save_data(data)
    if on_time:
        await update.message.reply_text("به موقع فرستادی عزیزم ❤️", reply_markup=main_menu()); status = "✅ به موقع"
    else:
        await update.message.reply_text("با تاخیر فرستادی، تکرارش کنی روی کل انرژیت تاثیر بد میزاره عزیزم 🙏", reply_markup=main_menu()); status = "❌ با تاخیر"
        if not is_silent(data["students"][str(user.id)]) and check_late_streak(data, str(user.id), "breakfast"):
            await update.message.reply_text("از روند اعلام بیداریت راضی نیستم گلم 🙏\nسعی کن فردا به موقع باشی 💪")
    try: await context.bot.send_message(ADMIN_ID, f"📸 عکس صبحانه\n👤 {name}\n⏰ {now.strftime('%H:%M')}\n{status}")
    except: pass

async def btn_dard_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    data["pending"][str(user.id)] = {"step": "dard_del"}; save_data(data)
    await update.message.reply_text("هرچی دلت میخواد بگو 💙\n\nاین پیامی که الان مینویسی هیچکسی بهش دسترسی نداره حتی خودم!\nبا خیال راحت حرف بزن و ذهنتو خالی کن چون نوشتن همیشه جوابه 🌿\n\nبعدش که بفرستی سریع پاکش میکنم چون فکرات به اندازه کافی تو مغزت بودن،\nالان وقتشه کلا پاک بشن! 🍃")

async def btn_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    student = data["students"][str(user.id)]; goal = student.get("goal"); goal_date = student.get("goal_date")
    if goal and goal_date:
        set_date = datetime.strptime(goal_date, "%Y-%m-%d").date(); days_passed = (get_now().date() - set_date).days
        if days_passed < 7:
            await update.message.reply_text(f"🎯 هدف هفتگی‌ات:\n\n«{goal}»\n\n⏳ {7-days_passed} روز تا پایان هفته مونده\nادامه بده قهرمان! 💪"); return
    data["pending"][str(user.id)] = {"step": "goal"}; save_data(data)
    await update.message.reply_text("🎯 هدف هفتگیت چیه؟\n\nیه هدف مشخص بنویس که این هفته میخوای بهش برسی:\n(مثلاً: ۵۰ سوال ریاضی حل کنم یا هر روز ۳ ساعت مطالعه داشته باشم)")

async def btn_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    data["pending"][str(user.id)] = {"step": "percent_correct"}; save_data(data)
    await update.message.reply_text("🧮 درصد سنج\n\nتعداد سوالات **درست** رو بنویس:")

async def btn_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
    for i in range(30):
        d = date_str(i); rec = data["daily_records"].get(d, {}).get(str(user.id), {})
        b = rec.get("breakfast"); r = rec.get("report")
        if b:
            if b["on_time"]: b_ok+=1
            else: b_late+=1
        else: b_miss+=1
        if r:
            if r["on_time"]: r_ok+=1
            else: r_late+=1
        else: r_miss+=1
    total_score = (b_ok*2)+(r_ok*2)-b_late-r_late
    rank = "🏆 افسانه‌ای" if total_score>=100 else "🌟 عالی" if total_score>=70 else "✅ خوب" if total_score>=40 else "⚠️ متوسط" if total_score>=20 else "❌ نیاز به تلاش بیشتر"
    await update.message.reply_text(f"🏅 امتیازات من (۳۰ روز اخیر)\n\n📸 صبحانه:\n   ✅ به موقع: {b_ok} روز\n   ⚠️ با تاخیر: {b_late} روز\n   ❌ نفرستاده: {b_miss} روز\n\n📝 گزارش شب:\n   ✅ به موقع: {r_ok} روز\n   ⚠️ با تاخیر: {r_late} روز\n   ❌ نفرستاده: {r_miss} روز\n\n🎯 امتیاز کل: {total_score}\n{rank}", reply_markup=main_menu())

async def btn_future_letter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    data["pending"][str(user.id)] = {"step": "future_letter"}; save_data(data)
    await update.message.reply_text("✉️ نامه به آینده\n\nبه یک ماه آینده خودت یه نامه بده و دقیقاً همون موقع تحویلش بگیر!\n\nنامه‌ات رو بنویس 👇")

async def btn_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    data["pending"][str(user.id)] = {"step": "reminder_title"}; save_data(data)
    await update.message.reply_text("⏰ یادم بنداز\n\nاسم یادآوری رو بنویس:\n(مثلاً: مطالعه شیمی، تکلیف ریاضی)")

# ── پرسش مستقیم از استاد ──
async def btn_ask_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    await update.message.reply_text("سوالتو مستقیم از استاد بپرس 👇", reply_markup=teacher_link_keyboard())

# ── رکورد های من ──
async def btn_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    uid = str(user.id)
    best_q, best_q_date = 0, None
    best_h, best_h_date = 0, None
    for d in week_dates():
        rep = data["daily_records"].get(d, {}).get(uid, {}).get("report")
        if rep:
            q = rep.get("questions_solved", 0)
            h = rep.get("study_hours", 0)
            if q > best_q: best_q, best_q_date = q, d
            if h > best_h: best_h, best_h_date = h, d
    msg = "🏆 رکورد های من (۷ روز اخیر)\n\n"
    if best_q_date:
        msg += f"✏️ بیشترین تست زده‌شده: {best_q} تست ({to_jalali(best_q_date)})\n"
    else:
        msg += "✏️ هنوز تستی ثبت نکردی.\n"
    if best_h_date:
        msg += f"📚 بیشترین ساعت مطالعه: {best_h} ساعت ({to_jalali(best_h_date)})\n"
    else:
        msg += "📚 هنوز ساعت مطالعه‌ای ثبت نکردی.\n"
    await update.message.reply_text(msg, reply_markup=more_tools_menu())

# ── توربو جادویی ──
async def turbo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)):
        return ConversationHandler.END
    await update.message.reply_text(
        "✨ توربو جادویی\n\n"
        "توربو یعنی چند تا کاری که هر روز می‌خوای انجام بدی تو یه هفته رو بهم می‌گی، "
        "منم هر روز دوبار یادآوری می‌کنم بهت.\n"
        "کم‌وقت می‌گیره ولی تاثیرش جادوییه ✨"
    )
    await update.message.reply_text("چند تا کار می‌خوای تعریف کنی؟ (بین ۱ تا ۷)", reply_markup=turbo_count_keyboard())
    return ASK_TURBO_COUNT

async def got_turbo_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    count = int(query.data.split("_")[1])
    context.user_data["turbo_total"] = count
    context.user_data["turbo_tasks"] = []
    context.user_data["turbo_index"] = 1
    await query.edit_message_text(f"تعداد کارها: {count}")
    await query.message.reply_text("کار شماره ۱ رو بنویس:")
    return ASK_TURBO_TASK

async def got_turbo_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("یه توضیح کامل‌تر بنویس:")
        return ASK_TURBO_TASK
    context.user_data.setdefault("turbo_tasks", []).append(text)
    context.user_data["turbo_index"] = context.user_data.get("turbo_index", 1) + 1
    idx   = context.user_data["turbo_index"]
    total = context.user_data.get("turbo_total", 1)
    if idx <= total:
        await update.message.reply_text(f"کار شماره {idx} رو بنویس:")
        return ASK_TURBO_TASK
    await update.message.reply_text(
        "⏰ چه ساعتی یادآوری کنم؟\n(یادآوری دوم، ساعت ۹ شب، خودکار ارسال میشه)",
        reply_markup=turbo_hour_keyboard()
    )
    return ASK_TURBO_HOUR

async def got_turbo_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    hour  = int(query.data.split("_")[1])
    tasks = context.user_data.get("turbo_tasks", [])
    data  = load_data()
    if str(user.id) not in data["students"]:
        await query.edit_message_text("اول /start بزن."); return ConversationHandler.END
    data["students"][str(user.id)]["turbo"] = {
        "tasks": tasks,
        "hour": hour,
        "start_date": get_today(),
        "sent": {},
    }
    save_data(data)
    tasks_list = "\n".join([f"• {t}" for t in tasks])
    await query.edit_message_text(
        f"✅ توربو جادویی فعال شد!\n\n📋 کارهات:\n{tasks_list}\n\n"
        f"⏰ یادآوری اول: ساعت {hour}:۰۰\n⏰ یادآوری دوم: ساعت {TURBO_SECOND_HOUR}:۰۰\n"
        f"📅 به مدت {TURBO_DAYS} روز"
    )
    return ConversationHandler.END

async def cancel_turbo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_menu())
    return ConversationHandler.END

# ── چت با هوش مصنوعی (Groq) ──
def call_groq(user_message: str) -> str:
    if not GROQ_API_KEY:
        return "⚠️ چت هوش مصنوعی فعلاً روی ربات تنظیم نشده."
    try:
        payload = json.dumps({
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "تو یه دستیار هوشمند و دلسوز برای دانش‌آموزای ایرانی هستی. کوتاه، دوستانه، محترمانه و به زبان فارسی جواب بده."},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 600,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; HamyarBot/1.0)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        logger.warning(f"خطای Groq: HTTP {e.code} - {body}")
        return "⚠️ الان نتونستم جواب بدم، چند لحظه دیگه دوباره امتحان کن."
    except Exception as e:
        logger.warning(f"خطای Groq: {e}")
        return "⚠️ الان نتونستم جواب بدم، چند لحظه دیگه دوباره امتحان کن."

async def btn_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    data["pending"][str(user.id)] = {"step": "ai_chat"}
    save_data(data)
    await update.message.reply_text(
        "🤖 چت با من\n\nهرچی میخوای بپرس، جواب میدم!\nبرای خروج «🔙 پایان چت» رو بزن.",
        reply_markup=chat_exit_menu()
    )

async def btn_chat_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    data["pending"].pop(str(user.id), None)
    save_data(data)
    await update.message.reply_text("چت تموم شد 👋", reply_markup=main_menu())

# ── دعوت از دوستان ──
async def btn_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if str(user.id) not in data["students"]:
        await update.message.reply_text("اول /start بزن."); return
    await update.message.reply_text(GUIDE_MESSAGE, reply_markup=main_menu())

async def btn_silent_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    student = data["students"][str(user.id)]
    if student.get("silent_mode"):
        student["silent_mode"] = False
        save_data(data)
        await update.message.reply_text(
            "🔔 باشه عزیزم، یادآوری‌ها رو دوباره فعال کردم و از این به بعد مثل قبل کنارتم 🤍",
            reply_markup=main_menu()
        )
    else:
        student["silent_mode"] = True
        save_data(data)
        await update.message.reply_text(
            "چشم عزیزم، من یادآوری‌ها رو فعلا خاموش می‌کنم تا دوباره خودت فعالش کنی 🤍\n\n"
            "تا وقتی این حالت روشنه، هیچ پیامی جز پیام‌های مشاور برات نمیفرستم (نه یادآوری صبحونه، نه گزارش شب، نه پیام‌های انگیزشی، هیچی).\n\n"
            "هر وقت آماده بودی، فقط کافیه دوباره دکمه «🔕 سکوت موقت» رو بزنی تا همه چی مثل قبل روشن بشه.",
            reply_markup=main_menu()
        )

async def btn_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    student = data["students"][str(user.id)]
    leave_until = student.get("leave_until")
    if leave_until and get_today() <= leave_until:
        reason_fa = "🤒 مریضی" if student.get("leave_reason") == "sick" else "💼 کار داشتن"
        await update.message.reply_text(
            f"🌴 الان تو مرخصی هستی ({reason_fa}) تا {to_jalali(leave_until)}.\n\n"
            "تا اون موقع فقط پیام‌های مشاور برات میاد. اگه میخوای زودتر تمومش کنی، بزن:",
            reply_markup=leave_end_keyboard()
        )
        return
    await update.message.reply_text(
        "🌴 مرخصی\n\nدلیل مرخصیت چیه؟",
        reply_markup=leave_reason_keyboard()
    )

async def handle_leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = update.effective_user; data = load_data()
    if str(user.id) not in data["students"]:
        await query.edit_message_text("اول /start بزن."); return
    reason = query.data.split("_", 1)[1]
    data["pending"][str(user.id)] = {"step": "leave_days", "leave_reason": reason}
    save_data(data)
    await query.edit_message_text("چند روز مرخصی میخوای؟ (بین ۱ تا ۷ روز)", reply_markup=leave_days_keyboard())

async def handle_leave_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = update.effective_user; data = load_data()
    if str(user.id) not in data["students"]:
        await query.edit_message_text("اول /start بزن."); return
    days = int(query.data.split("_", 1)[1])
    pending = data["pending"].get(str(user.id), {})
    reason = pending.get("leave_reason", "busy")
    leave_until = (get_now().date() + timedelta(days=days-1)).strftime("%Y-%m-%d")
    data["students"][str(user.id)]["leave_until"]  = leave_until
    data["students"][str(user.id)]["leave_reason"] = reason
    data["students"][str(user.id)]["leave_days"]   = days
    data["pending"].pop(str(user.id), None)
    save_data(data)
    reason_fa = "🤒 مریضی" if reason == "sick" else "💼 کار داشتن"
    await query.edit_message_text(
        f"🌴 مرخصیت ثبت شد!\n\nدلیل: {reason_fa}\nمدت: {days} روز (تا {to_jalali(leave_until)})\n\n"
        "تا اون موقع دیگه هیچ یادآوری یا پیامی از ربات برات نمیاد، فقط پیام‌های مشاور بهت میرسه. "
        "بعد از تموم شدن مرخصی، ربات خودکار برمیگرده به حالت عادی.\n\n"
        "اگه هر وقت خواستی زودتر تمومش کنی، از «🧰 ابزارهای بیشتر» دوباره «🌴 مرخصی» رو بزن."
    )

async def handle_leave_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = update.effective_user; data = load_data()
    if str(user.id) not in data["students"]:
        await query.edit_message_text("اول /start بزن."); return
    student = data["students"][str(user.id)]
    student.pop("leave_until", None); student.pop("leave_reason", None); student.pop("leave_days", None)
    save_data(data)
    await query.edit_message_text("🔔 مرخصیت تموم شد، خوش اومدی! از الان دوباره طبق روال قبل کنارتم 🤍")

async def btn_more_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    await update.message.reply_text("🧰 ابزارهای بیشتر:", reply_markup=more_tools_menu())

async def btn_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    await update.message.reply_text("برگشتی به منوی اصلی 👇", reply_markup=main_menu())

async def btn_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data()
    if not await is_active_student(update, context, data, str(user.id)): return
    student   = data["students"][str(user.id)]
    referrals = student.get("referrals", [])
    count     = len(referrals)
    sessions_earned = count // REFERRALS_PER_SESSION
    remaining = REFERRALS_PER_SESSION - (count % REFERRALS_PER_SESSION) if count % REFERRALS_PER_SESSION else REFERRALS_PER_SESSION
    link = referral_link(user.id)
    msg = (
        "🎁 دریافت مشاوره رایگان\n\n"
        f"لینک اختصاصی خودت:\n{link}\n\n"
        f"هر دوستی که با این لینک وارد ربات بشه و ثبت‌نام کنه، برات حساب میشه.\n"
        f"به ازای هر {REFERRALS_PER_SESSION} نفر دعوت، یک جلسه مشاوره تلفنی رایگان میگیری! 📞✨\n\n"
        f"👥 تعداد دعوت‌شده‌ها: {count} نفر\n"
        f"🏆 جلسات رایگان گرفته‌شده: {sessions_earned}\n"
        f"🎯 {remaining} نفر دیگه تا جایزه بعدی"
    )
    await update.message.reply_text(msg, reply_markup=more_tools_menu())

# ── دکمه‌های ادمین ──
async def send_long_message(update, text, **kwargs):
    """ارسال پیام طولانی به چند بخش - حد مجاز تلگرام ۴۰۹۶ کاراکتره"""
    max_len = 4000
    if len(text) <= max_len:
        await update.message.reply_text(text, **kwargs)
        return
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text); break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1: split_at = max_len
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    for i, part in enumerate(parts):
        if i == 0:
            await update.message.reply_text(part, **kwargs)
        else:
            await update.message.reply_text(part)

async def admin_btn_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []; await cmd_summary(update, context)

async def admin_btn_student_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_student_name"}; save_data(data)
    await update.message.reply_text("اسم و فامیل دانش‌آموز رو بنویس:")

async def admin_btn_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []; await cmd_ranking(update, context)

async def admin_btn_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.args = []; await cmd_weekly(update, context)

async def admin_btn_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await cmd_students(update, context)

async def admin_btn_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "admin_remove"}; save_data(data)
    await update.message.reply_text("اسم و فامیل دانش‌آموزی که میخوای حذف کنی رو بنویس:")

# ── جاب‌ها ──
async def job_wake_time_check(context: ContextTypes.DEFAULT_TYPE):
    """هر ۱۰ دقیقه اجرا میشه؛ بر اساس ساعت شخصیِ هر دانش‌آموز (نه یه ساعت ثابت برای همه)،
    سر ساعت انتخابیش یادآوری میفرسته و نیم‌ساعت بعدش (اگه بازم نفرستاده) هشدار میفرسته."""
    data = load_data(); today = get_today(); now = get_now(); changed = False
    for sid, student in data["students"].items():
        if student.get("wake_disabled") or is_silent(student):
            continue
        rec = data["daily_records"].setdefault(today, {}).setdefault(sid, {})
        if "breakfast" in rec:
            continue
        start, end = wake_time_window(now, student)
        if not rec.get("wake_reminder_sent") and start <= now < start + timedelta(minutes=10):
            try:
                await context.bot.send_message(int(sid), "صبحت بخیر عزیزدلم ❤️ وقتشه عکس صبحونتو بفرستی 😎")
                rec["wake_reminder_sent"] = True; changed = True
            except Exception as e:
                logger.warning(f"یادآوری اعلام بیداری {sid}: {e}")
        if not rec.get("wake_late_sent") and end <= now < end + timedelta(minutes=10):
            try:
                await context.bot.send_message(int(sid), "اعلام بیداری نکردیا 😒")
                rec["wake_late_sent"] = True; changed = True
            except Exception as e:
                logger.warning(f"هشدار دیرکرد اعلام بیداری {sid}: {e}")
    if changed: save_data(data)

async def job_report_reminder(context: ContextTypes.DEFAULT_TYPE):
    """ساعت ۱۱ شب؛ فقط به کسایی که هنوز گزارش نفرستادن یادآوری میکنه."""
    data = load_data(); today = get_today()
    for sid, student in data["students"].items():
        if is_silent(student):
            continue
        rec = data["daily_records"].get(today, {}).get(sid, {})
        if "report" in rec:
            continue
        try: await context.bot.send_message(int(sid), "گزارش کار فراموش نشه قهرمان😍")
        except Exception as e: logger.warning(f"یادآوری گزارش {sid}: {e}")

async def job_motivation(context: ContextTypes.DEFAULT_TYPE):
    quote = get_daily_quote(get_day_index())
    for sid, student in load_data()["students"].items():
        if is_silent(student):
            continue
        try: await context.bot.send_message(int(sid), quote)
        except Exception as e: logger.warning(f"انگیزشی {sid}: {e}")

async def job_goal_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); today = get_now().date(); changed = False
    for sid, sinfo in data["students"].items():
        goal = sinfo.get("goal"); goal_date = sinfo.get("goal_date")
        if not goal or not goal_date: continue
        set_date = datetime.strptime(goal_date, "%Y-%m-%d").date(); days_passed = (today - set_date).days
        if days_passed >= 7:
            if not is_silent(sinfo):
                try: await context.bot.send_message(int(sid), "🎯 یه هفته گذشت!\n\nوقتشه یه هدف جدید برای هفته جدید تعریف کنی 💪\nدکمه «🎯 هدف هفتگی» رو بزن.")
                except: pass
            data["students"][sid].pop("goal", None); data["students"][sid].pop("goal_date", None); changed = True
        else:
            if not is_silent(sinfo):
                try: await context.bot.send_message(int(sid), f"🎯 هدف هفتگیت:\n\n«{goal}»\n\n⏳ {7-days_passed} روز مونده! ادامه بده 💪")
                except: pass
    if changed: save_data(data)

async def job_check_reminders(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); now = get_now(); today = get_today(); changed = False
    for sid, sinfo in data["students"].items():
        if is_silent(sinfo):
            continue
        for rem in sinfo.get("reminders", []):
            if rem["done"]: continue
            if rem["date"] == today and now.hour >= rem["hour"]:
                try: await context.bot.send_message(int(sid), f"⏰ یادآوری: {rem['title']}"); rem["done"] = True; changed = True
                except Exception as e: logger.warning(f"یادآوری {sid}: {e}")
    if changed: save_data(data)

async def job_late_report_check(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); today = get_today()
    for sid, student in data["students"].items():
        if is_silent(student):
            continue
        rec = data["daily_records"].get(today, {}).get(sid, {})
        if "report" not in rec:
            try: await context.bot.send_message(int(sid), "گزارشتو نفرستادیا 😏")
            except Exception as e: logger.warning(f"چک گزارش دیرکرد {sid}: {e}")

def compute_missing_report_streak(data, sid, joined_date_str):
    """چند روز متوالی (تا امروز) این دانش‌آموز گزارش نفرستاده رو حساب میکنه."""
    today = get_now().date()
    try:
        joined = datetime.strptime(joined_date_str, "%Y-%m-%d").date()
    except Exception:
        joined = today
    streak = 0
    d = today
    while d >= joined:
        ds = d.strftime("%Y-%m-%d")
        rec = data["daily_records"].get(ds, {}).get(sid, {})
        if "report" in rec:
            break
        streak += 1
        d -= timedelta(days=1)
    return streak

async def job_report_streak_check(context: ContextTypes.DEFAULT_TYPE):
    """پیام دلسوزانه بر اساس استریک عدم‌ارسال گزارش میفرسته.
    به‌جای چک «دقیقاً مساوی» (که با یه‌روز خاموشی ربات برای همیشه از دست میره)،
    بالاترین آستانه‌ای که رد شده ولی هنوز پیامش نرفته رو پیدا میکنه و میفرسته - یعنی اگه یه شب جا بمونه، شب بعد جبران میشه."""
    data = load_data(); changed = False
    for sid, sinfo in data["students"].items():
        if is_silent(sinfo):
            continue
        streak = compute_missing_report_streak(data, sid, sinfo.get("joined"))
        last_sent = sinfo.get("last_streak_alert", 0)
        if streak == 0:
            if last_sent:
                sinfo["last_streak_alert"] = 0
                changed = True
            continue
        eligible = [t for t in REPORT_STREAK_MESSAGES if last_sent < t <= streak]
        if not eligible:
            continue
        threshold = max(eligible)
        try:
            await context.bot.send_message(int(sid), REPORT_STREAK_MESSAGES[threshold])
            sinfo["last_streak_alert"] = threshold
            changed = True
        except Exception as e:
            logger.warning(f"پیام نگرانی گزارش (استریک {threshold}) به {sid}: {e}")
    if changed: save_data(data)

async def job_turbo_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); now = get_now(); today = get_today(); hour = now.hour; changed = False
    for sid, sinfo in data["students"].items():
        if is_silent(sinfo): continue
        turbo = sinfo.get("turbo")
        if not turbo: continue
        try:
            start = datetime.strptime(turbo["start_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if (now.date() - start).days >= TURBO_DAYS:
            continue
        if hour not in (turbo.get("hour"), TURBO_SECOND_HOUR):
            continue
        sent_today = turbo.setdefault("sent", {}).get(today, [])
        if hour in sent_today:
            continue
        tasks_list = "\n".join([f"• {t}" for t in turbo.get("tasks", [])])
        try:
            await context.bot.send_message(int(sid), f"✨ یادآوری توربو جادویی\n\n{tasks_list}")
            turbo["sent"].setdefault(today, []).append(hour)
            changed = True
        except Exception as e:
            logger.warning(f"یادآوری توربو {sid}: {e}")
    if changed: save_data(data)

async def job_prune_old_records(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    removed = prune_old_records(data)
    if removed:
        save_data(data)
        logger.info(f"پاکسازی خودکار: {removed} روز رکورد قدیمی حذف شد (اطلاعات دانش‌آموزا دست‌نخورده موند)")

async def job_check_membership(context: ContextTypes.DEFAULT_TYPE):
    """هر چند ساعت چک میکنه ببینه کسی از کانال‌های اجباری لفت داده یا نه، اگه آره پیام میده."""
    data = load_data()
    for sid, student in list(data["students"].items()):
        if is_silent(student):
            continue
        try:
            not_joined = await check_membership(int(sid), context.bot)
        except Exception as e:
            logger.warning(f"چک عضویت دوره‌ای {sid}: {e}")
            await asyncio.sleep(0.1)
            continue
        if not_joined:
            ch_list = "\n".join([f"• {ch['title']}" for ch in not_joined])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 {ch['title']}", url=f"https://t.me/{ch['username'].lstrip('@')}")]
                for ch in not_joined
            ])
            try:
                await context.bot.send_message(
                    int(sid),
                    f"👋 دیدم از این کانال خارج شدی:\n\n{ch_list}\n\n"
                    f"برای اینکه بتونی همچنان از ربات استفاده کنی، لطفاً دوباره عضو شو 🙏",
                    reply_markup=kb,
                )
            except Exception as e:
                logger.warning(f"پیام یادآوری عضویت به {sid}: {e}")
        await asyncio.sleep(0.1)

async def job_check_letters(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(); today = get_today(); changed = False
    for sid, sinfo in data["students"].items():
        letter = sinfo.get("future_letter"); letter_date = sinfo.get("future_letter_date")
        if letter and letter_date and letter_date <= today:
            if is_silent(sinfo):
                continue  # نامه نگه داشته میشه تا وقتی سکوت موقت رو خودش خاموش کنه
            try:
                await context.bot.send_message(int(sid), f"✉️ نامه‌ای که یه ماه پیش به خودت نوشتی:\n\n«{letter}»\n\nچطوری؟ به اهدافت رسیدی؟ 🌟")
                data["students"][sid].pop("future_letter", None); data["students"][sid].pop("future_letter_date", None); changed = True
            except Exception as e: logger.warning(f"نامه به آینده {sid}: {e}")
    if changed: save_data(data)

async def job_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """هر پنجشنبه شب، خلاصه عملکرد هفتگی رو خودکار برای دانش‌آموزا میفرسته."""
    data = load_data()
    for sid, student in data["students"].items():
        if is_silent(student):
            continue
        b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
        for d in week_dates():
            rec = data["daily_records"].get(d, {}).get(sid, {})
            b = rec.get("breakfast"); r = rec.get("report")
            if b:
                if b["on_time"]: b_ok += 1
                else: b_late += 1
            else: b_miss += 1
            if r:
                if r["on_time"]: r_ok += 1
                else: r_late += 1
            else: r_miss += 1
        score = (b_ok*2)+(r_ok*2)-b_late-r_late
        rank = ("🏆 افسانه‌ای" if score >= 24 else "🌟 عالی" if score >= 16 else
                 "✅ خوب" if score >= 8 else "⚠️ متوسط" if score >= 2 else "❌ نیاز به تلاش بیشتر")
        msg = (
            "📊 خلاصه عملکرد این هفته‌ت:\n\n"
            f"📸 صبحونه:\n   ✅ به‌موقع: {b_ok} روز\n   ⚠️ با تاخیر: {b_late} روز\n   ❌ نفرستاده: {b_miss} روز\n\n"
            f"📝 گزارش شب:\n   ✅ به‌موقع: {r_ok} روز\n   ⚠️ با تاخیر: {r_late} روز\n   ❌ نفرستاده: {r_miss} روز\n\n"
            f"🎯 امتیاز این هفته: {score}\n{rank}\n\n"
            "هفته بعد بهتر از این هفته باش قهرمان 💪"
        )
        try: await context.bot.send_message(int(sid), msg)
        except Exception as e: logger.warning(f"خلاصه هفتگی {sid}: {e}")
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args if context.args else []
    data = load_data(); today = get_today(); records = data["daily_records"].get(today, {})
    students = data["students"]
    if args:
        students = {sid: s for sid, s in students.items() if s.get("grade") == args[0]}
        title = f"📊 گزارش امروز - پایه {args[0]} ({to_jalali(today)})"
    else:
        title = f"📊 گزارش امروز ({to_jalali(today)})"
    msg = title + "\n" + "━"*25 + "\n\n"
    for sid, sinfo in students.items():
        rec = records.get(sid, {}); b = rec.get("breakfast"); r = rec.get("report")
        b_st = f"✅ {b['time']}" if b and b["on_time"] else (f"⚠️ {b['time']}" if b else "❌ نفرستاده")
        r_st = f"✅ {r['time']} | 📚{r.get('study_hours',0)}h ✏️{r.get('questions_solved',0)}" if r else "❌ نفرستاده"
        msg += f"👤 {sinfo['name']} ({sinfo.get('grade','')})\n   📸 {b_st}\n   📝 {r_st}\n\n"
    if not students: msg += "کسی ثبت‌نام نکرده."
    await send_long_message(update, msg)

async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        with open(DATA_FILE, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"backup_{get_today()}.json",
                caption=f"💾 فایل داده‌ها | {get_today()}"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

async def job_backup(context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(DATA_FILE, "rb") as f:
            await context.bot.send_document(
                ADMIN_ID,
                document=f,
                filename=f"backup_{get_today()}.json",
                caption=f"💾 پشتیبان روزانه | {get_today()}"
            )
    except Exception as e:
        logger.warning(f"خطا در پشتیبان‌گیری: {e}")

async def admin_btn_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await cmd_backup(update, context)

async def admin_btn_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data()
    data["pending"][str(update.effective_user.id)] = {"step": "broadcast"}
    save_data(data)
    await update.message.reply_text("📣 پیام به همه\n\nپیامت رو بنویس:")

async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data(); students = data["students"]
    if not students: await update.message.reply_text("هنوز کسی ثبت‌نام نکرده."); return
    by_grade = {}
    for sid, s in students.items(): by_grade.setdefault(s.get("grade", "نامشخص"), []).append(s["name"])
    msg = f"👥 لیست شاگردها ({len(students)} نفر)\n\n"
    for grade in GRADES + ["نامشخص"]:
        if grade in by_grade:
            msg += f"🎓 پایه {grade} ({len(by_grade[grade])} نفر):\n"
            for name in by_grade[grade]: msg += f"   • {name}\n"
            msg += "\n"
    await send_long_message(update, msg)

async def cmd_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    data = load_data(); students = data["students"]
    if not students: await update.message.reply_text("هنوز کسی ثبت‌نام نکرده."); return
    dates = week_dates()
    inactive = []
    for sid, s in students.items():
        active = False
        for d in dates:
            rec = data["daily_records"].get(d, {}).get(sid, {})
            if "breakfast" in rec or "report" in rec:
                active = True
                break
        if not active:
            inactive.append(s["name"])
    msg = f"😴 غیرفعال‌های ۷ روز اخیر\n\n{len(inactive)} از {len(students)} نفر، تو یک هفته اخیر هیچ صبحانه یا گزارشی نفرستادن:\n\n"
    if inactive:
        msg += "\n".join([f"• {name}" for name in inactive])
    else:
        msg += "🎉 همه فعال بودن!"
    await send_long_message(update, msg)

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: await update.message.reply_text("مثال: /remove علی محمدی"); return
    target = " ".join(context.args).strip(); data = load_data(); found_id = None
    for sid, s in data["students"].items():
        if s["name"] == target: found_id = sid; break
    if not found_id: await update.message.reply_text(f"❌ «{target}» پیدا نشد."); return
    del data["students"][found_id]
    for d in data["daily_records"]: data["daily_records"][d].pop(found_id, None)
    save_data(data)
    await update.message.reply_text(f"✅ «{target}» حذف شد.")

async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args if context.args else []
    data = load_data(); dates = week_dates()
    students = {sid: s for sid, s in data["students"].items() if s.get("grade") == args[0]} if args else data["students"]
    title = f"🏆 رتبه‌بندی هفتگی{' - پایه '+args[0] if args else ''}"
    totals = {}
    for sid, sinfo in students.items():
        h = q = 0
        for d in dates:
            rep = data["daily_records"].get(d, {}).get(sid, {}).get("report")
            if rep: h+=rep.get("study_hours",0); q+=rep.get("questions_solved",0)
        totals[sid] = {"name": sinfo["name"], "grade": sinfo.get("grade",""), "hours": h, "questions": q}
    ranked = sorted(totals.values(), key=lambda t:(t["hours"],t["questions"]), reverse=True)
    medals = ["🥇","🥈","🥉"]
    msg = title + "\n" + "━"*20 + "\n\n"
    for i, t in enumerate(ranked): msg += f"{medals[i] if i<3 else str(i+1)+'.'} {t['name']} ({t['grade']})\n   📚 {t['hours']} ساعت  |  ✏️ {t['questions']} سوال\n\n"
    if not ranked: msg += "کسی ثبت‌نام نکرده."
    await send_long_message(update, msg)

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args if context.args else []
    data = load_data(); dates = week_dates()
    students = {sid: s for sid, s in data["students"].items() if s.get("grade") == args[0]} if args else data["students"]
    chart_title = f"Weekly Report{' - '+args[0] if args else ''}"
    totals = {}
    for sid, sinfo in students.items():
        h = q = 0
        for d in dates:
            rep = data["daily_records"].get(d, {}).get(sid, {}).get("report")
            if rep: h+=rep.get("study_hours",0); q+=rep.get("questions_solved",0)
        totals[sid] = {"name": sinfo["name"], "hours": h, "questions": q}
    if not totals: await update.message.reply_text("داده‌ای برای نمایش وجود نداره."); return
    names=[t["name"] for t in totals.values()]; hours=[t["hours"] for t in totals.values()]; questions=[t["questions"] for t in totals.values()]
    fig, ax = plt.subplots(figsize=(max(8,len(names)*1.5),6)); x=range(len(names)); w=0.35
    b1=ax.bar([i-w/2 for i in x],hours,w,label="Study Hours",color="#4CAF50",zorder=3)
    b2=ax.bar([i+w/2 for i in x],questions,w,label="Questions Solved",color="#2196F3",zorder=3)
    for bar in list(b1)+list(b2): ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+0.3,str(int(bar.get_height())),ha="center",va="bottom",fontsize=9)
    ax.set_xticks(list(x)); ax.set_xticklabels(names,rotation=25,ha="right",fontsize=10)
    ax.set_title(chart_title,fontsize=13,fontweight="bold"); ax.legend(); ax.grid(axis="y",linestyle="--",alpha=0.5,zorder=0)
    fig.tight_layout(); path=os.path.join(CHARTS_DIR,"weekly.png"); fig.savefig(path,dpi=150); plt.close(fig)
    with open(path,"rb") as img: await update.message.reply_photo(img, caption=f"📊 {chart_title}")

async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args if context.args else []
    data = load_data(); dates = monthly_dates()
    students = {sid: s for sid, s in data["students"].items() if s.get("grade") == args[0]} if args else data["students"]
    title = f"📅 گزارش ماهانه{' - پایه '+args[0] if args else ''} (۳۰ روز اخیر)"
    msg = title + "\n" + "━"*25 + "\n\n"
    for sid, sinfo in students.items():
        h = q = b_ok = b_late = b_miss = r_ok = r_late = r_miss = 0
        for d in dates:
            rec = data["daily_records"].get(d, {}).get(sid, {}); b = rec.get("breakfast"); r = rec.get("report")
            if b:
                if b["on_time"]: b_ok+=1
                else: b_late+=1
            else: b_miss+=1
            if r:
                h+=r.get("study_hours",0); q+=r.get("questions_solved",0)
                if r["on_time"]: r_ok+=1
                else: r_late+=1
            else: r_miss+=1
        msg += f"👤 {sinfo['name']} ({sinfo.get('grade','')})\n   📸 صبحانه: ✅{b_ok} ⚠️{b_late} ❌{b_miss}\n   📝 گزارش: ✅{r_ok} ⚠️{r_late} ❌{r_miss}\n   📚 {h} ساعت | ✏️ {q} سوال\n\n"
    if not students: msg += "کسی ثبت‌نام نکرده."
    await send_long_message(update, msg)

# ── main ──
async def on_startup(app: Application):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username
    logger.info(f"یوزرنیم ربات: @{BOT_USERNAME}")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start",    start))
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

    turbo_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✨ توربو جادویی$"), turbo_start)],
        states={
            ASK_TURBO_COUNT: [CallbackQueryHandler(got_turbo_count, pattern=r"^turbocount_\d+$")],
            ASK_TURBO_TASK:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_turbo_task)],
            ASK_TURBO_HOUR:  [CallbackQueryHandler(got_turbo_hour, pattern=r"^turbohour_\d+$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_turbo)],
        allow_reentry=True,
    )
    app.add_handler(turbo_conv)

    # دکمه‌های دانش‌آموز
    app.add_handler(MessageHandler(filters.Regex("^⏰ تنظیم اعلام بیداری$"), btn_wake_time_setting))
    app.add_handler(MessageHandler(filters.Regex("^💬 درد و دل$"),          btn_dard_del))
    app.add_handler(MessageHandler(filters.Regex("^🎯 هدف هفتگی$"),         btn_goal))
    app.add_handler(MessageHandler(filters.Regex("^🧮 درصد سنج$"),          btn_percentage))
    app.add_handler(MessageHandler(filters.Regex("^✉️ نامه به آینده$"),     btn_future_letter))
    app.add_handler(MessageHandler(filters.Regex("^🏅 امتیازات من$"),       btn_score))
    app.add_handler(MessageHandler(filters.Regex("^⏰ یادم بنداز$"),        btn_reminder))
    app.add_handler(MessageHandler(filters.Regex("^🎓 پرسش مستقیم از استاد$"), btn_ask_teacher))
    app.add_handler(MessageHandler(filters.Regex("^🏆 رکورد های من$"),      btn_records))
    app.add_handler(MessageHandler(filters.Regex("^🤖 چت با من$"),          btn_chat))
    app.add_handler(MessageHandler(filters.Regex("^🔙 پایان چت$"),         btn_chat_exit))
    app.add_handler(MessageHandler(filters.Regex("^🎁 دریافت مشاوره رایگان$"), btn_invite))
    app.add_handler(MessageHandler(filters.Regex("^📖 آموزش کار با ربات$"),  btn_guide))
    app.add_handler(MessageHandler(filters.Regex("^🔕 سکوت موقت$"),         btn_silent_mode))
    app.add_handler(MessageHandler(filters.Regex("^🧰 ابزارهای بیشتر$"),    btn_more_tools))
    app.add_handler(MessageHandler(filters.Regex("^🌴 مرخصی$"),            btn_leave))
    app.add_handler(MessageHandler(filters.Regex("^🔙 بازگشت به منوی اصلی$"), btn_back_to_main))

    # دکمه‌های ادمین
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش امروز$"),      admin_btn_summary))
    app.add_handler(MessageHandler(filters.Regex("^👤 گزارش دانش‌آموز$"),  admin_btn_student_report))
    app.add_handler(MessageHandler(filters.Regex("^🏆 رتبه‌بندی هفتگی$"),  admin_btn_ranking))
    app.add_handler(MessageHandler(filters.Regex("^📈 نمودار هفتگی$"),     admin_btn_weekly))
    app.add_handler(MessageHandler(filters.Regex("^👥 لیست دانش‌آموزا$"),  admin_btn_students))
    app.add_handler(MessageHandler(filters.Regex("^❌ حذف دانش‌آموز$"),    admin_btn_remove))
    app.add_handler(MessageHandler(filters.Regex("^📣 پیام به همه$"),       admin_btn_broadcast))
    app.add_handler(MessageHandler(filters.Regex("^💾 بکاپ داده‌ها$"),      admin_btn_backup))
    app.add_handler(MessageHandler(filters.Regex("^😴 غیرفعال‌های هفته اخیر$"), cmd_inactive))

    app.add_handler(MessageHandler(filters.Document.MimeType("application/json"), handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_grade_selection,       pattern=r"^grade_"))
    app.add_handler(CallbackQueryHandler(handle_check_join,            pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(handle_reminder_day,          pattern=r"^rday_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_reminder_hour,         pattern=r"^rhour_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_student_report_period, pattern=r"^srep_"))
    app.add_handler(CallbackQueryHandler(got_wake_time,                pattern=r"^waketime_"))
    app.add_handler(CallbackQueryHandler(handle_leave_reason,          pattern=r"^leavereason_"))
    app.add_handler(CallbackQueryHandler(handle_leave_days,            pattern=r"^leavedays_"))
    app.add_handler(CallbackQueryHandler(handle_leave_end,             pattern=r"^leaveend$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,    handle_text))

    app.add_handler(ChatMemberHandler(on_channel_membership_change, ChatMemberHandler.CHAT_MEMBER))

    jq = app.job_queue
    jq.run_daily(job_report_reminder,    time=time(19,30, tzinfo=pytz.utc), name="report_reminder")# ۲۳:۰۰ تهران
    jq.run_daily(job_motivation,         time=time(6,  0, tzinfo=pytz.utc), name="motivation")
    jq.run_daily(job_goal_reminder,      time=time(5,  0, tzinfo=pytz.utc), name="goal_reminder")
    jq.run_daily(job_check_letters,      time=time(5, 30, tzinfo=pytz.utc), name="letters")
    jq.run_daily(job_weekly_summary,     time=time(16,30, tzinfo=pytz.utc), days=(3,), name="weekly_summary")  # پنجشنبه ۲۰:۰۰ تهران
    jq.run_daily(job_backup,             time=time(20,30, tzinfo=pytz.utc), name="backup")
    jq.run_daily(job_late_report_check,    time=time(20,25, tzinfo=pytz.utc), name="late_report_check")   # ۲۳:۵۵ تهران
    jq.run_daily(job_report_streak_check,  time=time(20,27, tzinfo=pytz.utc), name="report_streak_check") # ۲۳:۵۷ تهران
    jq.run_daily(job_prune_old_records,    time=time(1, 0,  tzinfo=pytz.utc), name="prune_old_records")   # ۴:۳۰ تهران
    jq.run_repeating(job_wake_time_check, interval=600, first=60,             name="wake_time_check")     # هر ۱۰ دقیقه
    jq.run_repeating(job_check_membership, interval=21600, first=300,       name="check_membership")      # هر ۶ ساعت
    jq.run_repeating(job_turbo_reminder,  interval=1800, first=30,          name="turbo_reminder")
    jq.run_repeating(job_check_reminders, interval=600, first=10,           name="reminders")

    logger.info("✅ ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
