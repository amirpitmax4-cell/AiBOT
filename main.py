import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import os
import base64
from flask import Flask, render_template_string
from threading import Thread
from sambanova import SambaNova

TELEGRAM_BOT_TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"
SAMBA_API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"
ADMIN_ID = 5789565027

MODELS = {
    "Multi-Modal (متن و عکس)": [
        "Llama-3.2-11B-Vision-Instruct", 
        "Llama-3.2-90B-Vision-Instruct"
    ],
    "Text Only (فقط متن)": [
        "DeepSeek-R1", 
        "Meta-Llama-3.3-70B-Instruct", 
        "Qwen2.5-72B-Instruct",
        "gpt-oss-120b"
    ]
}
# لیستی جداگانه از مدل‌های ویژن برای بررسی سریع
VISION_MODELS = MODELS["Multi-Modal (متن و عکس)"]

# --- راه‌اندازی ربات و اتصال به SambaNova ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
samba_client = None

# تلاش برای اتصال به سرویس هوش مصنوعی
try:
    if "YOUR" not in SAMBA_API_KEY:
        samba_client = SambaNova(api_key=SAMBA_API_KEY)
        logging.info("✅ Successfully connected to SambaNova API.")
    else:
        logging.warning("⚠️ SambaNova API Key is not set. Please add it to your environment variables.")
except Exception as e:
    logging.error(f"❌ Failed to connect to SambaNova: {e}")

# متغیری برای ذخیره مدل انتخابی هر کاربر
user_data = {}

