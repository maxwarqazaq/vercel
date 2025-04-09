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
MAX_FILE_SIZE_MB = 80  # Max file size limit in MB

# Data storage
uploaded_files = {}  # Tracks uploaded files
users = set()  # Tracks unique users
welcome_message = "Welcome! Send me a file, and I'll upload it to the channel and share the URL."  # Default welcome message

# Admin user ID (replace with your Telegram user ID)
ADMIN_ID = YOUR_ADMIN_ID  # e.g., 123456789, find it by sending a message and checking logs

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

# Helper function to pin a message
def pin_message(chat_id, message_id):
    url = f"{BASE_API_URL}/pinChatMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Error pinning message: {response.text}")
    return response.status_code == 200

# Helper function to get file info and download link
def get_file_info(file_id):
    url = f"{BASE_API_URL}/getFile"
    payload = {"file_id": file_id}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json()
    print(f"Error getting file info: {response.text}")
    return None

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
    users.add(user_id)  # Track unique users

    # Command handlers
    if "text" in message:
        text = message["text"].lower()
        if text == "/start":
            send_message(chat_id, welcome_message)
        elif text == "/help":
            help_text = """
Available commands:
/start - Start the bot.
/help - Show this help message.
/restart - Restart the bot (clears cached data).
/upload - Learn how to upload files.
/fileinfo <message_id> - Get details about an uploaded file.
/listfiles - List all your uploaded files.
/clearfiles - Delete all your uploaded files.
/broadcast <message> - Send a message to the channel (admin only).
/download <message_id> - Download a file from the channel (up to 80MB).
/stats - Show bot usage statistics.
/pin <message_id> - Pin a file in the channel (admin only).
/search <type> - Search your files by type (e.g., photo, video).
/setwelcome <message> - Set a custom welcome message (admin only).
/savefile <message_id> - Log file details for saving (up to 80MB).
            """
            send_message(chat_id, help_text)
        elif text == "/restart":
            uploaded_files.clear()
            users.clear()
            send_message(chat_id, "Bot has been restarted. All cached data has been cleared.")
        elif text == "/upload":
            upload_instructions = """
To upload a file:
1. Send a file (document, photo, video, or audio) up to 80MB.
2. The bot will upload it to the channel and provide a URL.
3. Use /download <message_id> to get it back or /savefile to log it.
            """
            send_message(chat_id, upload_instructions)
        elif text.startswith("/fileinfo"):
            try:
                message_id = int(text.split()[1])
                if (message_id in uploaded_files and 
                    uploaded_files[message_id]["user_id"] == user_id):
                    file_info = uploaded_files[message_id]
                    info_text = f"""
File Info:
- Type: {file_info['file_type']}
- File ID: {file_info['file_id']}
- Size: {file_info['file_size']} bytes
- URL: https://t.me/{CHANNEL_USERNAME[1:]}/{message_id}
                    """
                    send_message(chat_id, info_text)
                else:
                    send_message(chat_id, "File not found or you don’t have access.")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /fileinfo <message_id>")
        elif text == "/listfiles":
            user_files = [f for f, info in uploaded_files.items() if info["user_id"] == user_id]
            if user_files:
                file_list = "\n".join(
                    f"- {info['file_type']} | ID: {fid} | URL: https://t.me/{CHANNEL_USERNAME[1:]}/{fid}"
                    for fid, info in uploaded_files.items() if info["user_id"] == user_id
                )
                send_message(chat_id, f"Your uploaded files:\n{file_list}")
            else:
                send_message(chat_id, "You haven’t uploaded any files yet.")
        elif text == "/clearfiles":
            user_files = [(f, info) for f, info in uploaded_files.items() if info["user_id"] == user_id]
            if not user_files:
                send_message(chat_id, "No files to clear.")
                return jsonify({"status": "processed"}), 200
            deleted_count = 0
            for message_id, _ in user_files:
                if delete_message(CHANNEL_USERNAME, message_id):
                    del uploaded_files[message_id]
                    deleted_count += 1
            send_message(chat_id, f"Cleared {deleted_count} of your files from the channel.")
        elif text.startswith("/broadcast") and user_id == ADMIN_ID:
            try:
                broadcast_message = text.split(" ", 1)[1]
                send_message(CHANNEL_USERNAME, broadcast_message)
                send_message(chat_id, "Message broadcasted to the channel!")
            except IndexError:
                send_message(chat_id, "Usage: /broadcast <message>")
        elif text.startswith("/broadcast"):
            send_message(chat_id, "You don’t have permission to broadcast.")
        elif text.startswith("/download"):
            try:
                message_id = int(text.split()[1])
                if (message_id in uploaded_files and 
                    uploaded_files[message_id]["user_id"] == user_id):
                    file_info = uploaded_files[message_id]
                    file_type = file_info["file_type"]
                    file_id = file_info["file_id"]
                    file_size = int(file_info["file_size"]) if file_info["file_size"] != "Unknown" else 0
                    
                    # Check file size (convert bytes to MB)
                    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                        send_message(chat_id, f"File is too large ({file_size / (1024*1024):.2f}MB). Max is {MAX_FILE_SIZE_MB}MB.")
                        return jsonify({"status": "processed"}), 200

                    # Get file download link
                    file_data = get_file_info(file_id)
                    if file_data and file_data.get("ok"):
                        file_path = file_data["result"]["file_path"]
                        download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
                        # Send file back to user
                        if file_type == "document":
                            requests.post(f"{BASE_API_URL}/sendDocument", json={"chat_id": chat_id, "document": file_id})
                        elif file_type == "photo":
                            requests.post(f"{BASE_API_URL}/sendPhoto", json={"chat_id": chat_id, "photo": file_id})
                        elif file_type == "video":
                            requests.post(f"{BASE_API_URL}/sendVideo", json={"chat_id": chat_id, "video": file_id})
                        elif file_type == "audio":
                            requests.post(f"{BASE_API_URL}/sendAudio", json={"chat_id": chat_id, "audio": file_id})
                        send_message(chat_id, f"File downloaded and sent to you!\nDownload URL (valid for 1 hour): {download_url}")
                    else:
                        send_message(chat_id, "Failed to retrieve file info.")
                else:
                    send_message(chat_id, "File not found or you don’t have access.")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /download <message_id>")
        elif text == "/stats":
            total_files = len(uploaded_files)
            total_users = len(users)
            stats_text = f"""
Bot Stats:
- Total Files Uploaded: {total_files}
- Total Unique Users: {total_users}
            """
            send_message(chat_id, stats_text)
        elif text.startswith("/pin") and user_id == ADMIN_ID:
            try:
                message_id = int(text.split()[1])
                if message_id in uploaded_files:
                    if pin_message(CHANNEL_USERNAME, message_id):
                        send_message(chat_id, f"File {message_id} pinned in the channel!")
                    else:
                        send_message(chat_id, "Failed to pin the file.")
                else:
                    send_message(chat_id, "File not found.")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /pin <message_id>")
        elif text.startswith("/pin"):
            send_message(chat_id, "You don’t have permission to pin messages.")
        elif text.startswith("/search"):
            try:
                file_type = text.split()[1].lower()
                if file_type not in ["document", "photo", "video", "audio"]:
                    send_message(chat_id, "Valid types: document, photo, video, audio")
                    return jsonify({"status": "processed"}), 200
                user_files = [(fid, info) for fid, info in uploaded_files.items() 
                             if info["user_id"] == user_id and info["file_type"] == file_type]
                if user_files:
                    file_list = "\n".join(
                        f"- ID: {fid} | URL: https://t.me/{CHANNEL_USERNAME[1:]}/{fid}"
                        for fid, _ in user_files
                    )
                    send_message(chat_id, f"Your {file_type}s:\n{file_list}")
                else:
                    send_message(chat_id, f"No {file_type}s found.")
            except IndexError:
                send_message(chat_id, "Usage: /search <type>")
        elif text.startswith("/setwelcome") and user_id == ADMIN_ID:
            try:
                global welcome_message
                welcome_message = text.split(" ", 1)[1]
                send_message(chat_id, "Welcome message updated!")
            except IndexError:
                send_message(chat_id, "Usage: /setwelcome <message>")
        elif text.startswith("/setwelcome"):
            send_message(chat_id, "You don’t have permission to set the welcome message.")
        elif text.startswith("/savefile"):
            try:
                message_id = int(text.split()[1])
                if (message_id in uploaded_files and 
                    uploaded_files[message_id]["user_id"] == user_id):
                    file_info = uploaded_files[message_id]
                    file_id = file_info["file_id"]
                    file_size = int(file_info["file_size"]) if file_info["file_size"] != "Unknown" else 0
                    
                    # Check file size
                    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                        send_message(chat_id, f"File is too large ({file_size / (1024*1024):.2f}MB). Max is {MAX_FILE_SIZE_MB}MB.")
                        return jsonify({"status": "processed"}), 200

                    # Get file download link
                    file_data = get_file_info(file_id)
                    if file_data and file_data.get("ok"):
                        file_path = file_data["result"]["file_path"]
                        download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
                        send_message(chat_id, f"File details logged for saving:\n- File ID: {file_id}\n- URL: {download_url}\nNote: Use this URL within 1 hour.")
                        # Here, you could integrate external storage (e.g., AWS S3) if needed
                    else:
                        send_message(chat_id, "Failed to retrieve file info.")
                else:
                    send_message(chat_id, "File not found or you don’t have access.")
            except (IndexError, ValueError):
                send_message(chat_id, "Usage: /savefile <message_id>")
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
    file_id = None
    file_type = None
    file_size = None
    if "document" in message:
        file_id = message["document"]["file_id"]
        file_type = "document"
        file_size = message["document"].get("file_size", "Unknown")
    elif "photo" in message:
        file_id = message["photo"][-1]["file_id"]  # Largest photo size
        file_type = "photo"
        file_size = message["photo"][-1].get("file_size", "Unknown")
    elif "video" in message:
        file_id = message["video"]["file_id"]
        file_type = "video"
        file_size = message["video"].get("file_size", "Unknown")
    elif "audio" in message:
        file_id = message["audio"]["file_id"]
        file_type = "audio"
        file_size = message["audio"].get("file_size", "Unknown")

    if file_id:
        # Check file size before uploading
        file_size_bytes = int(file_size) if file_size != "Unknown" else 0
        if file_size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
            send_message(chat_id, f"File too large ({file_size_bytes / (1024*1024):.2f}MB). Max is {MAX_FILE_SIZE_MB}MB.")
            return jsonify({"status": "processed"}), 200

        # Send file to channel
        result = send_file_to_channel(file_id, file_type)
        if result and result.get("ok"):
            channel_message_id = result["result"]["message_id"]
            channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

            # Store file info with size
            uploaded_files[channel_message_id] = {
                "file_id": file_id,
                "file_type": file_type,
                "user_id": user_id,
                "file_size": file_size
            }

            # Send URL with delete button
            reply_markup = {
                "inline_keyboard": [[{"text": "Delete File", "callback_data": f"delete_{channel_message_id}"}]]
            }
            send_message(chat_id, f"File uploaded to the channel! Here's the URL:\n{channel_url}", reply_markup)
        else:
            send_message(chat_id, "Failed to upload the file to the channel.")
    elif "text" not in message:
        send_message(chat_id, "Please send a valid file (document, photo, video, or audio) up to 80MB.")

    return jsonify({"status": "processed"}), 200

# Index route
@app.route('/', methods=['GET'])
def index():
    return "<h1>Telegram Bot Webhook is Running</h1>"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))  # Vercel sets PORT
    app.run(host="0.0.0.0", port=port, debug=True)
