import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import json
import os
import base64
import datetime
from sambanova import SambaNova, SambaNovaError
from flask import Flask
from threading import Thread

# --- تنظیمات Flask برای زنده نگه داشتن ربات در Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running correctly!"

def run_web_server():
    # دریافت پورت از متغیرهای محیطی یا استفاده از 8080 پیش‌فرض
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# --- تنظیمات اولیه و متغیرهای محیطی ---
# نکته مهم: بهتر است توکن‌ها را مستقیماً در کد نگذارید و از os.environ استفاده کنید
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA")
SAMBA_API_KEY = os.environ.get("SAMBA_API_KEY", "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa")
INITIAL_ADMIN_ID = int(os.environ.get("INITIAL_ADMIN_ID", 5789565027))

# فایل‌های ذخیره‌سازی
CONFIG_FILE = "config.json"
USERS_FILE = "users.json"
PLANS_FILE = "plans.json"
FORCE_SUB_CHANNELS_FILE = "force_sub_channels.json"
DAILY_MESSAGE_COUNTS_FILE = "daily_message_counts.json"

# مدل‌های هوش مصنوعی
VISION_MODELS = ["Llama-4-Maverick-17B-128E-Instruct"]
TEXT_MODELS = ["DeepSeek-V3.1", "gpt-oss-120b", "Qwen3-32B", "ALLaM-7B-Instruct-preview"]
ALL_AI_MODELS = VISION_MODELS + TEXT_MODELS

# تنظیمات لاگ‌گیری
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- راه‌اندازی ربات تلگرام ---
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ساخت کلاینت SambaNova
samba_client = None
try:
    samba_client = SambaNova(api_key=SAMBA_API_KEY)
    logger.info("SambaNova client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize SambaNova client: {e}")

# --- توابع مدیریت فایل (بارگذاری/ذخیره JSON) ---
def load_json_file(filename, default_value=None):
    if default_value is None:
        default_value = {} if filename not in [USERS_FILE, FORCE_SUB_CHANNELS_FILE] else []
    if not os.path.exists(filename) or os.stat(filename).st_size == 0:
        return default_value
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, Exception) as e:
        logger.error(f"Error loading {filename}: {e}")
        return default_value

def save_json_file(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")

# بارگذاری اولیه تنظیمات و داده‌ها
config = load_json_file(CONFIG_FILE, default_value={
    "admins": [INITIAL_ADMIN_ID],
    "force_subscribe_enabled": False,
    "free_tier_enabled": True,
    "free_tier_model": TEXT_MODELS[0] if TEXT_MODELS else None,
    "free_tier_limit": 50, 
    "vision_model_first_warning_sent": {} 
})
users = load_json_file(USERS_FILE, default_value={}) 
plans = load_json_file(PLANS_FILE, default_value={}) 
force_sub_channels = load_json_file(FORCE_SUB_CHANNELS_FILE, default_value=[]) 
daily_message_counts = load_json_file(DAILY_MESSAGE_COUNTS_FILE, default_value={}) 

# --- توابع کمکی ---

def safe_edit_message(text, chat_id, message_id, reply_markup=None, parse_mode=None):
    """تابع کمکی برای جلوگیری از کرش کردن هنگام ادیت پیام تکراری"""
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            pass # تغییر نکردن پیام مشکلی نیست
        else:
            logger.error(f"Error editing message: {e}")

def is_admin(user_id: int) -> bool:
    return user_id in config["admins"]

def update_user_data(user_id, key, value):
    user_id_str = str(user_id)
    if user_id_str not in users:
        users[user_id_str] = {"plan": None, "plan_expiry": None, "selected_model": None}
    users[user_id_str][key] = value
    save_json_file(users, USERS_FILE)

def get_user_data(user_id):
    user_id_str = str(user_id)
    return users.get(user_id_str, {"plan": None, "plan_expiry": None, "selected_model": None})

def get_today_message_count(user_id: int):
    today = datetime.date.today().isoformat()
    user_id_str = str(user_id)
    return daily_message_counts.get(user_id_str, {}).get(today, 0)

def increment_message_count(user_id: int):
    today = datetime.date.today().isoformat()
    user_id_str = str(user_id)
    if user_id_str not in daily_message_counts:
        daily_message_counts[user_id_str] = {}
    
    if len(daily_message_counts[user_id_str]) > 7: 
        old_dates = sorted(daily_message_counts[user_id_str].keys())[:-7]
        for old_date in old_dates:
            del daily_message_counts[user_id_str][old_date]

    daily_message_counts[user_id_str][today] = daily_message_counts[user_id_str].get(today, 0) + 1
    save_json_file(daily_message_counts, DAILY_MESSAGE_COUNTS_FILE)

def get_user_model_limit(user_id: int):
    if is_admin(user_id):
        return float('inf')

    user_data = get_user_data(user_id)
    if user_data["plan"] and user_data["plan_expiry"] and datetime.datetime.fromisoformat(user_data["plan_expiry"]) > datetime.datetime.now():
        plan_id = user_data["plan"]
        if plan_id in plans:
            return plans[plan_id].get("daily_limit", float('inf'))
        return float('inf')
    
    if config["free_tier_enabled"]:
        return config["free_tier_limit"]
    return 0

def get_user_allowed_models(user_id: int):
    if is_admin(user_id):
        return ALL_AI_MODELS

    user_data = get_user_data(user_id)
    if user_data["plan"] and user_data["plan_expiry"] and datetime.datetime.fromisoformat(user_data["plan_expiry"]) > datetime.datetime.now():
        plan_id = user_data["plan"]
        if plan_id in plans:
            return plans[plan_id].get("allowed_models", [])
        return []
    
    if config["free_tier_enabled"] and config["free_tier_model"]:
        return [config["free_tier_model"]]
    return []

def is_force_subscribed(user_id: int) -> bool:
    if not config["force_subscribe_enabled"] or not force_sub_channels:
        return True
    
    for channel_id in force_sub_channels:
        try:
            member = bot.get_chat_member(channel_id, user_id)
            if member.status in ['member', 'creator', 'administrator']:
                continue
            else:
                return False
        except Exception as e:
            logger.warning(f"Check subscription error: {e}")
            return False 
    return True

# --- دکوراتورها ---

def authorized_only(handler_function):
    def wrapper(message_or_call):
        user_id = message_or_call.from_user.id
        
        if not is_admin(user_id) and not is_force_subscribed(user_id):
            markup = InlineKeyboardMarkup()
            for channel_id in force_sub_channels:
                try:
                    chat = bot.get_chat(channel_id)
                    markup.add(InlineKeyboardButton(f"عضویت در {chat.title}", url=f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(channel_id)[4:]}"))
                except:
                    markup.add(InlineKeyboardButton(f"عضویت در کانال", url=f"https://t.me/c/{str(channel_id)[4:]}"))
            markup.add(InlineKeyboardButton("بررسی مجدد عضویت", callback_data="check_subscription"))
            bot.send_message(user_id, "برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:", reply_markup=markup)
            return
        
        return handler_function(message_or_call)
    return wrapper

def is_admin_only_decorator(handler_function):
    def wrapper(message_or_call):
        user_id = message_or_call.from_user.id
        if not is_admin(user_id):
            bot.send_message(user_id, "شما اجازه دسترسی به این بخش را ندارید.")
            return
        return handler_function(message_or_call)
    return wrapper

# --- Handler های ربات تلگرام ---

@bot.message_handler(commands=['start'])
@authorized_only
def send_welcome(message):
    user_id = message.from_user.id
    markup = InlineKeyboardMarkup(row_width=1)
    
    if is_admin(user_id):
        markup.add(InlineKeyboardButton("⚙️ پنل مدیریت ادمین", callback_data="admin_panel_main"))
    
    markup.add(InlineKeyboardButton("✨ انتخاب مدل هوش مصنوعی", callback_data="select_ai_model"))
    markup.add(InlineKeyboardButton("💰 خرید پلن اشتراک", callback_data="buy_plan_start"))
    markup.add(InlineKeyboardButton("❓ وضعیت اشتراک من", callback_data="my_subscription_status"))
    
    bot.send_message(message.chat.id, 
                     "سلام! به ربات هوش مصنوعی خوش آمدید. برای شروع یکی از گزینه‌های زیر را انتخاب کنید:", 
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
@authorized_only
def handle_check_subscription(call):
    bot.answer_callback_query(call.id, text="بررسی عضویت انجام شد.")
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main_menu")
@authorized_only
def back_to_main_menu_handler(call):
    send_welcome(call.message)

# --- مدیریت پنل ادمین ---
ADMIN_STATES = {} 

def admin_main_menu_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("👨‍💻 مدیریت ادمین‌ها", callback_data="admin_manage_admins"))
    markup.add(InlineKeyboardButton("👥 مدیریت کاربران مجاز (دستی)", callback_data="admin_manage_authorized_users"))
    markup.add(InlineKeyboardButton("➕/➖ کانال‌های عضویت اجباری", callback_data="admin_manage_force_sub"))
    markup.add(InlineKeyboardButton("📝 مدیریت پلن‌های اشتراک", callback_data="admin_manage_plans"))
    markup.add(InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="admin_bot_settings"))
    markup.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main_menu"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel_main")
