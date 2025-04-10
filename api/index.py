import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime
import humanize
import time
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor

# Flask application
app = Flask(__name__)

# Configuration
TOKEN = os.getenv('TOKEN')
CHANNEL_USERNAME = '@cdntelegraph'
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]
MAX_WORKERS = 100  # Increased thread pool size
REQUEST_TIMEOUT = 2  # 2 seconds timeout for API calls

# Global session for connection pooling
session = None

# Initialize the aiohttp session
@app.before_first_request
def init_session():
    global session
    session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(
            limit=100,  # Increased connection pool size
            force_close=True,
            enable_cleanup_closed=True,
            keepalive_timeout=60
        ),
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    )

# Optimized data structure for tracking files
uploaded_files = {}

# Thread pool for parallel execution
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

async def send_message_async(chat_id, text, reply_markup=None, disable_web_page_preview=True):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_web_page_preview
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                print(f"Error sending message: {await response.text()}")
            return await response.json()
    except Exception as e:
        print(f"Exception in send_message_async: {str(e)}")
        return None

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

async def send_file_to_channel_async(file_id, file_type, caption=None, chat_id=CHANNEL_USERNAME):
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
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                print(f"Error sending file: {await response.text()}")
            return await response.json()
    except Exception as e:
        print(f"Exception in send_file_to_channel_async: {str(e)}")
        return None

def create_file_info_message(file_data, channel_url):
    file_type_emoji = {
        "document": "📄",
        "photo": "🖼️",
        "video": "🎬",
        "audio": "🎵",
        "voice": "🎤"
    }.get(file_data["file_type"], "📁")
    
    upload_time = datetime.fromtimestamp(file_data["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
    relative_time = humanize.naturaltime(datetime.now() - datetime.fromtimestamp(file_data["timestamp"]))
    
    message = f"""
{file_type_emoji} <b>File Successfully Uploaded!</b>

📅 <b>Upload time:</b> {upload_time} ({relative_time})
"""
    
    if file_data.get("caption"):
        message += f"\n📝 <b>Caption:</b> {file_data['caption']}\n"
    
    message += f"""
🔗 <b>Channel URL:</b> <a href="{channel_url}">Click here to view</a>

<i>You can manage this file using the buttons below.</i>
"""
    return message

@app.route('/webhook', methods=['POST'])
async def webhook():
    start_time = time.time()
    update = request.get_json()
    
    if not update:
        return jsonify({"status": "no data"}), 400

    # Process callback queries
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
                if user_id in ADMIN_IDS or file_data["user_id"] == user_id:
                    # Process deletion asynchronously
                    await delete_message_async(CHANNEL_USERNAME, channel_message_id)
                    del uploaded_files[channel_message_id]
                    await edit_message_text_async(
                        chat_id, 
                        message_id,
                        "✅ <b>File successfully deleted from the channel!</b>",
                        reply_markup=None
                    )
                else:
                    await edit_message_text_async(
                        chat_id,
                        message_id,
                        "⛔ <b>Permission Denied</b>\n\nYou don't have permission to delete this file.",
                        reply_markup=callback["message"].get("reply_markup")
                    )
            else:
                await edit_message_text_async(
                    chat_id,
                    message_id,
                    "⚠️ <b>File not found</b>\n\nThis file may have already been deleted.",
                    reply_markup=None
                )
        return jsonify({"status": "processed"}), 200

    # Process messages
    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Process commands
    if "text" in message:
        text = message["text"]
        if text.startswith("/"):
            if text == "/start":
                await show_main_menu(chat_id, user_id=user_id)
            elif text == "/help":
                await show_help(chat_id)
            elif text == "/restart" and user_id in ADMIN_IDS:
                uploaded_files.clear()
                await send_message_async(chat_id, "🔄 <b>Bot has been restarted.</b>\n\nAll cached data has been cleared.")
            elif text == "/upload":
                await show_upload_instructions(chat_id)
            elif text == "/stats" and user_id in ADMIN_IDS:
                await show_stats(chat_id)
            elif text == "/mystats":
                await show_user_stats(chat_id, user_id)
            elif text == "/list":
                await show_user_files(chat_id, user_id)
            else:
                await send_message_async(chat_id, "❓ <b>Unknown Command</b>\n\nType /help to see available commands.")
            return jsonify({"status": "processed"}), 200

    # Process file uploads
    file_id = None
    file_type = None
    caption = None
    
    if "caption" in message:
        caption = message["caption"]
    
    if "document" in message:
        file_id = message["document"]["file_id"]
        file_type = "document"
    elif "photo" in message:
        file_id = message["photo"][-1]["file_id"]  # Largest photo size
        file_type = "photo"
    elif "video" in message:
        file_id = message["video"]["file_id"]
        file_type = "video"
    elif "audio" in message:
        file_id = message["audio"]["file_id"]
        file_type = "audio"
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        file_type = "voice"

    if file_id:
        # Send file to channel asynchronously
        result = await send_file_to_channel_async(file_id, file_type, caption)
        if result and result.get("ok"):
            channel_message_id = result["result"]["message_id"]
            channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

            # Store file info
            uploaded_files[channel_message_id] = {
                "file_id": file_id,
                "file_type": file_type,
                "user_id": user_id,
                "timestamp": message["date"],
                "caption": caption
            }

            # Create response message
            file_info = create_file_info_message(uploaded_files[channel_message_id], channel_url)
            
            buttons = [
                {"text": "🗑️ Delete File", "callback_data": f"delete_{channel_message_id}"},
                {"text": "🔗 Copy Link", "url": channel_url},
                {"text": "📊 File Stats", "callback_data": f"file_stats_{channel_message_id}"},
                {"text": "📤 Upload Another", "callback_data": "upload_instructions"}
            ]
            reply_markup = create_inline_keyboard(buttons)
            
            await send_message_async(chat_id, file_info, reply_markup)
        else:
            await send_message_async(chat_id, "❌ <b>Upload Failed</b>\n\nSorry, I couldn't upload your file to the channel. Please try again later.")
    else:
        await send_message_async(chat_id, "⚠️ <b>Unsupported Content</b>\n\nPlease send a document, photo, video, or audio file to upload.")

    # Log response time
    response_time = (time.time() - start_time) * 1000
    print(f"Request processed in {response_time:.2f}ms")
    
    return jsonify({"status": "processed"}), 200

async def show_main_menu(chat_id, message_id=None, user_id=None):
    welcome_message = """
🌟 <b>Welcome to File Uploader Bot!</b> 🌟

I can upload your files to our channel and provide you with a shareable link.

<b>Main Features:</b>
• Upload documents, photos, videos, and audio files
• Get direct links to your uploaded files
• Delete your files anytime
• View detailed file statistics
"""
    buttons = [
        {"text": "📤 Upload File", "callback_data": "upload_instructions"},
        {"text": "ℹ️ Help", "callback_data": "help"},
        {"text": "📊 My Stats", "callback_data": "user_stats"},
        {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"} if user_id in ADMIN_IDS else None
    ]
    buttons = [b for b in buttons if b is not None]
    
    reply_markup = create_inline_keyboard(buttons, columns=2)
    
    if message_id:
        await edit_message_text_async(chat_id, message_id, welcome_message, reply_markup)
    else:
        await send_message_async(chat_id, welcome_message, reply_markup)

async def delete_message_async(chat_id, message_id):
    url = f"{BASE_API_URL}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        async with session.post(url, json=payload) as response:
            return response.status == 200
    except Exception as e:
        print(f"Exception in delete_message_async: {str(e)}")
        return False

async def edit_message_text_async(chat_id, message_id, text, reply_markup=None):
    url = f"{BASE_API_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                print(f"Error editing message: {await response.text()}")
            return await response.json()
    except Exception as e:
        print(f"Exception in edit_message_text_async: {str(e)}")
        return None

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram File Uploader Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                color: #333;
            }
            h1 {
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }
            .status {
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .btn {
                display: inline-block;
                background-color: #3498db;
                color: white;
                padding: 10px 15px;
                text-decoration: none;
                border-radius: 5px;
                margin: 5px;
            }
        </style>
    </head>
    <body>
        <h1>Telegram File Uploader Bot</h1>
        <div class="status">
            <p><strong>Status:</strong> Running</p>
            <p>This is the webhook endpoint for the Telegram File Uploader Bot.</p>
        </div>
        <a href="https://t.me/IP_AdressBot" class="btn">Start the Bot</a>
        <a href="/setwebhook" class="btn">Set Webhook</a>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
