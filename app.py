import os
import time
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "9030923274:AAHoLPCafZSZ-WrTi6kZr1vEDQtrjueNgPg"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"
DIGISELLER_API_TOKEN = "A5CD7AE74E4846308F30A692510B6F9D"
RSC_BASE_URL = "https://resell.codes/api/v1"

ALLOWED_PRODUCT_IDS = [
    "6375625",
    "6370800",
    "6359892",
]

RENDER_APP_URL = "https://digiseller-bot-2z5g.onrender.com"

def send_telegram(text):
    """Надсилає сповіщення адміністратору в Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

def setup_telegram_webhook():
    """Автоматично реєструє вебхук для команд бота в Telegram."""
    try:
        webhook_url = f"{RENDER_APP_URL}/telegram-webhook"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={webhook_url}"
        requests.get(url, timeout=10)
    except Exception as e:
        print(f"Auto-setup webhook error: {e}", flush=True)

def verify_digiseller_unique_code(unique_code):
    """Перевіряє унікальний код через API Digiseller (info)."""
    url = "https://api.digiseller.com/api/v2/seller/uniques/info"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    params = {
        "token": DIGISELLER_API_TOKEN,
        "code": unique_code
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json(), None
        return None, f"HTTP {response.status_code}: {response.text}"
    except Exception as e:
        return None, f"Connection error: {e}"

def set_digiseller_code_delivered(unique_code):
    """Переводить статус унікального коду в «товар доставлен» (sold)."""
    url = "https://api.digiseller.com/api/v2/seller/uniques/sold"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "token": DIGISELLER_API_TOKEN,
        "code": unique_code
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return True, None
        return False, f"HTTP {response.status_code}: {response.text}"
    except Exception as e:
        return False, f"Connection error: {e}"

def get_rsc_telegram_stars_pricing():
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(f"{RSC_BASE_URL}/telegram/stars", headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Failed to fetch telegram stars pricing: {e}", flush=True)
    return None

def get_rsc_telegram_premium_pricing():
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(f"{RSC_BASE_URL}/telegram/premium", headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Failed to fetch telegram premium pricing: {e}", flush=True)
    return None

def get_rsc_gift_cards_catalog(category_id):
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(f"{RSC_BASE_URL}/gift-cards/categories/{category_id}/cards", headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", data)
    except Exception as e:
        print(f"Failed to fetch gift cards catalog for {category_id}: {e}", flush=True)
    return None

def execute_rsc_purchase(product_type, id_1, id_2, quantity=1, extra_data=None):
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    if product_type == "game_key":
        order_url = f"{RSC_BASE_URL}/game-keys/order"
        payload = {"game_id": id_1, "key_id": id_2, "quantity": quantity}
        codes_key = "keys"
    elif product_type == "gift_card":
        order_url = f"{RSC_BASE_URL}/gift-cards/order"
        payload = {"category_id": id_1, "card_id": id_2, "quantity": quantity}
        codes_key = "codes"
    else:
        return None, "Unknown product type"

    try:
        response = requests.post(order_url, json=payload, headers=headers, timeout=15)
        res_data = response.json()
    except Exception as e:
        return None, f"Connection error during order: {e}"

    if response.status_code != 200:
        err_msg = res_data.get("error", {}).get("message", response.text)
        return None, f"API error (HTTP {response.status_code}): {err_msg}"

    order_number = res_data.get("number")
    if not order_number:
        return None, "RSC server did not return an order number (number)"

    poll_url = f"{RSC_BASE_URL}/orders/{order_number}"
    max_attempts = 40
    
    for _ in range(max_attempts):
        time.sleep(3)
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=10)
            poll_data = poll_resp.json()
        except Exception:
            continue

        status = poll_data.get("status")
        if status == "completed":
            items = poll_data.get(codes_key, [])
            if items:
                return "\n".join(items), None
            return None, "Order completed, but the items list is empty"
        if status in ["failed", "refund"]:
            fail_reason = poll_data.get("fail_code", "unknown_fail")
            reason_text = poll_data.get("status_reason", "")
            return None, f"Order canceled/refunded. Reason: {fail_reason} ({reason_text})"

    return None, "Order execution timeout (Polling timeout)"

def execute_rsc_telegram_stars_order(username, quantity):
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "telegram_username": username,
        "quantity": int(quantity)
    }
    try:
        response = requests.post(f"{RSC_BASE_URL}/telegram/stars/buy", json=payload, headers=headers, timeout=15)
        res_data = response.json()
    except Exception as e:
        return None, f"Connection error during stars order: {e}"

    if response.status_code != 200:
        err_msg = res_data.get("error", {}).get("message", response.text)
        return None, f"API error (HTTP {response.status_code}): {err_msg}"

    order_number = res_data.get("number")
    if not order_number:
        return None, "RSC server did not return an order number (number)"

    poll_url = f"{RSC_BASE_URL}/orders/{order_number}"
    for _ in range(40):
        time.sleep(3)
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=10)
            poll_data = poll_resp.json()
        except Exception:
            continue

        status = poll_data.get("status")
        if status == "completed":
            return f"Order #{order_number} completed successfully for @{username} ({quantity} Stars)", None
        if status in ["failed", "refund"]:
            fail_reason = poll_data.get("fail_code", "unknown_fail")
            reason_text = poll_data.get("status_reason", "")
            return None, f"Order canceled/refunded. Reason: {fail_reason} ({reason_text})"

    return None, "Order execution timeout (Polling timeout)"

def execute_rsc_telegram_premium_order(username, months):
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "telegram_username": username,
        "months": int(months)
    }
    try:
        response = requests.post(f"{RSC_BASE_URL}/telegram/premium/buy", json=payload, headers=headers, timeout=15)
        res_data = response.json()
    except Exception as e:
        return None, f"Connection error during premium order: {e}"

    if response.status_code != 200:
        err_msg = res_data.get("error", {}).get("message", response.text)
        return None, f"API error (HTTP {response.status_code}): {err_msg}"

    order_number = res_data.get("number")
    if not order_number:
        return None, "RSC server did not return an order number (number)"

    poll_url = f"{RSC_BASE_URL}/orders/{order_number}"
    for _ in range(40):
        time.sleep(3)
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=10)
            poll_data = poll_resp.json()
        except Exception:
            continue

        status = poll_data.get("status")
        if status == "completed":
            return f"Order #{order_number} completed successfully for @{username} ({months} months Premium)", None
        if status in ["failed", "refund"]:
            fail_reason = poll_data.get("fail_code", "unknown_fail")
            reason_text = poll_data.get("status_reason", "")
            return None, f"Order canceled/refunded. Reason: {fail_reason} ({reason_text})"

    return None, "Order execution timeout (Polling timeout)"

@app.route('/')
def home():
    return "Digiseller-RSC Dynamic Unique Code Integration Service is running successfully!", 200

@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", {})
        text = message.get("text", "").strip().lower()
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))

        if chat_id == TELEGRAM_CHAT_ID and (text in ["/price", "/prices", "/прайс", "прайс", "ціни"]):
            stars_data = get_rsc_telegram_stars_pricing()
            prem_data = get_rsc_telegram_premium_pricing()
            pubg_data = get_rsc_gift_cards_catalog("pubg_mobile")
            roblox_data = get_rsc_gift_cards_catalog("roblox_global")
            
            price_msg = "📊 <b>Повний прайс ReSellCodes (RSC):</b>\n\n"
            
            if stars_data:
                price_msg += f"⭐ <b>Telegram Stars:</b>\n• За 1 зірку: <code>${stars_data.get('price_per_star', 'N/A')}</code>\n\n"
            
            if prem_data and "plans" in prem_data:
                price_msg += "💎 <b>Telegram Premium:</b>\n"
                for plan in prem_data["plans"]:
                    price_msg += f"• {plan.get('months')} міс: <code>${plan.get('price_usd')}</code>\n"
                price_msg += "\n"

            if pubg_data and isinstance(pubg_data, dict) and "offers" in pubg_data:
                price_msg += "🎯 <b>PUBG Mobile UC:</b>\n"
                for offer in pubg_data["offers"][:6]:
                    price_msg += f"• {offer.get('name', offer.get('card_id'))}: <code>${offer.get('price_usd')}</code>\n"
                price_msg += "\n"

            if roblox_data and isinstance(roblox_data, dict) and "offers" in roblox_data:
                price_msg += "🧱 <b>Roblox Robux:</b>\n"
                for offer in roblox_data["offers"][:6]:
                    price_msg += f"• {offer.get('name', offer.get('card_id'))}: <code>${offer.get('price_usd')}</code>\n"
            
            send_telegram(price_msg)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Telegram webhook error: {e}", flush=True)
        return jsonify({"status": "error"}), 200

@app.route('/webhook', methods=['POST', 'GET'])
@app.route('/webhook/', methods=['POST', 'GET'])
def digiseller_webhook():
    try:
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True, force=True) or {}
        values_data = request.values.to_dict()
        
        merged = {**args_data, **form_data, **json_data, **values_data}
        
        product_id = str(merged.get('ID_G') or merged.get('id_g') or merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or '')
        invoice_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or 'UNKNOWN'
        product_name = merged.get('name') or merged.get('goods_name') or ''
        
        # Отримуємо унікальний код від Digiseller
        unique_code = merged.get('unique_code') or merged.get('code') or merged.get('uniquecode') or ''

        raw_qty = merged.get('cnt') or merged.get('quantity') or merged.get('amount_goods') or 1
        try:
            quantity = int(raw_qty)
        except ValueError:
            quantity = 1

        if product_id and product_id not in ALLOWED_PRODUCT_IDS:
            return jsonify({"status": "ignored", "reason": f"Wrong product ID: {product_id}"}), 200

        # Перевірка унікального коду через Digiseller API (опціонально перед обробкою)
        if unique_code:
            code_info, code_err = verify_digiseller_unique_code(unique_code)
            if code_err:
                print(f"Warning/Error checking unique code {unique_code}: {code_err}")

        name_lower = product_name.lower()
        success = False
        issued_result = None

        if "premium" in name_lower or "премиум" in name_lower:
            # Зчитуємо місяці з параметрів кнопок вибору або назви
            raw_param = str(merged.get('Срок подписки') or merged.get('Subscription period') or merged.get('param') or '')
            if '6' in raw_param:
                months = 6
            elif '12' in raw_param or 'год' in raw_param or 'рік' in raw_param or '12 months' in raw_param.lower():
                months = 12
            else:
                months = 3

            # Зчитуємо юзернейм з текстового поля
            buyer_username = (
                merged.get('Укажите ваш @username') or 
                merged.get('Enter your @username') or 
                merged.get('username') or 
                merged.get('account') or 
                merged.get('param2') or 
                merged.get('param') or 
                'durov'
            )
            buyer_username = str(buyer_username).replace('@', '').strip()

            send_telegram(f"💎 <b>New Telegram Premium order!</b>\nInvoice: <code>{invoice_id}</code>\nUsername: @{buyer_username}\nMonths: {months}\nProcessing via API...")
            
            issued_result, error = execute_rsc_telegram_premium_order(buyer_username, months)
            if not error:
                success = True
            else:
                send_telegram(f"🚨 <b>PREMIUM PURCHASE ERROR!</b>\nInvoice: <code>{invoice_id}</code>\nError: {error}")

        elif "stars" in name_lower or "зірки" in name_lower or "звезд" in name_lower:
            buyer_username = (
                merged.get('Укажите ваш @username') or 
                merged.get('Enter your @username') or 
                merged.get('username') or 
                merged.get('account') or 
                merged.get('param2') or 
                merged.get('param') or 
                'durov'
            )
            buyer_username = str(buyer_username).replace('@', '').strip()

            numbers = re.findall(r'\d+', product_name)
            base_stars = int(numbers[0]) if numbers else 50
            total_stars = base_stars * quantity

            send_telegram(f"⭐ <b>New Telegram Stars order!</b>\nInvoice: <code>{invoice_id}</code>\nUsername: @{buyer_username}\nStars: {total_stars}\nProcessing via API...")
            
            issued_result, error = execute_rsc_telegram_stars_order(buyer_username, total_stars)
            if not error:
                success = True
            else:
                send_telegram(f"🚨 <b>STARS PURCHASE ERROR!</b>\nInvoice: <code>{invoice_id}</code>\nError: {error}")

        else:
            product_type = "gift_card"
            id_1 = "telegram_stars"
            id_2 = "50_stars"

            send_telegram(f"📥 <b>New order received!</b>\nInvoice: <code>{invoice_id}</code>\nProduct: {product_name}\nQty: {quantity}\nPurchasing Gift Code...")
            issued_result, error = execute_rsc_purchase(product_type, id_1, id_2, quantity)
            if not error:
                success = True
            else:
                send_telegram(f"🚨 <b>GIFT CODE PURCHASE ERROR!</b>\nInvoice: <code>{invoice_id}</code>\nError: {error}")

        # Якщо поповнення успішне — закриваємо унікальний код в Digiseller та повертаємо retval: 0
        if success:
            if unique_code:
                set_digiseller_code_delivered(unique_code)

            success_msg = (
                f"🛒 <b>SUCCESSFUL AUTO-ORDER!</b>\n\n"
                f"🆔 <b>Invoice:</b> <code>{invoice_id}</code>\n"
                f"📌 <b>Details:</b> {issued_result}"
            )
            send_telegram(success_msg)

            return jsonify({
                "retval": 0,
                "returntext": f"Замовлення успішно опрацьовано! Деталі: {issued_result}"
            }), 200
        else:
            return jsonify({
                "retval": 1,
                "returntext": "Помилка автоматичного поповнення. Зверніться до підтримки з унікальним кодом."
            }), 200

    except Exception as e:
        print(f"Webhook internal exception: {e}", flush=True)
        send_telegram(f"🔥 <b>Server internal error:</b> {str(e)}")
        return jsonify({
            "retval": 1,
            "returntext": "Internal server error."
        }), 500

if __name__ == '__main__':
    setup_telegram_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)










