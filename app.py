import os
import re
import time
import json
import sqlite3
import html
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- CONFIGURATION ----------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9030923274:AAHoLPCafZSZ-WrTi6kZr1vEDQtrjueNgPg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8508676381")

RESELL_CODES_API_KEY = os.getenv("RESELL_CODES_API_KEY", "rsc_live_b61d7b4894461371f7ed9b636752c35ac703a6d5c4625cda")
DIGISELLER_API_TOKEN = os.getenv("DIGISELLER_API_TOKEN", "A5CD7AE74E4846308F30A692510B6F9D")

DIGISELLER_WEBHOOK_SECRET = os.getenv("DIGISELLER_WEBHOOK_SECRET", "digi778899")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "tg778899")

RSC_BASE_URL = "https://resell.codes/api/v1"

DATABASE_PATH = os.getenv("DATABASE_PATH", "orders.sqlite3")

ALLOWED_PRODUCT_IDS = [
    "6375625",
    "6370800",
    "6359892",
]

RENDER_APP_URL = "https://digiseller-bot-2z5g.onrender.com"

REQUEST_TIMEOUT = 15
MAX_ORDER_ATTEMPTS = 40

# ---------------- DATABASE ----------------

def db_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    folder = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(folder, exist_ok=True)

    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                invoice_id TEXT PRIMARY KEY,
                product_id TEXT,
                product_name TEXT,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def reserve_order(invoice_id, product_id, product_name):
    """Атомарно резервирует заказ. Повторный invoice не обрабатывается."""
    try:
        with db_connection() as conn:
            conn.execute("""
                INSERT INTO orders (
                    invoice_id, product_id, product_name, status
                )
                VALUES (?, ?, ?, 'processing')
            """, (invoice_id, product_id, product_name))
            conn.commit()

        return True

    except sqlite3.IntegrityError:
        return False


def update_order(invoice_id, status, result=None, error=None):
    with db_connection() as conn:
        conn.execute("""
            UPDATE orders
            SET status = ?,
                result = ?,
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE invoice_id = ?
        """, (
            status,
            str(result)[:5000] if result is not None else None,
            str(error)[:3000] if error is not None else None,
            invoice_id
        ))
        conn.commit()


def get_order(invoice_id):
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE invoice_id = ?",
            (invoice_id,)
        ).fetchone()


# ---------------- TELEGRAM ----------------

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials are not configured")
        return False

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )

        response.raise_for_status()
        return response.json().get("ok", False)

    except Exception:
        logger.exception("Telegram notification failed")
        return False


def setup_telegram_webhook():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET:
        logger.warning("Telegram webhook credentials are missing")
        return

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/setWebhook"
        )

        response = requests.post(
            url,
            json={
                "url": f"{RENDER_APP_URL}/telegram-webhook",
                "secret_token": TELEGRAM_WEBHOOK_SECRET
            },
            timeout=10
        )

        response.raise_for_status()
        logger.info("Telegram webhook setup: %s", response.text)

    except Exception:
        logger.exception("Telegram webhook setup failed")


def verify_telegram_request():
    received = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )
    return bool(TELEGRAM_WEBHOOK_SECRET) and (
        received == TELEGRAM_WEBHOOK_SECRET
    )


# ---------------- DIGISELLER ----------------

