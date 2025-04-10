import os
import requests
import hmac
import hashlib
from flask import Flask, Response, request, jsonify, render_template_string, session, redirect, url_for
from datetime import datetime, timedelta
import time
import threading
from functools import wraps

# Flask application
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')  # For sessions

# Bot configuration
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'  # Channel username
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]  # Replace with your admin user IDs
MAX_FILE_SIZE_MB = 50  # Maximum file size in MB
RATE_LIMIT = 3  # Files per minute per user
BOT_USERNAME = "IP_AdressBot"  # Your bot's username

# User data and file storage (in memory for simplicity; use a database in production)
uploaded_files = {}
user_activity = {}
users = {}

# Telegram Login Widget settings
TELEGRAM_BOT_API_KEY = TOKEN
TELEGRAM_BOT_USERNAME = BOT_USERNAME

# Helper functions
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def create_inline_keyboard(buttons, columns=2):
    keyboard = []
    row = []
    for i, button in enumerate(buttons, 1):
        row.append(button)
        if i % columns == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard}

def create_reply_keyboard(buttons, resize=True, one_time=False):
    keyboard = []
    row = []
    for button in buttons:
        row.append({"text": button})
    keyboard.append(row)
    return {
        "keyboard": keyboard,
        "resize_keyboard": resize,
        "one_time_keyboard": one_time,
        "selective": True
    }

def send_message(chat_id, text, reply_markup=None, disable_web_page_preview=True):
    try:
        url = f"{BASE_API_URL}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    try:
        url = f"{BASE_API_URL}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error editing message: {e}")
        return None

