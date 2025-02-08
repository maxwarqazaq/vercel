import os
import requests
from flask import Flask, Response, request, jsonify

# Получаем токен из переменных окружения
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    raise ValueError("Bot token is not set in environment variables!")

# Создаем Flask приложение
app = Flask(__name__)

def parse_message(message):
    """ Парсим сообщение от Telegram API """
    print("message -->", message)

    if "message" not in message or "text" not in message["message"]:
        return None, None  # Если нет текста, пропускаем

    chat_id = message["message"]["chat"]["id"]
    txt = message["message"]["text"]

    print("chat_id -->", chat_id)
    print("txt -->", txt)

    return chat_id, txt

@app.route('/setwebhook', methods=['POST','GET'])
def setwebhook():
    webhook_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={os.environ.get('VERCEL_URL')}/webhook&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    response = requests.get(webhook_url)
    
    if response.status_code == 200:
        return "Webhook successfully set", 200
    else:
        return f"Error setting webhook: {response.text}", response.status_code
    return "Vercel URL not found", 400


def tel_send_message(chat_id, text):
    """ Отправка сообщения в Telegram """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "Підтвредити", "callback_data": "confirm"},
                {"text": "Скасувати", "callback_data": "cancel"}]
            ]
        }
    }
    response = requests.post(url, json=payload)

    if response.status_code != 200:
        print("Ошибка отправки сообщения:", response.text)

    return response

def delete_message(chat_id, message_id):
    """ Удаление сообщения с кнопками """
 
    url = f"https://api.telegram.org/bot6402853514:AAHM-zoo59uIa4Yfdi4cfFXTmXvX_XnSvLA/deleteMessage?chat_id={chat_id}&message_id={message_id}"
    response = requests.post(url)
    print(f"Удаление сообщения {message_id}: {response.status_code}, {response.text}") 
    if response.status_code != 200:
        print("Ошибка удаления сообщения:", response.text)    

@app.route('/webhook', methods=['POST'])
def webhook():
    """ Обработка входящих сообщений от Telegram API """
    msg = request.get_json()
    print("Получен вебхук:", msg)
    if "callback_query" in msg:
        callback = msg["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        print(f"Нажата кнопка. Удаляю сообщение {message_id} из чата {chat_id}")
        # Удаляем сообщение
        delete_message(chat_id, message_id)

        return jsonify({"status": "deleted"}), 200

    chat_id, txt = parse_message(msg)
    if chat_id is None or txt is None:
        return jsonify({"status": "ignored"}), 200

    if txt.lower() == "hi":
        tel_send_message(chat_id, "Кнопка!!")
    else:
        tel_send_message(chat_id, "Авторизація")

    return Response('ok', status=200)

@app.route("/", methods=['GET'])
def index():
    return "<h1>Telegram Bot Webhook is Running</h1>"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
