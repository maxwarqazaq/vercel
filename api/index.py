import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import json
import hashlib
import time

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Data storage
uploaded_files = {}
user_settings = {}
file_tags = {}
rate_limits = {}  # New: Track user rate limits

# Helper functions
def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error sending message: {e}")
        return None

def send_file_to_channel(file_id, file_type, chat_id=CHANNEL_USERNAME):
    methods = {
        "document": ("sendDocument", "document"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio")
    }
    if file_type not in methods:
        return None
    method, payload_key = methods[file_type]
    url = f"{BASE_API_URL}/{method}"
    payload = {"chat_id": chat_id, payload_key: file_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error sending file: {e}")
        return None

def delete_message(chat_id, message_id):
    url = f"{BASE_API_URL}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException as e:
        print(f"Error deleting message: {e}")
        return False

def get_file_info(file_id):
    url = f"{BASE_API_URL}/getFile"
    payload = {"file_id": file_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def send_typing_action(chat_id):
    url = f"{BASE_API_URL}/sendChatAction"
    payload = {"chat_id": chat_id, "action": "typing"}
    requests.post(url, json=payload, timeout=5)

def get_channel_stats():
    url = f"{BASE_API_URL}/getChat"
    payload = {"chat_id": CHANNEL_USERNAME}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def pin_message(chat_id, message_id):
    url = f"{BASE_API_URL}/pinChatMessage"
    payload = {"chat_id": chat_id, "message_id": message_id, "disable_notification": True}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def send_welcome_message(chat_id, username):
    welcome_text = f"""
Hello {username}! 👋 Welcome to the File Sharing Bot!

Features:
📤 Upload files to our channel
🗑️ Delete your uploaded files
📊 View channel statistics
📌 Pin important files

Type /help for all commands!
Current date: {datetime.now().strftime('%Y-%m-%d')}
"""
    send_message(chat_id, welcome_text)

def generate_file_hash(file_id):
    file_info = get_file_info(file_id)
    if file_info and file_info.get("ok"):
        file_path = file_info["result"]["file_path"]
        return hashlib.md5(file_path.encode()).hexdigest()
    return None

def send_poll(chat_id, question, options):
    url = f"{BASE_API_URL}/sendPoll"
    payload = {"chat_id": chat_id, "question": question, "options": json.dumps(options), "is_anonymous": False}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def forward_message(chat_id, from_chat_id, message_id):
    url = f"{BASE_API_URL}/forwardMessage"
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def ban_user(chat_id, user_id):
    url = f"{BASE_API_URL}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

# New helper functions
def check_rate_limit(user_id):
    """Limit users to 5 uploads per hour"""
    current_time = time.time()
    if user_id not in rate_limits:
        rate_limits[user_id] = {"count": 0, "timestamp": current_time}
    elif current_time - rate_limits[user_id]["timestamp"] > 3600:  # Reset after 1 hour
        rate_limits[user_id] = {"count": 0, "timestamp": current_time}
    
    if rate_limits[user_id]["count"] >= 5:
        return False
    rate_limits[user_id]["count"] += 1
    return True

def get_file_download_link(file_id):
    """Generate direct download link for a file"""
    file_info = get_file_info(file_id)
    if file_info and file_info.get("ok"):
        file_path = file_info["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    return None

def cleanup_expired_files():
    """Remove files older than 24 hours"""
    current_time = datetime.now()
    expired = [mid for mid, info in uploaded_files.items() 
              if (current_time - datetime.fromisoformat(info["timestamp"])).total_seconds() > 86400]
    for mid in expired:
        delete_message(CHANNEL_USERNAME, mid)
        del uploaded_files[mid]
        if mid in file_tags:
            del file_tags[mid]

# Set webhook
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')
    webhook_url = f"{BASE_API_URL}/setWebhook?url={vercel_url}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    try:
        response = requests.get(webhook_url, timeout=10)
        if response.status_code == 200:
            return "Webhook successfully set", 200
        return f"Error setting webhook: {response.text}", response.status_code
    except requests.RequestException as e:
        return f"Error setting webhook: {e}", 500

# Webhook handler
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "no data"}), 400

    # Handle callback queries
    if "callback_query" in update:
        callback = update["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        user_id = callback["from"]["id"]
        callback_data = callback["data"]

        if callback_data.startswith("delete_"):
            channel_message_id = int(callback_data.split("_")[1])
            if (channel_message_id in uploaded_files and 
                uploaded_files[channel_message_id]["user_id"] == user_id):
                if delete_message(CHANNEL_USERNAME, channel_message_id):
                    del uploaded_files[channel_message_id]
                    if channel_message_id in file_tags:
                        del file_tags[channel_message_id]
                    send_message(chat_id, "File successfully deleted!")
                else:
                    send_message(chat_id, "Failed to delete the file.")
            else:
                send_message(chat_id, "You don’t have permission to delete this file or it no longer exists.")
        elif callback_data.startswith("pin_"):
            channel_message_id = int(callback_data.split("_")[1])
            if (channel_message_id in uploaded_files and 
                uploaded_files[channel_message_id]["user_id"] == user_id):
                if pin_message(CHANNEL_USERNAME, channel_message_id):
                    send_message(chat_id, "File pinned successfully!")
                else:
                    send_message(chat_id, "Failed to pin the file.")
        elif callback_data.startswith("share_"):
            channel_message_id = int(callback_data.split("_")[1])
            if (channel_message_id in uploaded_files and 
                uploaded_files[channel_message_id]["user_id"] == user_id):
                if forward_message(chat_id, CHANNEL_USERNAME, channel_message_id):
                    send_message(chat_id, "File shared to this chat!")
                else:
                    send_message(chat_id, "Failed to share file.")
        return jsonify({"status": "processed"}), 200

    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    username = message["from"].get("username", "User")

    if user_id not in user_settings:
        user_settings[user_id] = {"notify": True, "lang": "en"}

    if "text" in message:
        text = message["text"].lower()
        send_typing_action(chat_id)

        if text == "/start":
            send_welcome_message(chat_id, username)
        elif text == "/help":
            help_text = """
<b>Available Commands:</b>
/start - Start the bot
/help - Show this help message
/restart - Clear cached data
/upload - Upload instructions
/stats - Channel statistics
/list - List your files
/pin_<message_id> - Pin a file
/tag_<message_id>_<tag> - Tag a file
/search_<tag> - Search by tag
/poll - Create a poll
/share_<message_id> - Share file
/download_<message_id> - Get direct download link
/settings_notify_on/off - Toggle notifications
/settings_lang_en/es/fr - Set language
/ban_<user_id> - Ban user (admin only)
/cleanup - Remove expired files (admin only)
"""
            if send_message(chat_id, help_text) is None:
                send_message(chat_id, "Error displaying help. Please try again.")
        elif text == "/restart":
            uploaded_files.clear()
            file_tags.clear()
            rate_limits.clear()
            send_message(chat_id, "Bot restarted. All cached data cleared.")
        elif text == "/upload":
            upload_instructions = """
<b>To upload a file:</b>
1. Send a file (document, photo, video, or audio)
2. Get a URL and management options
3. Use buttons to delete/pin/share
<i>Limit: 5 uploads per hour</i>
"""
            send_message(chat_id, upload_instructions)
        elif text == "/stats":
            stats = get_channel_stats()
            if stats and stats.get("ok"):
                result = stats["result"]
                stats_text = f"""
<b>Channel Statistics:</b>
🏷️ Title: {result.get("title", "N/A")}
👥 Members: {result.get("members_count", "N/A")}
📝 Description: {result.get("description", "No description")}
📂 Total uploads: {len(uploaded_files)}
"""
                send_message(chat_id, stats_text)
            else:
                send_message(chat_id, "Failed to fetch channel statistics.")
        elif text.startswith("/list"):
            if not uploaded_files:
                send_message(chat_id, "No files uploaded yet.")
            else:
                file_list = "<b>Your Uploaded Files:</b>\n"
                user_files = [f for f, v in uploaded_files.items() if v["user_id"] == user_id]
                if not user_files:
                    send_message(chat_id, "You haven't uploaded any files.")
                else:
                    for message_id, info in uploaded_files.items():
                        if info["user_id"] == user_id:
                            url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{message_id}"
                            tags = ", ".join(file_tags.get(message_id, []))
                            file_list += f"[{info['file_type']}] <a href='{url}'>Link</a> (Tags: {tags or 'None'})\n"
                    send_message(chat_id, file_list)
        elif text.startswith("/pin_"):
            try:
                message_id = int(text.split("_")[1])
                if message_id in uploaded_files and uploaded_files[message_id]["user_id"] == user_id:
                    if pin_message(CHANNEL_USERNAME, message_id):
                        send_message(chat_id, "File pinned successfully!")
                    else:
                        send_message(chat_id, "Failed to pin the file.")
                else:
                    send_message(chat_id, "You can only pin your own files!")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /pin_<message_id>")
        elif text.startswith("/tag_"):
            try:
                parts = text.split("_", 2)
                message_id = int(parts[1])
                tag = parts[2]
                if message_id in uploaded_files and uploaded_files[message_id]["user_id"] == user_id:
                    file_tags[message_id] = file_tags.get(message_id, []) + [tag]
                    send_message(chat_id, f"Tag '{tag}' added to file!")
                else:
                    send_message(chat_id, "You can only tag your own files!")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /tag_<message_id>_<tag>")
        elif text.startswith("/search_"):
            query = text.split("_", 1)[1]
            matches = []
            for message_id, tags in file_tags.items():
                if query in tags and uploaded_files[message_id]["user_id"] == user_id:
                    url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{message_id}"
                    matches.append(f"[{uploaded_files[message_id]['file_type']}] <a href='{url}'>Link</a>")
            if matches:
                send_message(chat_id, "<b>Found files:</b>\n" + "\n".join(matches))
            else:
                send_message(chat_id, "No files found with that tag.")
        elif text == "/poll":
            poll_result = send_poll(
                CHANNEL_USERNAME,
                "How do you rate this bot?",
                ["Excellent", "Good", "Average", "Poor"]
            )
            if poll_result and poll_result.get("ok"):
                send_message(chat_id, "Poll created in the channel!")
            else:
                send_message(chat_id, "Failed to create poll.")
        elif text.startswith("/share_"):
            try:
                message_id = int(text.split("_")[1])
                if message_id in uploaded_files and uploaded_files[message_id]["user_id"] == user_id:
                    if forward_message(chat_id, CHANNEL_USERNAME, message_id):
                        send_message(chat_id, "File shared to this chat!")
                    else:
                        send_message(chat_id, "Failed to share file.")
                else:
                    send_message(chat_id, "You can only share your own files!")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /share_<message_id>")
        elif text.startswith("/download_"):
            try:
                message_id = int(text.split("_")[1])
                if message_id in uploaded_files and uploaded_files[message_id]["user_id"] == user_id:
                    download_link = get_file_download_link(uploaded_files[message_id]["file_id"])
                    if download_link:
                        send_message(chat_id, f"Direct download link: <a href='{download_link}'>Download</a>")
                    else:
                        send_message(chat_id, "Failed to generate download link.")
                else:
                    send_message(chat_id, "You can only download your own files!")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /download_<message_id>")
        elif text.startswith("/settings_"):
            try:
                setting, value = text.split("_")[1:]
                if setting == "notify":
                    user_settings[user_id]["notify"] = value.lower() == "on"
                    send_message(chat_id, f"Notifications turned {'on' if value.lower() == 'on' else 'off'}")
                elif setting == "lang" and value in ["en", "es", "fr"]:
                    user_settings[user_id]["lang"] = value
                    send_message(chat_id, f"Language set to {value}")
                else:
                    raise ValueError
            except (IndexError, ValueError):
                settings_text = f"""
<b>Settings commands:</b>
- /settings_notify_on/off - Toggle notifications
- /settings_lang_en/es/fr - Set language
<b>Current settings:</b>
- Notifications: {user_settings[user_id]['notify']}
- Language: {user_settings[user_id]['lang']}
"""
                send_message(chat_id, settings_text)
        elif text.startswith("/ban_") and message["from"].get("is_admin", False):
            try:
                target_user_id = int(text.split("_")[1])
                if ban_user(CHANNEL_USERNAME, target_user_id):
                    send_message(chat_id, f"User {target_user_id} banned from channel!")
                else:
                    send_message(chat_id, "Failed to ban user.")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /ban_<user_id> (Admin only)")
        elif text == "/cleanup" and message["from"].get("is_admin", False):
            cleanup_expired_files()
            send_message(chat_id, "Expired files cleaned up!")
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
    if any(key in message for key in ["document", "photo", "video", "audio"]):
        send_typing_action(chat_id)
        
        if not check_rate_limit(user_id):
            send_message(chat_id, "Upload limit reached (5/hour). Please wait!")
            return jsonify({"status": "rate_limited"}), 429

        file_id = None
        file_type = None
        file_size = 0
        
        if "document" in message:
            file_id = message["document"]["file_id"]
            file_type = "document"
            file_size = message["document"].get("file_size", 0)
        elif "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            file_type = "photo"
            file_size = message["photo"][-1].get("file_size", 0)
        elif "video" in message:
            file_id = message["video"]["file_id"]
            file_type = "video"
            file_size = message["video"].get("file_size", 0)
        elif "audio" in message:
            file_id = message["audio"]["file_id"]
            file_type = "audio"
            file_size = message["audio"].get("file_size", 0)

        if file_id:
            file_hash = generate_file_hash(file_id)
            if any(f["file_hash"] == file_hash for f in uploaded_files.values() if "file_hash" in f):
                send_message(chat_id, "This file has already been uploaded!")
                return jsonify({"status": "duplicate"}), 200
                
            result = send_file_to_channel(file_id, file_type)
            if result and result.get("ok"):
                channel_message_id = result["result"]["message_id"]
                channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"
                
                uploaded_files[channel_message_id] = {
                    "file_id": file_id,
                    "file_type": file_type,
                    "user_id": user_id,
                    "size": file_size,
                    "timestamp": datetime.now().isoformat(),
                    "file_hash": file_hash
                }

                reply_markup = {
                    "inline_keyboard": [
                        [{"text": "Delete File", "callback_data": f"delete_{channel_message_id}"}],
                        [{"text": "Pin File", "callback_data": f"pin_{channel_message_id}"}],
                        [{"text": "Share File", "callback_data": f"share_{channel_message_id}"}]
                    ]
                }
                
                size_mb = file_size / (1024 * 1024)
                response_text = f"""
<b>File uploaded successfully!</b>
URL: <a href='{channel_url}'>Link</a>
Type: {file_type}
Size: {size_mb:.2f} MB
Use /tag_{channel_message_id}_<tag> to add tags
Use /share_{channel_message_id} to share
Use /download_{channel_message_id} for direct link
"""
                if user_settings[user_id]["notify"]:
                    send_message(chat_id, response_text, reply_markup)
            else:
                send_message(chat_id, "Failed to upload the file.")
        else:
            send_message(chat_id, "Please send a valid file.")

    return jsonify({"status": "processed"}), 200

# Index route
@app.route('/', methods=['GET'])
def index():
    return "<h1>Telegram Bot Webhook is Running</h1>"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
