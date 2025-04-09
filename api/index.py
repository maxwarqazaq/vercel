import os
import requests
from flask import Flask, Response, request, jsonify

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')  # Fetch token from Vercel environment variables
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'  # Channel username
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Dictionary to track files uploaded by the bot
uploaded_files = {}

# Helper function to send a message
def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error sending message: {response.text}")
    return response.json()

# Helper function to send a file to the channel
def send_file_to_channel(file_id, file_type, chat_id=CHANNEL_USERNAME):
    if file_type == "document":
        method = "sendDocument"
        payload_key = "document"
    elif file_type == "photo":
        method = "sendPhoto"
        payload_key = "photo"
    elif file_type == "video":
        method = "sendVideo"
        payload_key = "video"
    elif file_type == "audio":
        method = "sendAudio"
        payload_key = "audio"
    else:
        return None

    url = f"{BASE_API_URL}/{method}"
    payload = {"chat_id": chat_id, payload_key: file_id}
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

# Set webhook for Vercel
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    vercel_url = os.getenv('VERCEL_URL', 'https://your-project.vercel.app')  # Default for Vercel
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

    # Handle callback queries (delete button)
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
                    send_message(chat_id, "File successfully deleted!")
                else:
                    send_message(chat_id, "Failed to delete the file.")
            else:
                send_message(chat_id, "You don’t have permission to delete this file or it no longer exists.")
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
        if text == "/start":
            send_message(chat_id, "Welcome! Send me a file, and I'll upload it to the channel and share the URL.")
        elif text == "/help":
            help_text = """
Available commands:
/start - Start the bot and get instructions.
/help - Show this help message.
/restart - Restart the bot (clears cached data).
/upload - Learn how to upload files to the bot.
            """
            send_message(chat_id, help_text)
        elif text == "/restart":
            uploaded_files.clear()
            send_message(chat_id, "Bot has been restarted. All cached data has been cleared.")
        elif text == "/upload":
            upload_instructions = """
To upload a file:
1. Send a file (document, photo, video, or audio) to this bot.
2. The bot will upload it to the channel and provide a URL.
3. You can delete the file using the "Delete File" button.
            """
            send_message(chat_id, upload_instructions)
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
    file_id = None
    file_type = None
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

    if file_id:
        # Send file to channel
        result = send_file_to_channel(file_id, file_type)
        if result and result.get("ok"):
            channel_message_id = result["result"]["message_id"]
            channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

            # Store file info
            uploaded_files[channel_message_id] = {
                "file_id": file_id,
                "file_type": file_type,
                "user_id": user_id
            }

            # Send URL with delete button
            reply_markup = {
                "inline_keyboard": [[{"text": "Delete File", "callback_data": f"delete_{channel_message_id}"}]]
            }
            send_message(chat_id, f"File uploaded to the channel! Here's the URL:\n{channel_url}", reply_markup)
        else:
            send_message(chat_id, "Failed to upload the file to the channel.")
    else:
        send_message(chat_id, "Please send a valid file (document, photo, video, or audio).")

    return jsonify({"status": "processed"}), 200

# Index route
@app.route('/', methods=['GET'])
def index():
    return "<h1>Telegram Bot Webhook is Running</h1>"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))  # Vercel sets PORT
    app.run(host="0.0.0.0", port=port, debug=True)
