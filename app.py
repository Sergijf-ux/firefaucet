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

# --- ІНДИВІДУАЛЬНІ ЛІМІТИ ЗАКУПІВЛІ ДЛЯ КОЖНОГО ТОВАРУ ---
# Ключ — це card_id або унікальна назва, значення — максимальна ціна закупівлі у USD
MAX_PRICES = {
    "50_robux": 1.00,    # Купуємо 50 Robux тільки якщо закупка нижча за $1.00
    "100_robux": 1.95,   # Приклад для 100 Robux (коли повернеться)
    # Для інших товарів, які не знайдені в словнику, спрацює дефолтний ліміт $1.00
}

# Словник для фонового моніторингу змін
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

# --- ЕНДПОІНТ ДЛЯ ПЕРЕГЛЯДУ ВСЬОГО КАТАЛОГУ В ТЕЛЕГРАМ ---
@app.route('/catalog', methods=['GET'])
def view_full_catalog_in_telegram():
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        cat_list_url = "https://resell.codes/api/v1/gift-cards/categories"
        cat_resp = requests.get(cat_list_url, headers=headers, timeout=10)
        
        if cat_resp.status_code != 200:
            return "Error fetching categories from RSC", 500
            
        categories = cat_resp.json().get('categories', []) or cat_resp.json().get('data', []) or cat_resp.json()
        report_lines = ["📋 <b>АКТУАЛЬНИЙ КАТАЛОГ RESELL.CODES</b>\n"]
        
        for cat in categories:
            cat_id = cat.get('id') or cat.get('slug')
            cat_name = cat.get('name', 'Category')
            if not cat_id:
                continue
                
            cards_url = f"https://resell.codes/api/v1/gift-cards/categories/{cat_id}/cards"
            cards_resp = requests.get(cards_url, headers=headers, timeout=10)
            if cards_resp.status_code == 200:
                offers = cards_resp.json().get('offers', []) or cards_resp.json().get('cards', [])
                if offers:
                    report_lines.append(f"📂 <b>{cat_name}</b>")
                    for offer in offers:
                        title = offer.get('title', 'Unknown')
                        price = offer.get('price', '—')
                        stock = offer.get('stock', '—')
                        card_id = offer.get('card_id') or offer.get('id')
                        report_lines.append(f"  ▪️ {title} (ID: <code>{card_id}</code>)\n     Ціна: <b>${price}</b> | Залишок: <b>{stock}</b>")
                    report_lines.append("")

        full_message = "\n".join(report_lines)
        
        # Якщо повідомлення занадто довге для Telegram, розбиваємо або відправляємо як є
        if len(full_message) > 4000:
            chunks = [full_message[i:i+4000] for i in range(0, len(full_message), 4000)]
            for chunk in chunks:
                send_telegram(chunk)
        else:
            send_telegram(full_message)
            
        return "Catalog successfully sent to your Telegram!", 200
        
    except Exception as e:
        err_text = f"Error generating catalog: {e}"
        print(err_text)
        return err_text, 500

# Фоновий моніторинг змін цін
def check_all_products_loop():
    global previous_catalog
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json"
    }
    while True:
        try:
            cat_list_url = "https://resell.codes/api/v1/gift-cards/categories"
            cat_resp = requests.get(cat_list_url, headers=headers, timeout=10)
            
            if cat_resp.status_code == 200:
                categories = cat_resp.json().get('categories', []) or cat_resp.json().get('data', []) or cat_resp.json()
                for cat in categories:
                    cat_id = cat.get('id') or cat.get('slug')
                    if not cat_id:
                        continue
                    
                    cards_url = f"https://resell.codes/api/v1/gift-cards/categories/{cat_id}/cards"
                    cards_resp = requests.get(cards_url, headers=headers, timeout=10)
                    if cards_resp.status_code == 200:
                        offers = cards_resp.json().get('offers', []) or cards_resp.json().get('cards', [])
                        for offer in offers:
                            item_id = str(offer.get('card_id') or offer.get('id'))
                            title = offer.get('title', 'Unknown')
                            price = offer.get('price')
                            stock = offer.get('stock')
                            
                            if price is None:
                                continue
                                
                            if item_id not in previous_catalog:
                                previous_catalog[item_id] = {"price": price, "stock": stock, "title": title}
                                continue
                            
                            old = previous_catalog[item_id]
                            
                            if old["price"] != price:
                                diff = round(price - old["price"], 4)
                                sign = "+" if diff > 0 else ""
                                alert_msg = (
                                    f"🚨 <b>ЗМІНА ЦІНИ НА RSC!</b>\n"
                                    f"📦 <b>Товар:</b> {title}\n"
                                    f"💰 <b>Стара ціна:</b> ${old['price']} ➡️ <b>Нова:</b> ${price} ({sign}{diff}$)"
                                )
                                send_telegram(alert_msg)
                                old["price"] = price
                                
                            if old["stock"] != stock:
                                alert_msg = (
                                    f"📦 <b>ЗМІНА ЗАЛИШКУ НА RSC!</b>\n"
                                    f"🏷 <b>Товар:</b> {title}\n"
                                    f"📊 <b>Було:</b> {old['stock']} ➡️ <b>Стало:</b> {stock}"
                                )
                                send_telegram(alert_msg)
                                old["stock"] = stock
        except Exception as e:
            print(f"Monitor loop error: {e}")
            
        time.sleep(300)

