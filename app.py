import os
import time
import requests
from flask import Flask, request

app = Flask(__name__)

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
def digiseller_webhook():
    try:
        data = request.get_json(silent=True) or {}
        form_data = request.form.to_dict() or {}
        args_data = request.args.to_dict() or {}
        
        merged = {**args_data, **form_data, **data}
        print(f"INCOMING WEBHOOK DATA: {merged}", flush=True)

        # Ignore empty test pings from Digiseller
        if not merged:
            return "Webhook active / OK", 200

        # Support both uppercase and lowercase keys from Digiseller
        order_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or '—'
        product_id = str(merged.get('ID_D') or merged.get('id_d') or merged.get('product_id') or '—')
        email = merged.get('Email') or merged.get('email') or '—'

        if product_id == '—':
            return "Ignored: No product ID", 200

        # Dynamically read the purchase quantity from Digiseller (defaults to 1)
        raw_qty = merged.get('cnt') or merged.get('quantity') or merged.get('amount') or 1
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
                
                # STEP 1: Check current price and available stock
                cat_url = f"https://resell.codes/api/v1/gift-cards/categories/{mapping['category_id']}/cards"
                cat_resp = requests.get(cat_url, headers=headers, timeout=10)
                
                current_price = 0.0
                available_stock = 0
                if cat_resp.status_code == 200:
                    offers = cat_resp.json().get('offers', [])
                    for offer in offers:
                        if offer.get('card_id') == mapping['card_id']:  # <-- Виправлено дужку тут
                            current_price = float(offer.get('price_usd', 0))
                            available_stock = int(offer.get('stock', 0))
                            break
                
                max_allowed = mapping.get("max_price", 1.05)
                
                # Check if stock is sufficient
                if available_stock < req_quantity:
                    stock_msg = (
                        f"⚠️ <b>STOCK SHORTAGE BLOCK!</b>\n\n"
                        f"📦 <b>Card:</b> <code>{mapping['card_id']}</code>\n"
                        f"📉 <b>Available Stock:</b> {available_stock} pcs.\n"
                        f"🛒 <b>Requested Qty:</b> {req_quantity} pcs.\n"
                        f"🆔 <b>Digiseller Order:</b> <code>{order_id}</code>"
                    )
                    send_telegram(stock_msg)
                    return "Stock short / Not enough items", 200

                # Check max price limit per unit
                if current_price > max_allowed:
                    price_msg = (
                        f"⚠️ <b>PRICE LIMIT EXCEEDED BLOCK!</b>\n\n"
                        f"📦 <b>Card:</b> <code>{mapping['card_id']}</code>\n"
                        f"📈 <b>Current Price:</b> ${current_price}\n"
                        f"🛑 <b>Your Limit:</b> ${max_allowed}\n"
                        f"🆔 <b>Digiseller Order:</b> <code>{order_id}</code>"
                    )
                    send_telegram(price_msg)
                    return "Price exceeds limit", 200

                # STEP 2: Place order for exact quantity via Resell.codes API
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
                        # STEP 3: Poll order status by order number
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
                else:
                    print(f"Resell.codes API Error: {response.text}")
        except Exception as err:
            print(f"Purchase error: {err}")

        final_output_text = "\n".join(issued_codes) if issued_codes else ""

        if final_output_text:
            msg = (
                f"🛒 <b>AUTOMATED ORDER ({req_quantity} pcs.)!</b>\n\n"
                f"📦 <b>Digiseller Product ID:</b> <code>{product_id}</code>\n"
                f"🆔 <b>Digiseller Order:</b> <code>{order_id}</code>\n"
                f"📧 <b>Buyer:</b> {email}\n"
                f"🔑 <b>Issued Codes:</b>\n<code>{final_output_text}</code>"
            )
            send_telegram(msg)
            return final_output_text, 200
        else:
            return "Error issuing codes or insufficient balance.", 200

    except Exception as e:
        print(f"Server error: {e}", flush=True)
        return "ERROR", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
