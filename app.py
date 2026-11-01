import os
import time
import requests
import threading
from flask import Flask, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8807171182:AAEewfuvrhwHYRE0N3Xc7_IjGUpFsL_TgqY"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"

# --- PURCHASE PRICE LIMITS ---
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
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

# --- CATALOG ENDPOINT (FIXED 404) ---
@app.route('/catalog', methods=['GET'])
def view_full_catalog_in_telegram():
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        # Проверяем возможные рабочие эндпоинты каталога RSC API
        urls_to_try = [
            "https://resell.codes/api/v1/products",
            "https://resell.codes/api/v1/catalog",
            "https://resell.codes/api/v1/gift-cards"
        ]
        
        response = None
        for url in urls_to_try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                response = resp
                break
                
        if not response or response.status_code != 200:
            send_telegram("❌ Error fetching catalog: 404 (Endpoints not found)")
            return "Error fetching catalog: 404", 500
            
        data = response.json()
        offers = data.get('products', []) or data.get('catalog', []) or data.get('items', []) or data.get('cards', []) or data.get('data', []) or data
        
        if not isinstance(offers, list):
            offers = [offers]

        if not offers:
            send_telegram("⚠️ Catalog is empty.")
            return "Catalog is empty", 200

        catalog_msg = "📂 <b>CURRENT RSC CATALOG:</b>\n\n"
        for offer in offers:
            title = offer.get('title') or offer.get('name') or 'Unknown'
            price = offer.get('price', '—')
            stock = offer.get('stock', '—')
            card_id = offer.get('sku') or offer.get('card_id') or offer.get('id')
            
            line = f"▪️ {title}\n   SKU/ID: <code>{card_id}</code>\n   Price: <b>${price}</b> | Stock: <b>${stock}</b>\n\n"
            
            if len(catalog_msg) + len(line) > 4000:
                send_telegram(catalog_msg)
                catalog_msg = ""
            
            catalog_msg += line
            
        if catalog_msg:
            send_telegram(catalog_msg)
            
        return "Catalog successfully sent to your Telegram!", 200
        
    except Exception as e:
        err_text = f"❌ Error: {e}"
        send_telegram(err_text)
        return err_text, 500

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
            
            # Официальный метод покупки по SKU согласно документации RSC
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
                send_telegram(f"❌ <b>API Error:</b> {response.text}")
        except Exception as err:
            print(f"Purchase error: {err}")

        final_output_text = "\n".join(issued_codes) if issued_codes else ""

        if final_output_text:
            msg = (
                f"🛒 <b>SUCCESS ORDER!</b>\n\n"
                f"📦 <b>Product ID:</b> <code>{product_id}</code>\n"
                f"🆔 <b>Order:</b> <code>{order_id}</code>\n"
                f"🔑 <b>Keys:</b>\n<code>{final_output_text}</code>"
            )
            send_telegram(msg)
            return final_output_text, 200
        else:
            send_telegram(f"❌ <b>FAILED TO ISSUE KEY!</b> Product: {product_id}")
            return "Error issuing codes.", 200

    except Exception as e:
        print(f"Server error: {e}", flush=True)
        return "ERROR", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)



















