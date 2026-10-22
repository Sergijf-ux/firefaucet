import os
import requests
from flask import Flask, request

app = Flask(__name__)

# --- НАЛАШТУВАННЯ ---
TELEGRAM_BOT_TOKEN = "8807171182:AAEewfuvrhwHYRE0N3Xc7_IjGUpFsL_TgqY"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"

@app.route('/')
def home():
    return "Bot is running on Render!", 200

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Помилка Telegram: {e}")

@app.route('/webhook', methods=['POST', 'GET'])
def digiseller_webhook():
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict() or {}
        print(f"INCOMING WEBHOOK: {data}", flush=True)

        order_id = data.get('inv_id', data.get('order_id', '—'))
        product_id = str(data.get('product_id', data.get('id_goods', '—')))
        email = data.get('email', data.get('buyer_email', '—'))
        unique_code = data.get('uniquecode', data.get('unique_code', '—'))

        msg = (
            f"🛒 <b>ОТРИМАНО НОВЕ ЗАМОВЛЕННЯ!</b>\n\n"
            f"📦 <b>Товар ID:</b> <code>{product_id}</code>\n"
            f"🆔 <b>Замовлення:</b> <code>{order_id}</code>\n"
            f"📧 <b>Покупець:</b> {email}\n"
            f"🔑 <b>Унікальний код:</b> <code>{unique_code}</code>"
        )
        send_telegram(msg)

    except Exception as e:
        print(f"Помилка: {e}", flush=True)

    return 'YES', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
