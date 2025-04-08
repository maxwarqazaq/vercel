import os
import requests
from flask import Flask, Response, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import asyncio

# Get tokens from environment variables
TOKEN = os.getenv('TOKEN')
BOT_TOKEN = os.getenv('BOT_TOKEN') or '7135940302:AAFYWRjjhEnQ0_1ScjXtmLsS3gXxPvHr9Dk'
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME') or '@cdntelegraph'

if not TOKEN or not BOT_TOKEN:
    raise ValueError("Bot tokens are not set in environment variables!")

# Create Flask app
app = Flask(__name__)

# Dictionary to track files uploaded by the bot
uploaded_files = {}

# Telegram bot application (will be initialized later)
application = None

@app.route('/setwebhook', methods=['POST','GET'])
def setwebhook():
    webhook_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={os.environ.get('VERCEL_URL')}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    response = requests.get(webhook_url)
    
    if response.status_code == 200:
        return "Webhook successfully set", 200
    else:
        return f"Error setting webhook: {response.text}", response.status_code
    return "Vercel URL not found", 400

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads to Telegram channel"""
    try:
        # Check file type
        if update.message.document:
            file = update.message.document
        elif update.message.photo:
            file = update.message.photo[-1]  # Largest size
        elif update.message.video:
            file = update.message.video
        elif update.message.audio:
            file = update.message.audio
        else:
            await update.message.reply_text("Please send a valid file (document, photo, video, or audio).")
            return

        file_id = file.file_id

        # Send file to channel
        if update.message.document:
            sent_message = await context.bot.send_document(chat_id=CHANNEL_USERNAME, document=file_id)
        elif update.message.photo:
            sent_message = await context.bot.send_photo(chat_id=CHANNEL_USERNAME, photo=file_id)
        elif update.message.video:
            sent_message = await context.bot.send_video(chat_id=CHANNEL_USERNAME, video=file_id)
        elif update.message.audio:
            sent_message = await context.bot.send_audio(chat_id=CHANNEL_USERNAME, audio=file_id)

        # Generate public URL
        channel_message_id = sent_message.message_id
        channel_url = f"https://t.me/{CHANNEL_USERNAME[1:]}/{channel_message_id}"

        # Store file info
        uploaded_files[channel_message_id] = {
            "file_id": file_id,
            "file_type": "document" if update.message.document else
                         "photo" if update.message.photo else
                         "video" if update.message.video else
                         "audio",
            "user_id": update.message.from_user.id
        }

        # Send URL with delete button
        keyboard = [
            [InlineKeyboardButton("Delete File", callback_data=f"delete_{channel_message_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"File uploaded to the channel! Here's the URL:\n{channel_url}", reply_markup=reply_markup)

    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")

async def handle_file_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file deletion from channel"""
    query = update.callback_query
    await query.answer()

    channel_message_id = int(query.data.split("_")[1])

    if channel_message_id in uploaded_files and uploaded_files[channel_message_id]["user_id"] == query.from_user.id:
        try:
            await context.bot.delete_message(chat_id=CHANNEL_USERNAME, message_id=channel_message_id)
            del uploaded_files[channel_message_id]
            await query.edit_message_text("File successfully deleted!")
        except Exception as e:
            await query.edit_message_text(f"Failed to delete the file: {e}")
    else:
        await query.edit_message_text("You do not have permission to delete this file or it no longer exists.")

async def initialize_bot():
    """Initialize the Telegram bot handlers"""
    global application
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add file handler
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO, handle_file_upload))

    # Add callback query handler for delete button
    application.add_handler(CallbackQueryHandler(handle_file_deletion))

    await application.initialize()
    await application.start()
    print("Bot handlers initialized successfully")

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates"""
    if request.headers.get('content-type') == 'application/json':
        update_data = request.get_json()
        
        # Initialize bot if not already done
        if application is None:
            await initialize_bot()
        
        # Create Update object from webhook data
        update = Update.de_json(update_data, application.bot)
        
        # Process the update
        await application.process_update(update)
        
        return jsonify({"status": "processed"}), 200
    return jsonify({"status": "invalid content-type"}), 400

@app.route("/", methods=['GET'])
def index():
    return "<h1>Telegram File Upload Bot is Running</h1>"

if __name__ == '__main__':
    # Initialize the bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(initialize_bot())
    
    # Run the Flask app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