@app.route('/webhook', methods=['POST', 'GET'])
@app.route('/webhook/', methods=['POST', 'GET'])
def digiseller_webhook():
    try:
        raw_body = request.get_data(as_text=True)
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True, force=True) or {}
        values_data = request.values.to_dict()
        
        merged = {**args_data, **form_data, **json_data, **values_data}

        order_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or merged.get('inv') or 'manual_check'
        product_id = str(merged.get('ID_D') or merged.get('id_d') or merged.get('id_goods') or merged.get('goods_id') or merged.get('product_id') or '6223586')
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
            headers = {
                "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
                "Content-Type": "application/json"
            }
            
            cat_list_url = "https://resell.codes/api/v1/gift-cards/categories"
            cat_resp = requests.get(cat_list_url, headers=headers, timeout=10)
            
            target_category = None
            target_card_id = None
            current_card_price = None
            
            if cat_resp.status_code == 200:
                categories = cat_resp.json().get('categories', []) or cat_resp.json().get('data', []) or cat_resp.json()
                for cat in categories:
                    cat_name = str(cat.get('name', '')).lower()
                    cat_slug = str(cat.get('slug', '')).lower()
                    cat_id = cat.get('id') or cat.get('category_id')
                    
                    if 'roblox' in cat_name or 'roblox' in cat_slug or str(cat_id) == 'roblox':
                        target_category = cat_id or cat_slug
                        
                        cards_url = f"https://resell.codes/api/v1/gift-cards/categories/{target_category}/cards"
                        cards_resp = requests.get(cards_url, headers=headers, timeout=10)
                        if cards_resp.status_code == 200:
                            offers = cards_resp.json().get('offers', []) or cards_resp.json().get('cards', [])
                            for offer in offers:
                                offer_title = str(offer.get('title', '')).lower()
                                offer_card_id = offer.get('card_id') or offer.get('id')
                                if '50' in offer_title and 'robux' in offer_title:
                                    target_card_id = offer_card_id
                                    current_card_price = offer.get('price')
                                    break
                        break
            
            if not target_category:
                target_category = "roblox"
            if not target_card_id:
                target_card_id = "50_robux"

            print(f"Dynamic API Resolved -> Category: {target_category}, Card: {target_card_id}, Price: {current_card_price}", flush=True)

            # --- ІНДИВІДУАЛЬНИЙ ЗАХИСТ ЦІНИ ДЛЯ ЦЬОГО ТОВАРУ ---
            allowed_max_price = MAX_PRICES.get(str(target_card_id), 1.00) # Дефолт $1.00 якщо немає в словнику
            
            if current_card_price is not None and current_card_price > allowed_max_price:
                error_msg = (
                    f"❌ <b>ЗАХИСТ СПРАЦЬОВАВ:</b> Товар <code>{target_card_id}</code>\n"
                    f"💰 Ціна на RSC (${current_card_price}) вища за ваш ліміт (${allowed_max_price}). "
                    f"Закупка заблокована!"
                )
                send_telegram(error_msg)
                return "Error: Price is too high for this item, order paused.", 200

            rsc_url = "https://resell.codes/api/v1/gift-cards/order"
            payload = {
                "category_id": target_category,
                "card_id": target_card_id,
                "quantity": req_quantity
            }
            
            response = requests.post(rsc_url, json=payload, headers=headers, timeout=15)
            print(f"Resell.codes Response Status: {response.status_code}, Body: {response.text}", flush=True)
            
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
    monitor_thread = threading.Thread(target=check_all_products_loop, daemon=True)
    monitor_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)





















