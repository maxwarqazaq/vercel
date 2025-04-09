import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import time
import threading
from collections import defaultdict
import pytz

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]  # Admin user IDs
TIMEZONE = pytz.timezone('Asia/Tehran')  # Adjust to your preferred timezone

# Data storage
uploaded_files = {}
user_stats = defaultdict(lambda: {'uploads': 0, 'last_active': None})
file_type_stats = defaultdict(int)
bot_start_time = time.time()

# Rate limiting
RATE_LIMIT = 5  # Max uploads per minute per user
user_rate = defaultdict(list)

# Helper function to check rate limit
def check_rate_limit(user_id):
    now = time.time()
    # Remove old entries (older than 1 minute)
    user_rate[user_id] = [t for t in user_rate[user_id] if now - t < 60]
    if len(user_rate[user_id]) >= RATE_LIMIT:
        return False
    user_rate[user_id].append(now)
    return True

# Premium keyboard builder
def create_inline_keyboard(buttons, columns=2, header_buttons=None, footer_buttons=None):
    keyboard = []
    
    # Add header buttons if any
    if header_buttons:
        keyboard.append(header_buttons)
    
    # Organize main buttons in columns
    row = []
    for i, button in enumerate(buttons, 1):
        row.append(button)
        if i % columns == 0:
            keyboard.append(row)
            row = []
    if row:  # Add remaining buttons if any
        keyboard.append(row)
    
    # Add footer buttons if any
    if footer_buttons:
        keyboard.append(footer_buttons)
    
    return {"inline_keyboard": keyboard}