@is_admin_only_decorator
def admin_panel_main(call):
    safe_edit_message("به پنل مدیریت ادمین خوش آمدید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=admin_main_menu_markup())
    bot.answer_callback_query(call.id)

# --- زیرمنو: مدیریت ادمین‌ها ---
def admin_manage_admins_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add_admin"))
    markup.add(InlineKeyboardButton("➖ حذف ادمین", callback_data="admin_remove_admin"))
    markup.add(InlineKeyboardButton("📋 لیست ادمین‌ها", callback_data="admin_list_admins"))
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_manage_admins")
@is_admin_only_decorator
def admin_manage_admins(call):
    safe_edit_message("مدیریت ادمین‌ها:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=admin_manage_admins_markup())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_admin")
@is_admin_only_decorator
def admin_add_admin_prompt(call):
    ADMIN_STATES[call.from_user.id] = "awaiting_new_admin_id"
    safe_edit_message("لطفاً شناسه عددی ادمین جدید را ارسال کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_admins")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_admin")
@is_admin_only_decorator
def admin_remove_admin_prompt(call):
    ADMIN_STATES[call.from_user.id] = "awaiting_admin_id_to_remove"
    safe_edit_message("لطفاً شناسه عددی ادمین مورد نظر برای حذف را ارسال کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_admins")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_admins")
@is_admin_only_decorator
def admin_list_admins(call):
    admin_list_str = "\n".join(str(uid) for uid in config["admins"])
    safe_edit_message(f"لیست ادمین‌ها:\n{admin_list_str}", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_admins")))
    bot.answer_callback_query(call.id)

# --- زیرمنو: مدیریت کاربران مجاز ---
@bot.callback_query_handler(func=lambda call: call.data == "admin_manage_authorized_users")
@is_admin_only_decorator
def admin_manage_authorized_users(call):
    safe_edit_message("مدیریت کاربران مجاز (که از سیستم پلن استفاده نمی‌کنند):",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=admin_main_menu_markup()) # فعلا بازگشت ساده
    bot.answer_callback_query(call.id)

# --- زیرمنو: مدیریت کانال‌های عضویت اجباری ---
def admin_manage_force_sub_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ افزودن کانال", callback_data="admin_add_force_sub_channel"))
    markup.add(InlineKeyboardButton("➖ حذف کانال", callback_data="admin_remove_force_sub_channel"))
    markup.add(InlineKeyboardButton("📋 لیست کانال‌ها", callback_data="admin_list_force_sub_channels"))
    
    status = "روشن" if config["force_subscribe_enabled"] else "خاموش"
    markup.add(InlineKeyboardButton(f"وضعیت عضویت اجباری: {status}", callback_data="admin_toggle_force_sub"))
    
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_manage_force_sub")
@is_admin_only_decorator
def admin_manage_force_sub(call):
    safe_edit_message("مدیریت کانال‌های عضویت اجباری:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=admin_manage_force_sub_markup())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_force_sub_channel")
@is_admin_only_decorator
def admin_add_force_sub_channel_prompt(call):
    ADMIN_STATES[call.from_user.id] = "awaiting_channel_id_to_add"
    safe_edit_message("لطفاً شناسه عددی کانال (مثلاً `-1001234567890`) را ارسال کنید. ربات باید در کانال ادمین باشد.", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_force_sub")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_force_sub_channel")
@is_admin_only_decorator
def admin_remove_force_sub_channel_prompt(call):
    ADMIN_STATES[call.from_user.id] = "awaiting_channel_id_to_remove"
    safe_edit_message("لطفاً شناسه عددی کانال مورد نظر برای حذف را ارسال کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_force_sub")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_force_sub_channels")
@is_admin_only_decorator
def admin_list_force_sub_channels(call):
    if not force_sub_channels:
        channel_list_str = "هیچ کانالی ثبت نشده است."
    else:
        channel_info_list = []
        for cid in force_sub_channels:
            try:
                chat = bot.get_chat(cid)
                channel_info_list.append(f"• {chat.title} (`{cid}`)")
            except Exception as e:
                channel_info_list.append(f"• ناشناخته (`{cid}`) - خطا: {e}")
        channel_list_str = "\n".join(channel_info_list)
    
    safe_edit_message(f"کانال‌های عضویت اجباری:\n{channel_list_str}", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_force_sub")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_toggle_force_sub")
@is_admin_only_decorator
def admin_toggle_force_sub_handler(call):
    config["force_subscribe_enabled"] = not config["force_subscribe_enabled"]
    save_json_file(config, CONFIG_FILE)
    bot.answer_callback_query(call.id, text=f"وضعیت تغییر کرد.")
    admin_manage_force_sub(call)

# --- زیرمنو: مدیریت پلن‌ها ---
def admin_manage_plans_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="admin_add_plan"))
    markup.add(InlineKeyboardButton("📝 ویرایش پلن‌ها", callback_data="admin_edit_plans"))
    markup.add(InlineKeyboardButton("➖ حذف پلن", callback_data="admin_remove_plan"))
    markup.add(InlineKeyboardButton("📋 لیست پلن‌ها", callback_data="admin_list_plans"))
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_manage_plans")
@is_admin_only_decorator
def admin_manage_plans(call):
    safe_edit_message("مدیریت پلن‌های اشتراک:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=admin_manage_plans_markup())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_plan")
