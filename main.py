import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import json
import os
import base64
import io
from sambanova import SambaNova, SambaNovaError

# --- تنظیمات اولیه ---
TELEGRAM_BOT_TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"  # توکن ربات تلگرام خود را اینجا قرار دهید
SAMBA_API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"  # کلید API شما
ADMIN_ID = 5789565027  # شناسه کاربری عددی خودتان را به عنوان ادمین قرار دهید

# نام فایل برای ذخیره کاربران مجاز
USERS_FILE = "authorized_users.json"

# مدل‌های هوش مصنوعی
VISION_MODELS = ["Llama-4-Maverick-17B-128E-Instruct"]
TEXT_MODELS = ["DeepSeek-V3.1", "gpt-oss-120b", "Qwen3-32B", "ALLaM-7B-Instruct-preview"]
AI_MODELS = VISION_MODELS + TEXT_MODELS

# تنظیمات لاگ‌گیری و راه‌اندازی ربات
logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ساخت کلاینت SambaNova
try:
    samba_client = SambaNova(api_key=SAMBA_API_KEY)
except Exception as e:
    logging.error(f"Failed to initialize SambaNova client: {e}")
    samba_client = None

# متغیرهایی برای نگهداری وضعیت کاربر (جایگزین user_data و ConversationHandler)
user_states = {}  # e.g., {user_id: "awaiting_user_id_to_add"}
selected_models = {} # e.g., {user_id: "DeepSeek-V3.1"}

# --- توابع مدیریت کاربران ---
def load_authorized_users():
    if not os.path.exists(USERS_FILE): return []
    try:
        with open(USERS_FILE, "r") as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return []

def save_authorized_users(users_list):
    with open(USERS_FILE, "w") as f: json.dump(users_list, f)

def is_authorized(user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    return user_id in load_authorized_users()

# --- دکوراتور برای بررسی دسترسی کاربران ---
def authorized_only(handler_function):
    def wrapper(message_or_call):
        user_id = message_or_call.from_user.id
        if not is_authorized(user_id):
            bot.send_message(user_id, "شما اجازه استفاده از این ربات را ندارید.")
            return
        return handler_function(message_or_call)
    return wrapper

# --- Handler های اصلی ربات ---

@bot.message_handler(commands=['start'])
@authorized_only
def send_welcome(message):
    """دستور /start را مدیریت می‌کند."""
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("انتخاب مدل هوش مصنوعی", callback_data="select_model"))
    bot.send_message(message.chat.id, "سلام! به ربات هوش مصنوعی خوش آمدید. برای شروع، یک مدل را انتخاب کنید:", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """پنل مدیریت را فقط برای ادمین نمایش می‌دهد."""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "این دستور فقط برای ادمین است.")
        return

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("افزودن کاربر", callback_data="admin_add_user"))
    markup.row(InlineKeyboardButton("حذف کاربر", callback_data="admin_remove_user"))
    markup.row(InlineKeyboardButton("لیست کاربران", callback_data="admin_list_users"))
    bot.send_message(message.chat.id, "پنل مدیریت ادمین:", reply_markup=markup)

# --- Handler برای دکمه‌ها (CallbackQuery) ---

