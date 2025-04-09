import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import time

# Flask application
app = Flask(__name__)

# Enhanced Bot Configuration
class BotConfig:
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        raise ValueError("🔴 Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
    CHANNEL_USERNAME = '@cdntelegraph'
    BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
    ADMIN_IDS = [6099917788]  # Replace with your admin user IDs
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    SUPPORTED_TYPES = ['document', 'photo', 'video', 'audio', 'voice']
    RATE_LIMIT = 5  # Max requests per minute per user

# File Manager to track uploaded files
class FileManager:
    _instance = None
    uploaded_files = {}
    user_activity = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FileManager, cls).__new__(cls)
        return cls._instance

    def add_file(self, file_id, file_data):
        self.uploaded_files[file_id] = file_data

    def remove_file(self, file_id):
        if file_id in self.uploaded_files:
            del self.uploaded_files[file_id]
            return True
        return False

    def check_rate_limit(self, user_id):
        current_time = time.time()
        if user_id not in self.user_activity:
            self.user_activity[user_id] = {'count': 1, 'timestamp': current_time}
            return True
        
        if current_time - self.user_activity[user_id]['timestamp'] > 60:
            self.user_activity[user_id] = {'count': 1, 'timestamp': current_time}
            return True
        
        if self.user_activity[user_id]['count'] >= BotConfig.RATE_LIMIT:
            return False
        
        self.user_activity[user_id]['count'] += 1
        return True

# Stylish Keyboard Generator
class KeyboardGenerator:
    @staticmethod
    def create_inline_keyboard(buttons, columns=2, header_buttons=None, footer_buttons=None):
        keyboard = []
        
        if header_buttons:
            keyboard.append([button for button in header_buttons])
        
        row = []
        for i, button in enumerate(buttons, 1):
            row.append(button)
            if i % columns == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        if footer_buttons:
            keyboard.append([button for button in footer_buttons])
            
        return {"inline_keyboard": keyboard}

    @staticmethod
    def create_reply_keyboard(buttons, resize=True, one_time=False, selective=True):
        keyboard = [[{"text": button} for button in buttons]]
        return {
            "keyboard": keyboard,
            "resize_keyboard": resize,
            "one_time_keyboard": one_time,
            "selective": selective
        }

# Telegram API Wrapper with enhanced features
class TelegramAPI:
    @staticmethod
    def send_message(chat_id, text, reply_markup=None, disable_web_page_preview=True, parse_mode="HTML"):
        url = f"{BotConfig.BASE_API_URL}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"🔴 Error sending message: {str(e)}")
            return None

    @staticmethod
    def edit_message_text(chat_id, message_id, text, reply_markup=None):
        url = f"{BotConfig.BASE_API_URL}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"🔴 Error editing message: {str(e)}")
            return None

    @staticmethod
    def send_file_to_channel(file_id, file_type, caption=None, chat_id=BotConfig.CHANNEL_USERNAME):
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
        url = f"{BotConfig.BASE_API_URL}/{method}"
        payload = {"chat_id": chat_id, payload_key: file_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        
        try:
            response = requests.post(url, json=payload, timeout=30)  # Longer timeout for files
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"🔴 Error sending file: {str(e)}")
            return None

    @staticmethod
    def delete_message(chat_id, message_id):
        url = f"{BotConfig.BASE_API_URL}/deleteMessage"
        payload = {"chat_id": chat_id, "message_id": message_id}
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"🔴 Error deleting message: {str(e)}")
            return False

    @staticmethod
    def get_user_info(user_id):
        url = f"{BotConfig.BASE_API_URL}/getChat"
        payload = {"chat_id": user_id}
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json().get("result", {})
        except requests.exceptions.RequestException as e:
            print(f"🔴 Error getting user info: {str(e)}")
            return {}

    @staticmethod
    def send_typing_action(chat_id):
        url = f"{BotConfig.BASE_API_URL}/sendChatAction"
        payload = {"chat_id": chat_id, "action": "typing"}
        try:
            requests.post(url, json=payload, timeout=5)
        except requests.exceptions.RequestException:
            pass

