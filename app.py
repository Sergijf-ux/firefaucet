import os
import time
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8807171182:AAEewfuvrhwHYRE0N3Xc7_IjGUpFsL_TgqY"
TELEGRAM_CHAT_ID = "8508676381"
RESELL_CODES_API_KEY = "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda"
RSC_BASE_URL = "https://resell.codes/api/v1"

TARGET_PRODUCT_ID = "6349263"

def send_telegram(text):
    """Надсилає сповіщення адміністратору в Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

def get_rsc_telegram_stars_pricing():
    """Запит до API RSC для отримання актуальної ціни за 1 зірку."""
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
    """Запит до API RSC для отримання тарифів Telegram Premium."""
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
    """Запит до API RSC для отримання актуального каталогу карток."""
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
    """Створення замовлення в ReSellCodes та опитування статусу."""
    headers = {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    if product_type == "telegram_stars":
        order_url = f"{RSC_BASE_URL}/telegram/stars/buy"
        username = extra_data.get("telegram_username", "durov") if extra_data else "durov"
        payload = {"telegram_username": username, "quantity": quantity}
    elif product_type == "telegram_premium":
        order_url = f"{RSC_BASE_URL}/telegram/premium/buy"
        username = extra_data.get("telegram_username", "durov") if extra_data else "durov"
        months = extra_data.get("months", 3) if extra_data else 3
        payload = {"telegram_username": username, "months": months}
    elif product_type == "game_key":
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

    if product_type in ["telegram_stars", "telegram_premium"]:
        order_status = res_data.get("status")
        if order_status in ["processing", "completed"]:
            charged = res_data.get("charged_usd", "0")
            uname = res_data.get("telegram_username")
            return f"Telegram order successfully processed!\nUsername: @{uname}\nCharged: ${charged}", None
        else:
            return None, f"Telegram order status: {order_status}, Reason: {res_data.get('status_reason')}"

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

@app.route('/')
def home():
    return "Digiseller-RSC Dynamic Integration Service is running successfully!", 200

@app.route('/catalog', methods=['GET'])
def view_catalog():
    """Виводить зведені каталоги у браузер і надсилає звіт у Telegram."""
    stars_pricing = get_rsc_telegram_stars_pricing()
    premium_pricing = get_rsc_telegram_premium_pricing()
    roblox_cards = get_rsc_gift_cards_catalog("roblox_global")
    pubg_cards = get_rsc_gift_cards_catalog("pubg_mobile")
    
    star_price = "N/A"
    if stars_pricing and isinstance(stars_pricing, dict):
        star_price = stars_pricing.get("price_per_star", "N/A")

    premium_info = ""
    if premium_pricing and isinstance(premium_pricing, dict) and "plans" in premium_pricing:
        for plan in premium_pricing["plans"]:
            premium_info += f"• <b>{plan.get('months')} міс.:</b> ${plan.get('price_usd')}\n"
    
    roblox_info = ""
    if roblox_cards and isinstance(roblox_cards, dict) and "offers" in roblox_cards:
        for offer in roblox_cards["offers"]:
            roblox_info += f"• <b>{offer.get('name')}:</b> ${offer.get('price_usd')} (Stock: {offer.get('stock')})\n"
            
    pubg_info = ""
    if pubg_cards and isinstance(pubg_cards, dict) and "offers" in pubg_cards:
        for offer in pubg_cards["offers"]:
            pubg_info += f"• <b>{offer.get('name')}:</b> ${offer.get('price_usd')} (Stock: {offer.get('stock')})\n"

    tg_msg = (
        f"📊 <b>ПОТОЧНИЙ КАТАЛОГ RSC</b>\n\n"
        f"⭐ <b>Telegram Stars:</b>\n• Ціна за 1 зірку: <code>${star_price}</code>\n\n"
        f"💎 <b>Telegram Premium:</b>\n{premium_info or '• Немає даних\n'}\n"
        f"🎮 <b>Roblox Gift Cards:</b>\n{roblox_info or '• Немає даних\n'}\n"
        f"🎯 <b>PUBG Mobile:</b>\n{pubg_info or '• Немає даних\n'}"
    )
    
    send_telegram(tg_msg)
    
    return jsonify({
        "telegram_stars_pricing": stars_pricing,
        "telegram_premium_pricing": premium_pricing,
        "roblox_gift_cards": roblox_cards,
        "pubg_mobile": pubg_cards
    }), 200

@app.route('/webhook', methods=['POST', 'GET'])
@app.route('/webhook/', methods=['POST', 'GET'])
def digiseller_webhook():
    """Обробник вебхуків Digiseller з підтримкою Telegram Stars, Telegram Premium, Roblox та PUBG Mobile."""
    try:
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True, force=True) or {}
        values_data = request.values.to_dict()
        
        merged = {**args_data, **form_data, **json_data, **values_data}

        product_id = str(merged.get('ID_G') or merged.get('id_g') or merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or '')
        invoice_id = merged.get('ID_I') or merged.get('id_i') or merged.get('inv_id') or merged.get('order_id') or 'UNKNOWN'
        product_name = merged.get('name') or merged.get('goods_name') or ''
        
        try:
            amount = float(merged.get('Amount') or merged.get('amount') or merged.get('sum') or merged.get('OutSum') or 0)
        except ValueError:
            amount = 0.0

        raw_qty = merged.get('cnt') or merged.get('quantity') or merged.get('amount_goods') or 50
        try:
            quantity = int(raw_qty)
        except ValueError:
            quantity = 50

        telegram_username = (
            merged.get('options_1') or merged.get('account') or merged.get('username') or 
            merged.get('telegram_username') or merged.get('text1') or ''
        ).strip().lstrip('@')

        if product_id and product_id != TARGET_PRODUCT_ID:
            print(f"Ignored: Product ID {product_id} does not match target {TARGET_PRODUCT_ID}", flush=True)
            return jsonify({"status": "ignored", "reason": "Wrong product ID"}), 200

        product_type = "telegram_stars"
        id_1 = None
        id_2 = None
        extra_data = {}
        max_allowed_usd = 50.00

        name_lower = product_name.lower()
        
        if "premium" in name_lower or "премиум" in name_lower:
            product_type = "telegram_premium"
            months = 3
            if "6" in name_lower:
                months = 6
            elif "12" in name_lower or "год" in name_lower or "рік" in name_lower:
                months = 12
            
            extra_data["months"] = months
            
            prem_pricing = get_rsc_telegram_premium_pricing()
            plan_price = None
            if prem_pricing and isinstance(prem_pricing, dict) and "plans" in prem_pricing:
                for plan in prem_pricing["plans"]:
                    if plan.get("months") == months:
                        try:
                            plan_price = float(plan.get("price_usd"))
                        except (ValueError, TypeError):
                            pass
                        break
            
            if plan_price:
                max_allowed_usd = plan_price * 1.20
            else:
                max_allowed_usd = 50.00

        elif "pubg" in name_lower or "uc" in name_lower:
            product_type = "gift_card"
            id_1 = "pubg_mobile"
            numbers = re.findall(r'\d+', product_name)
            if numbers:
                id_2 = f"{numbers[0]}_uc"
            else:
                id_2 = "60_uc"
            
            pubg_catalog = get_rsc_gift_cards_catalog("pubg_mobile")
            card_price = None
            if pubg_catalog and isinstance(pubg_catalog, dict) and "offers" in pubg_catalog:
                for offer in pubg_catalog["offers"]:
                    if offer.get("card_id") == id_2:
                        try:
                            card_price = float(offer.get("price_usd"))
                        except (ValueError, TypeError):
                            pass
                        break
            
            if card_price:
                max_allowed_usd = card_price * 1.20
            else:
                max_allowed_usd = 500.00

        elif "robux" in name_lower or "roblox" in name_lower:
            product_type = "gift_card"
            id_1 = "roblox_global"
            numbers = re.findall(r'\d+', product_name)
            if numbers:
                id_2 = f"{numbers[0]}_robux"
            else:
                id_2 = "50_robux"
            
            roblox_catalog = get_rsc_gift_cards_catalog("roblox_global")
            card_price = None
            if roblox_catalog and isinstance(roblox_catalog, dict) and "offers" in roblox_catalog:
                for offer in roblox_catalog["offers"]:
                    if offer.get("card_id") == id_2:
                        try:
                            card_price = float(offer.get("price_usd"))
                        except (ValueError, TypeError):
                            pass
                        break
            
            if card_price:
                max_allowed_usd = card_price * 1.20
            else:
                max_allowed_usd = 15.00
            
        elif "stars" in name_lower or "telegram" in name_lower:
            product_type = "telegram_stars"
            
            pricing_data = get_rsc_telegram_stars_pricing()
            price_per_star = 0.0152250
            
            if pricing_data and isinstance(pricing_data, dict) and "price_per_star" in pricing_data:
                try:
                    price_per_star = float(pricing_data["price_per_star"])
                except (ValueError, TypeError):
                    pass

            calculated_cost = quantity * price_per_star
            max_allowed_usd = calculated_cost * 1.20
            if max_allowed_usd < 1.00:
                max_allowed_usd = 1.00

        if amount > 0 and amount > max_allowed_usd:
            print(f"Rejected: Amount {amount} USD exceeds limit {max_allowed_usd} USD for product {product_name}", flush=True)
            send_telegram(f"⚠️ <b>Order rejected due to price limit!</b>\nInvoice: <code>{invoice_id}</code>\nProduct: {product_name}\nAmount: {amount} USD (Max allowed: {max_allowed_usd} USD)")
            return jsonify({"status": "rejected", "reason": "Amount exceeds limit"}), 200

        if not telegram_username:
            telegram_username = "durov"

        send_telegram(f"📥 <b>New order received!</b>\nInvoice: <code>{invoice_id}</code>\nProduct: {product_name}\nType: {product_type}\nAmount: {amount} USD\nQty: {quantity}\nPurchasing...")

        extra_data["telegram_username"] = telegram_username
        issued_keys, error = execute_rsc_purchase(product_type, id_1, id_2, quantity, extra_data=extra_data)

        if error:
            alert_msg = (
                f"🚨 <b>AUTOMATED PURCHASE ERROR!</b>\n\n"
                f"🆔 <b>Invoice:</b> <code>{invoice_id}</code>\n"
                f"📦 <b>Product:</b> {product_name}\n"
                f"❌ <b>Error:</b> {error}\n\n"
                f"⚠️ <i>Fulfill the order manually!</i>"
            )
            send_telegram(alert_msg)
            return "Error processing order via API. Manual fulfillment required.", 200

        success_msg = (
            f"🛒 <b>SUCCESSFUL AUTO-ORDER!</b>\n\n"
            f"🆔 <b>Digiseller Invoice:</b> <code>{invoice_id}</code>\n"
            f"🔑 <b>Result / Codes:</b>\n<code>{issued_keys}</code>"
        )
        send_telegram(success_msg)
        
        return issued_keys, 200

    except Exception as e:
        print(f"Webhook internal exception: {e}", flush=True)
        send_telegram(f"🔥 <b>Server internal error:</b> {str(e)}")
        return "INTERNAL ERROR", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)















