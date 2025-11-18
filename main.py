import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import os
import base64
import time
from flask import Flask, render_template_string
from threading import Thread
from sambanova import SambaNova, SambaNovaError

# --- تنظیمات محیطی (Environment Variables) ---
# در Render باید این‌ها را در بخش Environment ست کنید
TELEGRAM_BOT_TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"  # توکن ربات تلگرام خود را اینجا قرار دهید
SAMBA_API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"  # کلید API شما
ADMIN_ID = 5789565027  # شناسه کاربری عددی خودتان را به عنوان ادمین قرار دهید

# --- پیکربندی مدل‌ها ---
# مدل‌ها را دسته‌بندی می‌کنیم تا در منو قشنگ‌تر نمایش داده شوند
MODELS = {
    "Vision (تصویری)": ["Llama-3.2-11B-Vision-Instruct", "Llama-3.2-90B-Vision-Instruct"],
    "Text (متنی)": ["DeepSeek-R1", "Meta-Llama-3.3-70B-Instruct", "Qwen2.5-72B-Instruct"]
}

# فلت کردن لیست برای استفاده‌های فنی
ALL_MODELS = [m for category in MODELS.values() for m in category]
VISION_MODELS = MODELS["Vision (تصویری)"]

# --- راه‌اندازی ---
logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# کلاینت سامبا
samba_client = None
try:
    if SAMBA_API_KEY != "YOUR_API_KEY_HERE":
        samba_client = SambaNova(api_key=SAMBA_API_KEY)
        logging.info("✅ SambaNova client connected.")
    else:
        logging.warning("⚠️ API Key not set.")
except Exception as e:
    logging.error(f"❌ Error init SambaNova: {e}")

# حافظه موقت
user_data = {} # ساختار: {user_id: {'model': 'name', ...}}

# --- بخش وب‌سرور (Flask) برای Render ---
app = Flask(__name__)