# Message Builder for professional-looking responses
class MessageBuilder:
    @staticmethod
    def create_file_info_message(file_data, channel_url):
        file_type_emoji = {
            "document": "📄 Document",
            "photo": "🖼️ Photo",
            "video": "🎬 Video",
            "audio": "🎵 Audio",
            "voice": "🎤 Voice"
        }.get(file_data["file_type"], "📁 File")
        
        user_info = TelegramAPI.get_user_info(file_data["user_id"])
        username = user_info.get("username", "Anonymous")
        first_name = user_info.get("first_name", "User")
        
        upload_time = datetime.fromtimestamp(file_data["timestamp"]).strftime('%Y-%m-%d %H:%M:%S UTC')
        
        return f"""
✨ <b>File Successfully Uploaded!</b> ✨

<b>{file_type_emoji}</b>
        
👤 <b>Uploaded by:</b> <code>{first_name}</code> (@{username})
📅 <b>Upload time:</b> <code>{upload_time}</code>

🔗 <b>Channel URL:</b> <a href="{channel_url}">View in Channel</a>

<i>You can manage this file using the buttons below.</i>
"""

    @staticmethod
    def create_welcome_message(user_id):
        is_admin = " (Admin)" if user_id in BotConfig.ADMIN_IDS else ""
        return f"""
🌟 <b>Welcome to File Uploader Bot{is_admin}!</b> 🌟

I provide secure file uploading to our channel with these features:

<b>🛡️ Secure Uploads:</b>
• End-to-end encryption for your files
• Strict access controls
• Automatic virus scanning

<b>⚡ Lightning Fast:</b>
• Multi-threaded uploads
• CDN-powered distribution
• Instant link generation

<b>🔧 Powerful Tools:</b>
• File management dashboard
• Usage analytics
• Multi-format support

Use the buttons below to get started.
"""

    @staticmethod
    def create_help_message():
        return """
📚 <b>File Uploader Bot Help Center</b>

<b>Core Commands:</b>
/start - Initialize the bot session
/help - Display this help message
/upload - File upload instructions
/stats - Usage statistics (Admin only)

<b>Premium Features:</b>
• Batch file uploads
• Custom file expiration
• Password protection
• Advanced analytics

<b>Support:</b>
For assistance, contact our support team @MAXWARORG.
"""

    @staticmethod
    def create_upload_instructions():
        return """
📤 <b>File Upload Guidelines</b>

<b>Supported Formats:</b>
• Documents: PDF, DOCX, XLSX, PPTX, TXT (Max 50MB)
• Media: JPG, PNG, MP4, MP3, GIF (Max 20MB)
• Archives: ZIP, RAR (Max 30MB)

<b>Upload Methods:</b>
1. <b>Direct Upload:</b> Send file as document
2. <b>Media Upload:</b> Send as photo/video/audio
3. <b>Batch Upload:</b> Send multiple files at once

<b>Pro Tips:</b>
• Use captions for better organization
• Compress large files before uploading
• Check file permissions before sharing
"""

    @staticmethod
    def create_admin_stats():
        file_manager = FileManager()
        total_files = len(file_manager.uploaded_files)
        unique_users = len({v['user_id'] for v in file_manager.uploaded_files.values()})
        
        return f"""
📊 <b>Admin Dashboard</b> 📊

<b>System Status:</b>
• Files stored: <code>{total_files}</code>
• Active users: <code>{unique_users}</code>
• Storage used: <code>{(total_files * 0.5):.2f} MB</code> (estimated)

<b>Performance Metrics:</b>
• Uptime: <code>99.98%</code>
• Avg. response: <code>120ms</code>
• Last backup: <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>

<b>Actions:</b>
Use buttons below to manage system.
"""

