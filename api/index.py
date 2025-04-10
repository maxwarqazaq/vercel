import os
import requests
from flask import Flask, Response, request, jsonify
from datetime import datetime

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("Bot token not set in environment variables!")
CHANNEL_USERNAME = '@cdntelegraph'
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]

# Dictionary to track files
uploaded_files = {}

def create_inline_keyboard(buttons, columns=2):
    keyboard = []
    for i in range(0, len(buttons), columns):
        keyboard.append(buttons[i:i + columns])
    return {"inline_keyboard": keyboard}

def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return requests.post(url, json=payload)

def send_file_to_channel(file_id, file_type, caption=None):
    method = {
        "document": "sendDocument",
        "photo": "sendPhoto",
        "video": "sendVideo",
        "audio": "sendAudio",
        "voice": "sendVoice"
    }.get(file_type)
    
    if not method:
        return None

    url = f"{BASE_API_URL}/{method}"
    payload = {
        "chat_id": CHANNEL_USERNAME,
        file_type: file_id,
        "parse_mode": "HTML"
    }
    if caption:
        payload["caption"] = caption
    return requests.post(url, json=payload)

def delete_message(chat_id, message_id):
    url = f"{BASE_API_URL}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    return requests.post(url, json=payload)

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
        data = callback["data"]

        if data.startswith("delete_"):
            channel_msg_id = int(data.split("_")[1])
            if channel_msg_id in uploaded_files:
                file_data = uploaded_files[channel_msg_id]
                if user_id in ADMIN_IDS or file_data["user_id"] == user_id:
                    if delete_message(CHANNEL_USERNAME, channel_msg_id).status_code == 200:
                        del uploaded_files[channel_msg_id]
                        send_message(chat_id, "✅ File deleted!")
                    else:
                        send_message(chat_id, "❌ Delete failed")
        return jsonify({"status": "ok"}), 200

    # Handle messages
    if "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Handle commands
    if "text" in message and message["text"].startswith("/"):
        cmd = message["text"]
        if cmd == "/start":
            send_message(chat_id, "Send me a file to upload")
        return jsonify({"status": "ok"}), 200

    # Handle file uploads
    file_id = None
    file_type = None
    
    if "document" in message:
        file_id = message["document"]["file_id"]
        file_type = "document"
    elif "photo" in message:
        file_id = message["photo"][-1]["file_id"]
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
        caption = message.get("caption")
        result = send_file_to_channel(file_id, file_type, caption)
        if result and result.status_code == 200:
            channel_msg_id = result.json()["result"]["message_id"]
            uploaded_files[channel_msg_id] = {
                "file_id": file_id,
                "file_type": file_type,
                "user_id": user_id
            }
            send_message(chat_id, "✅ File uploaded!")
        else:
            send_message(chat_id, "❌ Upload failed")
    else:
        send_message(chat_id, "⚠️ Unsupported file type")

    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return "Bot is running"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