@is_admin_only_decorator
def admin_add_plan_prompt(call):
    ADMIN_STATES[call.from_user.id] = {"state": "awaiting_plan_name", "data": {}}
    safe_edit_message("لطفاً نام پلن را ارسال کنید (مثلاً 'برنزی', 'یک ماهه نامحدود'):", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_plans")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_plans")
@is_admin_only_decorator
def admin_list_plans_handler(call):
    if not plans:
        plan_list_str = "هیچ پلنی تعریف نشده است."
    else:
        plan_details = []
        for plan_id, plan_data in plans.items():
            models = ", ".join(plan_data.get("allowed_models", ["None"]))
            plan_details.append(f"**{plan_data['name']}** (ID: `{plan_id}`)\n"
                                f"  قیمت: {plan_data['price']} تومان\n"
                                f"  مدت: {plan_data['duration_days']} روز\n"
                                f"  محدودیت روزانه: {plan_data.get('daily_limit', 'نامحدود')}\n"
                                f"  مدل‌ها: {models}\n")
        plan_list_str = "\n".join(plan_details)
    
    safe_edit_message(f"لیست پلن‌ها:\n{plan_list_str}", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode='Markdown',
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_plans")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_plan")
@is_admin_only_decorator
def admin_remove_plan_select(call):
    if not plans:
        bot.answer_callback_query(call.id, "هیچ پلنی برای حذف وجود ندارد.", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    for plan_id, plan_data in plans.items():
        markup.add(InlineKeyboardButton(plan_data['name'], callback_data=f"admin_remove_plan_{plan_id}"))
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_plans"))
    
    safe_edit_message("پلن مورد نظر برای حذف را انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_remove_plan_"))