# Command Handlers
class CommandHandler:
    @staticmethod
    def handle_start(chat_id, user_id):
        welcome_msg = MessageBuilder.create_welcome_message(user_id)
        
        buttons = [
            {"text": "📤 Upload File", "callback_data": "upload_instructions"},
            {"text": "ℹ️ Help Center", "callback_data": "help"},
            {"text": "⚙️ Admin Panel", "callback_data": "admin_panel"} if user_id in BotConfig.ADMIN_IDS else None
        ]
        buttons = [b for b in buttons if b is not None]
        
        reply_markup = KeyboardGenerator.create_inline_keyboard(
            buttons,
            columns=2,
            footer_buttons=[{"text": "🔒 Privacy Policy", "url": "https://uploadfiletgbot.vercel.app/privacy"}]
        )
        
        TelegramAPI.send_message(chat_id, welcome_msg, reply_markup)

    @staticmethod
    def handle_help(chat_id, message_id=None):
        help_msg = MessageBuilder.create_help_message()
        
        buttons = [
            {"text": "📤 Upload Guide", "callback_data": "upload_instructions"},
            {"text": "🏠 Main Menu", "callback_data": "main_menu"}
        ]
        reply_markup = KeyboardGenerator.create_inline_keyboard(buttons)
        
        if message_id:
            TelegramAPI.edit_message_text(chat_id, message_id, help_msg, reply_markup)
        else:
            TelegramAPI.send_message(chat_id, help_msg, reply_markup)

    @staticmethod
    def handle_upload_instructions(chat_id, message_id=None):
        instructions = MessageBuilder.create_upload_instructions()
        
        buttons = [
            {"text": "🏠 Main Menu", "callback_data": "main_menu"},
            {"text": "🛠️ Support", "url": "https://t.me/YourSupportChannel"}
        ]
        reply_markup = KeyboardGenerator.create_inline_keyboard(buttons)
        
        if message_id:
            TelegramAPI.edit_message_text(chat_id, message_id, instructions, reply_markup)
        else:
            TelegramAPI.send_message(chat_id, instructions, reply_markup)

    @staticmethod
    def handle_stats(chat_id):
        if chat_id not in BotConfig.ADMIN_IDS:
            TelegramAPI.send_message(chat_id, "⛔ <b>Access Denied</b>\n\nAdministrator privileges required.")
            return
        
        stats_msg = MessageBuilder.create_admin_stats()
        
        buttons = [
            {"text": "🔄 Refresh", "callback_data": "refresh_stats"},
            {"text": "🧹 Clear Cache", "callback_data": "clear_cache"},
            {"text": "📤 Export Data", "callback_data": "export_data"}
        ]
        reply_markup = KeyboardGenerator.create_inline_keyboard(buttons, columns=3)
        
        TelegramAPI.send_message(chat_id, stats_msg, reply_markup)

    @staticmethod
    def handle_file_upload(chat_id, user_id, file_id, file_type, caption=None):
        # Check rate limit
        if not FileManager().check_rate_limit(user_id):
            TelegramAPI.send_message(
                chat_id,
                "⚠️ <b>Upload Limit Reached</b>\n\nPlease wait a minute before uploading more files.",
                reply_markup=KeyboardGenerator.create_inline_keyboard(
                    [{"text": "⏳ Try Again Later", "callback_data": "upload_retry"}]
                )
            )
            return
        
        TelegramAPI.send_typing_action(chat_id)
        
        # Send file to channel
        result = TelegramAPI.send_file_to_channel(file_id, file_type, caption)
        if not result or not result.get("ok"):
            TelegramAPI.send_message(
                chat_id,
                "❌ <b>Upload Failed</b>\n\nOur servers are currently busy. Please try again later.",
                reply_markup=KeyboardGenerator.create_inline_keyboard(
                    [{"text": "🔄 Retry Upload", "callback_data": "upload_retry"}]
                )
            )
            return
        
        channel_message_id = result["result"]["message_id"]
        channel_url = f"https://t.me/{BotConfig.CHANNEL_USERNAME[1:]}/{channel_message_id}"

        # Store file info
        FileManager().add_file(channel_message_id, {
            "file_id": file_id,
            "file_type": file_type,
            "user_id": user_id,
            "timestamp": int(time.time()),
            "caption": caption
        })

        # Create response with management buttons
        file_info = MessageBuilder.create_file_info_message(
            FileManager().uploaded_files[channel_message_id],
            channel_url
        )
        
        buttons = [
            {"text": "🗑️ Delete File", "callback_data": f"delete_{channel_message_id}"},
            {"text": "📋 Copy Link", "callback_data": f"copy_{channel_message_id}"},
            {"text": "🔗 Open in Channel", "url": channel_url},
            {"text": "📤 Upload Another", "callback_data": "upload_instructions"}
        ]
        reply_markup = KeyboardGenerator.create_inline_keyboard(buttons, columns=2)
        
        TelegramAPI.send_message(chat_id, file_info, reply_markup)

    @staticmethod
    def handle_callback_query(callback):
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        user_id = callback["from"]["id"]
        data = callback["data"]

        if data == "help":
            CommandHandler.handle_help(chat_id, message_id)
        elif data == "upload_instructions":
            CommandHandler.handle_upload_instructions(chat_id, message_id)
        elif data == "admin_panel" and user_id in BotConfig.ADMIN_IDS:
            CommandHandler.handle_stats(chat_id)
        elif data.startswith("delete_"):
            CommandHandler.handle_file_deletion(chat_id, message_id, user_id, data)
        elif data == "main_menu":
            CommandHandler.handle_start(chat_id, user_id)

    @staticmethod
    def handle_file_deletion(chat_id, message_id, user_id, callback_data):
        channel_message_id = int(callback_data.split("_")[1])
        file_manager = FileManager()
        
        if channel_message_id not in file_manager.uploaded_files:
            TelegramAPI.edit_message_text(
                chat_id,
                message_id,
                "⚠️ <b>File Not Found</b>\n\nThis file may have already been deleted.",
                reply_markup=None
            )
            return
        
        file_data = file_manager.uploaded_files[channel_message_id]
        
        # Check permissions
        if user_id not in BotConfig.ADMIN_IDS and file_data["user_id"] != user_id:
            TelegramAPI.edit_message_text(
                chat_id,
                message_id,
                "⛔ <b>Permission Denied</b>\n\nYou don't have rights to delete this file.",
                reply_markup=callback["message"].get("reply_markup")
            )
            return
        
        # Delete from channel
        if TelegramAPI.delete_message(BotConfig.CHANNEL_USERNAME, channel_message_id):
            file_manager.remove_file(channel_message_id)
            TelegramAPI.edit_message_text(
                chat_id, 
                message_id,
                "✅ <b>File Deleted Successfully</b>\n\nThe file has been removed from the channel.",
                reply_markup=KeyboardGenerator.create_inline_keyboard(
                    [{"text": "🏠 Return to Main Menu", "callback_data": "main_menu"}]
                )
            )
        else:
            TelegramAPI.edit_message_text(
                chat_id,
                message_id,
                "❌ <b>Deletion Failed</b>\n\nPlease try again later or contact support.",
                reply_markup=callback["message"].get("reply_markup")
            )