# یک صفحه HTML زیبا برای اینکه نشان دهد ربات زنده است
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Status</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e2e; color: #cdd6f4; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background-color: #313244; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); text-align: center; border: 1px solid #45475a; }
        .status { font-size: 24px; color: #a6e3a1; margin-bottom: 10px; }
        .pulse { width: 15px; height: 15px; background-color: #a6e3a1; border-radius: 50%; display: inline-block; margin-right: 10px; animation: pulse-animation 2s infinite; }
        @keyframes pulse-animation { 0% { box-shadow: 0 0 0 0 rgba(166, 227, 161, 0.7); } 70% { box-shadow: 0 0 0 10px rgba(166, 227, 161, 0); } 100% { box-shadow: 0 0 0 0 rgba(166, 227, 161, 0); } }
        h1 { font-size: 2rem; margin: 0; }
        p { color: #a6adc8; }
    </style>
</head>
<body>
    <div class="card">
        <div class="status"><span class="pulse"></span>System Online</div>
        <h1>Telegram Bot is Running</h1>
        <p>Managed by Render & Flask</p>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# --- توابع کمکی ربات ---
def is_admin(user_id):
    return user_id == ADMIN_ID

def check_auth(func):
    def wrapper(message):
        if is_admin(message.from_user.id):
            return func(message)
        else:
            bot.reply_to(message, "⛔ <b>دسترسی غیرمجاز</b>\nشما اجازه استفاده از این ربات را ندارید.", parse_mode="HTML")
    return wrapper

def split_message(text, limit=4000):
    """تقسیم پیام‌های طولانی برای تلگرام"""
    return [text[i:i+limit] for i in range(0, len(text), limit)]

def get_user_model(user_id):
    return user_data.get(user_id, {}).get('model')

# --- هندلرها (Handlers) ---

@bot.message_handler(commands=['start'])
@check_auth
def send_welcome(message):
    user_first_name = message.from_user.first_name
    text = (
        f"👋 سلام <b>{user_first_name}</b> عزیز!\n\n"
        "🤖 من دستیار هوشمند شما هستم که به سرورهای قدرتمند <b>SambaNova</b> متصل است.\n\n"
        "🚀 <b>امکانات من:</b>\n"
        "• تحلیل تصاویر پیشرفته\n"
        "• پاسخ به سوالات پیچیده متنی\n"
        "• سرعت پردازش فوق‌العاده\n\n"
        "👇 برای شروع، لطفاً یک مدل هوش مصنوعی را انتخاب کنید:"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⚙️ انتخاب مدل (Select Model)", callback_data="select_model"))
    
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "select_model")
def handle_model_menu(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "شما ادمین نیستید!", show_alert=True)
        return

    markup = InlineKeyboardMarkup()
    
    # اضافه کردن دکمه‌ها بر اساس دسته‌بندی
    for category, models_list in MODELS.items():
        markup.add(InlineKeyboardButton(f"── {category} ──", callback_data="ignore"))
        # چیدن دکمه‌ها به صورت دوتایی
        row_btns = []
        for model in models_list:
            short_name = model.split("-")[0] + "..." + model.split("-")[-1] # کوتاه‌کردن نام برای دکمه
            if len(short_name) > 20: short_name = model[:20]
            
            # اگر این مدل انتخاب شده است، تیک کنارش بگذار
            current_model = get_user_model(call.from_user.id)
            btn_text = f"✅ {short_name}" if current_model == model else short_name
            
            row_btns.append(InlineKeyboardButton(btn_text, callback_data=f"set_{model}"))
        
        # اضافه کردن ردیف به کیبورد
        if len(row_btns) == 2:
            markup.row(row_btns[0], row_btns[1])
        elif len(row_btns) == 1:
            markup.row(row_btns[0])
        elif len(row_btns) > 2: # برای ۳ تایی
             markup.row(*row_btns)

    bot.edit_message_text(
        "🧠 لطفاً مدل مورد نظر خود را جهت پردازش انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def set_model(call):
    user_id = call.from_user.id
    if not is_admin(user_id): return

    model_name = call.data.replace("set_", "")
    if user_id not in user_data: user_data[user_id] = {}
    user_data[user_id]['model'] = model_name

    # متن تایید
    if model_name in VISION_MODELS:
        icon, type_text = "🖼️", "تحلیل تصویر"
        guide = "حالا می‌توانید یک <b>عکس</b> (با یا بدون کپشن) ارسال کنید."
    else:
        icon, type_text = "📝", "پردازش متن"
        guide = "حالا می‌توانید <b>سوال یا متن</b> خود را بنویسید."

    text = (
        f"✅ مدل تغییر کرد!\n\n"
        f"🔹 <b>مدل:</b> <code>{model_name}</code>\n"
        f"🔸 <b>نوع:</b> {icon} {type_text}\n\n"
        f"{guide}"
    )
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    bot.answer_callback_query(call.id, "مدل ذخیره شد")

@bot.message_handler(content_types=['text'], func=lambda m: not m.text.startswith('/'))
@check_auth
def handle_text(message):
    user_id = message.from_user.id
    model = get_user_model(user_id)

    if not model:
        bot.reply_to(message, "⚠️ هنوز مدلی انتخاب نکرده‌اید. لطفاً /start را بزنید.")
        return

    if model in VISION_MODELS:
        bot.reply_to(message, "📷 این مدل مخصوص <b>تصاویر</b> است. لطفاً یک عکس ارسال کنید.", parse_mode='HTML')
        return

    # ارسال اکشن typing برای حس بهتر
    bot.send_chat_action(message.chat.id, 'typing')
    
    loading_msg = bot.reply_to(message, f"⏳ <b>در حال فکر کردن با مدل {model}...</b>", parse_mode='HTML')

    try:
        start_time = time.time()
        response = samba_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message.text}],
        )
        content = response.choices[0].message.content
        duration = round(time.time() - start_time, 2)

        # حذف پیام Loading و ارسال پاسخ
        bot.delete_message(message.chat.id, loading_msg.message_id)
        
        # اضافه کردن هدر زیبا
        header = f"🤖 <b>پاسخ {model}:</b>\n⏱️ <code>{duration}s</code>\n\n"
        full_response = header + content
        
        # ارسال پیام (تکه‌تکه اگر طولانی باشد)
        for chunk in split_message(full_response):
            bot.reply_to(message, chunk, parse_mode='Markdown')

    except Exception as e:
        bot.edit_message_text(f"❌ <b>خطا در پردازش:</b>\n<code>{str(e)}</code>", message.chat.id, loading_msg.message_id, parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
@check_auth
def handle_photo(message):
    user_id = message.from_user.id
    model = get_user_model(user_id)

    if not model or model not in VISION_MODELS:
        bot.reply_to(message, "⚠️ مدل فعلی متنی است. لطفاً از منو، یک مدل <b>Vision</b> انتخاب کنید.", parse_mode='HTML')
        return

    bot.send_chat_action(message.chat.id, 'upload_photo')
    loading_msg = bot.reply_to(message, f"👁️ <b>در حال مشاهده و تحلیل تصویر با {model}...</b>", parse_mode='HTML')

    try:
        # دانلود عکس
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{base64_image}"
        
        caption = message.caption if message.caption else "لطفاً این تصویر را با جزئیات کامل توصیف کن."

        response = samba_client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }]
        )
        content = response.choices[0].message.content
        
        bot.delete_message(message.chat.id, loading_msg.message_id)
        
        for chunk in split_message(content):
            bot.reply_to(message, chunk, parse_mode='Markdown')

    except Exception as e:
        bot.edit_message_text(f"❌ <b>خطا در پردازش تصویر:</b>\n<code>{str(e)}</code>", message.chat.id, loading_msg.message_id, parse_mode='HTML')


# --- اجرای نهایی ---
if __name__ == '__main__':
    # 1. اجرای وب سرور برای زنده نگه داشتن در رندر
    keep_alive()
    
    print("🚀 Bot is starting...")
    # 2. اجرای ربات با قابلیت اتصال مجدد خودکار
    bot.infinity_polling(skip_pending=True)