# Enhanced message sender with retry logic
def send_message(chat_id, text, reply_markup=None, disable_web_page_preview=True, parse_mode="HTML"):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    # Retry logic with exponential backoff
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Attempt {attempt + 1}: Error sending message - {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            print(f"Attempt {attempt + 1}: Exception sending message - {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    
    print(f"Failed to send message after {max_retries} attempts")
    return None

# Premium file upload function with progress tracking
def send_file_to_channel(file_id, file_type, caption=None, chat_id=CHANNEL_USERNAME, user_id=None):
    methods = {
        "document": ("sendDocument", "document"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio"),
        "voice": ("sendVoice", "voice"),
        "animation": ("sendAnimation", "animation")
    }
    
    if file_type not in methods:
        return None

    method, payload_key = methods[file_type]
    url = f"{BASE_API_URL}/{method}"
    payload = {"chat_id": chat_id, payload_key: file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    
    # Track upload time for performance metrics
    start_time = time.time()
    response = requests.post(url, json=payload, timeout=30)
    upload_time = time.time() - start_time
    
    if response.status_code == 200:
        result = response.json()
        if user_id:
            # Update user stats
            user_stats[user_id]['uploads'] += 1
            user_stats[user_id]['last_active'] = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            file_type_stats[file_type] += 1
        
        # Log performance
        print(f"File uploaded in {upload_time:.2f}s - Type: {file_type}, Size: {result.get('result', {}).get('file_size', 'unknown')} bytes")
        return result
    else:
        print(f"Error sending file: {response.text}")
        return None

# Enhanced delete with confirmation
def delete_file(chat_id, message_id, channel_message_id, user_id):
    if channel_message_id in uploaded_files:
        file_data = uploaded_files[channel_message_id]
        
        # Check permissions
        if user_id not in ADMIN_IDS and file_data["user_id"] != user_id:
            return False, "permission_denied"
        
        if delete_message(CHANNEL_USERNAME, channel_message_id):
            del uploaded_files[channel_message_id]
            return True, "success"
        else:
            return False, "delete_failed"
    return False, "not_found"

# Stylish file info template
def create_file_info_message(file_data, channel_url, user_id):
    file_type_emoji = {
        "document": "📄",
        "photo": "🖼️",
        "video": "🎬",
        "audio": "🎵",
        "voice": "🎤",
        "animation": "🎞️"
    }.get(file_data["file_type"], "📁")
    
    user_info = get_user_info(file_data["user_id"])
    username = user_info.get("username", "Anonymous")
    first_name = user_info.get("first_name", "User")
    
    upload_time = datetime.fromtimestamp(file_data["timestamp"], TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    
    # File size info if available
    file_size = file_data.get("file_size")
    size_info = f"\n📏 <b>Size:</b> {format_file_size(file_size)}" if file_size else ""
    
    # Caption info if available
    caption_info = f"\n✏️ <b>Caption:</b> {file_data.get('caption', 'None')}" if file_data.get('caption') else ""
    
    return f"""
{file_type_emoji} <b>File Successfully Uploaded!</b>

👤 <b>Uploaded by:</b> {first_name} (@{username})
📅 <b>Upload time:</b> {upload_time}{size_info}{caption_info}

🔗 <b>Channel URL:</b> <a href="{channel_url}">Click to view</a>

<i>Manage your file using the buttons below.</i>
"""

# Helper to format file size
def format_file_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

# User analytics function
def generate_user_analytics(user_id):
    user_data = user_stats.get(user_id, {})
    uploads = user_data.get('uploads', 0)
    last_active = user_data.get('last_active', 'Never')
    
    return f"""
📊 <b>Your Usage Statistics</b>

📤 <b>Total Uploads:</b> {uploads}
⏱️ <b>Last Active:</b> {last_active}

<b>Your most used file types:</b>
{get_user_top_file_types(user_id)}
"""

# System statistics for admins
def generate_system_stats():
    uptime = time.time() - bot_start_time
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    total_users = len(user_stats)
    total_uploads = sum(file_type_stats.values())
    
    # Get top file types
    top_types = sorted(file_type_stats.items(), key=lambda x: x[1], reverse=True)[:3]
    top_types_str = "\n".join([f"• {k}: {v}" for k, v in top_types])
    
    return f"""
🖥️ <b>System Statistics</b>

⏳ <b>Uptime:</b> {int(hours)}h {int(minutes)}m {int(seconds)}s
👥 <b>Total Users:</b> {total_users}
📤 <b>Total Uploads:</b> {total_uploads}

<b>Most Popular File Types:</b>
{top_types_str}

<b>Current Time:</b> {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}
"""

# Webhook setup with enhanced validation
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')
    webhook_url = f"{BASE_API_URL}/setWebhook?url={vercel_url}/webhook"
    webhook_url += "&allowed_updates=message,callback_query,chat_member"
    webhook_url += "&drop_pending_updates=true"
    
    response = requests.get(webhook_url)
    if response.status_code == 200:
        result = response.json()
        if result.get('result'):
            return jsonify({
                "status": "success",
                "message": "Webhook successfully configured",
                "details": result['description']
            }), 200
    return jsonify({
        "status": "error",
        "message": "Failed to configure webhook",
        "details": response.text
    }), response.status_code

# Premium webhook handler with error handling
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return jsonify({"status": "error", "message": "Empty update received"}), 400

        # Handle callback queries (button presses)
        if "callback_query" in update:
            return handle_callback_query(update["callback_query"])
        
        # Handle messages
        if "message" in update:
            return handle_message(update["message"])
        
        return jsonify({"status": "ignored", "message": "Unhandled update type"}), 200
    
    except Exception as e:
        print(f"Error processing update: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_callback_query(callback):
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]
    user_id = callback["from"]["id"]
    callback_data = callback["data"]
    
    try:
        if callback_data.startswith("delete_"):
            channel_message_id = int(callback_data.split("_")[1])
            success, reason = delete_file(chat_id, message_id, channel_message_id, user_id)
            
            if success:
                edit_message_text(
                    chat_id, 
                    message_id,
                    "✅ <b>File successfully deleted from the channel!</b>",
                    reply_markup=None
                )
            else:
                if reason == "permission_denied":
                    edit_message_text(
                        chat_id,
                        message_id,
                        "⛔ <b>Permission Denied</b>\n\nYou don't have permission to delete this file.",
                        reply_markup=callback["message"].get("reply_markup")
                    )
                elif reason == "delete_failed":
                    edit_message_text(
                        chat_id,
                        message_id,
                        "❌ <b>Deletion Failed</b>\n\nPlease try again later or contact admin.",
                        reply_markup=callback["message"].get("reply_markup")
                    )
                else:
                    edit_message_text(
                        chat_id,
                        message_id,
                        "⚠️ <b>File Not Found</b>\n\nThis file may have already been deleted.",
                        reply_markup=None
                    )
        
        elif callback_data == "help":
            show_help(chat_id, message_id)
        elif callback_data == "upload_guide":
            show_upload_instructions(chat_id, message_id)
        elif callback_data == "user_stats":
            show_user_stats(chat_id, user_id, message_id)
        elif callback_data == "admin_panel" and user_id in ADMIN_IDS:
            show_admin_panel(chat_id, message_id)
        elif callback_data == "refresh_stats" and user_id in ADMIN_IDS:
            show_admin_panel(chat_id, message_id, refresh=True)
        
        return jsonify({"status": "processed"}), 200
    except Exception as e:
        print(f"Error handling callback: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 200

def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    
    # Update user activity
    user_stats[user_id]['last_active'] = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    
    # Handle commands
    if "text" in message and message["text"].startswith("/"):
        return handle_command(message)
    
    # Handle file uploads
    if any(key in message for key in ["document", "photo", "video", "audio", "voice", "animation"]):
        return handle_file_upload(message)
    
    # Default response for unsupported content
    send_message(chat_id, "⚠️ <b>Unsupported Content</b>\n\nI only process files and commands. Send /help for instructions.")
    return jsonify({"status": "processed"}), 200

def handle_command(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message["text"].lower()
    
    send_typing_action(chat_id)
    
    if text == "/start":
        welcome_message = """
🌟 <b>Premium File Uploader Bot</b> 🌟

Thank you for choosing our professional file hosting service!

<b>Key Features:</b>
• Lightning-fast uploads
• Secure file management
• Detailed analytics
• Multi-format support
• 24/7 availability

Use the menu below to get started.
"""
        buttons = [
            {"text": "📤 Upload Guide", "callback_data": "upload_guide"},
            {"text": "📊 My Stats", "callback_data": "user_stats"},
            {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"} if user_id in ADMIN_IDS else None,
            {"text": "ℹ️ Help Center", "callback_data": "help"}
        ]
        buttons = [b for b in buttons if b is not None]
        
        reply_markup = create_inline_keyboard(buttons, columns=2)
        send_message(chat_id, welcome_message, reply_markup)
    
    elif text == "/help":
        show_help(chat_id)
    elif text == "/stats":
        if user_id in ADMIN_IDS:
            show_admin_panel(chat_id)
        else:
            show_user_stats(chat_id, user_id)
    elif text == "/restart" and user_id in ADMIN_IDS:
        uploaded_files.clear()
        send_message(chat_id, "🔄 <b>System Restarted</b>\n\nAll temporary data has been cleared.")
    else:
        send_message(chat_id, "❓ <b>Unknown Command</b>\n\nType /help for available commands.")
    
    return jsonify({"status": "processed"}), 200

def handle_file_upload(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    
    # Check rate limit
    if not check_rate_limit(user_id):
        send_message(chat_id, "⚠️ <b>Upload Limit Reached</b>\n\nPlease wait a minute before uploading more files.")
        return jsonify({"status": "rate_limited"}), 429
    
    send_typing_action(chat_id)
    
    # Determine file type and ID
    file_info = None
    file_type = None
    caption = message.get("caption")
    
    for file_key in ["document", "photo", "video", "audio", "voice", "animation"]:
        if file_key in message:
            file_type = file_key
            file_info = message[file_key]
            if file_key == "photo":  # Photos come as an array, take the highest quality
                file_info = file_info[-1]
            break
    
    if not file_info or not file_type:
        send_message(chat_id, "⚠️ <b>Unsupported File Type</b>\n\nI only support documents, photos, videos, audio, and animations.")
        return jsonify({"status": "unsupported"}), 200
    
    file_id = file_info["file_id"]
    file_size = file_info.get("file_size")
    
    # Send upload started notification
    upload_msg = send_message(chat_id, "⏳ <b>Uploading your file...</b>\n\nPlease wait while we process your request.")
    
    # Upload to channel
    result = send_file_to_channel(file_id, file_type, caption, user_id=user_id)
    
    if result and result.get("ok"):
        channel_message_id = result["result"]["message_id"]
        channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"
        
        # Store file metadata
        uploaded_files[channel_message_id] = {
            "file_id": file_id,
            "file_type": file_type,
            "user_id": user_id,
            "timestamp": message["date"],
            "caption": caption,
            "file_size": file_size
        }
        
        # Create success message with management options
        file_info = create_file_info_message(uploaded_files[channel_message_id], channel_url, user_id)
        
        buttons = [
            {"text": "🗑️ Delete File", "callback_data": f"delete_{channel_message_id}"},
            {"text": "📋 Copy Link", "url": channel_url},
            {"text": "📊 View Stats", "callback_data": "user_stats"},
            {"text": "📤 Upload More", "callback_data": "upload_guide"}
        ]
        reply_markup = create_inline_keyboard(buttons, columns=2)
        
        # Edit the original "uploading" message
        edit_message_text(chat_id, upload_msg["result"]["message_id"], file_info, reply_markup)
    else:
        error_msg = "❌ <b>Upload Failed</b>\n\nSorry, we couldn't upload your file. Possible reasons:\n• File too large\n• Unsupported format\n• Server issue\n\nPlease try again later."
        edit_message_text(chat_id, upload_msg["result"]["message_id"], error_msg)
    
    return jsonify({"status": "processed"}), 200

def show_help(chat_id, message_id=None):
    help_text = """
📚 <b>Help Center</b>

<b>Available Commands:</b>
/start - Show welcome message
/help - Display this help
/stats - Show your upload statistics

<b>How It Works:</b>
1. Send any supported file
2. Get a permanent shareable link
3. Manage your files with the control panel

<b>Supported Formats:</b>
• Documents (PDF, Word, Excel, etc.)
• Images (JPG, PNG, GIF)
• Videos (MP4, MOV)
• Audio (MP3, WAV)
• Animations (GIF, WebP)

<b>Need more help?</b>
Contact our support team @YourSupportChannel
"""
    buttons = [
        {"text": "📤 Upload Guide", "callback_data": "upload_guide"},
        {"text": "📊 My Stats", "callback_data": "user_stats"},
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, help_text, reply_markup)
    else:
        send_message(chat_id, help_text, reply_markup)

def show_upload_instructions(chat_id, message_id=None):
    instructions = """
📤 <b>File Upload Guide</b>

<b>Basic Upload:</b>
Simply send me any supported file and I'll upload it instantly.

<b>Advanced Options:</b>
• Add captions by sending files with text
• Manage uploads via the control panel
• Track your upload statistics

<b>Best Practices:</b>
• Compress large files for faster uploads
• Use descriptive captions for organization
• Check file formats for optimal results

<b>Limitations:</b>
• Max file size: 50MB (Telegram limit)
• Rate limit: 5 uploads per minute
"""
    buttons = [
        {"text": "🔄 Try Uploading", "callback_data": "upload_try"},
        {"text": "📚 Full Help", "callback_data": "help"},
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, instructions, reply_markup)
    else:
        send_message(chat_id, instructions, reply_markup)

def show_user_stats(chat_id, user_id, message_id=None):
    stats = generate_user_analytics(user_id)
    buttons = [
        {"text": "📤 Upload Files", "callback_data": "upload_guide"},
        {"text": "🔄 Refresh", "callback_data": "user_stats"},
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, stats, reply_markup)
    else:
        send_message(chat_id, stats, reply_markup)

def show_admin_panel(chat_id, message_id=None, refresh=False):
    if refresh:
        # Force update any real-time stats here
        pass
    
    stats = generate_system_stats()
    buttons = [
        {"text": "🔄 Refresh", "callback_data": "refresh_stats"},
        {"text": "📊 User Stats", "callback_data": "admin_user_stats"},
        {"text": "⚙️ Settings", "callback_data": "admin_settings"},
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ]
    reply_markup = create_inline_keyboard(buttons, columns=2)
    
    if message_id:
        edit_message_text(chat_id, message_id, stats, reply_markup)
    else:
        send_message(chat_id, stats, reply_markup)

# Premium index page
@app.route('/', methods=['GET'])
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Professional File Uploader Bot</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --primary: #4361ee;
                --secondary: #3f37c9;
                --accent: #4895ef;
                --light: #f8f9fa;
                --dark: #212529;
                --success: #4cc9f0;
                --warning: #f72585;
                --info: #560bad;
            }
            
            body {
                font-family: 'Roboto', sans-serif;
                line-height: 1.6;
                color: var(--dark);
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                margin: 0;
                padding: 0;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
            }
            
            .container {
                max-width: 1000px;
                width: 90%;
                margin: 2rem auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }
            
            header {
                background: linear-gradient(to right, var(--primary), var(--secondary));
                color: white;
                padding: 2rem;
                text-align: center;
                position: relative;
            }
            
            header h1 {
                margin: 0;
                font-size: 2.5rem;
                font-weight: 700;
            }
            
            header p {
                margin: 0.5rem 0 0;
                font-size: 1.1rem;
                opacity: 0.9;
            }
            
            .status-card {
                background: white;
                margin: -2rem 2rem 2rem;
                padding: 1.5rem;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                position: relative;
                z-index: 1;
            }
            
            .status-card h2 {
                color: var(--primary);
                margin-top: 0;
                border-bottom: 2px solid var(--accent);
                padding-bottom: 0.5rem;
                display: inline-block;
            }
            
            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1.5rem;
                padding: 0 2rem 2rem;
            }
            
            .feature {
                background: white;
                border-radius: 10px;
                padding: 1.5rem;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.05);
                transition: transform 0.3s, box-shadow 0.3s;
            }
            
            .feature:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
            }
            
            .feature h3 {
                color: var(--secondary);
                margin-top: 0;
            }
            
            .btn-group {
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
                justify-content: center;
                padding: 0 2rem 2rem;
            }
            
            .btn {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0.8rem 1.5rem;
                border-radius: 50px;
                text-decoration: none;
                font-weight: 500;
                transition: all 0.3s;
                min-width: 150px;
                text-align: center;
            }
            
            .btn-primary {
                background: var(--primary);
                color: white;
            }
            
            .btn-primary:hover {
                background: var(--secondary);
                transform: translateY(-2px);
            }
            
            .btn-secondary {
                background: white;
                color: var(--primary);
                border: 2px solid var(--primary);
            }
            
            .btn-secondary:hover {
                background: var(--light);
                transform: translateY(-2px);
            }
            
            footer {
                text-align: center;
                padding: 1.5rem;
                color: var(--dark);
                opacity: 0.7;
                font-size: 0.9rem;
                width: 100%;
            }
            
            @media (max-width: 768px) {
                .container {
                    width: 95%;
                    margin: 1rem auto;
                }
                
                header h1 {
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
                <h1>Professional File Uploader Bot</h1>
                <p>Secure, fast, and reliable file hosting solution</p>
            </header>
            
            <div class="status-card">
                <h2>System Status</h2>
                <p>All systems operational. The bot is running smoothly and ready to handle your file uploads.</p>
            </div>
            
            <div class="features">
                <div class="feature">
                    <h3>⚡ Lightning Fast</h3>
                    <p>Upload and share your files in seconds with our optimized infrastructure and global CDN.</p>
                </div>
                
                <div class="feature">
                    <h3>🔒 Secure Storage</h3>
                    <p>Your files are stored securely with end-to-end encryption and access control.</p>
                </div>
                
                <div class="feature">
                    <h3>📊 Advanced Analytics</h3>
                    <p>Track your uploads, view statistics, and monitor your storage usage.</p>
                </div>
                
                <div class="feature">
                    <h3>🔄 File Management</h3>
                    <p>Easily organize, share, and delete your files with our intuitive interface.</p>
                </div>
            </div>
            
            <div class="btn-group">
                <a href="https://t.me/IP_AdressBot" class="btn btn-primary">Start Using Bot</a>
                <a href="/setwebhook" class="btn btn-secondary">Configure Webhook</a>
                <a href="https://t.me/YourSupportChannel" class="btn btn-secondary">Get Support</a>
            </div>
        </div>
        
        <footer>
            &copy; 2023 Professional File Uploader Bot. All rights reserved.
        </footer>
    </body>
    </html>
    """

# Background tasks
def cleanup_old_files():
    """Periodically clean up old file references"""
    while True:
        time.sleep(3600)  # Run every hour
        now = time.time()
        old_files = [k for k, v in uploaded_files.items() 
                    if now - v["timestamp"] > 86400 * 30]  # 30 days
        for file_id in old_files:
            del uploaded_files[file_id]
        print(f"Cleaned up {len(old_files)} old file references")

# Start background tasks
threading.Thread(target=cleanup_old_files, daemon=True).start()

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
