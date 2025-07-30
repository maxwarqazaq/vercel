import os
import json
import hashlib
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string
from werkzeug.utils import secure_filename
import requests
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import threading

app = Flask(__name__)

# Configuration
API_KEY = os.environ.get('ADMIN_API_KEY', '2154841a3ff6edf16371271e42604f4be60e6a45cf3b9391bbf1126d5d9b83e0')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7881373466:AAE1rR7Ka119zDC2wOFDF4ArNUVdzSLjs10')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')  # Set this in Vercel env vars

# File storage (using temp directory for Vercel)
UPLOAD_FOLDER = tempfile.gettempdir()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# File metadata storage (in memory for demo, use database in production)
file_metadata = {}

def generate_file_id():
    """Generate unique file ID"""
    return hashlib.md5(f"{datetime.now().timestamp()}".encode()).hexdigest()[:12]

def get_file_info(filename):
    """Get file information"""
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        stat = os.stat(filepath)
        return {
            'name': filename,
            'size': stat.st_size,
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    return None

def list_files():
    """List all files in upload directory"""
    files = []
    for filename in os.listdir(UPLOAD_FOLDER):
        if os.path.isfile(os.path.join(UPLOAD_FOLDER, filename)):
            file_info = get_file_info(filename)
            if file_info:
                files.append(file_info)
    return files

# API Key Middleware
def require_api_key(f):
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        
        key = auth_header.split(' ')[1]
        if key != API_KEY:
            return jsonify({'error': 'Invalid API key'}), 403
        
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# API Endpoints
@app.route('/api/upload', methods=['POST'])
@require_api_key
def upload_file():
    try:
        if 'fileuploader' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['fileuploader']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)
        
        # Store metadata
        file_metadata[unique_filename] = get_file_info(unique_filename)
        
        download_url = f"{request.host_url.rstrip('/')}/api/files/{unique_filename}"
        
        return jsonify({
            'success': True,
            'downloadUrl': download_url,
            'fileName': unique_filename,
            'fileInfo': file_metadata[unique_filename]
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files', methods=['GET'])
@require_api_key
def list_files_api():
    try:
        files = list_files()
        return jsonify({
            'success': True,
            'files': [f['name'] for f in files],
            'fileDetails': files
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<filename>', methods=['GET'])
@require_api_key
def download_file(filename):
    try:
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(filepath, as_attachment=True)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<filename>', methods=['DELETE'])
@require_api_key
def delete_file(filename):
    try:
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        os.remove(filepath)
        
        # Remove from metadata
        if filename in file_metadata:
            del file_metadata[filename]
        
        return jsonify({'success': True, 'message': 'File deleted'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/info/<filename>', methods=['GET'])
@require_api_key
def file_info_api(filename):
    try:
        file_info = get_file_info(filename)
        if not file_info:
            return jsonify({'error': 'File not found'}), 404
        
        return jsonify({
            'success': True,
            'fileInfo': file_info
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
@require_api_key
def storage_stats():
    try:
        files = list_files()
        total_files = len(files)
        total_size = sum(f['size'] for f in files)
        
        return jsonify({
            'success': True,
            'stats': {
                'totalFiles': total_files,
                'totalSize': total_size,
                'totalSizeMB': round(total_size / (1024 * 1024), 2)
            }
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Telegram Bot Webhook
@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    try:
        if not WEBHOOK_URL:
            return jsonify({'error': 'WEBHOOK_URL not configured'}), 400
        
        bot = Bot(token=BOT_TOKEN)
        result = bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        
        return jsonify({
            'success': True,
            'webhook_set': result,
            'webhook_url': f"{WEBHOOK_URL}/webhook"
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(), bot=Bot(token=BOT_TOKEN))
        
        # Process update in background
        threading.Thread(target=process_update, args=(update,)).start()
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def process_update(update):
    """Process Telegram update"""
    try:
        # Handle different types of updates
        if update.message:
            handle_message(update.message)
        elif update.callback_query:
            handle_callback_query(update.callback_query)
    
    except Exception as e:
        print(f"Error processing update: {e}")

def handle_message(message):
    """Handle incoming messages"""
    try:
        text = message.text or ""
        chat_id = message.chat_id
        
        if text.startswith('/start'):
            send_response(chat_id, "🤖 Welcome to File Share Bot!\n\nSend me a file to upload, or use:\n/list - List all files\n/info <filename> - Get file info\n/stats - Storage statistics")
        
        elif text.startswith('/list'):
            files = list_files()
            if not files:
                send_response(chat_id, "📁 No files found.")
            else:
                file_list = "\n".join([f"{i+1}. {f['name']}" for i, f in enumerate(files[:10])])
                if len(files) > 10:
                    file_list += f"\n... and {len(files) - 10} more files"
                send_response(chat_id, f"📁 Files:\n{file_list}")
        
        elif text.startswith('/info'):
            parts = text.split()
            if len(parts) < 2:
                send_response(chat_id, "Usage: /info <filename>")
                return
            
            filename = parts[1]
            file_info = get_file_info(filename)
            if file_info:
                size_mb = round(file_info['size'] / (1024 * 1024), 2)
                response = f"📄 File: {file_info['name']}\n"
                response += f"📏 Size: {size_mb} MB\n"
                response += f"📅 Created: {file_info['created']}"
                send_response(chat_id, response)
            else:
                send_response(chat_id, "❌ File not found.")
        
        elif text.startswith('/stats'):
            files = list_files()
            total_files = len(files)
            total_size = sum(f['size'] for f in files)
            total_size_mb = round(total_size / (1024 * 1024), 2)
            
            response = f"📊 Storage Statistics:\n"
            response += f"📁 Total Files: {total_files}\n"
            response += f"💾 Total Size: {total_size_mb} MB"
            send_response(chat_id, response)
        
        # Handle file uploads
        elif message.document:
            handle_file_upload(message)
        
        elif message.photo:
            handle_photo_upload(message)
    
    except Exception as e:
        send_response(chat_id, f"❌ Error: {str(e)}")

def handle_file_upload(message):
    """Handle file upload"""
    try:
        chat_id = message.chat_id
        document = message.document
        
        # Download file
        file_info = document.get_file()
        file_bytes = file_info.download_as_bytearray()
        
        # Upload to API
        files = {'fileuploader': (document.file_name, file_bytes)}
        headers = {'Authorization': f'Bearer {API_KEY}'}
        
        response = requests.post(f"{request.host_url.rstrip('/')}/api/upload", 
                               files=files, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            send_response(chat_id, f"✅ File uploaded successfully!\n📄 Name: {data['fileName']}\n🔗 Download: {data['downloadUrl']}")
        else:
            send_response(chat_id, f"❌ Upload failed: {response.text}")
    
    except Exception as e:
        send_response(chat_id, f"❌ Upload error: {str(e)}")

def handle_photo_upload(message):
    """Handle photo upload"""
    try:
        chat_id = message.chat_id
        photo = message.photo[-1]  # Get highest quality photo
        
        # Download photo
        file_info = photo.get_file()
        file_bytes = file_info.download_as_bytearray()
        
        # Upload to API
        filename = f"photo_{photo.file_id}.jpg"
        files = {'fileuploader': (filename, file_bytes)}
        headers = {'Authorization': f'Bearer {API_KEY}'}
        
        response = requests.post(f"{request.host_url.rstrip('/')}/api/upload", 
                               files=files, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            send_response(chat_id, f"✅ Photo uploaded successfully!\n📸 Name: {data['fileName']}\n🔗 Download: {data['downloadUrl']}")
        else:
            send_response(chat_id, f"❌ Upload failed: {response.text}")
    
    except Exception as e:
        send_response(chat_id, f"❌ Upload error: {str(e)}")

def send_response(chat_id, text):
    """Send response to Telegram chat"""
    try:
        bot = Bot(token=BOT_TOKEN)
        bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"Error sending message: {e}")

def handle_callback_query(callback_query):
    """Handle callback queries from inline keyboards"""
    try:
        # Handle button clicks
        pass
    except Exception as e:
        print(f"Error handling callback query: {e}")

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'files_count': len(list_files())
    })

# Main route
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'message': 'File Share API',
        'endpoints': {
            'upload': '/api/upload',
            'list': '/api/files',
            'download': '/api/files/<filename>',
            'delete': '/api/files/<filename> (DELETE)',
            'info': '/api/info/<filename>',
            'stats': '/api/stats',
            'webhook': '/webhook',
            'setwebhook': '/setwebhook'
        }
    })

if __name__ == '__main__':
    app.run(debug=True) 