@is_admin_only_decorator
def admin_remove_plan_confirm(call):
    plan_id = call.data.replace("admin_remove_plan_", "")
    if plan_id in plans:
        del plans[plan_id]
        save_json_file(plans, PLANS_FILE)
        bot.answer_callback_query(call.id, "پلن با موفقیت حذف شد.", show_alert=True)
        admin_manage_plans(call)
    else:
        bot.answer_callback_query(call.id, "پلن یافت نشد.", show_alert=True)
        admin_manage_plans(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_edit_plans")
@is_admin_only_decorator
def admin_edit_plans_select(call):
    if not plans:
        bot.answer_callback_query(call.id, "هیچ پلنی برای ویرایش وجود ندارد.", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    for plan_id, plan_data in plans.items():
        markup.add(InlineKeyboardButton(plan_data['name'], callback_data=f"admin_edit_plan_{plan_id}"))
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_plans"))
    
    safe_edit_message("پلن مورد نظر برای ویرایش را انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_edit_plan_"))
@is_admin_only_decorator
def admin_edit_plan_prompt(call):
    plan_id = call.data.replace("admin_edit_plan_", "")
    if plan_id not in plans:
        bot.answer_callback_query(call.id, "پلن یافت نشد.", show_alert=True)
        admin_manage_plans(call)
        return
    
    # اگر در حال ویرایش فیلدها نیست، یعنی تازه وارد شده
    if not call.data.startswith("admin_edit_plan_field_"):
        ADMIN_STATES[call.from_user.id] = {"state": "editing_plan", "plan_id": plan_id, "data": plans[plan_id].copy()}
    
    edit_plan_markup = InlineKeyboardMarkup(row_width=1)
    edit_plan_markup.add(InlineKeyboardButton("نام پلن", callback_data=f"admin_edit_plan_field_{plan_id}_name"))
    edit_plan_markup.add(InlineKeyboardButton("قیمت", callback_data=f"admin_edit_plan_field_{plan_id}_price"))
    edit_plan_markup.add(InlineKeyboardButton("مدت زمان (روز)", callback_data=f"admin_edit_plan_field_{plan_id}_duration_days"))
    edit_plan_markup.add(InlineKeyboardButton("محدودیت روزانه پیام", callback_data=f"admin_edit_plan_field_{plan_id}_daily_limit"))
    edit_plan_markup.add(InlineKeyboardButton("مدل‌های هوش مصنوعی", callback_data=f"admin_edit_plan_field_{plan_id}_allowed_models"))
    edit_plan_markup.add(InlineKeyboardButton("🔙 بازگشت به مدیریت پلن‌ها", callback_data="admin_manage_plans"))
    
    current_plan_info = f"در حال ویرایش پلن: **{plans[plan_id]['name']}** (ID: `{plan_id}`)\n" \
                        f"قیمت: {plans[plan_id]['price']} تومان\n" \
                        f"مدت: {plans[plan_id]['duration_days']} روز\n" \
                        f"محدودیت روزانه: {plans[plan_id].get('daily_limit', 'نامحدود')}\n" \
                        f"مدل‌ها: {', '.join(plans[plan_id].get('allowed_models', ['هیچ']))}"
    
    safe_edit_message(current_plan_info, 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode='Markdown',
                          reply_markup=edit_plan_markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_edit_plan_field_"))
@is_admin_only_decorator
def admin_edit_plan_field(call):
    parts = call.data.split('_')
    plan_id = parts[4]
    field_name = parts[5]

    if call.from_user.id not in ADMIN_STATES or ADMIN_STATES[call.from_user.id].get("plan_id") != plan_id:
        bot.answer_callback_query(call.id, "خطا: وضعیت ویرایش پلن نامعتبر است.", show_alert=True)
        return

    ADMIN_STATES[call.from_user.id]["state"] = f"awaiting_plan_edit_{field_name}"
    
    prompt_message = ""
    if field_name == "name":
        prompt_message = "لطفاً نام جدید پلن را ارسال کنید:"
    elif field_name == "price":
        prompt_message = "لطفاً قیمت جدید پلن را (به تومان، فقط عدد) ارسال کنید:"
    elif field_name == "duration_days":
        prompt_message = "لطفاً مدت زمان پلن را (به روز، فقط عدد) ارسال کنید:"
    elif field_name == "daily_limit":
        prompt_message = "لطفاً محدودیت روزانه پیام را (فقط عدد، 0 برای نامحدود) ارسال کنید:"
    elif field_name == "allowed_models":
        models_markup = InlineKeyboardMarkup(row_width=2)
        selected_models_for_plan = ADMIN_STATES[call.from_user.id]["data"].get("allowed_models", [])
        
        for model in ALL_AI_MODELS:
            status_emoji = "✅" if model in selected_models_for_plan else "⬜"
            models_markup.add(InlineKeyboardButton(f"{status_emoji} {model}", callback_data=f"admin_toggle_model_{plan_id}_{model}"))
        
        models_markup.add(InlineKeyboardButton("ذخیره و بازگشت", callback_data=f"admin_save_edit_plan_{plan_id}_models"))
        prompt_message = "مدل‌های مجاز را انتخاب کنید:"
        safe_edit_message(prompt_message, call.message.chat.id, call.message.message_id, reply_markup=models_markup)
        bot.answer_callback_query(call.id)
        return
    
    safe_edit_message(prompt_message, 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data=f"admin_edit_plan_{plan_id}")))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_toggle_model_"))
@is_admin_only_decorator
def admin_toggle_model_for_plan(call):
    parts = call.data.split('_')
    plan_id = parts[3]
    model_name = '_'.join(parts[4:])

    if call.from_user.id not in ADMIN_STATES or ADMIN_STATES[call.from_user.id].get("plan_id") != plan_id:
        return

    current_allowed_models = ADMIN_STATES[call.from_user.id]["data"].get("allowed_models", [])
    if model_name in current_allowed_models:
        current_allowed_models.remove(model_name)
    else:
        current_allowed_models.append(model_name)
    
    ADMIN_STATES[call.from_user.id]["data"]["allowed_models"] = current_allowed_models
    
    models_markup = InlineKeyboardMarkup(row_width=2)
    for model in ALL_AI_MODELS:
        status_emoji = "✅" if model in current_allowed_models else "⬜"
        models_markup.add(InlineKeyboardButton(f"{status_emoji} {model}", callback_data=f"admin_toggle_model_{plan_id}_{model}"))
    models_markup.add(InlineKeyboardButton("ذخیره و بازگشت", callback_data=f"admin_save_edit_plan_{plan_id}_models"))
    
    safe_edit_message("مدل‌های هوش مصنوعی مجاز برای این پلن را انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=models_markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_save_edit_plan_") and call.data.endswith("_models"))
