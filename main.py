import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import json
import os
import base64
import io
from sambanova import SambaNova, SambaNovaError

# --- تنظیمات اولیه ---
# توجه: توکن و کلید API شما باید به صورت امن مدیریت شوند،
# مثلاً از طریق متغیرهای محیطی در یک محیط واقعی.
TELEGRAM_BOT_TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"  # توکن ربات تلگرام خود را اینجا قرار دهید
SAMBA_API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"  # کلید API شما
ADMIN_ID = 5789565027  # شناسه کاربری عددی خودتان را به عنوان ادمین قرار دهید

# مدل‌های هوش مصنوعی پشتیبانی شده
VISION_MODELS = ["Llama-4-Maverick-17B-128E-Instruct"]
TEXT_MODELS = ["DeepSeek-V3.1", "gpt-oss-120b", "Qwen3-32B", "ALLaM-7B-Instruct-preview"]
AI_MODELS = VISION_MODELS + TEXT_MODELS

# تنظیمات لاگ‌گیری و راه‌اندازی ربات
logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ساخت کلاینت SambaNova
try:
    samba_client = SambaNova(api_key=SAMBA_API_KEY)
    logging.info("SambaNova client initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize SambaNova client: {e}")
    samba_client = None # اگر نتوانستیم متصل شویم، آن را None قرار می‌دهیم

# ذخیره وضعیت و مدل‌های انتخاب شده توسط کاربران (به صورت ساده برای مثال)
user_states = {}
selected_models = {}

# --- توابع کمکی (برخی از آن‌ها برای مثال ساده شده‌اند) ---
def is_authorized(user_id: int) -> bool:
    """در یک سیستم واقعی، این تابع باید لیست کاربران مجاز را از یک دیتابیس یا فایل بخواند."""
    # برای سادگی، فعلاً فقط ادمین مجاز است.
    return user_id == ADMIN_ID

def authorized_only(handler_function):
    """دکوراتور برای بررسی دسترسی کاربر."""
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
    """دستور /start را مدیریت می‌کند و دکمه انتخاب مدل را نمایش می‌دهد."""
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("انتخاب مدل هوش مصنوعی", callback_data="select_model"))
    bot.send_message(message.chat.id, "سلام! به ربات هوش مصنوعی خوش آمدید. برای شروع، یک مدل را انتخاب کنید:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "select_model")
@authorized_only
def handle_select_model_callback(call):
    """مدیریت کلیک روی دکمه 'انتخاب مدل هوش مصنوعی'."""
    markup = InlineKeyboardMarkup()
    for model in AI_MODELS:
        markup.row(InlineKeyboardButton(model, callback_data=f"model_{model}"))
    bot.edit_message_text("لطفاً یکی از مدل‌های زیر را انتخاب کنید:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
@authorized_only
def handle_model_selection(call):
    """مدیریت انتخاب مدل توسط کاربر."""
    user_id = call.from_user.id
    model_name = call.data.replace("model_", "")
    selected_models[user_id] = model_name
    message = f"مدل شما به **{model_name}** تغییر کرد.\n\n"
    if model_name in VISION_MODELS:
        message += "این مدل از تحلیل تصویر پشتیبانی می‌کند. می‌توانید یک عکس (با یا بدون کپشن) ارسال کنید."
    else:
        message += "حالا می‌توانید پیام متنی خود را ارسال کنید."
    bot.edit_message_text(message, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['text'], func=lambda message: not message.text.startswith('/'))
@authorized_only
def handle_text_messages(message):
    """پردازش پیام‌های متنی کاربر."""
    user_id = message.from_user.id
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
    
    if samba_client:
        try:
            response = samba_client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": message.text}],
            )
            response_text = response.choices[0].message.content
        except SambaNovaError as e:
            response_text = f"خطا در ارتباط با API SambaNova: {e}"
        except Exception as e:
            response_text = f"یک خطای پیش‌بینی نشده رخ داد: {e}"
    else:
        response_text = "سرویس SambaNova در دسترس نیست. لطفاً با ادمین تماس بگیرید."

    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)

@bot.message_handler(content_types=['photo'])
@authorized_only
def handle_photo_messages(message):
    """پردازش عکس‌های ارسالی کاربر."""
    user_id = message.from_user.id
    selected_model = selected_models.get(user_id)

    if not selected_model:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("انتخاب مدل", callback_data="select_model"))
        bot.reply_to(message, "لطفاً ابتدا یک مدل را انتخاب کنید.", reply_markup=markup)
        return
    
    if selected_model not in VISION_MODELS:
        bot.reply_to(message, f"مدل فعلی ({selected_model}) از تصویر پشتیبانی نمی‌کند. لطفاً یک مدل تصویری انتخاب کنید.")
        return

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
            
        except SambaNovaError as e:
            response_text = f"خطا در ارتباط با API SambaNova: {e}"
        except Exception as e:
            response_text = f"یک خطای پیش‌بینی نشده در پردازش تصویر رخ داد: {e}"
    else:
        response_text = "سرویس SambaNova در دسترس نیست. لطفاً با ادمین تماس بگیرید."

    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)

# --- نقطه شروع ربات ---
if __name__ == '__main__':
    if not samba_client:
        print("کلاینت SambaNova راه‌اندازی نشد. لطفاً کلید API را بررسی کنید.")
    else:
        print("ربات تلگرام در حال اجرا است...")
        bot.polling(non_stop=True)