def verify_digiseller_unique_code(unique_code):
    url = "https://api.digiseller.com/api/v2/seller/uniques/info"

    try:
        response = requests.get(
            url,
            params={
                "token": DIGISELLER_API_TOKEN,
                "code": unique_code
            },
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None, f"Digiseller HTTP {response.status_code}"

        data = response.json()

        if not isinstance(data, dict):
            return None, "Invalid Digiseller response"

        if "retval" in data and str(data["retval"]) != "0":
            return None, f"Digiseller rejected unique code: {data}"

        return data, None

    except Exception as e:
        return None, f"Unique code verification error: {e}"


def set_digiseller_code_delivered(unique_code):
    url = "https://api.digiseller.com/api/v2/seller/uniques/sold"

    try:
        response = requests.post(
            url,
            json={
                "token": DIGISELLER_API_TOKEN,
                "code": unique_code
            },
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"

        data = response.json()

        if isinstance(data, dict) and "retval" in data:
            if str(data["retval"]) != "0":
                return False, str(data)

        return True, None

    except Exception as e:
        return False, str(e)


# ---------------- RESELLCODES ----------------

def rsc_headers():
    return {
        "Authorization": f"Bearer {RESELL_CODES_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def parse_api_response(response):
    try:
        return response.json()
    except ValueError:
        return {}


def api_error(response, data):
    if isinstance(data, dict):
        error = data.get("error", {})
        if isinstance(error, dict):
            message = error.get("message")
        else:
            message = error

        if message:
            return str(message)

    return response.text[:1000]


def get_rsc_telegram_stars_pricing():
    try:
        response = requests.get(
            f"{RSC_BASE_URL}/telegram/stars",
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            return parse_api_response(response)

        logger.error("Stars pricing HTTP %s", response.status_code)

    except Exception:
        logger.exception("Stars pricing error")

    return None


def get_rsc_telegram_premium_pricing():
    try:
        response = requests.get(
            f"{RSC_BASE_URL}/telegram/premium",
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            return parse_api_response(response)

        logger.error("Premium pricing HTTP %s", response.status_code)

    except Exception:
        logger.exception("Premium pricing error")

    return None


def get_rsc_gift_cards_catalog(category_id):
    try:
        response = requests.get(
            f"{RSC_BASE_URL}/gift-cards/categories/{category_id}/cards",
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            data = parse_api_response(response)

            if isinstance(data, dict):
                return data.get("data", data)

    except Exception:
        logger.exception("Gift cards catalog error")

    return None


def poll_rsc_order(order_number, codes_key=None):
    poll_url = f"{RSC_BASE_URL}/orders/{order_number}"

    for attempt in range(MAX_ORDER_ATTEMPTS):
        time.sleep(3)

        try:
            response = requests.get(
                poll_url,
                headers=rsc_headers(),
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code != 200:
                logger.warning(
                    "RSC polling HTTP %s",
                    response.status_code
                )
                continue

            data = response.json()
            status = data.get("status")

            if status == "completed":
                if codes_key is None:
                    return (
                        f"Order #{order_number} completed successfully",
                        None
                    )

                items = data.get(codes_key, [])

                if not items:
                    return None, "Completed order has no codes"

                if not isinstance(items, list):
                    return None, "Invalid codes format from RSC"

                if not all(isinstance(item, str) and item.strip()
                           for item in items):
                    return None, "Invalid code item received from RSC"

                return "\n".join(items), None

            if status in ["failed", "refund"]:
                return None, (
                    f"RSC order {status}: "
                    f"{data.get('fail_code', 'unknown')}; "
                    f"{data.get('status_reason', '')}"
                )

        except Exception:
            logger.exception("RSC polling error")

    return None, "RSC order polling timeout; manual check required"


def execute_rsc_purchase(product_type, id_1, id_2, quantity=1):
    if product_type == "game_key":
        order_url = f"{RSC_BASE_URL}/game-keys/order"
        payload = {
            "game_id": id_1,
            "key_id": id_2,
            "quantity": quantity
        }
        codes_key = "keys"

    elif product_type == "gift_card":
        order_url = f"{RSC_BASE_URL}/gift-cards/order"
        payload = {
            "category_id": id_1,
            "card_id": id_2,
            "quantity": quantity
        }
        codes_key = "codes"

    else:
        return None, "Unknown product type"

    try:
        response = requests.post(
            order_url,
            json=payload,
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        data = parse_api_response(response)

        if response.status_code != 200:
            return None, api_error(response, data)

        order_number = data.get("number")

        if not order_number:
            return None, "RSC did not return order number"

        return poll_rsc_order(order_number, codes_key)

    except Exception as e:
        return None, f"RSC purchase connection error: {e}"


def execute_rsc_telegram_stars_order(username, quantity):
    payload = {
        "telegram_username": username,
        "quantity": int(quantity)
    }

    try:
        response = requests.post(
            f"{RSC_BASE_URL}/telegram/stars/buy",
            json=payload,
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        data = parse_api_response(response)

        if response.status_code != 200:
            return None, api_error(response, data)

        order_number = data.get("number")

        if not order_number:
            return None, "RSC did not return order number"

        return poll_rsc_order(order_number)

    except Exception as e:
        return None, f"Stars purchase error: {e}"


def execute_rsc_telegram_premium_order(username, months):
    payload = {
        "telegram_username": username,
        "months": int(months)
    }

    try:
        response = requests.post(
            f"{RSC_BASE_URL}/telegram/premium/buy",
            json=payload,
            headers=rsc_headers(),
            timeout=REQUEST_TIMEOUT
        )

        data = parse_api_response(response)

        if response.status_code != 200:
            return None, api_error(response, data)

        order_number = data.get("number")

        if not order_number:
            return None, "RSC did not return order number"

        return poll_rsc_order(order_number)

    except Exception as e:
        return None, f"Premium purchase error: {e}"


# ---------------- HELPERS ----------------

def extract_username(data):
    username = (
        data.get("Укажите ваш @username")
        or data.get("Enter your @username")
        or data.get("options_1")
        or data.get("text1")
        or data.get("username")
        or data.get("telegram_username")
        or data.get("account")
        or data.get("param2")
        or data.get("param")
        or ""
    )

    username = str(username).strip().lstrip("@")

    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return None

    return username


def extract_months(data):
    value = str(
        data.get("Срок подписки")
        or data.get("Subscription period")
        or data.get("options_0")
        or data.get("param")
        or data.get("name")
        or data.get("goods_name")
        or ""
    ).lower()

    match = re.search(r"\b(3|6|12)\b", value)

    return int(match.group(1)) if match else None


def extract_number_from_text(text):
    numbers = re.findall(r"\d+", str(text))

    if not numbers:
        return None

    amount = int(numbers[0])

    if amount <= 0:
        return None

    return amount


def webhook_authorized():
    if not DIGISELLER_WEBHOOK_SECRET:
        return False

    received = (
        request.headers.get("X-Webhook-Secret")
        or request.args.get("secret")
        or ""
    )

    return received == DIGISELLER_WEBHOOK_SECRET


def order_error(invoice_id, message):
    update_order(invoice_id, "needs_review", error=message)

    send_telegram(
        "🚨 <b>ORDER REQUIRES MANUAL CHECK</b>\n"
        f"Invoice: <code>{html.escape(str(invoice_id))}</code>\n"
        f"Error: {html.escape(str(message)[:2000])}\n"
        "Automatic repeat purchase is blocked."
    )


# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return (
        "Digiseller-RSC Dynamic Unique Code Integration Service "
        "is running successfully!",
        200
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if not verify_telegram_request():
        return jsonify({"status": "unauthorized"}), 403

    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", {})

        text = str(message.get("text", "")).strip().lower()
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))

        if chat_id != str(TELEGRAM_CHAT_ID):
            return jsonify({"status": "ignored"}), 200

        if text in ["/price", "/prices", "/прайс", "прайс", "ціни"]:
            stars = get_rsc_telegram_stars_pricing()
            premium = get_rsc_telegram_premium_pricing()
            pubg = get_rsc_gift_cards_catalog("pubg_mobile")
            roblox = get_rsc_gift_cards_catalog("roblox_global")

            # Частина 1: Stars, Premium, PUBG Mobile UC
            msg_1 = "📊 <b>ResellCodes price list [1/2]</b>\n\n"

            if stars:
                msg_1 += (
                    "⭐ <b>Telegram Stars:</b>\n"
                    f"• Price per Star: "
                    f"<code>${html.escape(str(stars.get('price_per_star', 'N/A')))}</code>\n\n"
                )
            else:
                msg_1 += "⭐ Stars price unavailable\n\n"

            if premium and isinstance(premium.get("plans"), list):
                msg_1 += "💎 <b>Telegram Premium:</b>\n"

                for plan in premium["plans"]:
                    msg_1 += (
                        f"• {html.escape(str(plan.get('months')))} months: "
                        f"<code>${html.escape(str(plan.get('price_usd')))}</code>\n"
                    )

                msg_1 += "\n"

            if isinstance(pubg, dict) and isinstance(pubg.get("offers"), list):
                msg_1 += "🎯 <b>PUBG Mobile UC:</b>\n"

                for offer in pubg["offers"]:
                    name = offer.get("name", offer.get("card_id", ""))
                    price = offer.get("price_usd", "N/A")

                    msg_1 += (
                        f"• {html.escape(str(name))}: "
                        f"<code>${html.escape(str(price))}</code>\n"
                    )

            send_telegram(msg_1)

            # Частина 2: Roblox Robux
            if isinstance(roblox, dict) and isinstance(roblox.get("offers"), list):
                msg_2 = "🧱 <b>Roblox Robux [2/2]:</b>\n"

                for offer in roblox["offers"]:
                    name = offer.get("name", offer.get("card_id", ""))
                    price = offer.get("price_usd", "N/A")

                    msg_2 += (
                        f"• {html.escape(str(name))}: "
                        f"<code>${html.escape(str(price))}</code>\n"
                    )

                send_telegram(msg_2)

        return jsonify({"status": "ok"}), 200

    except Exception:
        logger.exception("Telegram webhook error")
        return jsonify({"status": "error"}), 200


@app.route("/webhook", methods=["POST"])
@app.route("/webhook/", methods=["POST"])
def digiseller_webhook():

    if not webhook_authorized():
        logger.warning("Unauthorized Digiseller webhook request")
        return jsonify({
            "retval": 1,
            "returntext": "Unauthorized request"
        }), 403

    invoice_id = "UNKNOWN"

    try:
        args_data = request.args.to_dict()
        form_data = request.form.to_dict()
        json_data = request.get_json(silent=True) or {}

        merged = {
            **args_data,
            **form_data,
            **json_data
        }

        product_id = str(
            merged.get("ID_G")
            or merged.get("id_g")
            or merged.get("product_id")
            or ""
        )

        invoice_id = str(
            merged.get("ID_I")
            or merged.get("id_i")
            or merged.get("inv_id")
            or merged.get("order_id")
            or ""
        )

        product_name = str(
            merged.get("name")
            or merged.get("goods_name")
            or merged.get("options_0")
            or ""
        ).strip()

        unique_code = str(
            merged.get("unique_code")
            or merged.get("code")
            or merged.get("uniquecode")
            or ""
        ).strip()

        if not invoice_id:
            return jsonify({
                "retval": 1,
                "returntext": "Missing invoice ID"
            }), 200

        if not product_id or product_id not in ALLOWED_PRODUCT_IDS:
            return jsonify({
                "retval": 1,
                "returntext": "Unknown or unauthorized product ID"
            }), 200

        if not unique_code:
            return jsonify({
                "retval": 1,
                "returntext": "Missing Digiseller unique code"
            }), 200

        raw_qty = (
            merged.get("cnt")
            or merged.get("quantity")
            or merged.get("amount_goods")
            or 1
        )

        try:
            quantity = int(raw_qty)
        except (ValueError, TypeError):
            return jsonify({
                "retval": 1,
                "returntext": "Invalid quantity"
            }), 200

        if quantity < 1 or quantity > 1000:
            return jsonify({
                "retval": 1,
                "returntext": "Quantity outside allowed range"
            }), 200

        try:
            paid_amount = float(merged.get("Amount") or merged.get("amount") or 0)
        except (ValueError, TypeError):
            paid_amount = 0.0

        # Check Digiseller unique code before reserving and purchasing.
        code_info, code_error = verify_digiseller_unique_code(unique_code)

        if code_error:
            send_telegram(
                "🚨 <b>UNIQUE CODE VERIFICATION FAILED</b>\n"
                f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                f"Error: {html.escape(str(code_error))}"
            )
            return jsonify({
                "retval": 1,
                "returntext": "Unique code verification failed"
            }), 200

        if not product_name and isinstance(code_info, dict):
            product_name = str(code_info.get("name_goods") or "").strip()

        if not product_name:
            return jsonify({
                "retval": 1,
                "returntext": "Missing product name"
            }), 200

        # Reserve invoice atomically before making any supplier purchase.
        if not reserve_order(invoice_id, product_id, product_name):
            existing = get_order(invoice_id)

            status = existing["status"] if existing else "unknown"

            send_telegram(
                "⚠️ <b>Repeated webhook blocked</b>\n"
                f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                f"Current status: {html.escape(status)}"
            )

            return jsonify({
                "retval": 1,
                "returntext": "This order has already been registered"
            }), 200

        search_text = f"{product_name} {merged.get('options_0', '')} {merged.get('param', '')}".lower()

        issued_result = None
        error = None

        # --- 1. TELEGRAM PREMIUM ---
        if "premium" in search_text or "премиум" in search_text:
            months = extract_months(merged)
            username = extract_username(merged)

            if not months or not username:
                error = "Missing or invalid Premium months / username"
            else:
                # Stop-Loss перевірка ціни
                prem_data = get_rsc_telegram_premium_pricing()
                if prem_data and isinstance(prem_data.get("plans"), list) and paid_amount > 0:
                    for p in prem_data["plans"]:
                        if p.get("months") == months:
                            rsc_cost = float(p.get("price_usd", 0))
                            if rsc_cost > paid_amount:
                                error = f"STOP LOSS: RSC price (${rsc_cost}) exceeds paid amount (${paid_amount})"
                            break

                if not error:
                    send_telegram(
                        "💎 <b>New Premium order</b>\n"
                        f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                        f"Username: @{html.escape(username)}\n"
                        f"Months: {months}"
                    )

                    issued_result, error = execute_rsc_telegram_premium_order(
                        username, months
                    )

        # --- 2. TELEGRAM STARS ---
        elif (
            "stars" in search_text
            or "зірки" in search_text
            or "звезд" in search_text
        ):
            stars_per_unit = extract_number_from_text(search_text)
            username = extract_username(merged)

            if not stars_per_unit or not username:
                error = "Missing Stars amount or valid username"
            else:
                total_stars = stars_per_unit * quantity

                # Stop-Loss перевірка ціни
                stars_data = get_rsc_telegram_stars_pricing()
                if stars_data and "price_per_star" in stars_data and paid_amount > 0:
                    rsc_cost = float(stars_data["price_per_star"]) * total_stars
                    if rsc_cost > paid_amount:
                        error = f"STOP LOSS: RSC price (${rsc_cost:.4f}) exceeds paid amount (${paid_amount})"

                if not error:
                    send_telegram(
                        "⭐ <b>New Stars order</b>\n"
                        f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                        f"Username: @{html.escape(username)}\n"
                        f"Stars: {total_stars}"
                    )

                    issued_result, error = execute_rsc_telegram_stars_order(
                        username, total_stars
                    )

        # --- 3. ROBLOX GIFT CARDS ---
        elif "robux" in search_text or "roblox" in search_text:
            nominal = extract_number_from_text(search_text)
            if not nominal:
                error = "Missing Robux nominal in product name"
            else:
                card_id = f"{nominal}_robux"

                # Stop-Loss перевірка ціни по каталогу
                roblox_cat = get_rsc_gift_cards_catalog("roblox_global")
                if isinstance(roblox_cat, dict) and isinstance(roblox_cat.get("offers"), list) and paid_amount > 0:
                    for offer in roblox_cat["offers"]:
                        if offer.get("card_id") == card_id:
                            rsc_cost = float(offer.get("price_usd", 0)) * quantity
                            if rsc_cost > paid_amount:
                                error = f"STOP LOSS: RSC price (${rsc_cost:.4f}) exceeds paid amount (${paid_amount})"
                            break

                if not error:
                    send_telegram(
                        "🧱 <b>New Roblox order</b>\n"
                        f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                        f"Card: {html.escape(card_id)} x{quantity}"
                    )

                    issued_result, error = execute_rsc_purchase(
                        "gift_card", "roblox_global", card_id, quantity
                    )

        # --- 4. PUBG MOBILE UC ---
        elif "pubg" in search_text or "uc" in search_text:
            nominal = extract_number_from_text(search_text)
            if not nominal:
                error = "Missing PUBG UC nominal in product name"
            else:
                card_id = f"{nominal}_uc"

                # Stop-Loss перевірка ціни по каталогу
                pubg_cat = get_rsc_gift_cards_catalog("pubg_mobile")
                if isinstance(pubg_cat, dict) and isinstance(pubg_cat.get("offers"), list) and paid_amount > 0:
                    for offer in pubg_cat["offers"]:
                        if offer.get("card_id") == card_id:
                            rsc_cost = float(offer.get("price_usd", 0)) * quantity
                            if rsc_cost > paid_amount:
                                error = f"STOP LOSS: RSC price (${rsc_cost:.4f}) exceeds paid amount (${paid_amount})"
                            break

                if not error:
                    send_telegram(
                        "🎯 <b>New PUBG UC order</b>\n"
                        f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                        f"Card: {html.escape(card_id)} x{quantity}"
                    )

                    issued_result, error = execute_rsc_purchase(
                        "gift_card", "pubg_mobile", card_id, quantity
                    )

        # --- 5. UNKNOWN PRODUCT ---
        else:
            error = (
                "Product is not configured. "
                "No automatic purchase was made."
            )

        if error:
            order_error(invoice_id, error)

            return jsonify({
                "retval": 1,
                "returntext": (
                    "Automatic processing failed. "
                    "Contact support."
                )
            }), 200

        # Supplier operation completed.
        # Mark Digiseller code as sold; do not repeat supplier purchase
        # if this final operation fails.
        sold, sold_error = set_digiseller_code_delivered(unique_code)

        if not sold:
            update_order(
                invoice_id,
                "completed_warning",
                result=issued_result,
                error=f"Purchase completed; Digiseller sold status failed: {sold_error}"
            )

            send_telegram(
                "⚠️ <b>Purchase completed, but Digiseller status update failed</b>\n"
                f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
                f"Error: {html.escape(str(sold_error))}\n"
                "Do not repeat the supplier purchase."
            )

        else:
            update_order(
                invoice_id,
                "completed",
                result=issued_result
            )

        send_telegram(
            "✅ <b>RSC purchase completed</b>\n"
            f"Invoice: <code>{html.escape(invoice_id)}</code>\n"
            f"Result: {html.escape(str(issued_result)[:2500])}"
        )

        return jsonify({
            "retval": 0,
            "returntext": (
                f"Order processed successfully.\n{issued_result}"
            )
        }), 200

    except Exception as e:
        logger.exception("Digiseller webhook internal error")

        if invoice_id and invoice_id != "UNKNOWN":
            try:
                order_error(invoice_id, str(e))
            except Exception:
                logger.exception("Could not update order status")

        return jsonify({
            "retval": 1,
            "returntext": "Internal processing error. Contact support."
        }), 200


# ---------------- START ----------------

init_database()
setup_telegram_webhook()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )










