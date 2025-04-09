import os
import requests
import logging
from flask import Flask, request, jsonify
from datetime import datetime
from typing import Optional, Dict, Any

# Flask application setup
app = Flask(__name__)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')  # Log to a file for persistence
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')
CHANNEL_USERNAME = '@cdntelegraph'
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"

if not TOKEN:
    logger.error("Bot token not set in environment variables")
    raise ValueError("Bot token not set! Configure 'TOKEN' in environment variables.")

# In-memory storage with a cap
MAX_FILES = 1000
uploaded_files: Dict[int, Dict[str, Any]] = {}

# Helper function to manage in-memory storage
def manage_uploaded_files(channel_message_id: int, file_data: Optional[Dict] = None) -> Optional[Dict]:
    if file_data is not None:  # Store
        if len(uploaded_files) >= MAX_FILES:
            logger.warning("Max file limit reached, removing oldest entry")
            oldest_key = next(iter(uploaded_files))
            del uploaded_files[oldest_key]
        uploaded_files[channel_message_id] = file_data
        return file_data
    else:  # Retrieve
        return uploaded_files.get(channel_message_id)

def delete_uploaded_file(channel_message_id: int):
    if channel_message_id in uploaded_files:
        del uploaded_files[channel_message_id]

# Telegram API call without rate limiting
def telegram_api_call(method: str, payload: Dict) -> Optional[Dict]:
    url = f"{BASE_API_URL}/{method}"
    try:
        logger.debug(f"Making API call: {method} with payload: {payload}")
        response = requests.post(url, json=payload, timeout=3)  # Reduced timeout
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result}")
            return None
        return result
    except requests.RequestException as e:
        logger.error(f"API call failed: {str(e)}")
        return None
    except ValueError as e:
        logger.error(f"JSON parsing failed: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in API call: {str(e)}")
        return None

# Stylish message templates with buttons
class MessageTemplates:
    @staticmethod
    def welcome(channel: str) -> tuple[str, Dict]:
        text = f"""
🌟 <b>Welcome to FileShare Pro</b> 🌟
Your premium file sharing assistant!
Upload files to {channel} with ease.
        """
        markup = {
            "inline_keyboard": [
                [{"text": "📖 How to Use", "callback_data": "show_upload"}],
                [{"text": "ℹ️ About", "callback_data": "show_about"}]
            ]
        }
        return text, markup

    @staticmethod
    def help() -> tuple[str, Dict]:
        text = """
📚 <b>Command Center</b> 📚
Control your file sharing experience:
        """
        markup = {
            "inline_keyboard": [
                [{"text": "🚀 Start", "callback_data": "cmd_start"}],
                [{"text": "📤 Upload Guide", "callback_data": "show_upload"}],
                [{"text": "🔄 Restart", "callback_data": "cmd_restart"}],
                [{"text": "ℹ️ About", "callback_data": "show_about"}]
            ]
        }
        return text, markup

    @staticmethod
    def upload_guide() -> tuple[str, Dict]:
        text = """
📤 <b>Upload Master Guide</b> 📤
1. Send any file to me
2. Get a shareable link
3. Manage with buttons
        """
        markup = {
            "inline_keyboard": [
                [{"text": "🎯 Try Now", "callback_data": "cmd_start"}],
                [{"text": "❓ Help", "callback_data": "show_help"}]
            ]
        }
        return text, markup

    @staticmethod
    def about() -> tuple[str, Dict]:
        text = """
🤖 <b>FileShare Pro</b> 🤖
Version: 2.1
Powered by: xAI
Updated: April 2025
        """
        markup = {
            "inline_keyboard": [
                [{"text": "🌐 Support", "url": "https://t.me/xAISupport"}],
                [{"text": "🏠 Home", "callback_data": "cmd_start"}]
            ]
        }
        return text, markup

