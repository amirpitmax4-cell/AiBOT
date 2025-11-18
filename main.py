import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import os
import base64
from flask import Flask
from threading import Thread
from sambanova import SambaNova

# --- تنظیمات (Environment Variables) ---
# مقادیر را از متغیرهای محیطی رندر می‌خوانیم
TOKEN = "8300190763:AAGFBs0TuLVKSlJ0xwI1My-9f1rZlMX0mnA"  # توکن ربات تلگرام خود را اینجا قرار دهید
API_KEY = "b46dffe7-a5e0-4c75-ade5-04b5ae9819aa"  # کلید API شما
ADMIN_ID = 5789565027  # شناسه کاربری عددی خودتان را به عنوان ادمین قرار دهید

bot = telebot.TeleBot(TOKEN)
samba = None

# تلاش برای اتصال به هوش مصنوعی
try:
    if "YOUR" not in API_KEY:
        samba = SambaNova(api_key=API_KEY)
        print("✅ SambaNova Connected.")
    else:
        print("⚠️ API Key Not Found.")
except Exception as e:
    print(f"❌ Connection Error: {e}")

# لیست مدل‌ها
VISION_MODEL = "Llama-3.2-11B-Vision-Instruct"  # مدلی که هم عکس می‌فهمه هم متن

# ذخیره وضعیت کاربران
user_models = {}

# ==========================================
# بخش سایت (FLASK) - ساده‌ترین حالت ممکن
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    # فقط یک متن ساده برمی‌گرداند تا رندر بفهمد سایت زنده است
    return "<h1>Bot is Online & Running!</h1>"

def run_web():
    # پورت را از رندر می‌گیرد یا پیش‌فرض 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()
# ==========================================

# --- توابع کمکی ---
def is_admin(user_id):
    return user_id == ADMIN_ID

def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

# --- هندلر استارت ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ شما ادمین نیستید.")
        return
    
    # پیش‌فرض مدل ویژن را برای کاربر ست می‌کنیم
    user_models[message.from_user.id] = VISION_MODEL
    
    bot.reply_to(message, 
                 "👋 سلام!\n\n"
                 "من روی مدل **Llama 3.2 Vision** تنظیم شدم.\n"
                 "📸 می‌تونی **عکس** بفرستی.\n"
                 "📝 می‌تونی **متن** بفرستی.\n"
                 "هر طور راحتی صحبت کن!", 
                 parse_mode="Markdown")

# --- هندلر همه پیام‌های متنی ---
@bot.message_handler(content_types=['text'])
def text_handler(message):
    if not is_admin(message.from_user.id): return

    # اعلام وضعیت تایپینگ
    bot.send_chat_action(message.chat.id, 'typing')

    try:
        # مستقیم می‌فرستیم به مدل (چون مدل ویژن متن خالی رو هم جواب میده)
        response = samba.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": message.text}],
        )
        reply = response.choices[0].message.content
        
        # ارسال پاسخ (تکه‌تکه اگر طولانی بود)
        for chunk in split_text(reply):
            bot.reply_to(message, chunk, parse_mode="Markdown")
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# --- هندلر عکس ---
@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    if not is_admin(message.from_user.id): return

    bot.send_chat_action(message.chat.id, 'upload_photo')
    temp_msg = bot.reply_to(message, "👀 در حال دیدن عکس...")

    try:
        # دریافت و تبدیل عکس
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64_img = base64.b64encode(downloaded).decode('utf-8')
        img_url = f"data:image/jpeg;base64,{b64_img}"
        
        caption = message.caption if message.caption else "توضیح بده چی می‌بینی؟"

        # ارسال به هوش مصنوعی
        response = samba.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image_url", "image_url": {"url": img_url}}
                ]
            }]
        )
        reply = response.choices[0].message.content
        
        bot.delete_message(message.chat.id, temp_msg.message_id)
        
        for chunk in split_text(reply):
            bot.reply_to(message, chunk, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, temp_msg.message_id)

# --- اجرای نهایی ---
if __name__ == "__main__":
    # اول سرور سایت رو روشن می‌کنیم
    keep_alive()
    
    # بعد ربات رو روشن می‌کنیم
    print("🤖 Bot Started...")
    bot.infinity_polling(skip_pending=True)