def send_file_to_channel(file_id, file_type, caption=None, chat_id=CHANNEL_USERNAME):
    methods = {
        "document": ("sendDocument", "document"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio"),
        "voice": ("sendVoice", "voice")
    }
    
    if file_type not in methods:
        return None

    method, payload_key = methods[file_type]
    url = f"{BASE_API_URL}/{method}"
    payload = {"chat_id": chat_id, payload_key: file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode": "HTML"
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()

def delete_message(chat_id, message_id):
    url = f"{BASE_API_URL}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    response = requests.post(url, json=payload, timeout=30)
    return response.status_code == 200

def get_user_info(user_id):
    url = f"{BASE_API_URL}/getChat"
    payload = {"chat_id": user_id}
    response = requests.post(url, json=payload, timeout=30)
    if response.status_code == 200:
        return response.json().get("result", {})
    return {}

def send_typing_action(chat_id):
    url = f"{BASE_API_URL}/sendChatAction"
    payload = {"chat_id": chat_id, "action": "typing"}
    requests.post(url, json=payload, timeout=30)

def create_file_info_message(file_data, channel_url):
    file_type_emoji = {
        "document": "📄",
        "photo": "🖼️",
        "video": "🎬",
        "audio": "🎵",
        "voice": "🎤"
    }.get(file_data["file_type"], "📁")
    
    user_info = get_user_info(file_data["user_id"])
    username = user_info.get("username", "Unknown")
    first_name = user_info.get("first_name", "User")
    
    upload_time = datetime.fromtimestamp(file_data["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
    
    return f"""
{file_type_emoji} <b>File Successfully Uploaded!</b>

👤 <b>Uploaded by:</b> {first_name} (@{username})
📅 <b>Upload time:</b> {upload_time}
📏 <b>File size:</b> {file_data.get('file_size', 'N/A')} MB

🔗 <b>Channel URL:</b> <a href="{channel_url}">Click here to view</a>

<i>You can delete this file using the button below.</i>
"""

def check_rate_limit(user_id):
    now = time.time()
    if user_id not in user_activity:
        user_activity[user_id] = []
    
    user_activity[user_id] = [t for t in user_activity[user_id] if now - t < 60]
    
    if len(user_activity[user_id]) >= RATE_LIMIT:
        return False
    
    user_activity[user_id].append(now)
    return True

# Webhook and routes
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://uploadfiletgbot.vercel.app')
    webhook_url = f"{BASE_API_URL}/setWebhook?url={vercel_url}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    response = requests.get(webhook_url, timeout=30)
    if response.status_code == 200:
        return "Webhook successfully set", 200
    return f"Error setting webhook: {response.text}", response.status_code

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "no data"}), 400

    if "callback_query" in update:
        handle_callback_query(update["callback_query"])
    elif "message" in update:
        handle_message(update["message"])

    return jsonify({"status": "processed"}), 200

def handle_callback_query(callback):
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]
    user_id = callback["from"]["id"]
    callback_data = callback["data"]

    if callback_data.startswith("delete_"):
        channel_message_id = int(callback_data.split("_")[1])
        handle_delete(chat_id, message_id, user_id, channel_message_id)
    elif callback_data in ["help", "upload_instructions", "main_menu", "admin_panel", "admin_stats", "admin_list", "admin_users", "admin_restart", "privacy"]:
        handle_menu_action(chat_id, message_id, user_id, callback_data)

def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    if "text" in message:
        handle_text_command(chat_id, user_id, message["text"])
    elif any(key in message for key in ["document", "photo", "video", "audio", "voice"]):
        handle_file_upload(chat_id, user_id, message)

def handle_text_command(chat_id, user_id, text):
    send_typing_action(chat_id)
    if text == "/start":
        show_main_menu(chat_id, user_id)
    elif text == "/help":
        show_help(chat_id)
    elif text == "/upload":
        show_upload_instructions(chat_id)
    elif text == "/stats" and user_id in ADMIN_IDS:
        show_stats(chat_id)
    elif text == "/list" and user_id in ADMIN_IDS:
        list_files(chat_id, user_id)
    elif text == "/privacy":
        show_privacy_policy(chat_id)
    elif text == "/restart" and user_id in ADMIN_IDS:
        uploaded_files.clear()
        send_message(chat_id, "🔄 <b>Bot has been restarted.</b>\n\nAll cached data has been cleared.")
    else:
        send_message(chat_id, "❓ <b>Unknown Command</b>\n\nType /help to see available commands.")

def handle_file_upload(chat_id, user_id, message):
    if not check_rate_limit(user_id):
        send_message(chat_id, "⚠️ <b>Rate Limit Exceeded</b>\n\nPlease wait a minute before uploading more files.")
        return

    file_id, file_type, caption, file_size = extract_file_info(message)
    if file_size > MAX_FILE_SIZE_MB:
        send_message(chat_id, f"⚠️ <b>File Too Large</b>\n\nMaximum file size is {MAX_FILE_SIZE_MB} MB. Your file is {file_size:.2f} MB.")
        return

    send_typing_action(chat_id)
    result = send_file_to_channel(file_id, file_type, caption)
    if result and result.get("ok"):
        channel_message_id = result["result"]["message_id"]
        channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

        uploaded_files[channel_message_id] = {
            "file_id": file_id,
            "file_type": file_type,
            "user_id": user_id,
            "timestamp": message["date"],
            "caption": caption,
            "file_size": round(file_size, 2)
        }

        file_info = create_file_info_message(uploaded_files[channel_message_id], channel_url)
        buttons = [
            {"text": "🗑️ Delete File", "callback_data": f"delete_{channel_message_id}"},
            {"text": "🔗 Copy Link", "url": channel_url},
            {"text": "📤 Upload Another", "callback_data": "upload_instructions"},
            {"text": "🏠 Main Menu", "callback_data": "main_menu"}
        ]
        reply_markup = create_inline_keyboard(buttons)
        send_message(chat_id, file_info, reply_markup)
    else:
        send_message(chat_id, "❌ <b>Upload Failed</b>\n\nSorry, I couldn't upload your file. Please try again.")

def extract_file_info(message):
    if "document" in message:
        return message["document"]["file_id"], "document", message.get("caption"), message["document"].get("file_size", 0) / (1024 * 1024)
    elif "photo" in message:
        return message["photo"][-1]["file_id"], "photo", message.get("caption"), message["photo"][-1].get("file_size", 0) / (1024 * 1024)
    elif "video" in message:
        return message["video"]["file_id"], "video", message.get("caption"), message["video"].get("file_size", 0) / (1024 * 1024)
    elif "audio" in message:
        return message["audio"]["file_id"], "audio", message.get("caption"), message["audio"].get("file_size", 0) / (1024 * 1024)
    elif "voice" in message:
        return message["voice"]["file_id"], "voice", message.get("caption"), message["voice"].get("file_size", 0) / (1024 * 1024)
    return None, None, None, 0

def show_main_menu(chat_id, user_id=None, message_id=None):
    welcome_message = """
🌟 <b>Welcome to File Uploader Bot!</b> 🌟

I can upload your files to our channel and provide you with a shareable link.

<b>Main Features:</b>
• Upload documents, photos, videos, and audio files
• Get direct links to your uploaded files
• Delete your files anytime
• Simple and intuitive interface

Use the buttons below to get started or type /help for more information.
"""
    buttons = [
        {"text": "📤 Upload File", "callback_data": "upload_instructions"},
        {"text": "ℹ️ Help", "callback_data": "help"},
        {"text": "🔒 Privacy Policy", "callback_data": "privacy"}
    ]
    if user_id and user_id in ADMIN_IDS:
        buttons.append({"text": "🛠️ Admin Panel", "callback_data": "admin_panel"})
    
    reply_markup = create_inline_keyboard(buttons, columns=2)
    
    if message_id:
        edit_message_text(chat_id, message_id, welcome_message, reply_markup)
    else:
        send_message(chat_id, welcome_message, reply_markup)

def show_help(chat_id, message_id=None):
    help_text = """
📚 <b>File Uploader Bot Help</b>

<b>Available commands:</b>
/start - Start the bot and get instructions
/help - Show this help message
/upload - Learn how to upload files
/privacy - View our privacy policy

<b>How to use:</b>
1. Send me a file (document, photo, video, or audio)
2. I'll upload it to our channel
3. You'll get a shareable link
4. You can delete it anytime with the delete button

<b>Features:</b>
• Fast and secure file uploading
• Direct links to your files
• Delete functionality for your files
• Support for various file types
• Rate limiting (max {RATE_LIMIT} files per minute)
• File size limit ({MAX_FILE_SIZE_MB} MB max)
""".format(RATE_LIMIT=RATE_LIMIT, MAX_FILE_SIZE_MB=MAX_FILE_SIZE_MB)
    buttons = [
        {"text": "📤 How to Upload", "callback_data": "upload_instructions"},
        {"text": "🔒 Privacy Policy", "callback_data": "privacy"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, help_text, reply_markup)
    else:
        send_message(chat_id, help_text, reply_markup)

def show_upload_instructions(chat_id, message_id=None):
    instructions = """
📤 <b>How to Upload Files</b>

1. <b>Simple Upload:</b>
   • Just send me any file (document, photo, video, or audio)
   • I'll automatically upload it to the channel

2. <b>With Caption:</b>
   • Send a file with a caption
   • The caption will be included with your file

3. <b>Supported Formats:</b>
   • Documents (PDF, Word, Excel, etc.)
   • Photos (JPG, PNG, etc.)
   • Videos (MP4, etc.)
   • Audio files (MP3, etc.)

<b>Limitations:</b>
• Max file size: {MAX_FILE_SIZE_MB} MB
• Max uploads: {RATE_LIMIT} per minute

<i>Note: Large files may take longer to process.</i>
""".format(MAX_FILE_SIZE_MB=MAX_FILE_SIZE_MB, RATE_LIMIT=RATE_LIMIT)
    buttons = [
        {"text": "🔙 Main Menu", "callback_data": "main_menu"},
        {"text": "ℹ️ General Help", "callback_data": "help"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, instructions, reply_markup)
    else:
        send_message(chat_id, instructions, reply_markup)

def show_privacy_policy(chat_id, message_id=None):
    privacy_text = """
🔒 <b>Privacy Policy</b>

We are committed to protecting your privacy. Here's how we handle your data:

1. <b>Data Collection:</b> We only collect the data necessary for file uploading and management, such as your Telegram ID, username, and file metadata.

2. <b>Data Usage:</b> Your data is used solely to provide our services, including uploading files and managing your uploads. We do not share your data with third parties unless required by law.

3. <b>Data Storage:</b> Files and user data are stored temporarily and can be deleted at your request or automatically after a set period.

4. <b>Your Rights:</b> You can request deletion of your data or files at any time by contacting us or using the delete button.

5. <b>Contact Us:</b> For privacy concerns, contact our admin at @AdminUsername.

By using this bot, you agree to this privacy policy.
"""
    buttons = [
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    if message_id:
        edit_message_text(chat_id, message_id, privacy_text, reply_markup)
    else:
        send_message(chat_id, privacy_text, reply_markup)

def show_admin_panel(chat_id, message_id=None):
    admin_text = """
🛠️ <b>Admin Panel</b>

<b>Available Commands:</b>
/stats - Show bot statistics
/list - List all uploaded files
/restart - Clear all cached data

<b>Quick Actions:</b>
"""
    buttons = [
        {"text": "📊 View Stats", "callback_data": "admin_stats"},
        {"text": "📜 List Files", "callback_data": "admin_list"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons, columns=2)
    
    if message_id:
        edit_message_text(chat_id, message_id, admin_text, reply_markup)
    else:
        send_message(chat_id, admin_text, reply_markup)

def show_stats(chat_id):
    total_files = len(uploaded_files)
    active_users = len({v['user_id'] for v in uploaded_files.values()})
    total_size = sum(v.get('file_size', 0) for v in uploaded_files.values())
    
    stats_message = f"""
📊 <b>Bot Statistics</b>

• Total files uploaded: {total_files}
• Active users: {active_users}
• Total storage used: {total_size:.2f} MB
• Rate limit: {RATE_LIMIT} files per minute
• Max file size: {MAX_FILE_SIZE_MB} MB

<b>System Status:</b>
The bot is functioning normally.
"""
    buttons = [
        {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    send_message(chat_id, stats_message, reply_markup)

def list_files(chat_id, user_id):
    if user_id not in ADMIN_IDS:
        send_message(chat_id, "⛔ <b>Permission Denied</b>\n\nOnly admins can use this command.")
        return
    
    if not uploaded_files:
        send_message(chat_id, "ℹ️ <b>No files uploaded yet.</b>")
        return
    
    message = "📜 <b>Recently Uploaded Files</b>\n\n"
    for i, (msg_id, file_data) in enumerate(list(uploaded_files.items())[-10:], 1):
        user_info = get_user_info(file_data["user_id"])
        username = user_info.get("username", "Unknown")
        file_type = file_data["file_type"].capitalize()
        timestamp = datetime.fromtimestamp(file_data["timestamp"]).strftime('%Y-%m-%d %H:%M')
        
        message += f"{i}. <b>{file_type}</b> by @{username}\n"
        message += f"   📅 {timestamp} | 📏 {file_data.get('file_size', 'N/A')} MB\n"
        message += f"   🔗 <a href='https://t.me/{CHANNEL_USERNAME[1:]}/{msg_id}'>View File</a>\n\n"
    
    if len(uploaded_files) > 10:
        message += f"<i>Showing last 10 of {len(uploaded_files)} files</i>"
    
    buttons = [
        {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    send_message(chat_id, message, reply_markup)

def handle_delete(chat_id, message_id, user_id, channel_message_id):
    if channel_message_id in uploaded_files:
        file_data = uploaded_files[channel_message_id]
        if user_id in ADMIN_IDS or file_data["user_id"] == user_id:
            if delete_message(CHANNEL_USERNAME, channel_message_id):
                del uploaded_files[channel_message_id]
                edit_message_text(chat_id, message_id, "✅ <b>File successfully deleted!</b>", reply_markup=None)
            else:
                edit_message_text(chat_id, message_id, "❌ <b>Failed to delete the file.</b>\n\nPlease try again.", reply_markup=create_inline_keyboard([{"text": "Try Again", "callback_data": f"delete_{channel_message_id}"}]))
        else:
            edit_message_text(chat_id, message_id, "⛔ <b>Permission Denied</b>\n\nOnly the uploader or admins can delete this file.", reply_markup=None)
    else:
        edit_message_text(chat_id, message_id, "⚠️ <b>File not found</b>\n\nThis file may have already been deleted.", reply_markup=None)

def handle_menu_action(chat_id, message_id, user_id, action):
    if action == "help":
        show_help(chat_id, message_id)
    elif action == "upload_instructions":
        show_upload_instructions(chat_id, message_id)
    elif action == "main_menu":
        show_main_menu(chat_id, message_id, user_id)
    elif action == "privacy":
        show_privacy_policy(chat_id, message_id)
    elif action == "admin_panel" and user_id in ADMIN_IDS:
        show_admin_panel(chat_id, message_id)
    elif action == "admin_stats" and user_id in ADMIN_IDS:
        show_stats(chat_id)
    elif action == "admin_list" and user_id in ADMIN_IDS:
        list_files(chat_id, user_id)

# Background task
def clean_activity_data():
    while True:
        now = time.time()
        for user_id in list(user_activity.keys()):
            user_activity[user_id] = [t for t in user_activity[user_id] if now - t < 120]
            if not user_activity[user_id]:
                del user_activity[user_id]
        time.sleep(3600)

cleaner_thread = threading.Thread(target=clean_activity_data, daemon=True)
cleaner_thread.start()

# Web Routes with Optional Telegram Login
@app.route('/', methods=['GET'])
def home():
    user_id = session.get('user_id', None)
    is_logged_in = user_id is not None
    is_admin = user_id in ADMIN_IDS if is_logged_in else False
    return render_template_string(HOME_HTML, bot_username=TELEGRAM_BOT_USERNAME, privacy_policy_url='/privacy', is_logged_in=is_logged_in, is_admin=is_admin)

@app.route('/login', methods=['GET'])
def login():
    return render_template_string(LOGIN_HTML, bot_username=TELEGRAM_BOT_USERNAME)

@app.route('/', methods=['POST'])  # This matches your data-auth-url
def auth():
    data = request.form
    if 'id' in data and 'first_name' in data and 'auth_date' in data:
        user_id = data['id']
        first_name = data['first_name']
        auth_date = int(data['auth_date'])
        hash_ = data['hash']

        check_string = '\n'.join([f"{key}={value}" for key, value in sorted(data.items()) if key != 'hash'])
        secret_key = hmac.new(b'WebAppData', TELEGRAM_BOT_API_KEY.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash == hash_:
            session['user_id'] = user_id
            session['first_name'] = first_name
            return redirect(url_for('home'))
        else:
            return jsonify({"error": "Authentication failed"}), 401
    return jsonify({"error": "Invalid data"}), 400

@app.route('/logout', methods=['GET'])
def logout():
    session.pop('user_id', None)
    session.pop('first_name', None)
    return redirect(url_for('home'))

@app.route('/privacy', methods=['GET'])
def privacy_policy():
    return render_template_string(PRIVACY_HTML)

@app.route('/admin', methods=['GET'])
@login_required
def admin_panel():
    user_id = session.get('user_id')
    if user_id not in ADMIN_IDS:
        return "Access denied", 403
    return render_template_string(ADMIN_HTML, uploaded_files=uploaded_files, CHANNEL_USERNAME=CHANNEL_USERNAME)

# HTML Templates as Strings
HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram File Uploader Bot</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4361ee; --secondary-color: #3f37c9; --accent-color: #4895ef; --dark-color: #2b2d42; --light-color: #f8f9fa; --success-color: #4cc9f0; --danger-color: #f72585; --warning-color: #f8961e; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); min-height: 100vh; padding: 2rem; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; background-color: white; border-radius: 15px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); position: relative; overflow: hidden; }
        .container::before { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 10px; background: linear-gradient(90deg, var(--primary-color), var(--accent-color)); }
        header { text-align: center; margin-bottom: 3rem; }
        h1 { font-size: 2.5rem; color: var(--primary-color); margin-bottom: 1rem; font-weight: 700; }
        .subtitle { font-size: 1.2rem; color: var(--dark-color); opacity: 0.8; margin-bottom: 2rem; }
        .status-card, .feature-card { background-color: white; border-radius: 10px; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05); transition: transform 0.3s, box-shadow 0.3s; }
        .status-card:hover, .feature-card:hover { transform: translateY(-5px); box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1); }
        .status-title { font-size: 1.5rem; color: var(--dark-color); margin-bottom: 1rem; display: flex; align-items: center; }
        .status-title::before { content: '✓'; width: 30px; height: 30px; background-color: var(--success-color); color: white; border-radius: 50%; text-align: center; line-height: 30px; margin-right: 10px; font-size: 1rem; }
        .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 2rem; margin-bottom: 3rem; }
        .feature-icon { font-size: 2.5rem; color: var(--primary-color); margin-bottom: 1rem; }
        .feature-title { font-size: 1.3rem; color: var(--dark-color); margin-bottom: 0.5rem; font-weight: 600; }
        .btn { display: inline-block; padding: 0.8rem 1.5rem; background: linear-gradient(135deg, var(--primary-color), var(--secondary-color)); color: white; text-decoration: none; border-radius: 50px; font-weight: 500; transition: all 0.3s; border: none; cursor: pointer; box-shadow: 0 5px 15px rgba(67, 97, 238, 0.3); margin: 0.5rem; }
        .btn:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(67, 97, 238, 0.4); color: white; }
        .btn-outline { background: transparent; border: 2px solid var(--primary-color); color: var(--primary-color); box-shadow: none; }
        .btn-outline:hover { background: linear-gradient(135deg, var(--primary-color), var(--secondary-color)); color: white; }
        .btn-group { display: flex; flex-wrap: wrap; justify-content: center; margin-top: 2rem; }
        footer { text-align: center; margin-top: 3rem; color: var(--dark-color); opacity: 0.7; font-size: 0.9rem; }
        .login-section { text-align: center; margin-top: 2rem; }
        @media (max-width: 768px) { .container { padding: 1.5rem; } h1 { font-size: 2rem; } .features { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Telegram File Uploader Bot</h1>
            <p class="subtitle">Easily upload and share files through Telegram</p>
        </header>
        
        <div class="status-card">
            <h2 class="status-title">Bot Status: Running</h2>
            <p>This is the webhook endpoint for the Telegram File Uploader Bot. The bot is currently online and ready to process your requests.</p>
        </div>
        
        <div class="features">
            <div class="feature-card">
                <div class="feature-icon">📤</div>
                <h3 class="feature-title">File Upload</h3>
                <p>Upload documents, photos, videos, and audio files directly to your Telegram channel with ease.</p>
            </div>
            
            <div class="feature-card">
                <div class="feature-icon">🔗</div>
                <h3 class="feature-title">Shareable Links</h3>
                <p>Get direct links to your uploaded files that you can share with anyone.</p>
            </div>
            
            <div class="feature-card">
                <div class="feature-icon">🛡️</div>
                <h3 class="feature-title">Secure & Private</h3>
                <p>Your files are securely stored and can be deleted anytime, with a strict privacy policy.</p>
            </div>
        </div>
        
        <div class="btn-group">
            <a href="https://t.me/{{ bot_username }}" class="btn">Start the Bot</a>
            <a href="/setwebhook" class="btn btn-outline">Set Webhook</a>
            {% if is_logged_in and is_admin %}
                <a href="/admin" class="btn">Admin Panel</a>
            {% endif %}
            {% if is_logged_in %}
                <a href="/logout" class="btn btn-outline">Logout</a>
            {% endif %}
        </div>
        
        <div class="login-section">
            {% if not is_logged_in %}
                <p>Want to access additional features? <a href="/login" class="btn-outline">Login with Telegram</a></p>
            {% else %}
                <p>Welcome! You are logged in.</p>
            {% endif %}
        </div>
        
        <footer>
            <p>© 2025 Telegram File Uploader Bot. All rights reserved. <a href="{{ privacy_policy_url }}">Privacy Policy</a></p>
        </footer>
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login with Telegram</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); font-family: 'Poppins', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-container { background: white; padding: 2rem; border-radius: 15px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); text-align: center; }
        h1 { color: #4361ee; margin-bottom: 1rem; }
        .telegram-login { margin-top: 1rem; }
        .back-btn { display: inline-block; padding: 0.8rem 1.5rem; background: #4361ee; color: white; border-radius: 50px; text-decoration: none; margin-top: 1rem; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Login with Telegram</h1>
        <p>Click the button below to log in using your Telegram account for additional features.</p>
        <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="{{ bot_username }}" data-size="large" data-auth-url="https://uploadfiletgbot.vercel.app/" data-request-access="write"></script>
        <p>By logging in, you agree to our <a href="/privacy">Privacy Policy</a>.</p>
        <a href="/" class="back-btn">Back to Home</a>
    </div>
</body>
</html>
"""

PRIVACY_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); font-family: 'Poppins', sans-serif; padding: 2rem; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 2rem; border-radius: 15px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); }
        h1 { color: #4361ee; margin-bottom: 1rem; }
        p { line-height: 1.6; color: #2b2d42; margin-bottom: 1rem; opacity: 0.9; }
        a { color: #4361ee; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .back-btn { display: inline-block; padding: 0.8rem 1.5rem; background: #4361ee; color: white; border-radius: 50px; text-decoration: none; margin-top: 2rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Privacy Policy</h1>
        <p>We are committed to protecting your privacy. This Privacy Policy explains how we collect, use, and safeguard your information when you use our Telegram File Uploader Bot and website.</p>

        <h2>1. Data Collection</h2>
        <p>We collect only the data necessary for providing our services, including your Telegram ID, username, and file metadata (e.g., file type, size, and upload time) when you interact with the bot. If you choose to log in via Telegram on our website, we may also store your user ID and name for authentication purposes.</p>

        <h2>2. Data Usage</h2>
        <p>Your data is used exclusively to facilitate file uploads, provide shareable links, manage your interactions with the bot, and (if logged in) access additional website features. We do not share your data with third parties unless required by law or with your explicit consent.</p>

        <h2>3. Data Storage</h2>
        <p>Files and user data are stored temporarily on our servers and can be deleted at your request or automatically after a set period (e.g., 30 days). You can request deletion at any time by contacting us or using the delete function in the bot. Website login data is stored in session cookies and cleared when you log out or the session expires.</p>

        <h2>4. Your Rights</h2>
        <p>You have the right to access, correct, or delete your personal data. If you have concerns or questions about your data, please contact our admin at @AdminUsername.</p>

        <h2>5. Security</h2>
        <p>We implement reasonable security measures to protect your data from unauthorized access, alteration, or disclosure. However, no method of transmission over the Internet or electronic storage is 100% secure, and we cannot guarantee absolute security.</p>

        <h2>6. Third-Party Services</h2>
        <p>Our bot and website use Telegram's API and infrastructure. Their privacy policies also apply to any data processed through their services.</p>

        <h2>7. Changes to This Policy</h2>
        <p>We may update this Privacy Policy from time to time. Any changes will be posted here, and we encourage you to review this policy periodically.</p>

        <h2>8. Contact Us</h2>
        <p>If you have any questions or concerns about this Privacy Policy, please contact us at @AdminUsername or via our website.</p>

        <a href="/" class="back-btn">Back to Home</a>
    </div>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); font-family: 'Poppins', sans-serif; padding: 2rem; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 2rem; border-radius: 15px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); }
        h1 { color: #4361ee; margin-bottom: 1rem; }
        .file-list { margin-top: 2rem; }
        .file-item { border-bottom: 1px solid #eee; padding: 1rem 0; }
        .btn { display: inline-block; padding: 0.8rem 1.5rem; background: #4361ee; color: white; border-radius: 50px; text-decoration: none; margin: 0.5rem; }
        .btn:hover { background: #3f37c9; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Admin Panel</h1>
        <p>Manage uploaded files, users, and bot settings.</p>

        <div class="file-list">
            <h2>Uploaded Files</h2>
            {% for msg_id, file_data in uploaded_files.items() %}
                <div class="file-item">
                    <p><strong>File Type:</strong> {{ file_data.file_type|capitalize }}</p>
                    <p><strong>Uploaded By:</strong> User ID {{ file_data.user_id }}</p>
                    <p><strong>Size:</strong> {{ file_data.file_size }} MB</p>
                    <p><strong>Uploaded At:</strong> {{ datetime.fromtimestamp(file_data.timestamp).strftime('%Y-%m-%d %H:%M:%S') }}</p>
                    <a href="https://t.me/{{ CHANNEL_USERNAME[1:] }}/{{ msg_id }}" class="btn">View File</a>
                    <a href="#" class="btn" onclick="deleteFile({{ msg_id }})">Delete</a>
                </div>
            {% endfor %}
        </div>

        <a href="/" class="btn">Back to Home</a>
        <a href="/logout" class="btn">Logout</a>
    </div>

    <script>
        function deleteFile(msg_id) {
            if (confirm("Are you sure you want to delete this file?")) {
                fetch('/delete_file/' + msg_id, { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            alert('File deleted successfully!');
                            location.reload();
                        } else {
                            alert('Failed to delete file.');
                        }
                    });
            }
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