@is_admin_only_decorator
def admin_save_edit_plan_models(call):
    plan_id = call.data.split('_')[4]
    if call.from_user.id not in ADMIN_STATES:
        return
    
    plans[plan_id] = ADMIN_STATES[call.from_user.id]["data"]
    save_json_file(plans, PLANS_FILE)
    bot.answer_callback_query(call.id, "مدل‌ها ذخیره شد.")
    
    # بازگشت به منوی ویرایش
    call.data = f"admin_edit_plan_{plan_id}"
    admin_edit_plan_prompt(call)

# --- زیرمنو: تنظیمات ربات ---
def admin_bot_settings_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    
    fs_status = "✅ روشن" if config["force_subscribe_enabled"] else "❌ خاموش"
    markup.add(InlineKeyboardButton(f"عضویت اجباری: {fs_status}", callback_data="admin_toggle_force_sub_from_settings"))
    
    ft_status = "✅ روشن" if config["free_tier_enabled"] else "❌ خاموش"
    markup.add(InlineKeyboardButton(f"حالت رایگان (Free Tier): {ft_status}", callback_data="admin_toggle_free_tier"))
    
    if config["free_tier_enabled"]:
        markup.add(InlineKeyboardButton(f"مدل رایگان: {config.get('free_tier_model', 'تعیین نشده')}", callback_data="admin_set_free_tier_model"))
        markup.add(InlineKeyboardButton(f"محدودیت رایگان: {config.get('free_tier_limit', 'نامحدود')} پیام/روز", callback_data="admin_set_free_tier_limit"))
    
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_bot_settings")
@is_admin_only_decorator
def admin_bot_settings(call):
    safe_edit_message("تنظیمات کلی ربات:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=admin_bot_settings_markup())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_toggle_force_sub_from_settings")
@is_admin_only_decorator
def admin_toggle_force_sub_from_settings(call):
    config["force_subscribe_enabled"] = not config["force_subscribe_enabled"]
    save_json_file(config, CONFIG_FILE)
    bot.answer_callback_query(call.id, text="تنظیمات تغییر کرد.")
    admin_bot_settings(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_toggle_free_tier")
@is_admin_only_decorator
def admin_toggle_free_tier_handler(call):
    config["free_tier_enabled"] = not config["free_tier_enabled"]
    save_json_file(config, CONFIG_FILE)
    bot.answer_callback_query(call.id, text="تنظیمات تغییر کرد.")
    admin_bot_settings(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_set_free_tier_model")
@is_admin_only_decorator
def admin_set_free_tier_model_prompt(call):
    markup = InlineKeyboardMarkup(row_width=2)
    for model in ALL_AI_MODELS:
        status_emoji = "✅" if model == config.get("free_tier_model") else "⬜"
        markup.add(InlineKeyboardButton(f"{status_emoji} {model}", callback_data=f"admin_select_free_tier_model_{model}"))
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_bot_settings"))
    safe_edit_message("مدل هوش مصنوعی رایگان را انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_select_free_tier_model_"))
@is_admin_only_decorator
def admin_select_free_tier_model_handler(call):
    model_name = call.data.replace("admin_select_free_tier_model_", "")
    config["free_tier_model"] = model_name
    save_json_file(config, CONFIG_FILE)
    bot.answer_callback_query(call.id, text=f"مدل رایگان به {model_name} تغییر یافت.")
    admin_bot_settings(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_set_free_tier_limit")
@is_admin_only_decorator
def admin_set_free_tier_limit_prompt(call):
    ADMIN_STATES[call.from_user.id] = "awaiting_free_tier_limit"
    safe_edit_message("لطفاً محدودیت روزانه پیام برای حالت رایگان را (فقط عدد) ارسال کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 لغو", callback_data="admin_bot_settings")))
    bot.answer_callback_query(call.id)

