import os
import requests
from flask import Flask, Response, request, jsonify, render_template_string
from datetime import datetime
import traceback
import subprocess

# Flask application
app = Flask(__name__)

# Bot configuration
TOKEN = os.getenv('TOKEN')  # Fetch token from Vercel environment variables
if not TOKEN:
    raise ValueError("Bot token is not set in environment variables! Set 'TOKEN' in Vercel settings.")
CHANNEL_USERNAME = '@cdntelegraph'  # Channel username
BASE_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = [6099917788]  # Replace with your admin user IDs

# Dictionary to track files uploaded by the bot
uploaded_files = {}

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

🔗 <b>Channel URL:</b> <a href="{channel_url}">Click here to view</a>

<i>You can delete this file using the button below.</i>
"""

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
                    {"text": "🛠️ Admin Panel", "callback_data": "admin_panel"} if user_id in ADMIN_IDS else None
                ]
                buttons = [b for b in buttons if b is not None]  # Remove None for non-admins
                
                reply_markup = create_inline_keyboard(buttons, columns=2)
                send_message(chat_id, welcome_message, reply_markup)
                
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
                stats_message = f"""
📊 <b>Bot Statistics</b>

• Total files uploaded: {len(uploaded_files)}
• Active users: {len({v['user_id'] for v in uploaded_files.values()})}

<b>Storage Status:</b>
The bot is functioning normally.
"""
                send_message(chat_id, stats_message)
            elif text == "/console" and user_id in ADMIN_IDS:
                console_url = f"/admin/console?user_id={user_id}"
                send_message(chat_id, f"🔧 <b>Admin Console</b>\n\nAccess the console here: {console_url}")
            else:
                send_message(chat_id, "❓ <b>Unknown Command</b>\n\nType /help to see available commands.")
        return jsonify({"status": "processed"}), 200

    # Handle file uploads
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
                "caption": caption
            }

            # Create stylish message with delete button
            file_info = create_file_info_message(uploaded_files[channel_message_id], channel_url)
            
            buttons = [
                {"text": "🗑️ Delete File", "callback_data": f"delete_{channel_message_id}"},
                {"text": "🔗 Copy Link", "url": channel_url},
                {"text": "📤 Upload Another", "callback_data": "upload_instructions"}
            ]
            reply_markup = create_inline_keyboard(buttons)
            
            send_message(chat_id, file_info, reply_markup)
        else:
            send_message(chat_id, "❌ <b>Upload Failed</b>\n\nSorry, I couldn't upload your file to the channel. Please try again later.")
    else:
        send_message(chat_id, "⚠️ <b>Unsupported Content</b>\n\nPlease send a document, photo, video, or audio file to upload.")

    return jsonify({"status": "processed"}), 200

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
"""
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