# --- وب‌سرور Flask برای زنده نگه داشتن ربات ---
app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>وضعیت ربات</title>
    <style>
        body { background-color: #1a1a1a; color: #e0e0e0; font-family: 'Vazirmatn', sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .container { text-align: center; padding: 2rem; border-radius: 1rem; background: #2c2c2c; box-shadow: 0 8px 20px rgba(0,0,0,0.5); }
        .dot { height: 12px; width: 12px; background-color: #4caf50; border-radius: 50%; display: inline-block; margin-left: 8px; box-shadow: 0 0 10px #4caf50; }
        h1 { font-size: 1.5rem; }
        p { color: #b0b0b0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ربات تلگرام SambaNova</h1>
        <p>ربات با موفقیت آنلاین شد</p>
        <p><span class="dot"></span>سیستم فعال است</p>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    """یک ترد جدید برای اجرای وب‌سرور ایجاد می‌کند."""
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# --- توابع کمکی ---
def is_admin(user_id):
    """بررسی می‌کند که آیا کاربر ادمین است یا خیر."""
    return user_id == ADMIN_ID

def check_auth(func):
    """یک دکوریتور برای محدود کردن دسترسی به ادمین."""
    def wrapper(message_or_call):
        user_id = message_or_call.from_user.id
        if is_admin(user_id):
            return func(message_or_call)
        else:
            # نوع پیام را تشخیص می‌دهد (پیام متنی یا دکمه شیشه‌ای)
            if isinstance(message_or_call, telebot.types.Message):
                bot.reply_to(message_or_call, "⛔ شما اجازه دسترسی به این ربات را ندارید.")
            elif isinstance(message_or_call, telebot.types.CallbackQuery):
                bot.answer_callback_query(message_or_call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
    return wrapper

def split_message(text, limit=4096):
    """متن‌های طولانی را برای ارسال در تلگرام تکه‌تکه می‌کند."""
    return [text[i:i + limit] for i in range(0, len(text), limit)]

# --- دستورات اصلی ربات (Message Handlers) ---

@bot.message_handler(commands=['start'])
@check_auth
def send_welcome(message):
    """هنگام ارسال دستور /start اجرا می‌شود."""
    user_id = message.from_user.id
    # اگر کاربر برای اولین بار استارت می‌زند، یک مدل پیش‌فرض برای او تنظیم می‌کنیم
    if user_id not in user_data:
        user_data[user_id] = {'model': VISION_MODELS[0]} # پیش‌فرض: اولین مدل تصویری
    
    current_model = user_data[user_id]['model']
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔄 تغییر مدل هوش مصنوعی", callback_data="select_model"))
    
    text = (
        f"👋 سلام!\n\n"
        f"🤖 مدل فعلی شما روی <code>{current_model}</code> تنظیم شده است.\n\n"
        "✨ این مدل قابلیت درک **متن و تصویر** را دارد.\n"
        "می‌توانید یک عکس بفرستید یا فقط پیام متنی ارسال کنید."
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)

# --- مدیریت دکمه‌های شیشه‌ای (Callback Query Handlers) ---

@bot.callback_query_handler(func=lambda call: call.data == "select_model")
@check_auth
def handle_model_menu(call):
    """منوی انتخاب مدل را نمایش می‌دهد."""
    markup = InlineKeyboardMarkup(row_width=1)
    current_model = user_data.get(call.from_user.id, {}).get('model')

    # ساخت دکمه‌ها برای هر مدل
    for category, models_list in MODELS.items():
        # اضافه کردن یک عنوان برای هر دسته
        markup.add(InlineKeyboardButton(f"--- {category} ---", callback_data="ignore"))
        for model in models_list:
            # اگر مدل فعلی کاربر همین مدل بود، یک تیک ✅ کنار آن نمایش بده
            btn_text = f"✅ {model}" if current_model == model else model
            markup.add(InlineKeyboardButton(btn_text, callback_data=f"set_{model}"))
    
    bot.edit_message_text(
        "لطفاً مدل هوش مصنوعی مورد نظر خود را انتخاب کنید:", 
        call.message.chat.id, 
        call.message.message_id, 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
@check_auth
def set_model(call):
    """مدل انتخابی کاربر را ذخیره می‌کند."""
    user_id = call.from_user.id
    model_name = call.data.replace("set_", "")
    
    # ذخیره مدل جدید
    user_data[user_id] = {'model': model_name}
    
    # پیام تأیید به کاربر
    msg = f"✅ مدل با موفقیت به <b>{model_name}</b> تغییر کرد.\n\n"
    if model_name in VISION_MODELS:
        msg += "اکنون می‌توانید هم <b>متن</b> و هم <b>عکس</b> ارسال کنید."
    else:
        msg += "این مدل فقط از <b>متن</b> پشتیبانی می‌کند."
    
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    bot.answer_callback_query(call.id, "مدل ذخیره شد")

# --- مدیریت ورودی‌های کاربر (متن و عکس) ---

@bot.message_handler(content_types=['text'], func=lambda m: not m.text.startswith('/'))
@check_auth
def handle_text(message):
    """پردازش پیام‌های متنی."""
    user_id = message.from_user.id
    model = user_data.get(user_id, {}).get('model', VISION_MODELS[0])

    bot.send_chat_action(message.chat.id, 'typing')

    try:
        response = samba_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message.text}],
        )
        content = response.choices[0].message.content
        for chunk in split_message(content):
            bot.reply_to(message, chunk, parse_mode='Markdown')
            
    except Exception as e:
        bot.reply_to(message, f"❌ یک خطا رخ داد: {e}")

@bot.message_handler(content_types=['photo'])
@check_auth
def handle_photo(message):
    """پردازش تصاویر ارسالی."""
    user_id = message.from_user.id
    model = user_data.get(user_id, {}).get('model', VISION_MODELS[0])
    
    # اگر مدل انتخاب شده قابلیت پردازش تصویر نداشت، به کاربر اطلاع بده
    if model not in VISION_MODELS:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("تغییر به یک مدل تصویری", callback_data="select_model"))
        bot.reply_to(message, "⚠️ مدل فعلی شما فقط متنی است و نمی‌تواند عکس را تحلیل کند. لطفاً مدل را عوض کنید:", reply_markup=markup)
        return

    loading_msg = bot.reply_to(message, "...👀 در حال پردازش تصویر")
    bot.send_chat_action(message.chat.id, 'upload_photo')

    try:
        # دریافت عکس و تبدیل آن به فرمت Base64
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{base64_image}"
        
        caption = message.caption if message.caption else "این تصویر را به طور کامل تحلیل کن."

        # ارسال درخواست به API
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
        bot.edit_message_text(f"❌ یک خطا رخ داد: {e}", message.chat.id, loading_msg.message_id)

# --- اجرای نهایی ربات ---
if __name__ == '__main__':
    if not samba_client:
        logging.error("Bot cannot start without a valid SambaNova API connection.")
    else:
        keep_alive() # وب‌سرور را برای آنلاین ماندن اجرا می‌کند
        logging.info("🤖 Bot is starting...")
        bot.infinity_polling(skip_pending=True)
