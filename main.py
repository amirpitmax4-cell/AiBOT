import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import os
import base64
from flask import Flask
from threading import Thread
from sambanova import SambaNova, SambaNovaError

# --- تنظیمات اولیه ---
# در Render حتماً این مقادیر را در بخش Environment Variables وارد کنید
TELEGRAM_BOT_TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"  # توکن ربات تلگرام خود را اینجا قرار دهید
SAMBA_API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"  # کلید API شما
ADMIN_ID = 5789565027  # شناسه کاربری عددی خودتان را به عنوان ادمین قرار دهید

VISION_MODELS = ["Llama-3.2-11B-Vision-Instruct", "Llama-3.2-90B-Vision-Instruct"] # مدل‌های ویژن نمونه
TEXT_MODELS = ["DeepSeek-R1", "Meta-Llama-3.3-70B-Instruct", "Qwen2.5-72B-Instruct"]
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
    samba_client = None

# ذخیره وضعیت (در حافظه موقت - با ریست شدن سرور پاک می‌شود)
selected_models = {}

# --- وب‌سرور Flask برای Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "I am alive! Bot is running..."

def run_web():
    # رندر پورت را در متغیر محیطی PORT قرار می‌دهد
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- توابع کمکی ---
def is_authorized(user_id: int) -> bool:
    return user_id == ADMIN_ID

def authorized_only(handler_function):
    def wrapper(message_or_call):
        user_id = message_or_call.from_user.id
        if not is_authorized(user_id):
            bot.send_message(user_id, "⛔ شما اجازه استفاده از این ربات را ندارید.")
            return
        return handler_function(message_or_call)
    return wrapper

# --- Handler های ربات ---

@bot.message_handler(commands=['start'])
@authorized_only
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🤖 انتخاب مدل هوش مصنوعی", callback_data="select_model"))
    bot.send_message(message.chat.id, "سلام! به ربات هوش مصنوعی خوش آمدید.\nبرای شروع، یک مدل را انتخاب کنید:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "select_model")
@authorized_only
def handle_select_model_callback(call):
    markup = InlineKeyboardMarkup()
    # دکمه‌ها را در ردیف‌های دوتایی می‌چینیم برای زیبایی بیشتر
    for i in range(0, len(AI_MODELS), 2):
        chunk = AI_MODELS[i:i + 2]
        row = [InlineKeyboardButton(model, callback_data=f"model_{model}") for model in chunk]
        markup.row(*row)
    
    bot.edit_message_text("لطفاً یکی از مدل‌های زیر را انتخاب کنید:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
@authorized_only
def handle_model_selection(call):
    user_id = call.from_user.id
    model_name = call.data.replace("model_", "")
    selected_models[user_id] = model_name
    
    msg_text = f"✅ مدل فعال: **{model_name}**\n\n"
    if model_name in VISION_MODELS:
        msg_text += "🖼️ این مدل تصویری است. یک عکس (با یا بدون کپشن) ارسال کنید."
    else:
        msg_text += "📝 این مدل متنی است. سوال یا متن خود را بنویسید."
        
    bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id, "مدل ذخیره شد")

@bot.message_handler(content_types=['text'], func=lambda message: not message.text.startswith('/'))
@authorized_only
def handle_text_messages(message):
    user_id = message.from_user.id
    selected_model = selected_models.get(user_id)

    if not selected_model:
        bot.reply_to(message, "⚠️ لطفاً ابتدا با دستور /start یک مدل انتخاب کنید.")
        return

    if selected_model in VISION_MODELS:
        bot.reply_to(message, "📷 مدل انتخابی شما تصویری است. لطفاً عکس ارسال کنید.")
        return

    processing_msg = bot.reply_to(message, f"⏳ در حال تفکر با مدل {selected_model}...")
    
    if samba_client:
        try:
            response = samba_client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": message.text}],
            )
            response_text = response.choices[0].message.content
        except Exception as e:
            response_text = f"❌ خطا: {e}"
    else:
        response_text = "خطا: کلاینت SambaNova متصل نیست."

    # تلگرام محدودیت ۴۰۹۶ کاراکتر دارد، اگر متن طولانی بود باید تکه تکه شود (ساده شده)
    if len(response_text) > 4000:
        response_text = response_text[:4000] + "... (متن بریده شد)"
        
    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode='Markdown')

@bot.message_handler(content_types=['photo'])
@authorized_only
def handle_photo_messages(message):
    user_id = message.from_user.id
    selected_model = selected_models.get(user_id)

    if not selected_model or selected_model not in VISION_MODELS:
        bot.reply_to(message, "⚠️ لطفاً ابتدا یک مدل تصویری (Vision) انتخاب کنید.")
        return

    processing_msg = bot.reply_to(message, f"👁️ در حال تحلیل تصویر با {selected_model}...")
    
    if samba_client:
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            base64_image = base64.b64encode(downloaded_file).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{base64_image}"
            
            caption = message.caption or "Describe this image."
            messages_payload = [{
                "role": "user", 
                "content": [
                    {"type": "text", "text": caption}, 
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }]
            
            response = samba_client.chat.completions.create(model=selected_model, messages=messages_payload)
            response_text = response.choices[0].message.content
            
        except Exception as e:
            response_text = f"❌ خطا: {e}"
    else:
        response_text = "خطا: سرویس SambaNova در دسترس نیست."

    bot.edit_message_text(response_text, chat_id=message.chat.id, message_id=processing_msg.message_id)

# --- نقطه شروع ---
if __name__ == '__main__':
    # 1. اجرای وب‌سرور در یک ترد جداگانه
    keep_alive()
    
    # 2. اجرای ربات تلگرام
    if not samba_client:
        print("Warning: SambaNova client not initialized.")
    
    print("Bot is running...")
    # استفاده از infinity_polling پایداری بیشتری دارد
    bot.infinity_polling(skip_pending=True)