# Core functions
def send_message(chat_id: int, text: str, reply_markup: Optional[Dict] = None) -> Optional[Dict]:
    payload = {
        "chat_id": chat_id,
        "text": text.strip(),
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api_call("sendMessage", payload)

def send_file_to_channel(file_id: str, file_type: str, chat_id: str = CHANNEL_USERNAME) -> Optional[Dict]:
    file_methods = {
        "document": ("sendDocument", "document"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio")
    }
    if file_type not in file_methods:
        logger.warning(f"Unsupported file type: {file_type}")
        return None
    method, payload_key = file_methods[file_type]
    payload = {"chat_id": chat_id, payload_key: file_id}
    return telegram_api_call(method, payload)

def delete_message(chat_id: str, message_id: int) -> bool:
    payload = {"chat_id": chat_id, "message_id": message_id}
    result = telegram_api_call("deleteMessage", payload)
    return bool(result and result.get("ok"))

# Global error handler
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({"status": "error", "message": "Internal server error"}), 500

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

# Webhook setup
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')
    if not vercel_url:
        logger.error("VERCEL_URL not set in environment variables")
        return "VERCEL_URL not set", 500
    webhook_url = f"{BASE_API_URL}/setWebhook?url={vercel_url}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    try:
        response = requests.get(webhook_url, timeout=3)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Failed to set webhook: {result}")
            return f"Failed to set webhook: {result}", 500
        logger.info("Webhook set successfully")
        return "Webhook successfully set", 200
    except requests.RequestException as e:
        logger.error(f"Webhook setup failed: {str(e)}")
        return f"Error setting webhook: {str(e)}", 500

# Webhook handler
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if not update:
            logger.warning("No data received in webhook")
            return jsonify({"status": "no data"}), 400

        # Handle callback queries
        if "callback_query" in update:
            callback = update["callback_query"]
            chat_id = callback["message"]["chat"]["id"]
            user_id = callback["from"]["id"]
            callback_data = callback["data"]

            handlers = {
                "cmd_start": MessageTemplates.welcome(CHANNEL_USERNAME),
                "show_help": MessageTemplates.help(),
                "show_upload": MessageTemplates.upload_guide(),
                "show_about": MessageTemplates.about(),
                "cmd_restart": ("🔄 Bot restarted! Cache cleared.", None)
            }

            if callback_data.startswith("delete_"):
                try:
                    channel_message_id = int(callback_data.split("_")[1])
                    file_data = manage_uploaded_files(channel_message_id)
                    if file_data and file_data["user_id"] == user_id:
                        if delete_message(CHANNEL_USERNAME, channel_message_id):
                            delete_uploaded_file(channel_message_id)
                            send_message(chat_id, "✅ File deleted successfully!")
                        else:
                            send_message(chat_id, "❌ Deletion failed")
                    else:
                        send_message(chat_id, "⚠️ No permission or file not found")
                except (IndexError, ValueError) as e:
                    logger.error(f"Invalid callback data: {callback_data}, error: {str(e)}")
                    send_message(chat_id, "❌ Invalid request")
            
            elif callback_data in handlers:
                text, markup = handlers[callback_data]
                if callback_data == "cmd_restart":
                    uploaded_files.clear()
                send_message(chat_id, text, markup)

            return jsonify({"status": "processed"}), 200

        # Handle messages
        message = update.get("message")
        if not message:
            logger.info("No message in update")
            return jsonify({"status": "ignored"}), 200

        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]

        # Command handling
        if "text" in message:
            text = message["text"].lower()
            commands = {
                "/start": MessageTemplates.welcome(CHANNEL_USERNAME),
                "/help": MessageTemplates.help(),
                "/upload": MessageTemplates.upload_guide(),
                "/about": MessageTemplates.about(),
                "/restart": ("🔄 Bot restarting...", {
                    "inline_keyboard": [[{"text": "✅ Confirm", "callback_data": "cmd_restart"}]]
                })
            }
            
            if text in commands:
                text, markup = commands[text]
                send_message(chat_id, text, markup)
                return jsonify({"status": "processed"}), 200

        # File upload handling
        file_types = {
            "document": ("document", "file_id"),
            "photo": ("photo", -1),
            "video": ("video", "file_id"),
            "audio": ("audio", "file_id")
        }

        file_id = None
        file_type = None
        for f_type, (key, attr) in file_types.items():
            if key in message:
                try:
                    file_id = message[key][attr]["file_id"] if key == "photo" else message[key][attr]
                    file_type = f_type
                    break
                except (KeyError, IndexError) as e:
                    logger.error(f"Failed to parse file data: {str(e)}")
                    send_message(chat_id, "❌ Invalid file data", {
                        "inline_keyboard": [[{"text": "📖 Learn How", "callback_data": "show_upload"}]]
                    })
                    return jsonify({"status": "processed"}), 200

        if file_id:
            if file_type not in file_types:
                send_message(chat_id, "❌ Unsupported file type", {
                    "inline_keyboard": [[{"text": "📖 Learn How", "callback_data": "show_upload"}]]
                })
                return jsonify({"status": "processed"}), 200
            result = send_file_to_channel(file_id, file_type)
            if result and result.get("ok"):
                channel_message_id = result["result"]["message_id"]
                channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"
                
                file_data = {
                    "file_id": file_id,
                    "file_type": file_type,
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                }
                manage_uploaded_files(channel_message_id, file_data)

                reply_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "🗑️ Delete", "callback_data": f"delete_{channel_message_id}"},
                            {"text": "🌐 Open", "url": channel_url}
                        ],
                        [
                            {"text": "📋 Share", "switch_inline_query": channel_url},
                            {"text": "🏠 Home", "callback_data": "cmd_start"}
                        ]
                    ]
                }
                send_message(chat_id, 
                            f"🎉 <b>File Uploaded!</b>\n"
                            f"🔗 <a href='{channel_url}'>Link</a>\n"
                            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            reply_markup)
            else:
                logger.error(f"File upload failed: {result}")
                send_message(chat_id, "❌ Upload failed", {
                    "inline_keyboard": [[{"text": "🔄 Retry", "callback_data": "show_upload"}]]
                })
        else:
            send_message(chat_id, "📎 Send a valid file!", {
                "inline_keyboard": [[{"text": "📖 Learn How", "callback_data": "show_upload"}]]
            })

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/', methods=['GET'])
def index():
    return """
    <h1 style='font-family: Arial, sans-serif; color: #2c3e50;'>
        🚀 FileShare Pro Server
    </h1>
    <p style='font-family: Arial, sans-serif; color: #7f8c8d;'>
        Status: Active | Time: {time}
    </p>
    """.format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
