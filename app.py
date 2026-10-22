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
        data = request.get_json(silent=True) or {}
        form_data = request.form.to_dict() or {}
        args_data = request.args.to_dict() or {}
        
        merged = {**args_data, **form_data, **data}

        order_id = merged.get('ID_I') or merged.get('inv_id') or merged.get('order_id') or '—'
        product_id = merged.get('ID_D') or merged.get('product_id') or merged.get('id_goods') or '—'
        email = merged.get('Email') or merged.get('email') or '—'

        # 1. Запит до Resell.codes за ключем
        issued_code = ""
        try:
            rsc_url = "https://resell.codes/api/v1/order" # Ендпоінт Resell.codes
            headers = {"Authorization": f"Bearer {RESELL_CODES_API_KEY}"}
            payload = {"product_id": product_id, "order_id": order_id}
            
            # Якщо завантажуєте ключі заздалегідь або купуєте авто:
            # response = requests.post(rsc_url, json=payload, headers=headers, timeout=10)
            # if response.status_code == 200:
            #     issued_code = response.json().get("code", "")
        except Exception as err:
            print(f"Помилка закупівлі ключа: {err}")

        # 2. Відправляємо вам сповіщення в Telegram
        msg = (
            f"🛒 <b>НОВЕ ЗАМОВЛЕННЯ!</b>\n\n"
            f"📦 <b>Товар ID:</b> <code>{product_id}</code>\n"
            f"🆔 <b>Замовлення:</b> <code>{order_id}</code>\n"
            f"📧 <b>Покупець:</b> {email}\n"
            f"🔑 <b>Виданий ключ:</b> <code>{issued_code if issued_code else 'Автовидача'}</code>"
        )
        send_telegram(msg)

        # 3. ПОВЕРТАЄМО КЛЮЧ ПОКУПЦЕВІ НА DIGISELLER
        # Digiseller відобразить цей текст покупцеві на сторінці після оплати
        if issued_code:
            return f"Ваш ключ: {issued_code}", 200
        else:
            return "Дякуємо за покупку! Дякуємо за замовлення.", 200

    except Exception as e:
        print(f"Помилка сервера: {e}", flush=True)
        return "ERROR", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