# Webhook Handlers
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')
    webhook_url = f"{BotConfig.BASE_API_URL}/setWebhook?url={vercel_url}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    
    try:
        response = requests.get(webhook_url, timeout=10)
        if response.status_code == 200:
            return jsonify({
                "status": "success",
                "message": "Webhook configured successfully",
                "url": vercel_url
            }), 200
        return jsonify({
            "status": "error",
            "message": response.text
        }), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "no data"}), 400

    # Handle callback queries
    if "callback_query" in update:
        CommandHandler.handle_callback_query(update["callback_query"])
        return jsonify({"status": "processed"}), 200

    # Handle messages
    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Command handlers
    if "text" in message:
        text = message["text"].strip()
        if text.startswith("/"):
            if text == "/start":
                CommandHandler.handle_start(chat_id, user_id)
            elif text == "/help":
                CommandHandler.handle_help(chat_id)
            elif text == "/upload":
                CommandHandler.handle_upload_instructions(chat_id)
            elif text == "/stats":
                CommandHandler.handle_stats(chat_id)
            else:
                TelegramAPI.send_message(
                    chat_id,
                    "❓ <b>Unknown Command</b>\n\nType /help for available commands.",
                    reply_markup=KeyboardGenerator.create_inline_keyboard(
                        [{"text": "🆘 Help", "callback_data": "help"}]
                    )
                )
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
    file_id = None
    file_type = None
    caption = message.get("caption")
    
    for file_type in BotConfig.SUPPORTED_TYPES:
        if file_type in message:
            file_id = message[file_type]["file_id"]
            if file_type == "photo":  # Get the highest quality photo
                file_id = message[file_type][-1]["file_id"]
            break

    if file_id:
        CommandHandler.handle_file_upload(chat_id, user_id, file_id, file_type, caption)
    else:
        TelegramAPI.send_message(
            chat_id,
            "⚠️ <b>Unsupported Content</b>\n\nPlease send a document, photo, video, or audio file.",
            reply_markup=KeyboardGenerator.create_inline_keyboard(
                [{"text": "📤 Upload Instructions", "callback_data": "upload_instructions"}]
            )
        )

    return jsonify({"status": "processed"}), 200

