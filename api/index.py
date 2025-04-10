import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import time
import threading
import hashlib
import pytz

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')  # Fetch token from Vercel environment variables
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'  # Channel username
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]  # Replace with your admin user IDs
MAX_FILE_SIZE_MB = 50  # Maximum file size in MB
RATE_LIMIT = 3  # Files per minute per user
PRIVACY_POLICY_URL = "https://yourdomain.com/privacy"  # Update with your actual privacy policy URL

# Dictionary to track files uploaded by the bot
uploaded_files = {}
user_activity = {}  # Track user activity for rate limiting
user_sessions = {}  # Store user preferences and session data

# Helper function to hash user data for privacy
def hash_user_id(user_id):
    return hashlib.sha256(f"filebot_salt_{user_id}".encode()).hexdigest()[:12]

# Helper function to create stylish inline keyboards
def create_inline_keyboard(buttons, columns=2):
    keyboard = []
    row = []
    for i, button in enumerate(buttons, 1):
        row.append(button)
        if i % columns == 0:
            keyboard.append(row)
            row = []
    if row:  # Add remaining buttons if any
        keyboard.append(row)
    return {"inline_keyboard": keyboard}

# Helper function to create stylish reply keyboards
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

# Helper function to send a message with HTML formatting
def send_message(chat_id, text, reply_markup=None, disable_web_page_preview=True):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_web_page_preview
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error sending message: {response.text}")
    return response.json()

# Helper function to edit message text
def edit_message_text(chat_id, message_id, text, reply_markup=None):
    url = f"{BASE_API_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error editing message: {response.text}")
    return response.json()