# --- مدیریت پیام‌های متنی از ادمین در حالت انتظار (اصلاح شده) ---
@bot.message_handler(content_types=['text'], func=lambda message: is_admin(message.from_user.id) and message.from_user.id in ADMIN_STATES)
@is_admin_only_decorator
def handle_admin_state_messages(message):
    user_id = message.from_user.id
    state_data = ADMIN_STATES.get(user_id)
    if not state_data: return 

    # --- FIX: رفع باگ AttributeError ---
    if isinstance(state_data, dict):
        current_state = state_data.get("state")
        data_payload = state_data.get("data", {})
    else:
        current_state = state_data
        data_payload = {}
    # -----------------------------------

    try:
        if current_state == "awaiting_new_admin_id":
            new_admin_id = int(message.text)
            if new_admin_id not in config["admins"]:
                config["admins"].append(new_admin_id)
                save_json_file(config, CONFIG_FILE)
                bot.reply_to(message, f"ادمین {new_admin_id} با موفقیت اضافه شد.")
            else:
                bot.reply_to(message, f"ادمین {new_admin_id} از قبل وجود دارد.")
            del ADMIN_STATES[user_id]
            admin_manage_admins(message)
        
        elif current_state == "awaiting_admin_id_to_remove":
            admin_to_remove_id = int(message.text)
            if admin_to_remove_id == INITIAL_ADMIN_ID:
                 bot.reply_to(message, "ادمین اصلی (INITIAL_ADMIN_ID) قابل حذف نیست.")
            elif admin_to_remove_id in config["admins"]:
                config["admins"].remove(admin_to_remove_id)
                save_json_file(config, CONFIG_FILE)
                bot.reply_to(message, f"ادمین {admin_to_remove_id} با موفقیت حذف شد.")
            else:
                bot.reply_to(message, f"ادمین {admin_to_remove_id} یافت نشد.")
            del ADMIN_STATES[user_id]
            admin_manage_admins(message)

        elif current_state == "awaiting_channel_id_to_add":
            channel_id = int(message.text)
            if channel_id not in force_sub_channels:
                force_sub_channels.append(channel_id)
                save_json_file(force_sub_channels, FORCE_SUB_CHANNELS_FILE)
                bot.reply_to(message, f"کانال {channel_id} با موفقیت اضافه شد.")
            else:
                bot.reply_to(message, f"کانال {channel_id} از قبل وجود دارد.")
            del ADMIN_STATES[user_id]
            admin_manage_force_sub(message)
        
        elif current_state == "awaiting_channel_id_to_remove":
            channel_id = int(message.text)
            if channel_id in force_sub_channels:
                force_sub_channels.remove(channel_id)
                save_json_file(force_sub_channels, FORCE_SUB_CHANNELS_FILE)
                bot.reply_to(message, f"کانال {channel_id} با موفقیت حذف شد.")
            else:
                bot.reply_to(message, f"کانال {channel_id} یافت نشد.")
            del ADMIN_STATES[user_id]
            admin_manage_force_sub(message)

        elif current_state == "awaiting_plan_name":
            plan_name = message.text
            plan_id = str(len(plans) + 1) 
            data_payload["name"] = plan_name
            ADMIN_STATES[user_id] = {"state": "awaiting_plan_price", "data": data_payload, "plan_id": plan_id}
            bot.reply_to(message, f"نام پلن '{plan_name}' ثبت شد. لطفاً قیمت پلن را (به تومان، فقط عدد) ارسال کنید:")

        elif current_state == "awaiting_plan_price":
            price = int(message.text)
            data_payload["price"] = price
            ADMIN_STATES[user_id] = {"state": "awaiting_plan_duration", "data": data_payload, "plan_id": state_data["plan_id"]}
            bot.reply_to(message, f"قیمت {price} ثبت شد. لطفاً مدت زمان پلن را (به روز، فقط عدد) ارسال کنید:")

        elif current_state == "awaiting_plan_duration":
            duration = int(message.text)
            data_payload["duration_days"] = duration
            ADMIN_STATES[user_id] = {"state": "awaiting_plan_daily_limit", "data": data_payload, "plan_id": state_data["plan_id"]}
            bot.reply_to(message, f"مدت {duration} روز ثبت شد. لطفاً محدودیت روزانه پیام را (فقط عدد، 0 برای نامحدود) ارسال کنید:")

        elif current_state == "awaiting_plan_daily_limit":
            daily_limit = int(message.text)
            data_payload["daily_limit"] = daily_limit if daily_limit > 0 else float('inf')
            
            models_markup = InlineKeyboardMarkup(row_width=2)
            for model in ALL_AI_MODELS:
                models_markup.add(InlineKeyboardButton(f"⬜ {model}", callback_data=f"admin_toggle_model_{state_data['plan_id']}_{model}"))
            models_markup.add(InlineKeyboardButton("ذخیره و بازگشت", callback_data=f"admin_save_edit_plan_{state_data['plan_id']}_models"))
            
            data_payload["allowed_models"] = [] 
            ADMIN_STATES[user_id] = {"state": "selecting_plan_models", "data": data_payload, "plan_id": state_data["plan_id"]}
            bot.reply_to(message, "لطفاً مدل‌های هوش مصنوعی مجاز برای این پلن را انتخاب کنید:", reply_markup=models_markup)
            
        elif current_state.startswith("awaiting_plan_edit_"):
            plan_id = state_data["plan_id"]
            field_name = current_state.replace("awaiting_plan_edit_", "")
            
            if field_name == "name":
                plans[plan_id]["name"] = message.text
                bot.reply_to(message, "نام پلن با موفقیت ویرایش شد.")
            elif field_name == "price":
                plans[plan_id]["price"] = int(message.text)
                bot.reply_to(message, "قیمت پلن با موفقیت ویرایش شد.")
            elif field_name == "duration_days":
                plans[plan_id]["duration_days"] = int(message.text)
                bot.reply_to(message, "مدت زمان پلن با موفقیت ویرایش شد.")
            elif field_name == "daily_limit":
                new_limit = int(message.text)
                plans[plan_id]["daily_limit"] = new_limit if new_limit > 0 else float('inf')
                bot.reply_to(message, "محدودیت روزانه پیام با موفقیت ویرایش شد.")
            
            save_json_file(plans, PLANS_FILE)
            del ADMIN_STATES[user_id]
            bot.send_message(message.chat.id, "بازگشت به منوی ویرایش پلن...", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("بازگشت", callback_data=f"admin_edit_plan_{plan_id}")))
            
        elif current_state == "awaiting_free_tier_limit":
            new_limit = int(message.text)
            if new_limit >= 0:
                config["free_tier_limit"] = new_limit
                save_json_file(config, CONFIG_FILE)
                bot.reply_to(message, f"محدودیت رایگان به {new_limit} پیام/روز تغییر یافت.")
            else:
                bot.reply_to(message, "لطفاً یک عدد مثبت یا صفر (برای نامحدود) ارسال کنید.")
            del ADMIN_STATES[user_id]
            admin_bot_settings(message) 
        
        else:
            bot.reply_to(message, "درخواست نامعتبر در حالت مدیریت.")
            del ADMIN_STATES[user_id]

    except ValueError:
        bot.reply_to(message, "ورودی نامعتبر است. لطفاً یک عدد صحیح معتبر ارسال کنید.")
    except Exception as e:
        logger.error(f"Error in admin state {current_state} for user {user_id}: {e}")
        bot.reply_to(message, "خطایی رخ داد. دوباره تلاش کنید.")

# --- انتخاب مدل AI توسط کاربر ---
@bot.callback_query_handler(func=lambda call: call.data == "select_ai_model")
@authorized_only
def select_ai_model_menu(call):
    user_id = call.from_user.id
    allowed_models = get_user_allowed_models(user_id)
    
    if not allowed_models:
        bot.answer_callback_query(call.id, "شما به هیچ مدلی دسترسی ندارید.", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    for model in ALL_AI_MODELS:
        if model in allowed_models:
            markup.add(InlineKeyboardButton(model, callback_data=f"user_select_model_{model}"))
        else:
            markup.add(InlineKeyboardButton(f"🔒 {model} (نیاز به پلن)", callback_data="ignore"))
    
    markup.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main_menu"))
    
    safe_edit_message("لطفاً یکی از مدل‌های هوش مصنوعی زیر را انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_select_model_"))