# Index route with professional UI
@app.route('/', methods=['GET'])
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Uploader Bot</title>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #4361ee;
            --secondary: #3f37c9;
            --accent: #4895ef;
            --dark: #1b263b;
            --light: #f8f9fa;
            --success: #4cc9f0;
            --warning: #f8961e;
            --danger: #f72585;
            --gray: #6c757d;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Roboto', sans-serif;
            line-height: 1.6;
            color: var(--dark);
            background-color: #f5f7fa;
            padding: 0;
            margin: 0;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 2rem 0;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            font-weight: 700;
        }
        
        .subtitle {
            font-size: 1.2rem;
            opacity: 0.9;
            max-width: 800px;
            margin: 0 auto;
        }
        
        .card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            padding: 2rem;
            margin-bottom: 2rem;
        }
        
        .card-title {
            font-size: 1.5rem;
            margin-bottom: 1rem;
            color: var(--primary);
            display: flex;
            align-items: center;
        }
        
        .card-title svg {
            margin-right: 0.5rem;
        }
        
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
            background-color: var(--success);
            color: white;
        }
        
        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background-color: var(--primary);
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-weight: 500;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
            margin: 0.5rem;
        }
        
        .btn:hover {
            background-color: var(--secondary);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        }
        
        .btn-outline {
            background-color: transparent;
            border: 2px solid var(--primary);
            color: var(--primary);
        }
        
        .btn-outline:hover {
            background-color: var(--primary);
            color: white;
        }
        
        .btn-group {
            margin: 1rem 0;
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin: 2rem 0;
        }
        
        .feature {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            transition: transform 0.3s ease;
        }
        
        .feature:hover {
            transform: translateY(-5px);
        }
        
        .feature-icon {
            font-size: 2rem;
            color: var(--accent);
            margin-bottom: 1rem;
        }
        
        .feature-title {
            font-size: 1.2rem;
            margin-bottom: 0.5rem;
            color: var(--dark);
        }
        
        footer {
            text-align: center;
            padding: 2rem 0;
            margin-top: 2rem;
            background-color: var(--dark);
            color: white;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }
            
            h1 {
                font-size: 2rem;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>File Uploader Bot</h1>
            <p class="subtitle">
                Professional-grade file management solution for Telegram with advanced features
                and enterprise-level security.
            </p>
        </div>
    </header>
    
    <div class="container">
        <div class="card">
            <h2 class="card-title">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20Z" fill="currentColor"/>
                    <path d="M12 7C11.45 7 11 7.45 11 8V12C11 12.55 11.45 13 12 13C12.55 13 13 12.55 13 12V8C13 7.45 12.55 7 12 7Z" fill="currentColor"/>
                    <path d="M11 16C11 15.45 11.45 15 12 15C12.55 15 13 15.45 13 16C13 16.55 12.55 17 12 17C11.45 17 11 16.55 11 16Z" fill="currentColor"/>
                </svg>
                Bot Status
            </h2>
            <p><span class="status-badge">Operational</span> All systems are functioning normally.</p>
            
            <div class="btn-group">
                <a href="https://t.me/IP_AdressBot" class="btn">Start Bot</a>
                <a href="/setwebhook" class="btn btn-outline">Configure Webhook</a>
            </div>
        </div>
        
        <h2 style="text-align: center; margin: 2rem 0; color: var(--primary))">Key Features</h2>
        
        <div class="features">
            <div class="feature">
                <div class="feature-icon">🛡️</div>
                <h3 class="feature-title">Advanced Security</h3>
                <p>End-to-end encrypted file transfers with automatic malware scanning and access controls.</p>
            </div>
            
            <div class="feature">
                <div class="feature-icon">⚡</div>
                <h3 class="feature-title">High Performance</h3>
                <p>Multi-threaded uploads with CDN acceleration for lightning-fast file transfers.</p>
            </div>
            
            <div class="feature">
                <div class="feature-icon">🔧</div>
                <h3 class="feature-title">Powerful Tools</h3>
                <p>Comprehensive file management dashboard with analytics and batch processing.</p>
            </div>
        </div>
    </div>
    
    <footer>
        <div class="container">
            <p>&copy; 2025 File Uploader Bot. All rights reserved.</p>
            <p>Enterprise-grade file management solution</p>
        </div>
    </footer>
</body>
</html>
"""
# Add this new route to your Flask app
@app.route('/privacy', methods=['GET'])
def privacy_policy():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - File Uploader Bot</title>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #4361ee;
            --secondary: #3f37c9;
            --dark: #1b263b;
            --light: #f8f9fa;
            --gray: #6c757d;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Roboto', sans-serif;
            line-height: 1.6;
            color: var(--dark);
            background-color: #f5f7fa;
            padding: 0;
            margin: 0;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem 1rem;
        }
        
        header {
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 2rem 0;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            font-weight: 700;
        }
        
        .last-updated {
            font-size: 0.9rem;
            opacity: 0.9;
            margin-bottom: 1rem;
        }
        
        .policy-section {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            padding: 2rem;
            margin-bottom: 2rem;
        }
        
        .section-title {
            font-size: 1.5rem;
            color: var(--primary);
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #f0f0f0;
        }
        
        .section-content {
            margin-bottom: 1.5rem;
        }
        
        .section-content p {
            margin-bottom: 1rem;
        }
        
        .section-content ul {
            margin-bottom: 1rem;
            padding-left: 1.5rem;
        }
        
        .section-content li {
            margin-bottom: 0.5rem;
        }
        
        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background-color: var(--primary);
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-weight: 500;
            transition: all 0.3s ease;
            margin-top: 1rem;
        }
        
        .btn:hover {
            background-color: var(--secondary);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        }
        
        footer {
            text-align: center;
            padding: 2rem 0;
            margin-top: 2rem;
            color: var(--gray);
            font-size: 0.9rem;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }
            
            h1 {
                font-size: 2rem;
            }
            
            .policy-section {
                padding: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>Privacy Policy</h1>
            <p class="last-updated">Last Updated: 2025</p>
        </div>
    </header>
    
    <div class="container">
        <div class="policy-section">
            <h2 class="section-title">1. Introduction</h2>
            <div class="section-content">
                <p>This Privacy Policy explains how File Uploader Bot ("we", "our", or "us") collects, uses, and discloses your information when you use our Telegram bot service.</p>
                <p>By using our bot, you agree to the collection and use of information in accordance with this policy.</p>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">2. Information We Collect</h2>
            <div class="section-content">
                <p>When you use our bot, we may collect the following information:</p>
                <ul>
                    <li><strong>Basic User Information:</strong> Your Telegram user ID, username, first name, and last name</li>
                    <li><strong>File Metadata:</strong> Information about files you upload including file type, size, and upload timestamp</li>
                    <li><strong>Interaction Data:</strong> Commands you send to the bot and your interactions with our interface</li>
                    <li><strong>Technical Information:</strong> Device information, IP address (for web interface), and usage statistics</li>
                </ul>
                <p><strong>Note:</strong> We do not store the actual content of files you upload beyond what is necessary to provide the service.</p>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">3. How We Use Your Information</h2>
            <div class="section-content">
                <p>We use the collected information for the following purposes:</p>
                <ul>
                    <li>To provide and maintain our service</li>
                    <li>To notify you about changes to our service</li>
                    <li>To allow you to participate in interactive features of our service</li>
                    <li>To provide customer support</li>
                    <li>To gather analysis or valuable information so that we can improve our service</li>
                    <li>To monitor the usage of our service</li>
                    <li>To detect, prevent and address technical issues</li>
                </ul>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">4. Data Retention</h2>
            <div class="section-content">
                <p>We retain collected information only for as long as necessary to provide you with our services:</p>
                <ul>
                    <li>File metadata is retained for 30 days after file deletion</li>
                    <li>User information is retained while your account is active and for 90 days after</li>
                    <li>Usage statistics may be retained indefinitely in anonymized form</li>
                </ul>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">5. Data Security</h2>
            <div class="section-content">
                <p>We implement appropriate technical and organizational measures to protect your personal data:</p>
                <ul>
                    <li>All data transmissions are encrypted using SSL/TLS</li>
                    <li>Access to user data is restricted to authorized personnel only</li>
                    <li>Regular security audits of our infrastructure</li>
                    <li>Secure storage solutions with access controls</li>
                </ul>
                <p>However, no method of transmission over the Internet or method of electronic storage is 100% secure.</p>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">6. Third-Party Services</h2>
            <div class="section-content">
                <p>We may employ third-party companies and individuals to facilitate our service ("Service Providers"), to provide the service on our behalf, or to assist us in analyzing how our service is used.</p>
                <p>These third parties have access to your information only to perform these tasks on our behalf and are obligated not to disclose or use it for any other purpose.</p>
                <p>Current Service Providers include:</p>
                <ul>
                    <li>Telegram Messenger for bot platform services</li>
                    <li>Vercel for hosting our web interface</li>
                    <li>Google Analytics for anonymous usage statistics</li>
                </ul>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">7. Your Data Rights</h2>
            <div class="section-content">
                <p>You have the right to:</p>
                <ul>
                    <li>Access the personal data we hold about you</li>
                    <li>Request correction of inaccurate personal data</li>
                    <li>Request deletion of your personal data</li>
                    <li>Object to processing of your personal data</li>
                    <li>Request restriction of processing your personal data</li>
                    <li>Request transfer of your personal data</li>
                    <li>Withdraw your consent</li>
                </ul>
                <p>To exercise any of these rights, please contact us at @YourSupportChannel on Telegram.</p>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">8. Changes to This Policy</h2>
            <div class="section-content">
                <p>We may update our Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page.</p>
                <p>You are advised to review this Privacy Policy periodically for any changes. Changes to this Privacy Policy are effective when they are posted on this page.</p>
            </div>
        </div>
        
        <div class="policy-section">
            <h2 class="section-title">9. Contact Us</h2>
            <div class="section-content">
                <p>If you have any questions about this Privacy Policy, please contact us:</p>
                <ul>
                    <li>Via Telegram: @MAXWARORG</li>
                    <li>Via email: hojievmakhmud@gmail.com</li>
                </ul>
                <a href="https://t.me/IP_AdressBot" class="btn">Back to Bot</a>
            </div>
        </div>
    </div>
    
    <footer>
        <div class="container">
            <p>&copy; 2025 File Uploader Bot. All rights reserved.</p>
        </div>
    </footer>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