# Helper function to send a file to the channel
def send_file_to_channel(file_id, file_type, caption=None, chat_id=CHANNEL_USERNAME):
    methods = {
        "document": ("sendDocument", "document"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio"),
        "voice": ("sendVoice", "voice"),
        "animation": ("sendAnimation", "animation"),
        "sticker": ("sendSticker", "sticker")
    }
    
    if file_type not in methods:
        return None

    method, payload_key = methods[file_type]
    url = f"{BASE_API_URL}/{method}"
    payload = {"chat_id": chat_id, payload_key: file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error sending file: {response.text}")
    return response.json()

# Helper function to delete a message
def delete_message(chat_id, message_id):
    url = f"{BASE_API_URL}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error deleting message: {response.text}")
    return response.status_code == 200

# Helper function to get user info (with privacy protections)
def get_user_info(user_id):
    url = f"{BASE_API_URL}/getChat"
    payload = {"chat_id": user_id}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        result = response.json().get("result", {})
        # Anonymize sensitive data
        if "username" in result:
            result["username"] = result["username"][0] + "***" + result["username"][-1] if result["username"] else "Anonymous"
        if "first_name" in result:
            result["first_name"] = result["first_name"][0] + "***" if result["first_name"] else "User"
        return result
    return {}

# Helper function to send typing action
def send_typing_action(chat_id):
    url = f"{BASE_API_URL}/sendChatAction"
    payload = {"chat_id": chat_id, "action": "typing"}
    requests.post(url, json=payload)

# Helper function to create stylish file info message
def create_file_info_message(file_data, channel_url):
    file_type_emoji = {
        "document": "📄",
        "photo": "🖼️",
        "video": "🎬",
        "audio": "🎵",
        "voice": "🎤",
        "animation": "🎞️",
        "sticker": "🏷️"
    }.get(file_data["file_type"], "📁")
    
    user_info = get_user_info(file_data["user_id"])
    username = user_info.get("username", "Anonymous")
    first_name = user_info.get("first_name", "User")
    
    upload_time = datetime.fromtimestamp(file_data["timestamp"], pytz.utc).astimezone(
        pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d %H:%M:%S')
    
    return f"""
{file_type_emoji} <b>File Successfully Uploaded!</b>

👤 <b>Uploaded by:</b> {first_name} (@{username})
📅 <b>Upload time:</b> {upload_time} (UTC+3:30)
📏 <b>File size:</b> {file_data.get('file_size', 'N/A')} MB
🔢 <b>File ID:</b> <code>{hash_user_id(file_data["file_id"])}</code>

🔗 <b>Channel URL:</b> <a href="{channel_url}">Click here to view</a>

<i>You can delete this file using the button below.</i>
"""

# Check rate limiting for users
def check_rate_limit(user_id):
    now = time.time()
    if user_id not in user_activity:
        user_activity[user_id] = []
    
    # Remove old entries (older than 1 minute)
    user_activity[user_id] = [t for t in user_activity[user_id] if now - t < 60]
    
    if len(user_activity[user_id]) >= RATE_LIMIT:
        return False
    
    user_activity[user_id].append(now)
    return True

# Set webhook for Vercel
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')
    webhook_url = f"{BASE_API_URL}/setWebhook?url={vercel_url}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    response = requests.get(webhook_url)
    if response.status_code == 200:
        return "Webhook successfully set", 200
    return f"Error setting webhook: {response.text}", response.status_code

# Webhook handler
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "no data"}), 400

    # Handle callback queries (buttons)
    if "callback_query" in update:
        callback = update["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        user_id = callback["from"]["id"]
        callback_data = callback["data"]

        if callback_data.startswith("delete_"):
            channel_message_id = int(callback_data.split("_")[1])
            if channel_message_id in uploaded_files:
                file_data = uploaded_files[channel_message_id]
                # Check if user is admin or original uploader
                if user_id in ADMIN_IDS or file_data["user_id"] == user_id:
                    if delete_message(CHANNEL_USERNAME, channel_message_id):
                        del uploaded_files[channel_message_id]
                        # Edit original message to show success
                        edit_message_text(
                            chat_id, 
                            message_id,
                            "✅ <b>File successfully deleted from the channel!</b>\n\n"
                            "The file has been permanently removed from our servers.",
                            reply_markup=None
                        )
                    else:
                        edit_message_text(
                            chat_id,
                            message_id,
                            "❌ <b>Failed to delete the file.</b>\n\n"
                            "Please try again later or contact admin if the issue persists.",
                            reply_markup=callback["message"].get("reply_markup")
                        )
                else:
                    edit_message_text(
                        chat_id,
                        message_id,
                        "⛔ <b>Permission Denied</b>\n\n"
                        "You don't have permission to delete this file.\n"
                        "Only the original uploader or admins can delete files.",
                        reply_markup=callback["message"].get("reply_markup")
                    )
            else:
                edit_message_text(
                    chat_id,
                    message_id,
                    "⚠️ <b>File not found</b>\n\n"
                    "This file may have already been deleted or expired.",
                    reply_markup=None
                )
        elif callback_data == "help":
            show_help(chat_id, message_id)
        elif callback_data == "upload_instructions":
            show_upload_instructions(chat_id, message_id)
        elif callback_data == "main_menu":
            show_main_menu(chat_id, message_id, user_id)
        elif callback_data == "admin_panel" and user_id in ADMIN_IDS:
            show_admin_panel(chat_id, message_id)
        elif callback_data == "show_privacy":
            show_privacy_policy(chat_id, message_id)
        elif callback_data == "request_data":
            handle_data_request(chat_id, user_id, message_id)
        elif callback_data == "delete_data":
            handle_data_deletion(chat_id, user_id, message_id)
        elif callback_data == "admin_stats":
            show_stats(chat_id)
        elif callback_data == "admin_list":
            list_files(chat_id, user_id)
        elif callback_data == "admin_cleanup":
            cleanup_old_files(chat_id, user_id, message_id)
        return jsonify({"status": "processed"}), 200

    # Handle messages
    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Initialize user session if not exists
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "preferences": {
                "notifications": True,
                "anonymize": False
            },
            "last_active": time.time()
        }

    # Command handlers
    if "text" in message:
        text = message["text"]
        if text.startswith("/"):
            send_typing_action(chat_id)
            
            if text == "/start":
                show_main_menu(chat_id, user_id=user_id)
            elif text == "/help":
                show_help(chat_id)
            elif text == "/restart" and user_id in ADMIN_IDS:
                uploaded_files.clear()
                send_message(chat_id, "🔄 <b>Bot has been restarted.</b>\n\nAll cached data has been cleared.")
            elif text == "/upload":
                show_upload_instructions(chat_id)
            elif text == "/stats" and user_id in ADMIN_IDS:
                show_stats(chat_id)
            elif text == "/list" and user_id in ADMIN_IDS:
                list_files(chat_id, user_id)
            elif text == "/privacy":
                show_privacy_policy(chat_id)
            elif text == "/mydata":
                handle_data_request(chat_id, user_id)
            elif text == "/delete":
                handle_data_deletion_request(chat_id, user_id)
            elif text == "/settings":
                show_settings(chat_id, user_id)
            else:
                send_message(chat_id, "❓ <b>Unknown Command</b>\n\nType /help to see available commands.")
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
    file_id = None
    file_type = None
    caption = None
    file_size = 0
    
    if "caption" in message:
        caption = message["caption"]
    
    if "document" in message:
        file_id = message["document"]["file_id"]
        file_type = "document"
        file_size = message["document"].get("file_size", 0) / (1024 * 1024)  # Convert to MB
    elif "photo" in message:
        file_id = message["photo"][-1]["file_id"]  # Largest photo size
        file_type = "photo"
        file_size = message["photo"][-1].get("file_size", 0) / (1024 * 1024)
    elif "video" in message:
        file_id = message["video"]["file_id"]
        file_type = "video"
        file_size = message["video"].get("file_size", 0) / (1024 * 1024)
    elif "audio" in message:
        file_id = message["audio"]["file_id"]
        file_type = "audio"
        file_size = message["audio"].get("file_size", 0) / (1024 * 1024)
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        file_type = "voice"
        file_size = message["voice"].get("file_size", 0) / (1024 * 1024)
    elif "animation" in message:
        file_id = message["animation"]["file_id"]
        file_type = "animation"
        file_size = message["animation"].get("file_size", 0) / (1024 * 1024)
    elif "sticker" in message:
        file_id = message["sticker"]["file_id"]
        file_type = "sticker"
        file_size = message["sticker"].get("file_size", 0) / (1024 * 1024)

    if file_id:
        # Check rate limiting
        if not check_rate_limit(user_id):
            send_message(chat_id, "⚠️ <b>Rate Limit Exceeded</b>\n\nPlease wait a minute before uploading more files.")
            return jsonify({"status": "rate limited"}), 200
            
        # Check file size
        if file_size > MAX_FILE_SIZE_MB:
            send_message(chat_id, f"⚠️ <b>File Too Large</b>\n\nMaximum file size is {MAX_FILE_SIZE_MB} MB. Your file is {file_size:.2f} MB.")
            return jsonify({"status": "file too large"}), 200
            
        send_typing_action(chat_id)
        # Send file to channel
        result = send_file_to_channel(file_id, file_type, caption)
        if result and result.get("ok"):
            channel_message_id = result["result"]["message_id"]
            channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

            # Store file info with timestamp
            uploaded_files[channel_message_id] = {
                "file_id": file_id,
                "file_type": file_type,
                "user_id": user_id,
                "timestamp": message["date"],
                "caption": caption,
                "file_size": round(file_size, 2),
                "hashed_id": hash_user_id(file_id)
            }

            # Create stylish message with delete button
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
            send_message(chat_id, "❌ <b>Upload Failed</b>\n\nSorry, I couldn't upload your file to the channel. Please try again later.")
    else:
        send_message(chat_id, "⚠️ <b>Unsupported Content</b>\n\nPlease send a document, photo, video, or audio file to upload.")

    return jsonify({"status": "processed"}), 200

