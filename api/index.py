import os
import requests
import hmac
import hashlib
from flask import Flask, Response, request, jsonify, render_template_string, session, redirect, url_for
from datetime import datetime
import time
import threading
import logging
from functools import wraps
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# In-memory user and file storage (replace with a real database in production)
users = {}  # {username: password}
uploaded_files = {}  # {message_id: file_data}
user_activity = {}

# Helper functions
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
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
        logger.error(f"Error sending message: {e}")
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
        logger.error(f"Error editing message: {e}")
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
        payload["parse_mode"] = "HTML"
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
    
    user_info = get_user_info(file_data.get("user_id", None)) if file_data.get("user_id") else {"username": file_data["user_id"], "first_name": file_data["user_id"]}
    username = user_info.get("username", file_data["user_id"])
    first_name = user_info.get("first_name", file_data["user_id"])
    
    upload_time = datetime.fromtimestamp(file_data["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
    
    return f"""
{file_type_emoji} <b>File Successfully Uploaded!</b>

👤 <b>Uploaded by:</b> {first_name} (@{username})
📅 <b>Upload time:</b> {upload_time}
📏 <b>File size:</b> {file_data.get('file_size', 'N/A')} MB

🔗 <b>Channel URL:</b> <a href="{channel_url}">Click here to view</a>

<i>You can delete this file using the button below.</i>
"""

def check_rate_limit(user_id_or_username):
    now = time.time()
    if user_id_or_username not in user_activity:
        user_activity[user_id_or_username] = []
    
    user_activity[user_id_or_username] = [t for t in user_activity[user_id_or_username] if now - t < 60]
    
    if len(user_activity[user_id_or_username]) >= RATE_LIMIT:
        return False
    
    user_activity[user_id_or_username].append(now)
    return True

# Webhook and routes for Telegram bot
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-app.vercel.app')
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
    elif callback_data in ["help", "upload_instructions", "main_menu", "admin_panel", "admin_stats", "admin_list", "privacy"]:
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

1. <b>Data Collection:</b> We only collect the data necessary for file uploading and management, such as your user ID, username, and file metadata.

2. <b>Data Usage:</b> Your data is used solely to provide our services, including uploading files and managing your uploads. We do not share your data with third parties unless required by law.

3. <b>Data Storage:</b> Files and user data are stored temporarily and can be deleted at your request or automatically after a set period.

4. <b>Your Rights:</b> You can request deletion of your data or files at any time by contacting us or using the delete button.

5. <b>Contact Us:</b> For privacy concerns, contact our admin at @MAXWARORG.

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

# Web Routes
@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return render_template_string(HOME_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users:
            return render_template_string(REGISTRATION_HTML, error="Username already exists!")
        users[username] = password
        return redirect(url_for('login'))
    return render_template_string(REGISTRATION_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        return render_template_string(LOGIN_HTML, error="Invalid credentials!")
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)
        if file and check_rate_limit(session['username']):
            filename = secure_filename(file.filename)
            file_size = os.path.getsize(file) / (1024 * 1024)  # Convert to MB
            if file_size > MAX_FILE_SIZE_MB:
                return render_template_string(DASHBOARD_HTML, error=f"File too large! Maximum size is {MAX_FILE_SIZE_MB} MB.", files=list(uploaded_files.values()))
            
            # Upload file to Telegram (simplified; adjust for actual file upload)
            # For real implementation, you need to upload the file to Telegram first, then get file_id
            # Here, we'll simulate with a placeholder file_id
            result = send_file_to_channel(None, "document", caption=f"Uploaded by {session['username']} via website")
            if result and result.get("ok"):
                channel_message_id = result["result"]["message_id"]
                channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

                uploaded_files[channel_message_id] = {
                    "file_type": "document",
                    "user_id": session['username'],
                    "timestamp": int(time.time()),
                    "caption": f"Uploaded by {session['username']} via website",
                    "file_size": round(file_size, 2)
                }

                return render_template_string(DASHBOARD_HTML, success="File uploaded successfully!", files=list(uploaded_files.values()))
            else:
                return render_template_string(DASHBOARD_HTML, error="Failed to upload file.", files=list(uploaded_files.values()))
        else:
            return render_template_string(DASHBOARD_HTML, error="Rate limit exceeded. Please wait a minute.", files=list(uploaded_files.values()))

    return render_template_string(DASHBOARD_HTML, files=list(uploaded_files.values()))

@app.route('/delete_file/<int:msg_id>')
@login_required
def delete_file(msg_id):
    username = session['username']
    if msg_id in uploaded_files and (username in ADMIN_IDS or uploaded_files[msg_id]["user_id"] == username):
        if delete_message(CHANNEL_USERNAME, msg_id):
            del uploaded_files[msg_id]
            return redirect(url_for('dashboard'))
    return redirect(url_for('dashboard'))

@app.route('/privacy', methods=['GET'])
def privacy_policy():
    return render_template_string(PRIVACY_HTML)

# Background task
def clean_activity_data():
    while True:
        now = time.time()
        for user in list(user_activity.keys()):
            user_activity[user] = [t for t in user_activity[user] if now - t < 120]
            if not user_activity[user]:
                del user_activity[user]
        time.sleep(3600)

cleaner_thread = threading.Thread(target=clean_activity_data, daemon=True)
cleaner_thread.start()

# HTML Templates
HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram File Uploader</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50c878; --accent-color: #f8f9fa; --dark-color: #1a1a1a; --light-color: #ffffff; --shadow-color: rgba(0, 0, 0, 0.1); }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #e3f2fd, #f5f7fa); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 2rem; }
        .container { max-width: 1200px; width: 100%; background: var(--light-color); border-radius: 20px; box-shadow: 0 15px 40px var(--shadow-color); padding: 4rem; text-align: center; animation: fadeIn 1s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: scale(0.9); } to { opacity: 1; transform: scale(1); } }
        h1 { color: var(--primary-color); font-size: 3rem; margin-bottom: 1.5rem; font-weight: 700; text-shadow: 0 2px 5px rgba(0, 0, 0, 0.1); }
        p { color: var(--dark-color); font-size: 1.2rem; margin-bottom: 2rem; opacity: 0.9; }
        .btn { display: inline-block; padding: 1rem 2.5rem; background: linear-gradient(45deg, var(--primary-color), var(--secondary-color)); color: var(--light-color); text-decoration: none; border-radius: 50px; font-weight: 600; transition: all 0.3s ease; box-shadow: 0 8px 20px var(--shadow-color); margin: 0.5rem; }
        .btn:hover { transform: translateY(-5px); box-shadow: 0 12px 30px var(--shadow-color); }
        footer { margin-top: 3rem; color: var(--dark-color); opacity: 0.7; font-size: 0.9rem; }
        @media (max-width: 768px) { .container { padding: 2rem; } h1 { font-size: 2.2rem; } p { font-size: 1rem; } .btn { padding: 0.8rem 1.5rem; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>Welcome to File Uploader</h1>
        <p>Upload and share files securely through our platform.</p>
        <a href="/register" class="btn">Register</a>
        <a href="/login" class="btn">Login</a>
        <footer>© 2025 File Uploader. All rights reserved. <a href="/privacy" style="color: var(--primary-color);">Privacy Policy</a></footer>
    </div>
</body>
</html>
"""

REGISTRATION_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Register - File Uploader</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50c878; --accent-color: #f8f9fa; --dark-color: #1a1a1a; --light-color: #ffffff; --shadow-color: rgba(0, 0, 0, 0.1); }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #e3f2fd, #f5f7fa); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 2rem; }
        .container { max-width: 500px; width: 100%; background: var(--light-color); border-radius: 20px; box-shadow: 0 15px 40px var(--shadow-color); padding: 3rem; text-align: center; animation: slideIn 1s ease-in; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(50px); } to { opacity: 1; transform: translateY(0); } }
        h1 { color: var(--primary-color); font-size: 2.5rem; margin-bottom: 1.5rem; font-weight: 700; }
        form { display: flex; flex-direction: column; gap: 1.5rem; }
        input { padding: 0.8rem; border: 2px solid var(--primary-color); border-radius: 10px; font-size: 1rem; transition: border-color 0.3s ease; }
        input:focus { outline: none; border-color: var(--secondary-color); box-shadow: 0 0 10px var(--secondary-color); }
        .error { color: #e74c3c; font-size: 0.9rem; margin-top: 0.5rem; }
        .btn { padding: 1rem 2.5rem; background: linear-gradient(45deg, var(--primary-color), var(--secondary-color)); color: var(--light-color); border: none; border-radius: 50px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 8px 20px var(--shadow-color); }
        .btn:hover { transform: translateY(-5px); box-shadow: 0 12px 30px var(--shadow-color); }
        a { color: var(--primary-color); text-decoration: none; font-size: 0.9rem; margin-top: 1rem; display: inline-block; }
        a:hover { text-decoration: underline; }
        @media (max-width: 768px) { .container { padding: 2rem; } h1 { font-size: 2rem; } input, .btn { padding: 0.7rem; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>Register</h1>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            {% if error %}
                <p class="error">{{ error }}</p>
            {% endif %}
            <button type="submit" class="btn">Register</button>
        </form>
        <a href="/login">Already have an account? Login</a>
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
    <title>Login - File Uploader</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50c878; --accent-color: #f8f9fa; --dark-color: #1a1a1a; --light-color: #ffffff; --shadow-color: rgba(0, 0, 0, 0.1); }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #e3f2fd, #f5f7fa); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 2rem; }
        .container { max-width: 500px; width: 100%; background: var(--light-color); border-radius: 20px; box-shadow: 0 15px 40px var(--shadow-color); padding: 3rem; text-align: center; animation: slideIn 1s ease-in; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(50px); } to { opacity: 1; transform: translateY(0); } }
        h1 { color: var(--primary-color); font-size: 2.5rem; margin-bottom: 1.5rem; font-weight: 700; }
        form { display: flex; flex-direction: column; gap: 1.5rem; }
        input { padding: 0.8rem; border: 2px solid var(--primary-color); border-radius: 10px; font-size: 1rem; transition: border-color 0.3s ease; }
        input:focus { outline: none; border-color: var(--secondary-color); box-shadow: 0 0 10px var(--secondary-color); }
        .error { color: #e74c3c; font-size: 0.9rem; margin-top: 0.5rem; }
        .btn { padding: 1rem 2.5rem; background: linear-gradient(45deg, var(--primary-color), var(--secondary-color)); color: var(--light-color); border: none; border-radius: 50px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 8px 20px var(--shadow-color); }
        .btn:hover { transform: translateY(-5px); box-shadow: 0 12px 30px var(--shadow-color); }
        a { color: var(--primary-color); text-decoration: none; font-size: 0.9rem; margin-top: 1rem; display: inline-block; }
        a:hover { text-decoration: underline; }
        @media (max-width: 768px) { .container { padding: 2rem; } h1 { font-size: 2rem; } input, .btn { padding: 0.7rem; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>Login</h1>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            {% if error %}
                <p class="error">{{ error }}</p>
            {% endif %}
            <button type="submit" class="btn">Login</button>
        </form>
        <a href="/register">Don't have an account? Register</a>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - File Uploader</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50c878; --accent-color: #f8f9fa; --dark-color: #1a1a1a; --light-color: #ffffff; --shadow-color: rgba(0, 0, 0, 0.1); }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #e3f2fd, #f5f7fa); min-height: 100vh; padding: 2rem; }
        .container { max-width: 1200px; margin: 0 auto; background: var(--light-color); border-radius: 20px; box-shadow: 0 15px 40px var(--shadow-color); padding: 4rem; animation: fadeIn 1s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: scale(0.9); } to { opacity: 1; transform: scale(1); } }
        h1 { color: var(--primary-color); font-size: 2.5rem; margin-bottom: 2rem; font-weight: 700; }
        .upload-form { margin-bottom: 2rem; }
        form { display: flex; flex-direction: column; gap: 1.5rem; max-width: 500px; margin: 0 auto; }
        input[type="file"] { padding: 0.8rem; border: 2px solid var(--primary-color); border-radius: 10px; font-size: 1rem; transition: border-color 0.3s ease; }
        input[type="file"]:focus { outline: none; border-color: var(--secondary-color); box-shadow: 0 0 10px var(--secondary-color); }
        .btn { padding: 1rem 2.5rem; background: linear-gradient(45deg, var(--primary-color), var(--secondary-color)); color: var(--light-color); border: none; border-radius: 50px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 8px 20px var(--shadow-color); }
        .btn:hover { transform: translateY(-5px); box-shadow: 0 12px 30px var(--shadow-color); }
        .message { margin: 1rem 0; padding: 1rem; border-radius: 10px; text-align: center; }
        .success { background: #d4edda; color: #155724; }
        .error { background: #f8d7da; color: #721c24; }
        .file-list { margin-top: 2rem; }
        .file-item { border-bottom: 1px solid #eee; padding: 1rem 0; }
        a { color: var(--primary-color); text-decoration: none; margin-left: 1rem; }
        a:hover { text-decoration: underline; }
        .logout-btn { display: inline-block; padding: 0.8rem 1.5rem; background: #e74c3c; color: var(--light-color); border-radius: 50px; text-decoration: none; margin-top: 1rem; }
        .logout-btn:hover { background: #c0392b; }
        @media (max-width: 768px) { .container { padding: 2rem; } h1 { font-size: 2rem; } .btn, input[type="file"] { padding: 0.7rem; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>Dashboard</h1>
        {% if success %}
            <div class="message success">{{ success }}</div>
        {% endif %}
        {% if error %}
            <div class="message error">{{ error }}</div>
        {% endif %}
        <div class="upload-form">
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="file" required>
                <button type="submit" class="btn">Upload File</button>
            </form>
        </div>
        <div class="file-list">
            <h2>Your Uploaded Files</h2>
            {% if files %}
                {% for file in files %}
                    <div class="file-item">
                        <p><strong>Type:</strong> {{ file.file_type|capitalize }}</p>
                        <p><strong>Size:</strong> {{ file.file_size }} MB</p>
                        <p><strong>Uploaded At:</strong> {{ datetime.fromtimestamp(file.timestamp).strftime('%Y-%m-%d %H:%M:%S') }}</p>
                        <a href="https://t.me/{{ CHANNEL_USERNAME[1:] }}/{{ loop.index0 + 1 }}" target="_blank">View</a>
                        <a href="{{ url_for('delete_file', msg_id=loop.index0 + 1) }}" onclick="return confirm('Are you sure?')">Delete</a>
                    </div>
                {% endfor %}
            {% else %}
                <p>No files uploaded yet.</p>
            {% endif %}
        </div>
        <a href="/logout" class="logout-btn">Logout</a>
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
    <title>Privacy Policy - File Uploader</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50c878; --accent-color: #f8f9fa; --dark-color: #1a1a1a; --light-color: #ffffff; --shadow-color: rgba(0, 0, 0, 0.1); }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark-color); background: linear-gradient(135deg, #e3f2fd, #f5f7fa); padding: 2rem 0; }
        .container { max-width: 1000px; margin: 0 auto; background: var(--light-color); padding: 4rem 5rem; border-radius: 20px; box-shadow: 0 15px 40px var(--shadow-color); animation: fadeIn 1s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        header { text-align: center; margin-bottom: 3rem; }
        h1 { color: var(--primary-color); font-size: 3rem; font-weight: 700; margin-bottom: 1.5rem; }
        h2 { color: var(--primary-color); font-size: 1.8rem; font-weight: 600; margin: 2.5rem 0 1.5rem; border-bottom: 3px solid var(--primary-color); padding-bottom: 0.7rem; }
        p { margin-bottom: 1.5rem; color: var(--dark-color); font-size: 1.1rem; opacity: 0.9; }
        a { color: var(--primary-color); text-decoration: none; transition: color 0.3s ease; }
        a:hover { color: var(--secondary-color); text-decoration: underline; }
        .policy-section { background: var(--accent-color); padding: 2rem; border-radius: 15px; margin-bottom: 2rem; box-shadow: 0 5px 15px var(--shadow-color); }
        .back-btn { display: inline-block; padding: 1rem 2rem; background: var(--primary-color); color: var(--light-color); border-radius: 50px; text-decoration: none; font-weight: 600; transition: all 0.3s ease; box-shadow: 0 8px 20px var(--shadow-color); margin-top: 2rem; }
        .back-btn:hover { transform: translateY(-5px); box-shadow: 0 12px 30px var(--shadow-color); background: var(--secondary-color); }
        @media (max-width: 768px) { .container { padding: 2rem; } h1 { font-size: 2.2rem; } h2 { font-size: 1.4rem; } p { font-size: 1rem; } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Privacy Policy</h1>
            <p>Ensuring your privacy and data security is our top priority.</p>
        </header>
        <div class="policy-section">
            <p>At File Uploader, we are dedicated to safeguarding your privacy. This Privacy Policy outlines how we collect, use, store, and protect your personal data when you interact with our service.</p>
        </div>
        <h2>1. Data We Collect</h2>
        <p>We only collect essential information necessary for our services, including your username, file metadata (type, size, upload time), and login details.</p>
        <h2>2. How We Use Your Data</h2>
        <p>Your data is used to facilitate file uploads, manage your account, and ensure service functionality. We do not share your data with third parties unless required by law.</p>
        <h2>3. Data Storage</h2>
        <p>Files and user data are stored temporarily and can be deleted at your request or after a set period (up to 30 days).</p>
        <h2>4. Your Rights</h2>
        <p>You have the right to access, correct, or delete your data at any time. Contact us for assistance.</p>
        <h2>5. Contact Us</h2>
        <p>For privacy concerns, reach out to our admin at <a href="https://t.me/MAXWARORG">@MAXWARORG</a>.</p>
        <a href="/" class="back-btn">Back to Home</a>
    </div>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
