import os
import time
import requests
from flask import Flask, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8807171182:AAEewfuvrhwHYRE0N3Xc7_IjGUpFsL_TgqY"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"

# Product mapping and price limit (max_price per 1 unit)
PRODUCT_MAPPING = {
    "6223586": {
        "category_id": "roblox",
        "card_id": "50_robux",
        "max_price": 0.95  # Max price limit per 1 unit
    }
}

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

@app.route('/webhook', methods=['POST', 'GET'])
@app.route('/webhook/', methods=['POST', 'GET'])
def digiseller_webhook():
    try:
        raw_body = request.get_data(as_text=True)
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True, force=True) or {}
        values_data = request.values.to_dict()
        
        print(f"--- RAW WEBHOOK START ---", flush=True)
        print(f"RAW BODY: {raw_body}", flush=True)
        print(f"ARGS: {args_data}", flush=True)
        print(f"FORM: {form_data}", flush=True)
        print(f"JSON: {json_data}", flush=True)
        print(f"--- RAW WEBHOOK END ---", flush=True)
        
        merged = {**args_data, **form_data, **json_data, **values_data}

        order_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or merged.get('inv') or 'manual_check'
        product_id = str(merged.get('ID_D') or merged.get('id_d') or merged.get('id_goods') or merged.get('goods_id') or merged.get('product_id') or '—')
        email = merged.get('Email') or merged.get('email') or '—'

        if product_id == '—':
            product_id = '6223586'

        raw_qty = merged.get('cnt') or merged.get('quantity') or merged.get('amount') or merged.get('qty') or 1
        try:
            req_quantity = int(raw_qty)
        except ValueError:
            req_quantity = 1

        issued_codes = []
        
        try:
            mapping = PRODUCT_MAPPING.get(product_id)
            if not mapping:
                print(f"Error: No mapping found for Digiseller product ID {product_id}!")
            else:
                headers = {
                    "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                cat_url = f"https://resell.codes/api/v1/gift-cards/categories/{mapping['category_id']}/cards"
                cat_resp = requests.get(cat_url, headers=headers, timeout=10)
                
                current_price = 0.0
                available_stock = 0
                if cat_resp.status_code == 200:
                    offers = cat_resp.json().get('offers', [])
                    for offer in offers:
                        if offer.get('card_id') == mapping['card_id']:  # Виправлено дужку
                            current_price = float(offer.get('price_usd', 0))
                            available_stock = int(offer.get('stock', 0))
                            break
                
                max_allowed = mapping.get("max_price", 0.95)
                
                if available_stock < req_quantity:
                    send_telegram(f"⚠️ <b>STOCK SHORTAGE!</b> Order: {order_id}")
                    return "Stock short", 200

                if current_price > max_allowed:
                    send_telegram(f"⚠️ <b>PRICE EXCEEDED!</b> Price: {current_price}")
                    return "Price exceeds limit", 200

                rsc_url = "https://resell.codes/api/v1/gift-cards/order"
                payload = {
                    "category_id": mapping["category_id"],
                    "card_id": mapping["card_id"],
                    "quantity": req_quantity
                }
                
                response = requests.post(rsc_url, json=payload, headers=headers, timeout=15)
                if response.status_code == 200:
                    resp_data = response.json()
                    rsc_order_number = resp_data.get('number')
                    
                    codes = resp_data.get('codes', []) or resp_data.get('keys', [])
                    if codes:
                        issued_codes = codes
                    elif rsc_order_number:
                        for _ in range(6):
                            time.sleep(3)
                            status_url = f"https://resell.codes/api/v1/orders/{rsc_order_number}"
                            status_resp = requests.get(status_url, headers=headers, timeout=10)
                            if status_resp.status_code == 200:
                                order_data = status_resp.json()
                                fetched_codes = order_data.get('codes', []) or order_data.get('keys', [])
                                if fetched_codes:
                                    issued_codes = fetched_codes
                                    break
                                if order_data.get('status') == 'completed':
                                    break
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