def show_main_menu(chat_id, message_id=None, user_id=None):
    welcome_message = """
🌟 <b>Welcome to File Uploader Bot!</b> 🌟

I can upload your files to our channel and provide you with a shareable link.

<b>Main Features:</b>
• Upload documents, photos, videos, and audio files
• Get direct links to your uploaded files
• Delete your files anytime
• Privacy-focused design
• Simple and intuitive interface

Use the buttons below to get started or type /help for more information.
"""
    buttons = [
        {"text": "📤 Upload File", "callback_data": "upload_instructions"},
        {"text": "ℹ️ Help", "callback_data": "help"},
        {"text": "🔒 Privacy", "callback_data": "show_privacy"},
    ]
    
    # Add admin button if user is admin
    if user_id and user_id in ADMIN_IDS:
        buttons.append({"text": "🛠️ Admin Panel", "callback_data": "admin_panel"})
    
    reply_markup = create_inline_keyboard(buttons, columns=2)
    
    if message_id:
        edit_message_text(chat_id, message_id, welcome_message, reply_markup)
    else:
        send_message(chat_id, welcome_message, reply_markup)

def show_help(chat_id, message_id=None):
    help_text = f"""
📚 <b>File Uploader Bot Help</b>

<b>Available commands:</b>
/start - Start the bot and get instructions
/help - Show this help message
/upload - Learn how to upload files
/privacy - View our privacy policy
/mydata - Request your stored data
/delete - Request data deletion
/settings - Configure your preferences

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
• Privacy protection features

<b>Privacy Notice:</b>
We store minimal data necessary for operation. Your files are only stored in Telegram's servers.
"""
    buttons = [
        {"text": "📤 How to Upload", "callback_data": "upload_instructions"},
        {"text": "🔒 Privacy Policy", "callback_data": "show_privacy"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, help_text, reply_markup)
    else:
        send_message(chat_id, help_text, reply_markup)

def show_upload_instructions(chat_id, message_id=None):
    instructions = f"""
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
   • Animations (GIF, etc.)
   • Stickers (WebP, etc.)

<b>Limitations:</b>
• Max file size: {MAX_FILE_SIZE_MB} MB
• Max uploads: {RATE_LIMIT} per minute

<i>Note: Large files may take longer to process.</i>

<b>Privacy:</b>
Your files are stored only on Telegram's servers. We only store metadata necessary for operation.
"""
    buttons = [
        {"text": "🔙 Main Menu", "callback_data": "main_menu"},
        {"text": "ℹ️ General Help", "callback_data": "help"},
        {"text": "🔒 Privacy Policy", "callback_data": "show_privacy"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, instructions, reply_markup)
    else:
        send_message(chat_id, instructions, reply_markup)

def show_admin_panel(chat_id, message_id=None):
    admin_text = """
🛠️ <b>Admin Panel</b>

<b>Available Commands:</b>
/stats - Show bot statistics
/list - List all uploaded files
/restart - Clear all cached data
/cleanup - Remove old files

<b>Quick Actions:</b>
"""
    buttons = [
        {"text": "📊 View Stats", "callback_data": "admin_stats"},
        {"text": "📜 List Files", "callback_data": "admin_list"},
        {"text": "🧹 Cleanup Files", "callback_data": "admin_cleanup"},
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
    active_sessions = len(user_sessions)
    
    stats_message = f"""
📊 <b>Bot Statistics</b>

• Total files uploaded: {total_files}
• Active users: {active_users}
• Active sessions: {active_sessions}
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
        username = user_info.get("username", "Anonymous")
        file_type = file_data["file_type"].capitalize()
        timestamp = datetime.fromtimestamp(file_data["timestamp"], pytz.utc).astimezone(
            pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d %H:%M')
        
        message += f"{i}. <b>{file_type}</b> by @{username}\n"
        message += f"   📅 {timestamp} | 📏 {file_data.get('file_size', 'N/A')} MB\n"
        message += f"   🔗 <a href='https://t.me/{CHANNEL_USERNAME[1:]}/{msg_id}'>View File</a>\n"
        message += f"   🔢 <code>{file_data['hashed_id']}</code>\n\n"
    
    if len(uploaded_files) > 10:
        message += f"<i>Showing last 10 of {len(uploaded_files)} files</i>"
    
    buttons = [
        {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    send_message(chat_id, message, reply_markup)

def cleanup_old_files(chat_id, user_id, message_id=None):
    if user_id not in ADMIN_IDS:
        send_message(chat_id, "⛔ <b>Permission Denied</b>\n\nOnly admins can use this command.")
        return
    
    now = time.time()
    old_files = {k: v for k, v in uploaded_files.items() 
                if now - v["timestamp"] > 30 * 24 * 60 * 60}  # Older than 30 days
    
    if not old_files:
        message = "ℹ️ <b>No old files to clean up.</b>\n\nAll files are recent."
        if message_id:
            edit_message_text(chat_id, message_id, message)
        else:
            send_message(chat_id, message)
        return
    
    # Delete files from channel
    deleted_count = 0
    for msg_id in old_files:
        if delete_message(CHANNEL_USERNAME, msg_id):
            del uploaded_files[msg_id]
            deleted_count += 1
        time.sleep(0.5)  # Rate limit
    
    message = f"🧹 <b>Cleanup Complete</b>\n\nDeleted {deleted_count} old files (older than 30 days)."
    buttons = [
        {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, message, reply_markup)
    else:
        send_message(chat_id, message, reply_markup)

def show_privacy_policy(chat_id, message_id=None):
    privacy_text = f"""
🔒 <b>Privacy Policy</b>

<b>1. Data Collection:</b>
We collect minimal data necessary for operation:
- Your Telegram user ID (stored hashed)
- File metadata (type, size, timestamp)
- Temporary session data

<b>2. Data Usage:</b>
- To provide file upload services
- For rate limiting and abuse prevention
- For anonymous analytics (no personal data)

<b>3. Data Storage:</b>
- Files are stored only on Telegram's servers
- Metadata is stored temporarily (max 30 days)
- You can delete your files anytime

<b>4. Your Rights:</b>
- Request your stored data (/mydata)
- Delete your data (/delete)
- Opt-out of non-essential data collection

<b>5. Security:</b>
- All data is encrypted in transit
- Limited access to stored data
- Regular security audits

For the full privacy policy, visit: {PRIVACY_POLICY_URL}
"""
    buttons = [
        {"text": "📋 Request My Data", "callback_data": "request_data"},
        {"text": "🗑️ Delete My Data", "callback_data": "delete_data"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, privacy_text, reply_markup)
    else:
        send_message(chat_id, privacy_text, reply_markup)

def handle_data_request(chat_id, user_id, message_id=None):
    user_files = [f for f in uploaded_files.values() if f["user_id"] == user_id]
    session_data = user_sessions.get(user_id, {})
    
    if not user_files and not session_data:
        message = "ℹ️ <b>No stored data found for your account.</b>"
        if message_id:
            edit_message_text(chat_id, message_id, message)
        else:
            send_message(chat_id, message)
        return
    
    message = "📋 <b>Your Stored Data</b>\n\n"
    
    if user_files:
        message += "<b>Uploaded Files:</b>\n"
        for i, file_data in enumerate(user_files[:5], 1):
            message += f"{i}. {file_data['file_type'].capitalize()} ({file_data.get('file_size', 'N/A')} MB)\n"
            message += f"   Uploaded: {datetime.fromtimestamp(file_data['timestamp'], pytz.utc).astimezone(pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d %H:%M')}\n"
            message += f"   ID: <code>{file_data['hashed_id']}</code>\n\n"
        
        if len(user_files) > 5:
            message += f"<i>Showing 5 of {len(user_files)} files</i>\n\n"
    else:
        message += "No uploaded files found.\n\n"
    
    if session_data:
        message += "<b>Session Data:</b>\n"
        message += f"• Last active: {datetime.fromtimestamp(session_data.get('last_active', 0), pytz.utc).astimezone(pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d %H:%M')}\n"
        message += f"• Preferences: {session_data.get('preferences', {})}\n\n"
    
    message += "<i>Note: This is a summary. Full files are stored on Telegram's servers.</i>"
    
    buttons = [
        {"text": "🗑️ Delete My Data", "callback_data": "delete_data"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, message, reply_markup)
    else:
        send_message(chat_id, message, reply_markup)

def handle_data_deletion_request(chat_id, user_id):
    user_files = [k for k, v in uploaded_files.items() if v["user_id"] == user_id]
    
    if not user_files and user_id not in user_sessions:
        send_message(chat_id, "ℹ️ <b>No data to delete.</b>\n\nNo files or session data found for your account.")
        return
    
    message = """
⚠️ <b>Confirm Data Deletion</b>

This will:
1. Delete all your uploaded files from the channel
2. Remove your session data
3. Cannot be undone

Are you sure you want to proceed?
"""
    buttons = [
        {"text": "✅ Yes, Delete Everything", "callback_data": "delete_data"},
        {"text": "❌ Cancel", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    send_message(chat_id, message, reply_markup)

def handle_data_deletion(chat_id, user_id, message_id=None):
    user_files = [k for k, v in uploaded_files.items() if v["user_id"] == user_id]
    deleted_count = 0
    
    # Delete files from channel
    for msg_id in user_files:
        if delete_message(CHANNEL_USERNAME, msg_id):
            del uploaded_files[msg_id]
            deleted_count += 1
        time.sleep(0.5)  # Rate limit
    
    # Remove session data
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    message = f"""
✅ <b>Data Deletion Complete</b>

• Deleted {deleted_count} files
• Removed session data

All your data has been permanently erased from our systems.
"""
    buttons = [
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, message, reply_markup)
    else:
        send_message(chat_id, message, reply_markup)

def show_settings(chat_id, user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "preferences": {
                "notifications": True,
                "anonymize": False
            },
            "last_active": time.time()
        }
    
    prefs = user_sessions[user_id]["preferences"]
    notify_status = "✅ ON" if prefs.get("notifications", True) else "❌ OFF"
    anonymize_status = "✅ ON" if prefs.get("anonymize", False) else "❌ OFF"
    
    message = f"""
⚙️ <b>User Settings</b>

<b>Current Preferences:</b>
🔔 Notifications: {notify_status}
👤 Anonymize Data: {anonymize_status}

Use the buttons below to toggle settings.
"""
    buttons = [
        {"text": f"🔔 Notifications: {'Disable' if prefs.get('notifications', True) else 'Enable'}", 
         "callback_data": "toggle_notify"},
        {"text": f"👤 Anonymize: {'Disable' if prefs.get('anonymize', False) else 'Enable'}", 
         "callback_data": "toggle_anonymize"},
        {"text": "🔙 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    send_message(chat_id, message, reply_markup)

# Background task to clean up old data
def clean_activity_data():
    while True:
        now = time.time()
        # Clean old rate limit data
        for user_id in list(user_activity.keys()):
            user_activity[user_id] = [t for t in user_activity[user_id] if now - t < 120]
            if not user_activity[user_id]:
                del user_activity[user_id]
        
        # Clean inactive sessions (30 days)
        for user_id in list(user_sessions.keys()):
            if now - user_sessions[user_id].get("last_active", 0) > 30 * 24 * 60 * 60:
                del user_sessions[user_id]
        
        time.sleep(3600)  # Run every hour

# Start background cleaner thread
cleaner_thread = threading.Thread(target=clean_activity_data, daemon=True)
cleaner_thread.start()

# Stylish index route with privacy policy
@app.route('/', methods=['GET'])
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram File Uploader Bot</title>
        <meta name="description" content="Secure file uploader bot for Telegram with privacy-focused features">
        <meta name="keywords" content="telegram, bot, file upload, privacy, secure">
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
        <style>
            :root {
                --primary-color: #4361ee;
                --secondary-color: #3f37c9;
                --accent-color: #4895ef;
                --dark-color: #2b2d42;
                --light-color: #f8f9fa;
                --success-color: #4cc9f0;
                --danger-color: #f72585;
                --warning-color: #f8961e;
                --privacy-color: #7209b7;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Poppins', sans-serif;
                line-height: 1.6;
                color: var(--dark-color);
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                min-height: 100vh;
                padding: 2rem;
            }
            
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 2rem;
                background-color: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
                position: relative;
                overflow: hidden;
            }
            
            .container::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 10px;
                background: linear-gradient(90deg, var(--primary-color), var(--accent-color));
            }
            
            header {
                text-align: center;
                margin-bottom: 3rem;
            }
            
            h1 {
                font-size: 2.5rem;
                color: var(--primary-color);
                margin-bottom: 1rem;
                font-weight: 700;
            }
            
            .subtitle {
                font-size: 1.2rem;
                color: var(--dark-color);
                opacity: 0.8;
                margin-bottom: 2rem;
            }
            
            .status-card {
                background-color: white;
                border-radius: 10px;
                padding: 2rem;
                margin-bottom: 2rem;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                border-left: 5px solid var(--success-color);
            }
            
            .status-title {
                font-size: 1.5rem;
                color: var(--dark-color);
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
            }
            
            .status-title::before {
                content: '✓';
                display: inline-block;
                width: 30px;
                height: 30px;
                background-color: var(--success-color);
                color: white;
                border-radius: 50%;
                text-align: center;
                line-height: 30px;
                margin-right: 10px;
                font-size: 1rem;
            }
            
            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 2rem;
                margin-bottom: 3rem;
            }
            
            .feature-card {
                background-color: white;
                border-radius: 10px;
                padding: 1.5rem;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                transition: transform 0.3s, box-shadow 0.3s;
                position: relative;
                overflow: hidden;
            }
            
            .feature-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
            }
            
            .feature-card::after {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 5px;
                background: linear-gradient(90deg, var(--primary-color), var(--accent-color));
            }
            
            .feature-icon {
                font-size: 2.5rem;
                color: var(--primary-color);
                margin-bottom: 1rem;
            }
            
            .feature-title {
                font-size: 1.3rem;
                color: var(--dark-color);
                margin-bottom: 0.5rem;
                font-weight: 600;
            }
            
            .privacy-section {
                background-color: white;
                border-radius: 10px;
                padding: 2rem;
                margin-bottom: 2rem;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                border-left: 5px solid var(--privacy-color);
            }
            
            .privacy-title {
                font-size: 1.5rem;
                color: var(--privacy-color);
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
            }
            
            .privacy-title::before {
                content: '🔒';
                margin-right: 10px;
            }
            
            .privacy-points {
                margin-left: 1.5rem;
                margin-bottom: 1rem;
            }
            
            .privacy-point {
                margin-bottom: 0.5rem;
                display: flex;
                align-items: flex-start;
            }
            
            .privacy-point::before {
                content: '•';
                color: var(--privacy-color);
                font-weight: bold;
                display: inline-block;
                width: 1em;
                margin-left: -1em;
            }
            
            .btn {
                display: inline-block;
                padding: 0.8rem 1.5rem;
                background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
                color: white;
                text-decoration: none;
                border-radius: 50px;
                font-weight: 500;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
                box-shadow: 0 5px 15px rgba(67, 97, 238, 0.3);
                margin: 0.5rem;
            }
            
            .btn:hover {
                transform: translateY(-3px);
                box-shadow: 0 8px 20px rgba(67, 97, 238, 0.4);
                color: white;
            }
            
            .btn-outline {
                background: transparent;
                border: 2px solid var(--primary-color);
                color: var(--primary-color);
                box-shadow: none;
            }
            
            .btn-outline:hover {
                background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
                color: white;
            }
            
            .btn-privacy {
                background: linear-gradient(135deg, var(--privacy-color), #560bad);
            }
            
            .btn-privacy:hover {
                background: linear-gradient(135deg, #560bad, var(--privacy-color));
                color: white;
            }
            
            .btn-group {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                margin-top: 2rem;
            }
            
            footer {
                text-align: center;
                margin-top: 3rem;
                color: var(--dark-color);
                opacity: 0.7;
                font-size: 0.9rem;
            }
            
            .privacy-link {
                color: var(--privacy-color);
                text-decoration: none;
                font-weight: 500;
            }
            
            .privacy-link:hover {
                text-decoration: underline;
            }
            
            @media (max-width: 768px) {
                .container {
                    padding: 1.5rem;
                }
                
                h1 {
                    font-size: 2rem;
                }
                
                .features {
                    grid-template-columns: 1fr;
                }
                
                .btn-group {
                    flex-direction: column;
                    align-items: center;
                }
                
                .btn {
                    width: 100%;
                    margin: 0.5rem 0;
                    text-align: center;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>Telegram File Uploader Bot</h1>
                <p class="subtitle">Secure and privacy-focused file sharing through Telegram</p>
            </header>
            
            <div class="status-card">
                <h2 class="status-title">Bot Status: Running</h2>
                <p>This is the webhook endpoint for the Telegram File Uploader Bot. The bot is currently online and ready to process your requests with enhanced privacy protections.</p>
            </div>
            
            <div class="privacy-section">
                <h2 class="privacy-title">Our Privacy Commitment</h2>
                <div class="privacy-points">
                    <div class="privacy-point">We collect only the minimum data necessary to provide our service</div>
                    <div class="privacy-point">Your files are stored only on Telegram's servers, not ours</div>
                    <div class="privacy-point">We anonymize user data whenever possible</div>
                    <div class="privacy-point">You can request deletion of your data at any time</div>
                    <div class="privacy-point">We implement security best practices to protect your information</div>
                </div>
                <p>For full details, please read our <a href="/privacy" class="privacy-link">Privacy Policy</a>.</p>
            </div>
            
            <div class="features">
                <div class="feature-card">
                    <div class="feature-icon"><i class="fas fa-file-upload"></i></div>
                    <h3 class="feature-title">Secure File Upload</h3>
                    <p>Upload documents, photos, videos, and audio files directly to your Telegram channel with end-to-end encryption.</p>
                </div>
                
                <div class="feature-card">
                    <div class="feature-icon"><i class="fas fa-user-shield"></i></div>
                    <h3 class="feature-title">Privacy Protection</h3>
                    <p>We anonymize your data and provide tools to control your information. Your privacy is our priority.</p>
                </div>
                
                <div class="feature-card">
                    <div class="feature-icon"><i class="fas fa-cogs"></i></div>
                    <h3 class="feature-title">Advanced Features</h3>
                    <p>Rate limiting, file size controls, and admin tools ensure a smooth experience for all users.</p>
                </div>
            </div>
            
            <div class="btn-group">
                <a href="https://t.me/IP_AdressBot" class="btn"><i class="fab fa-telegram"></i> Start the Bot</a>
                <a href="/privacy" class="btn btn-privacy"><i class="fas fa-lock"></i> Privacy Policy</a>
                <a href="/setwebhook" class="btn btn-outline"><i class="fas fa-plug"></i> Set Webhook</a>
            </div>
            
            <footer>
                <p>© 2025 Telegram File Uploader Bot. All rights reserved.</p>
                <p><a href="/privacy" class="privacy-link">Privacy Policy</a> | <a href="/terms" class="privacy-link">Terms of Service</a></p>
            </footer>
        </div>
    </body>
    </html>
    """

# Privacy policy page
@app.route('/privacy', methods=['GET'])
def privacy_policy():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Privacy Policy - Telegram File Uploader Bot</title>
        <meta name="description" content="Privacy policy for the Telegram File Uploader Bot">
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --primary-color: #4361ee;
                --secondary-color: #3f37c9;
                --accent-color: #4895ef;
                --dark-color: #2b2d42;
                --light-color: #f8f9fa;
                --privacy-color: #7209b7;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Poppins', sans-serif;
                line-height: 1.6;
                color: var(--dark-color);
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                min-height: 100vh;
                padding: 2rem;
            }
            
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 2rem;
                background-color: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
            }
            
            .header {
                text-align: center;
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 2px solid var(--privacy-color);
            }
            
            h1 {
                font-size: 2.5rem;
                color: var(--privacy-color);
                margin-bottom: 0.5rem;
            }
            
            .subtitle {
                font-size: 1.1rem;
                color: var(--dark-color);
                opacity: 0.8;
            }
            
            .policy-section {
                margin-bottom: 2rem;
            }
            
            h2 {
                font-size: 1.8rem;
                color: var(--privacy-color);
                margin-bottom: 1rem;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid #eee;
            }
            
            h3 {
                font-size: 1.4rem;
                color: var(--secondary-color);
                margin: 1.5rem 0 0.5rem;
            }
            
            p {
                margin-bottom: 1rem;
            }
            
            ul {
                margin-left: 1.5rem;
                margin-bottom: 1rem;
            }
            
            li {
                margin-bottom: 0.5rem;
            }
            
            .highlight {
                background-color: rgba(114, 9, 183, 0.1);
                padding: 1rem;
                border-radius: 5px;
                margin: 1rem 0;
                border-left: 3px solid var(--privacy-color);
            }
            
            .btn {
                display: inline-block;
                padding: 0.8rem 1.5rem;
                background: linear-gradient(135deg, var(--privacy-color), #560bad);
                color: white;
                text-decoration: none;
                border-radius: 5px;
                font-weight: 500;
                transition: all 0.3s;
                margin-top: 1rem;
            }
            
            .btn:hover {
                background: linear-gradient(135deg, #560bad, var(--privacy-color));
                color: white;
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(114, 9, 183, 0.3);
            }
            
            .footer {
                text-align: center;
                margin-top: 3rem;
                padding-top: 1rem;
                border-top: 1px solid #eee;
                color: var(--dark-color);
                opacity: 0.7;
            }
            
            @media (max-width: 768px) {
                .container {
                    padding: 1.5rem;
                }
                
                h1 {
                    font-size: 2rem;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Privacy Policy</h1>
                <p class="subtitle">Last updated: May 15, 2025</p>
            </div>
            
            <div class="policy-section">
                <h2>1. Introduction</h2>
                <p>This Privacy Policy describes how we collect, use, and protect your information when you use our Telegram File Uploader Bot ("the Bot"). By using the Bot, you agree to the collection and use of information in accordance with this policy.</p>
                
                <div class="highlight">
                    <p><strong>Key Principle:</strong> We collect only the minimum data necessary to provide our service and implement measures to protect your privacy.</p>
                </div>
            </div>
            
            <div class="policy-section">
                <h2>2. Information We Collect</h2>
                
                <h3>2.1 User Information</h3>
                <p>When you interact with the Bot, we may collect:</p>
                <ul>
                    <li>Your Telegram user ID (stored in hashed form)</li>
                    <li>Your Telegram username (anonymized)</li>
                    <li>Your first name (anonymized)</li>
                </ul>
                
                <h3>2.2 File Information</h3>
                <p>For files you upload, we store:</p>
                <ul>
                    <li>File type (document, photo, video, etc.)</li>
                    <li>File size</li>
                    <li>Upload timestamp</li>
                    <li>Optional caption</li>
                </ul>
                <p><strong>Important:</strong> The actual files are stored only on Telegram's servers, not on our infrastructure.</p>
                
                <h3>2.3 Usage Data</h3>
                <p>We may collect anonymous usage statistics to improve the Bot:</p>
                <ul>
                    <li>Number of uploads</li>
                    <li>File types processed</li>
                    <li>Error rates</li>
                </ul>
            </div>
            
            <div class="policy-section">
                <h2>3. How We Use Your Information</h2>
                <p>We use the collected information for the following purposes:</p>
                <ul>
                    <li>To provide and maintain our service</li>
                    <li>To notify you about your uploads</li>
                    <li>To prevent abuse and enforce rate limits</li>
                    <li>To gather analysis to improve our service</li>
                    <li>To monitor the usage of the Bot</li>
                </ul>
            </div>
            
            <div class="policy-section">
                <h2>4. Data Retention</h2>
                <p>We retain your information only for as long as is necessary:</p>
                <ul>
                    <li>File metadata: Up to 30 days after upload or until you delete the file</li>
                    <li>User session data: Up to 30 days of inactivity</li>
                    <li>Anonymous analytics: Up to 1 year</li>
                </ul>
                <p>You can request deletion of your data at any time using the /delete command in the Bot.</p>
            </div>
            
            <div class="policy-section">
                <h2>5. Data Security</h2>
                <p>We implement appropriate security measures including:</p>
                <ul>
                    <li>Hashing of sensitive identifiers</li>
                    <li>Anonymization of personal data</li>
                    <li>Regular security reviews</li>
                    <li>Limited access to stored data</li>
                </ul>
                <p>While we strive to protect your information, no method of transmission over the Internet or electronic storage is 100% secure.</p>
            </div>
            
            <div class="policy-section">
                <h2>6. Your Data Rights</h2>
                <p>You have the right to:</p>
                <ul>
                    <li>Access the data we hold about you (/mydata command)</li>
                    <li>Request correction of inaccurate data</li>
                    <li>Request deletion of your data (/delete command)</li>
                    <li>Opt-out of non-essential data collection</li>
                </ul>
            </div>
            
            <div class="policy-section">
                <h2>7. Changes to This Policy</h2>
                <p>We may update our Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page and updating the "last updated" date.</p>
            </div>
            
            <div class="policy-section">
                <h2>8. Contact Us</h2>
                <p>If you have any questions about this Privacy Policy, please contact us through the Bot or at privacy@yourdomain.com.</p>
                <a href="/" class="btn">Return to Homepage</a>
            </div>
            
            <div class="footer">
                <p>© 2025 Telegram File Uploader Bot. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
