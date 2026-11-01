import os
import time
import requests
import threading
from flask import Flask, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# --- КОНФІГУРАЦІЯ ---
TELEGRAM_BOT_TOKEN = "8807171182:AAEewfuvrhwHYRE0N3Xc7_IjGUpFsL_TgqY"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"

# --- ЛІМІТИ ЦІН ДЛЯ ЗАКУПІВЛІ ---
MAX_PRICES = {
    "roblox": 1.00,
}

previous_catalog = {}

@app.route('/')
def home():
    return "Bot is running on Render!", 200

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram status: {resp.status_code}, response: {resp.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

# --- ЕНДПОІНТ КАТАЛОГУ (ДІАГНОСТИКА RSC API) ---
@app.route('/catalog', methods=['GET'])
def view_full_catalog_in_telegram():
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        test_url = "https://resell.codes/api/v1/"
        response = requests.get(test_url, headers=headers, timeout=10)
        
        # Очищаємо текст від можливих проблемних символів для HTML-парсера
        safe_text = str(response.text[:300]).replace('<', '&lt;').replace('>', '&gt;')
        
        debug_msg = f"🔍 <b>ДІАГНОСТИКА RSC API:</b>\nСтатус: {response.status_code}\nВідповідь: <code>{safe_text}</code>"
        send_telegram(debug_msg)
            
        return "Diagnostic sent to Telegram!", 200
        
    except Exception as e:
        err_text = f"❌ Помилка: {e}"
        send_telegram(err_text)
        return err_text, 500

# --- ЦИКЛ МОНІТОРИНГУ ---
def check_all_products_loop():
    while True:
        try:
            headers = {
                "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
                "Content-Type": "application/json"
            }
            resp = requests.get("https://resell.codes/api/v1/", headers=headers, timeout=10)
            print(f"Monitor check status: {resp.status_code}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(300)

# --- ВЕБХУК DIGISELLER ---
@app.route('/webhook', methods=['POST', 'GET'])
@app.route('/webhook/', methods=['POST', 'GET'])
def digiseller_webhook():
    try:
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True, force=True) or {}
        values_data = request.values.to_dict()
        
        merged = {**args_data, **form_data, **json_data, **values_data}

        order_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or merged.get('inv') or 'manual_check'
        product_id = str(merged.get('ID_D') or merged.get('id_d') or merged.get('id_goods') or merged.get('goods_id') or merged.get('product_id') or '6223586')

        if product_id == '—':
            product_id = '6223586'

        raw_qty = merged.get('cnt') or merged.get('quantity') or merged.get('amount') or merged.get('qty') or 1
        try:
            req_quantity = int(raw_qty)
        except ValueError:
            req_quantity = 1

        issued_codes = []
        
        try:
            headers = {
                "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
                "Content-Type": "application/json"
            }
            
            rsc_url = "https://resell.codes/api/v1/orders"
            payload = {
                "sku": "roblox-gift-card-50-robux",
                "quantity": req_quantity
            }
            
            response = requests.post(rsc_url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                resp_data = response.json()
                codes = resp_data.get('codes', []) or resp_data.get('keys', [])
                if codes:
                    issued_codes = codes
            else:
                send_telegram(f"❌ <b>Помилка API:</b> {response.text}")
        except Exception as err:
            print(f"Purchase error: {err}")

        final_output_text = "\n".join(issued_codes) if issued_codes else ""

        if final_output_text:
            msg = (
                f"🛒 <b>УСПІШНЕ ЗАМОВЛЕННЯ!</b>\n\n"
                f"📦 <b>ID товару:</b> <code>{product_id}</code>\n"
                f"🆔 <b>Замовлення:</b> <code>{order_id}</code>\n"
                f"🔑 <b>Ключі:</b>\n<code>{final_output_text}</code>"
            )
            send_telegram(msg)
            return final_output_text, 200
        else:
            send_telegram(f"❌ <b>ПОМИЛКА ВИДАЧІ КЛЮЧА!</b> Товар: {product_id}")
            return "Error issuing codes.", 200

    except Exception as e:
        print(f"Server error: {e}", flush=True)
        return "ERROR", 500

if __name__ == '__main__':
    monitor_thread = threading.Thread(target=check_all_products_loop, daemon=True)
    monitor_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)



