@authorized_only
def user_select_model_handler(call):
    user_id = call.from_user.id
    model_name = call.data.replace("user_select_model_", "")
    
    allowed_models = get_user_allowed_models(user_id)
    if model_name not in allowed_models:
        bot.answer_callback_query(call.id, "شما به این مدل دسترسی ندارید.", show_alert=True)
        return
    
    update_user_data(user_id, "selected_model", model_name)
    
    message_text = f"مدل شما به **{model_name}** تغییر کرد.\n\n"
    if model_name in VISION_MODELS:
        message_text += "این مدل از تحلیل تصویر پشتیبانی می‌کند. می‌توانید یک عکس ارسال کنید."
    else:
        message_text += "حالا می‌توانید پیام متنی خود را ارسال کنید."
    
    safe_edit_message(message_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id, text=f"مدل به {model_name} تغییر یافت.")
    
    config["vision_model_first_warning_sent"].pop(user_id, None)
    save_json_file(config, CONFIG_FILE)

# --- مدیریت خرید پلن ---
@bot.callback_query_handler(func=lambda call: call.data == "buy_plan_start")
@authorized_only
def buy_plan_start(call):
    if not plans:
        bot.answer_callback_query(call.id, "هیچ پلنی برای خرید در دسترس نیست.", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    for plan_id, plan_data in plans.items():
        markup.add(InlineKeyboardButton(f"{plan_data['name']} - {plan_data['price']} تومان ({plan_data['duration_days']} روز)", 
                                        callback_data=f"buy_plan_{plan_id}"))
    markup.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main_menu"))
    
    safe_edit_message("لطفاً پلن مورد نظر خود را برای خرید انتخاب کنید:", 
                          call.message.chat.id, call.message.message_id, 
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_plan_"))
@authorized_only
def buy_plan_details(call):
    plan_id = call.data.replace("buy_plan_", "")
    if plan_id not in plans:
        bot.answer_callback_query(call.id, "پلن یافت نشد.", show_alert=True)
        return
    
    plan_data = plans[plan_id]
    
    details_message = f"**جزئیات پلن:**\n" \
                      f"نام: **{plan_data['name']}**\n" \
                      f"قیمت: **{plan_data['price']}** تومان\n" \
                      f"مدت: **{plan_data['duration_days']}** روز\n" \
                      f"محدودیت روزانه پیام: {plan_data.get('daily_limit', 'نامحدود')}\n" \
                      f"مدل‌های مجاز: {', '.join(plan_data.get('allowed_models', ['هیچ']))}\n\n" \
                      f"برای خرید، مبلغ **{plan_data['price']} تومان** را واریز کرده و عکس رسید را ارسال کنید.\n" \
                      f"**شماره کارت:** `1234-1234-1234-1234` (مثال)\n" 
    
    ADMIN_STATES[call.from_user.id] = {"state": "awaiting_payment_receipt", "plan_id": plan_id}

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 انصراف", callback_data="buy_plan_start"))
    
    safe_edit_message(details_message, 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode='Markdown',
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

# --- وضعیت اشتراک کاربر ---
@bot.callback_query_handler(func=lambda call: call.data == "my_subscription_status")
@authorized_only
def my_subscription_status(call):
    user_id = call.from_user.id
    user_data = get_user_data(user_id)
    
    status_message = "وضعیت اشتراک شما:\n\n"
    
    if is_admin(user_id):
        status_message += "شما ادمین هستید و دسترسی نامحدود دارید. 👑\n"
    elif user_data["plan"] and user_data["plan_expiry"] and datetime.datetime.fromisoformat(user_data["plan_expiry"]) > datetime.datetime.now():
        plan_id = user_data["plan"]
        plan_name = plans.get(plan_id, {}).get("name", "نامعلوم")
        expiry_date = datetime.datetime.fromisoformat(user_data["plan_expiry"]).strftime("%Y/%m/%d %H:%M:%S")
        
        status_message += f"**پلن فعال:** {plan_name}\n"
        status_message += f"**تاریخ انقضا:** {expiry_date}\n"
        
        daily_limit = get_user_model_limit(user_id)
        if daily_limit != float('inf'):
            today_count = get_today_message_count(user_id)
            status_message += f"**پیام‌های امروز:** {today_count} از {int(daily_limit)}\n"
        else:
            status_message += "**محدودیت روزانه:** نامحدود\n"
    else:
        status_message += "شما هیچ پلن فعالی ندارید.\n"
        if config["free_tier_enabled"]:
            today_count = get_today_message_count(user_id)
            status_message += f"**حالت رایگان فعال:** {config.get('free_tier_model', 'تعیین نشده')}\n"
            status_message += f"**محدودیت روزانه رایگان:** {today_count} از {config['free_tier_limit']} پیام\n"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main_menu"))
    
    safe_edit_message(status_message, 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode='Markdown',
                          reply_markup=markup)
    bot.answer_callback_query(call.id)

# --- پردازش پیام‌های عمومی (متن و عکس) ---

@bot.message_handler(content_types=['text', 'photo'])
@authorized_only
def handle_general_messages(message):
    user_id = message.from_user.id

    # اگر کاربر در حال خرید پلن است
    if user_id in ADMIN_STATES:
        state_data = ADMIN_STATES[user_id]
        if isinstance(state_data, dict) and state_data.get("state") == "awaiting_payment_receipt":
            if message.content_type == 'photo':
                plan_id = state_data["plan_id"]
                if plan_id not in plans:
                    bot.reply_to(message, "خطا: پلن انتخاب شده یافت نشد.")
                    del ADMIN_STATES[user_id]
                    return
                
                plan_data = plans[plan_id]
                
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"approve_payment_{user_id}_{plan_id}"))
                markup.add(InlineKeyboardButton("❌ رد پرداخت", callback_data=f"reject_payment_{user_id}"))
                
                caption_text = f"**درخواست خرید پلن!**\n\n" \
                               f"**کاربر:** {message.from_user.first_name} (`{user_id}`)\n" \
                               f"**پلن:** {plan_data['name']} (ID: `{plan_id}`)\n" \
                               f"**مبلغ:** {plan_data['price']} تومان\n"
                
                bot.send_photo(INITIAL_ADMIN_ID, message.photo[-1].file_id, 
                               caption=caption_text, parse_mode='Markdown', reply_markup=markup)
                
                bot.reply_to(message, "رسید پرداخت شما دریافت شد. منتظر تایید ادمین باشید.")
                del ADMIN_STATES[user_id]
                return
            else:
                bot.reply_to(message, "لطفاً **عکس رسید پرداخت** را ارسال کنید.")
                return

    # اگر ادمین در حال مدیریت است
    if is_admin(user_id) and user_id in ADMIN_STATES:
        handle_admin_state_messages(message)
        return

    # پردازش عادی
    selected_model = get_user_data(user_id)["selected_model"]
    
    if not selected_model:
        markup = InlineKeyboardMarkup(); markup.add(InlineKeyboardButton("✨ انتخاب مدل هوش مصنوعی", callback_data="select_ai_model"))
        bot.reply_to(message, "لطفاً ابتدا یک مدل هوش مصنوعی را انتخاب کنید.", reply_markup=markup)
        return

    if not is_admin(user_id):
        current_count = get_today_message_count(user_id)
        limit = get_user_model_limit(user_id)
        
        if limit != float('inf') and current_count >= limit:
            bot.reply_to(message, "محدودیت روزانه شما به پایان رسیده است.")
            return

    if selected_model in VISION_MODELS:
        if message.content_type == 'text':
            if not config["vision_model_first_warning_sent"].get(user_id, False):
                bot.reply_to(message, "این مدل تصویری است. لطفاً عکس ارسال کنید.")
                config["vision_model_first_warning_sent"][user_id] = True
                save_json_file(config, CONFIG_FILE)
            return 
        
        elif message.content_type == 'photo':
            processing_msg = bot.reply_to(message, f"در حال پردازش تصویر با مدل {selected_model}...")
            
            if samba_client:
                try:
                    file_info = bot.get_file(message.photo[-1].file_id)
                    downloaded_file = bot.download_file(file_info.file_path)
                    base64_image = base64.b64encode(downloaded_file).decode('utf-8')
                    image_url = f"data:image/jpeg;base64,{base64_image}"
                    
                    caption = message.caption or "What do you see in this image?"
                    messages_payload = [{"role": "user", "content": [{"type": "text", "text": caption}, {"type": "image_url", "image_url": {"url": image_url}}]}]
                    
                    response = samba_client.chat.completions.create(model=selected_model, messages=messages_payload)
                    response_text = response.choices[0].message.content
                    increment_message_count(user_id)
                except Exception as e:
                    response_text = f"خطا: {e}"
                    logger.error(f"Error vision: {e}")
            else:
                response_text = "سرویس در دسترس نیست."
            
            safe_edit_message(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)
            
    elif selected_model in TEXT_MODELS:
        if message.content_type == 'photo':
            bot.reply_to(message, "این مدل متنی است. لطفاً متن ارسال کنید.")
            return
        
        elif message.content_type == 'text':
            processing_msg = bot.reply_to(message, f"در حال پردازش متن با مدل {selected_model}...")
            
            if samba_client:
                try:
                    response = samba_client.chat.completions.create(
                        model=selected_model,
                        messages=[{"role": "user", "content": message.text}],
                    )
                    response_text = response.choices[0].message.content
                    increment_message_count(user_id)
                except Exception as e:
                    response_text = f"خطا: {e}"
                    logger.error(f"Error text: {e}")
            else:
                response_text = "سرویس در دسترس نیست."
            
            safe_edit_message(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)

# --- تایید/رد پرداخت توسط ادمین ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_payment_"))
@is_admin_only_decorator
def approve_payment_handler(call):
    parts = call.data.split('_')
    user_id = int(parts[2])
    plan_id = parts[3]
    
    if plan_id not in plans:
        bot.answer_callback_query(call.id, "خطا: پلن یافت نشد.", show_alert=True)
        return

    plan_data = plans[plan_id]
    
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=plan_data["duration_days"])).isoformat()
    update_user_data(user_id, "plan", plan_id)
    update_user_data(user_id, "plan_expiry", expiry_date)
    update_user_data(user_id, "selected_model", None)
    
    bot.send_message(user_id, f"✅ پرداخت شما تایید شد. پلن {plan_data['name']} برای شما فعال گردید.")
    bot.edit_message_caption(f"{call.message.caption}\n\n**✅ تایید شد!**", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id, text="تایید شد.")
    
@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_payment_"))
@is_admin_only_decorator
def reject_payment_handler(call):
    parts = call.data.split('_')
    user_id = int(parts[2])
    
    bot.send_message(user_id, "❌ پرداخت شما رد شد.")
    bot.edit_message_caption(f"{call.message.caption}\n\n**❌ رد شد!**", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id, text="رد شد.")

# --- شروع ربات ---
if __name__ == '__main__':
    # اجرای سرور وب در ترد جداگانه
    keep_alive()
    
    logger.info("Bot started polling...")
    # استفاده از بلوک try-except برای جلوگیری از بسته شدن برنامه در صورت خطای لحظه‌ای اینترنت
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling failed: {e}")
            time.sleep(5)