<b>Note:</b> Large files may take longer to process.
"""
    buttons = [
        {"text": "🔙 Main Menu", "callback_data": "main_menu"},
        {"text": "ℹ️ General Help", "callback_data": "help"}
    ]
    reply_markup = create_inline_keyboard(buttons)
    
    if message_id:
        edit_message_text(chat_id, message_id, instructions, reply_markup)
    else:
        send_message(chat_id, instructions, reply_markup)

# Admin console
@app.route('/admin/console', methods=['GET', 'POST'])
def admin_console():
    if request.method == 'POST':
        # Check for admin authentication
        user_id = request.form.get('user_id')
        if not user_id or int(user_id) not in ADMIN_IDS:
            return jsonify({'output': '⛔ Unauthorized access!'}), 403
            
        command = request.form.get('command')
        output = ""
        
        try:
            # Execute simple Python commands
            if command.startswith('!'):
                # System command
                result = subprocess.run(command[1:], shell=True, capture_output=True, text=True)
                output = result.stdout or result.stderr
            else:
                # Python command
                local_vars = {
                    'app': app,
                    'requests': requests,
                    'uploaded_files': uploaded_files,
                    'ADMIN_IDS': ADMIN_IDS,
                    'TOKEN': TOKEN,
                    'BASE_API_URL': BASE_API_URL,
                    'CHANNEL_USERNAME': CHANNEL_USERNAME
                }
                
                # Try eval first (for expressions)
                try:
                    output = str(eval(command, globals(), local_vars))
                except:
                    # If eval fails, try exec (for statements)
                    try:
                        exec(command, globals(), local_vars)
                        output = "Command executed successfully"
                    except Exception as e:
                        output = f"Error: {str(e)}\n\n{traceback.format_exc()}"
        except Exception as e:
            output = f"Error: {str(e)}\n\n{traceback.format_exc()}"
        
        return jsonify({'output': output})
    
    # Verify admin access
    user_id = request.args.get('user_id')
    if not user_id or int(user_id) not in ADMIN_IDS:
        return "⛔ Unauthorized access!", 403
    
    # HTML for the admin console
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bot Admin Console</title>
        <style>
            body { 
                font-family: 'Courier New', monospace; 
                margin: 0; 
                padding: 20px; 
                background: #1e1e1e; 
                color: #f0f0f0; 
                line-height: 1.5;
            }
            #console { 
                background: #252525; 
                border: 1px solid #444; 
                padding: 15px; 
                height: 70vh; 
                overflow-y: auto;
                margin-bottom: 15px;
                white-space: pre-wrap;
                border-radius: 5px;
                font-size: 14px;
            }
            #command { 
                width: calc(100% - 90px); 
                padding: 10px; 
                background: #333; 
                color: #fff; 
                border: 1px solid #555; 
                font-family: monospace;
                border-radius: 5px;
                font-size: 14px;
            }
            button {
                padding: 10px 15px;
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-family: 'Courier New', monospace;
                margin-left: 5px;
            }
            button:hover {
                background: #45a049;
            }
            .prompt { color: #4CAF50; font-weight: bold; }
            .error { color: #F44336; }
            .output { color: #9E9E9E; }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }
            .title {
                color: #4CAF50;
                font-size: 24px;
                font-weight: bold;
            }
            .info {
                color: #9E9E9E;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">Bot Admin Console</div>
            <div class="info">User ID: {{ user_id }}</div>
        </div>
        <div id="console"></div>
        <form id="cmdForm" onsubmit="sendCommand(); return false;">
            <input type="hidden" id="user_id" value="{{ user_id }}">
            <input type="text" id="command" placeholder="Enter command (Python code or !system command)" autocomplete="off">
            <button type="submit">Execute</button>
        </form>
        
        <script>
            const consoleDiv = document.getElementById('console');
            const commandInput = document.getElementById('command');
            const userId = document.getElementById('user_id').value;
            
            // Add welcome message
            addToConsole('Bot Admin Console - Ready\nType Python commands or prefix system commands with !\n', 'output');
            
            function addToConsole(text, className) {
                const line = document.createElement('div');
                line.className = className;
                line.textContent = text;
                consoleDiv.appendChild(line);
                consoleDiv.scrollTop = consoleDiv.scrollHeight;
            }
            
            function sendCommand() {
                const command = commandInput.value.trim();
                if (!command) return;
                
                addToConsole('>>> ' + command, 'prompt');
                commandInput.value = '';
                
                fetch('/admin/console', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `user_id=${userId}&command=${encodeURIComponent(command)}`
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Unauthorized');
                    }
                    return response.json();
                })
                .then(data => {
                    addToConsole(data.output, 'output');
                })
                .catch(error => {
                    addToConsole('Error: ' + error.message, 'error');
                });
            }
            
            // Focus the command input on page load
            commandInput.focus();
            
            // Handle up arrow for command history
            let commandHistory = [];
            let historyIndex = -1;
            
            commandInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (historyIndex < commandHistory.length - 1) {
                        historyIndex++;
                        commandInput.value = commandHistory[commandHistory.length - 1 - historyIndex];
                    }
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (historyIndex > 0) {
                        historyIndex--;
                        commandInput.value = commandHistory[commandHistory.length - 1 - historyIndex];
                    } else {
                        historyIndex = -1;
                        commandInput.value = '';
                    }
                } else if (e.key === 'Enter') {
                    if (commandInput.value.trim()) {
                        commandHistory.push(commandInput.value.trim());
                        if (commandHistory.length > 50) commandHistory.shift();
                        historyIndex = -1;
                    }
                }
            });
        </script>
    </body>
    </html>
    ''', user_id=user_id)

# Index route
@app.route('/', methods=['GET'])
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram File Uploader Bot</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                color: #333;
                line-height: 1.6;
            }
            h1 {
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }
            .status {
                background-color: #e8f4fc;
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
                transition: background-color 0.3s;
            }
            .btn:hover {
                background-color: #2980b9;
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
    app.run(host="0.0.0.0", port=port, debug=True)