@bot.callback_query_handler(func=lambda call: True)
@authorized_only
def handle_callback_query(call):
    """تمام کلیک‌های روی دکمه‌های شیشه‌ای را مدیریت می‌کند."""
    user_id = call.from_user.id
    
    # دکمه‌های عمومی
    if call.data == "select_model":
        markup = InlineKeyboardMarkup()
        for model in AI_MODELS:
            markup.row(InlineKeyboardButton(model, callback_data=f"model_{model}"))
        bot.edit_message_text("لطفاً یکی از مدل‌های زیر را انتخاب کنید:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    
    elif call.data.startswith("model_"):
        model_name = call.data.replace("model_", "")
        selected_models[user_id] = model_name
        message = f"مدل شما به **{model_name}** تغییر کرد.\n\n"
        if model_name in VISION_MODELS:
            message += "این مدل از تحلیل تصویر پشتیبانی می‌کند. می‌توانید یک عکس (با یا بدون کپشن) ارسال کنید."
        else:
            message += "حالا می‌توانید پیام متنی خود را ارسال کنید."
        bot.edit_message_text(message, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    # دکمه‌های پنل ادمین
    elif call.data == "admin_add_user":
        user_states[user_id] = "awaiting_user_id_to_add"
        bot.send_message(user_id, "لطفاً شناسه کاربری (ID) فرد مورد نظر برای افزودن را ارسال کنید:")
    
    elif call.data == "admin_remove_user":
        user_states[user_id] = "awaiting_user_id_to_remove"
        bot.send_message(user_id, "لطفاً شناسه کاربری (ID) فرد مورد نظر برای حذف را ارسال کنید:")

    elif call.data == "admin_list_users":
        users = load_authorized_users()
        if not users:
            bot.send_message(user_id, "هیچ کاربری در لیست مجاز وجود ندارد.")
        else:
            user_list_str = "\n".join(str(uid) for uid in users)
            bot.send_message(user_id, f"لیست کاربران مجاز:\n{user_list_str}")

    bot.answer_callback_query(call.id) # برای اینکه علامت ساعت کنار دکمه از بین برود


# --- Handler برای پیام‌های متنی و عکس ---

@bot.message_handler(content_types=['text'], func=lambda message: not message.text.startswith('/'))
@authorized_only
def handle_text(message):
    """پیام‌های متنی را پردازش می‌کند."""
    user_id = message.from_user.id
    current_state = user_states.get(user_id)

    # بررسی اینکه آیا ادمین در حال افزودن/حذف کاربر است
    if current_state == "awaiting_user_id_to_add":
        try:
            user_id_to_add = int(message.text)
            users = load_authorized_users()
            if user_id_to_add not in users:
                users.append(user_id_to_add)
                save_authorized_users(users)
                bot.reply_to(message, f"کاربر {user_id_to_add} با موفقیت اضافه شد.")
            else:
                bot.reply_to(message, f"کاربر {user_id_to_add} از قبل وجود دارد.")
            del user_states[user_id]
        except ValueError:
            bot.reply_to(message, "شناسه نامعتبر است. لطفاً یک عدد ارسال کنید.")
        return

    elif current_state == "awaiting_user_id_to_remove":
        try:
            user_id_to_remove = int(message.text)
            users = load_authorized_users()
            if user_id_to_remove in users:
                users.remove(user_id_to_remove)
                save_authorized_users(users)
                bot.reply_to(message, f"کاربر {user_id_to_remove} با موفقیت حذف شد.")
            else:
                bot.reply_to(message, f"کاربر {user_id_to_remove} یافت نشد.")
            del user_states[user_id]
        except ValueError:
            bot.reply_to(message, "شناسه نامعتبر است. لطفاً یک عدد ارسال کنید.")
        return

    # پردازش عادی پیام کاربر
    selected_model = selected_models.get(user_id)
    if not selected_model:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("انتخاب مدل", callback_data="select_model"))
        bot.reply_to(message, "لطفاً ابتدا یک مدل را انتخاب کنید.", reply_markup=markup)
        return

    if selected_model in VISION_MODELS:
        bot.reply_to(message, "این مدل برای تحلیل تصویر است. لطفاً یک عکس ارسال کنید.")
        return

    processing_msg = bot.reply_to(message, f"در حال پردازش متن با مدل {selected_model}...")
    
    try:
        response = samba_client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "user", "content": message.text}],
        )
        response_text = response.choices[0].message.content
    except SambaNovaError as e:
        response_text = f"خطا در ارتباط با API: {e}"
    except Exception as e:
        response_text = f"یک خطای پیش‌بینی نشده رخ داد: {e}"

    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)


@bot.message_handler(content_types=['photo'])
@authorized_only
def handle_photo(message):
    """عکس‌های ارسالی را پردازش می‌کند."""
    user_id = message.from_user.id
    selected_model = selected_models.get(user_id)

    if not selected_model:
        markup = InlineKeyboardMarkup(); markup.row(InlineKeyboardButton("انتخاب مدل", callback_data="select_model"))
        bot.reply_to(message, "لطفاً ابتدا یک مدل را انتخاب کنید.", reply_markup=markup)
        return
    
    if selected_model not in VISION_MODELS:
        bot.reply_to(message, f"مدل فعلی ({selected_model}) از تصویر پشتیبانی نمی‌کند. لطفاً یک مدل تصویری انتخاب کنید.")
        return

    processing_msg = bot.reply_to(message, f"در حال پردازش تصویر با مدل {selected_model}...")
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{base64_image}"
        
        caption = message.caption or "What do you see in this image?"
        messages_payload = [{"role": "user", "content": [{"type": "text", "text": caption}, {"type": "image_url", "image_url": {"url": image_url}}]}]
        
        response = samba_client.chat.completions.create(model=selected_model, messages=messages_payload)
        response_text = response.choices[0].message.content
        
    except SambaNovaError as e:
        response_text = f"خطا در ارتباط با API: {e}"
    except Exception as e:
        response_text = f"یک خطای پیش‌بینی نشده در پردازش تصویر رخ داد: {e}"

    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)


if __name__ == '__main__':
    if not samba_client:
        print("کلاینت SambaNova راه‌اندازی نشد. لطفاً کلید API را بررسی کنید.")
    else:
        print("ربات در حال اجرا است...")
        bot.polling(non_stop=True)
