import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import time
import threading

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

# Dictionary to track files uploaded by the bot
uploaded_files = {}
user_activity = {}  # Track user activity for rate limiting

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

# Helper function to get user info
def get_user_info(user_id):
    url = f"{BASE_API_URL}/getChat"
    payload = {"chat_id": user_id}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json().get("result", {})
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
                            "✅ <b>File successfully deleted from the channel!</b>",
                            reply_markup=None
                        )
                    else:
                        edit_message_text(
                            chat_id,
                            message_id,
                            "❌ <b>Failed to delete the file.</b>\n\nPlease try again later or contact admin.",
                            reply_markup=callback["message"].get("reply_markup")
                        )
                else:
                    edit_message_text(
                        chat_id,
                        message_id,
                        "⛔ <b>Permission Denied</b>\n\nYou don't have permission to delete this file.",
                        reply_markup=callback["message"].get("reply_markup")
                    )
            else:
                edit_message_text(
                    chat_id,
                    message_id,
                    "⚠️ <b>File not found</b>\n\nThis file may have already been deleted.",
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
        return jsonify({"status": "processed"}), 200

    # Handle messages
    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Command handlers
    if "text" in message:
        text = message["text"]
        if text.startswith("/"):
            send_typing_action(chat_id)
            
            if text == "/start":
                show_main_menu(chat_id, user_id=user_id)
            elif text == "/help":
                show_help(chat_id)
            elif text == "/restart":
                if user_id in ADMIN_IDS:
                    uploaded_files.clear()
                    send_message(chat_id, "🔄 <b>Bot has been restarted.</b>\n\nAll cached data has been cleared.")
                else:
                    send_message(chat_id, "⛔ <b>Permission Denied</b>\n\nOnly admins can use this command.")
            elif text == "/upload":
                show_upload_instructions(chat_id)
            elif text == "/stats" and user_id in ADMIN_IDS:
                show_stats(chat_id)
            elif text == "/list" and user_id in ADMIN_IDS:
                list_files(chat_id, user_id)
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
                "file_size": round(file_size, 2)
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
• Simple and intuitive interface

Use the buttons below to get started or type /help for more information.
"""
    buttons = [
        {"text": "📤 Upload File", "callback_data": "upload_instructions"},
        {"text": "ℹ️ Help", "callback_data": "help"},
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
    help_text = """
📚 <b>File Uploader Bot Help</b>

<b>Available commands:</b>
/start - Start the bot and get instructions
/help - Show this help message
/upload - Learn how to upload files

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

# Background task to clean up old rate limit data
def clean_activity_data():
    while True:
        now = time.time()
        for user_id in list(user_activity.keys()):
            user_activity[user_id] = [t for t in user_activity[user_id] if now - t < 120]  # Keep 2 minutes of data
            if not user_activity[user_id]:
                del user_activity[user_id]
        time.sleep(3600)  # Run every hour

# Start background cleaner thread
cleaner_thread = threading.Thread(target=clean_activity_data, daemon=True)
cleaner_thread.start()

# Stylish index route
@app.route('/', methods=['GET'])
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram File Uploader Bot</title>
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
            }
            
            .feature-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
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
            }
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
                    <p>Your files are securely stored and can be deleted anytime you want.</p>
                </div>
            </div>
            
            <div class="btn-group">
                <a href="https://t.me/IP_AdressBot" class="btn">Start the Bot</a>
                <a href="/setwebhook" class="btn btn-outline">Set Webhook</a>
            </div>
            
            <footer>
                <p>© 2025 Telegram File Uploader Bot. All rights reserved.</p>
            </footer>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
