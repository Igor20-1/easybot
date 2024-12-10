import requests
import time
import json
import os
from datetime import datetime, timedelta
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from requests.exceptions import HTTPError, ConnectionError, ChunkedEncodingError, Timeout
from http.client import RemoteDisconnected
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from colorama import Fore, Style, init
import telebot

init()

# CoinGecko API key
API_KEY = "YOUR KEY :)"
# CoinGecko API base URL
BASE_URL = "https://api.coingecko.com/api/v3"

#RANGE
MIN_MARKET_CAP = 3000000
MAX_MARKET_CAP = 3050000
range_step = 100000
user_ranges = {}
start_messages = {}

CACHE_FILE = "solana_tokens.json"
DEX_CACHE_FILE = "DexCacheScr.json"
NOTI_CACHE_FILE = "noti_jet.json"
USERS_FILE = "users.json"

TELEGRAM_BOT_TOKEN = "YOUR TOKEN :)"
ALLOWED_CHAT_IDS = {$YOUR CHATID$}
ADMIN_CHAT_ID = $YOUR CHATID$

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
message_states = {}
range_message_states = {}

start_message_id = None

DELAY = 2

RETRY_DELAY = 5
MAX_RETRIES = 10

def load_noti_cache():
    if os.path.exists(NOTI_CACHE_FILE):
        try:
            with open(NOTI_CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Ошибка чтения noti_jet кеша из файла {NOTI_CACHE_FILE}. Создается новый кеш.")
            return {}
    return {}

def save_noti_cache(noti_cache):
    try:
        with open(NOTI_CACHE_FILE, "w") as f:
            json.dump(noti_cache, f, indent=4)
    except IOError as e:
        print(f"Ошибка записи noti_jet кеша в файл: {e}")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Ошибка чтения файла пользователей {USERS_FILE}. Создается новый файл.")
            return {}
    return {}

def save_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=4)
    except IOError as e:
        print(f"Ошибка записи в файл пользователей: {e}")

def update_start_message(chat_id, min_val, max_val):
    global start_messages
    try:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        range_button = telebot.types.KeyboardButton('Range')
        markup.add(range_button)
        new_text = f"Текущий диапазон: {min_val}$ - {max_val}$"

        if chat_id in start_messages:
            try:
                bot.unpin_chat_message(chat_id)
            except Exception as e:
                print(f"Ошибка при откреплении сообщения в чате {chat_id}: {e}")
            try:
                bot.delete_message(chat_id, start_messages[chat_id])
            except Exception as e:
                print(f"Ошибка при удалении сообщения в чате {chat_id}: {e}")


        msg = bot.send_message(chat_id, new_text, reply_markup=markup)
        bot.pin_chat_message(chat_id, msg.message_id)
        start_messages[chat_id] = msg.message_id



    except Exception as e:
        print(f"Ошибка при обновлении стартового сообщения в чате {chat_id}: {e}")

def copy_to_noti_cache(coin_id, coin_data, noti_cache_ref):
    noti_cache = noti_cache_ref[0]
    if coin_id not in noti_cache:
        noti_cache[coin_id] = coin_data.copy()
        noti_cache[coin_id]['id'] = coin_id
        noti_cache[coin_id]["copied"] = True
        noti_cache[coin_id]["notified"] = False
        save_noti_cache(noti_cache)
        return True
    return False

def load_dex_cache():
    if os.path.exists(DEX_CACHE_FILE):
        try:
            with open(DEX_CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Ошибка чтения DexScreener кеша из файла {DEX_CACHE_FILE}. Создается новый кеш.")
            return {}
    return {}

def save_dex_cache(dex_cache):
    try:
        with open(DEX_CACHE_FILE, "w") as f:
            json.dump(dex_cache, f, indent=4)
    except IOError as e:
        print(f"Ошибка записи DexScreener кеша в файл: {e}")

def copy_to_dex_cache(coin_id, coin_data, dex_cache):
    if coin_id not in dex_cache:
        dex_cache[coin_id] = coin_data.copy()
        save_dex_cache(dex_cache)
        return True
    return False

def log_debug(message):
    print(f"{Fore.RED}[DEBUG {datetime.now()}]: {message}{Style.RESET_ALL}")

@bot.message_handler(func=lambda message: message.text == "Range")
def range_command(message):
  keyboard = InlineKeyboardMarkup()
  keyboard.add(InlineKeyboardButton("Select range", callback_data="select_range"))
  sent_message = bot.send_message(
      message.chat.id, "Select market capitalization range:", reply_markup=keyboard
  )
  range_message_states[sent_message.message_id] = {"state": "initial"}

@bot.callback_query_handler(func=lambda call: call.data.startswith("range_"))
def range_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    min_val, max_val = map(int, call.data.split("_")[1:])


    keyboard = InlineKeyboardMarkup(row_width=1)
    for i in range(int(max_val/range_step) , int(min_val/range_step), -1):
        min_val_narrow = (i-1)*range_step
        max_val_narrow = i * range_step
        callback_data = f"set_range_{min_val_narrow}_{max_val_narrow}"
        button_text = f"From {max_val_narrow}$ to {min_val_narrow}$"

        keyboard.add(InlineKeyboardButton(button_text, callback_data=callback_data))

    keyboard.add(InlineKeyboardButton("Back", callback_data="back_to_ranges"))
    keyboard.add(InlineKeyboardButton("Close", callback_data="close_range"))

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text="Select market capitalization range:",
        reply_markup=keyboard,
    )

    range_message_states[message_id] = {"state": "selecting_narrow_range", "min_val": min_val, "max_val": max_val}

@bot.callback_query_handler(func=lambda call: call.data == "close_range")
def close_range_callback(call):
    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    if call.message.message_id in range_message_states:
      del range_message_states[call.message.message_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_range_"))
def set_range_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    username = call.from_user.username
    users = load_users()

    min_val, max_val = map(int, call.data.split("_")[2:])

    if chat_id != ADMIN_CHAT_ID:
        # Запрос администратору
        request_message = bot.send_message(
            ADMIN_CHAT_ID,
            f"Пользователь @{username} запрашивает изменение ценового диапазона на {min_val}$ - {max_val}$, применить?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Да", callback_data=f"accept_range:{user_id}:{min_val}:{max_val}"),
                        InlineKeyboardButton("Нет", callback_data=f"decline_range:{user_id}:{min_val}:{max_val}")
                    ]
                ]
            )
        )

        users[user_id] = {"username": username, "requested_min": min_val, "requested_max": max_val,
                         "request_message_id": request_message.message_id}
        save_users(users)

        bot.send_message(chat_id, f"Запрос на изменение диапазона был отправлен администратору @{bot.get_me().username}")
        bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)

    else:
        global MIN_MARKET_CAP, MAX_MARKET_CAP
        MIN_MARKET_CAP = min_val
        MAX_MARKET_CAP = max_val
        user_ranges[chat_id] = {"min": min_val, "max": max_val}

        save_dex_cache({})
        save_noti_cache({})
        cache_lock = threading.Lock()
        with cache_lock:
            save_cache({}, load_non_solana_cache())
            print("Все кеши очищены.")

        for chat_id in ALLOWED_CHAT_IDS:
            update_start_message(chat_id, MIN_MARKET_CAP, MAX_MARKET_CAP)

        bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)
        return

@bot.callback_query_handler(func=lambda call: call.data == "back_to_ranges")
def back_to_ranges_callback(call):

    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if message_id in range_message_states:
        select_range_callback(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_range:"))
def accept_range_callback(call):
    _, user_id_str, min_val_str, max_val_str = call.data.split(":")
    user_id = int(user_id_str)
    min_val = int(min_val_str)
    max_val = int(max_val_str)
    users = load_users()
    username = users.get(user_id, {}).get("username")

    global MIN_MARKET_CAP, MAX_MARKET_CAP
    MIN_MARKET_CAP = min_val
    MAX_MARKET_CAP = max_val
    user_ranges[ADMIN_CHAT_ID] = {"min": min_val, "max": max_val}

    save_dex_cache({})
    save_noti_cache({})
    cache_lock = threading.Lock()
    with cache_lock:
        save_cache({}, load_non_solana_cache())
        print("Все кеши очищены.")

    for chat_id in ALLOWED_CHAT_IDS:
        update_start_message(chat_id, MIN_MARKET_CAP, MAX_MARKET_CAP)


    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=f"Запрос для @{username} был принят.")

    def delete_message_after_delay(chat_id, message_id_to_delete):
        time.sleep(3)
        bot.delete_message(chat_id, message_id_to_delete)

    threading.Thread(target=delete_message_after_delay, args=(call.message.chat.id, call.message.message_id)).start()

    try:
        user_message = bot.send_message(user_id, f"Ваш запрос был принят администратором @{bot.get_me().username}")
        threading.Thread(target=delete_message_after_delay, args=(user_id, user_message.message_id)).start()


    except Exception as e:
        print(f"Ошибка отправки сообщения пользователю: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("decline_range:"))
def decline_range_callback(call):
    _, user_id_str, _, _ = call.data.split(":")
    user_id = int(user_id_str)
    users = load_users()
    username = users.get(user_id, {}).get("username")



    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=f"Запрос для @{username} был отклонен.")
    try:
      bot.send_message(user_id, f"Ваш запрос был отклонен администратором @{bot.get_me().username}")
    except Exception as e:
        print(f"Ошибка отправки сообщения пользователю: {e}")

    def delete_message_after_delay(chat_id, message_id_to_delete):
        time.sleep(3)
        bot.delete_message(chat_id, message_id_to_delete)
    threading.Thread(target=delete_message_after_delay, args=(call.message.chat.id, call.message.message_id)).start()

@bot.callback_query_handler(func=lambda call: call.data == "select_range")
def select_range_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    keyboard = InlineKeyboardMarkup(row_width=1)
    for i in range(10, 0, -1):
        min_val = i * 1000000
        max_val = (i + 1) * 1000000
        callback_data = f"range_{min_val}_{max_val}"
        button_text = f"From {max_val}$ to {min_val}$"
        keyboard.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    keyboard.add(InlineKeyboardButton("Close", callback_data="close_range"))

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text="Select market capitalization range:",
        reply_markup=keyboard
    )

    range_message_states[message_id] = {"state": "selecting_range"}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Ошибка чтения кеша из файла {CACHE_FILE}. Создается новый кеш.")
            return {}
    return {}

def format_number(number):
    if number is not None:
        if number == 0:
          return 0
        formatted_number = "{:.10f}".format(number)
        while formatted_number.endswith("0") and "." in formatted_number:
            formatted_number = formatted_number[:-1]
        if formatted_number.endswith("."):
            formatted_number = formatted_number[:-1]
        return formatted_number

    return "N/A"

def create_short_message(coin_data):
    return f"""
<b>{coin_data['name']}</b>

Market Cap: ${int(coin_data['market_cap'])}
Current Price: ${format_number(coin_data['current_price'])}
"""

def create_expanded_message(coin_data):
    message = f"""
<b>{coin_data['name']}</b>

Current Price: <b>{format_number(coin_data['current_price'])}$</b>
Market Cap: <b>{int(coin_data['market_cap'])}$</b>
Liquidity: <b>{int(coin_data.get('liquidity_usd', 0))}$</b>
24h Price Change: <b>{format_number(coin_data.get('price_change_h24', 0))}%</b>
Total Volume: <b>{int(coin_data['total_volume'])}$</b>

Contract Address: {coin_data['contract_address']}
"""
    if coin_data.get("liquidity_usd", 0) < coin_data["market_cap"]:
        buys = coin_data.get('h1_buys', 'N/A')
        sells = coin_data.get('h1_sells', 'N/A')
        message += f"""
1h Buys/Sells: {buys}/{sells}
Price Change (5m): {format_number(coin_data.get('price_change_m5', 0))}%
Price Change (1h): {format_number(coin_data.get('price_change_h1', 0))}%
Price Change (6h): {format_number(coin_data.get('price_change_h6', 0))}%
Price Change (24h): {format_number(coin_data.get('price_change_h24', 0))}%
"""
    message += f"""
<b>Website:</b> {coin_data.get('website', 'N/A')}
<b>Telegram:</b> {coin_data.get('telegram', 'N/A')}
"""

    return message

@bot.callback_query_handler(func=lambda call: call.data.startswith("more_info_"))
def handle_more_info(call):
    try:
        coin_id = call.data.split("_")[2]
        print(f"DEBUG: handle_more_info called with coin_id: {coin_id}")
        noti_cache = load_noti_cache()
        print(f"DEBUG: noti_cache keys: {noti_cache.keys()}")

        coin_data = noti_cache.get(coin_id)

        if coin_data:
            message_states[call.message.message_id] = "expanded"
            full_message = create_expanded_message(coin_data)
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("DexScreener", url=coin_data.get('dexscreener_url', 'N/A')))
            keyboard.add(InlineKeyboardButton("Close", callback_data=f"close_info_{coin_id}"))
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=full_message,
                                  parse_mode='HTML', reply_markup=keyboard, disable_web_page_preview=True)
        else:
             print(f"DEBUG: Coin data not found in noti_cache for coin_id: {coin_id}")

    except Exception as e:
        print(f"DEBUG: Error in handle_more_info: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("close_info_"))
def handle_close_info(call):
    coin_id = call.data.split("_")[2]
    noti_cache = load_noti_cache()
    coin_data = noti_cache.get(coin_id)

    if coin_data:
        message_states[call.message.message_id] = "short"
        short_message = create_short_message(coin_data)
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("More Info...", callback_data=f"more_info_{coin_id}"))

        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=short_message, parse_mode='HTML', reply_markup=keyboard, disable_web_page_preview=True)

@bot.message_handler(commands=['test'])
def test_command(message):
    if message.text == "/test":
      bot.reply_to(message, "Working")

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = int(message.from_user.id)
    chat_id = int(message.chat.id)
    username = message.from_user.username

    if chat_id not in ALLOWED_CHAT_IDS:
        keyboard = InlineKeyboardMarkup()
        yes_button = InlineKeyboardButton("Да", callback_data=f"allow_user:{user_id}:{chat_id}")
        no_button = InlineKeyboardButton("Нет", callback_data=f"deny_user:{user_id}:{chat_id}")
        keyboard.add(yes_button, no_button)
        bot.send_message(ADMIN_CHAT_ID, f"@{username} запрашивает доступ к боту, разрешить?\n(ID: {user_id}, Chat ID: {chat_id})", reply_markup=keyboard)
    else:
        send_welcome_message(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("allow_user:"))
def allow_user_callback(call):
    try:
        _, user_id_str, chat_id_str = call.data.split(":")
        parts = call.data.strip().split(":")
        print(f"DEBUG: Parts after split: {parts}")
        if len(parts) == 3:
            _, user_id_str, chat_id_str = parts
            user_id = int(user_id_str)
            chat_id = int(chat_id_str)
            ALLOWED_CHAT_IDS.add(chat_id)
            bot.answer_callback_query(call.id, "Доступ разрешен")
            send_welcome_message(chat_id)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        else:
             print(f"DEBUG: Incorrect number of parts in call.data: {len(parts)}")
             bot.send_message(ADMIN_CHAT_ID, "Ошибка: некорректный формат callback_data.")

    except (ValueError, TypeError) as e:
        print(f"Ошибка при обработке запроса на доступ: {e}")
        bot.send_message(ADMIN_CHAT_ID, "Произошла ошибка при обработке запроса на доступ. Пожалуйста, попробуйте еще раз.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("deny_user:"))
def deny_user_callback(call):
    try:
        _, user_id_str, chat_id_str = call.data.split(":")
        user_id = int(user_id_str)
        chat_id = int(chat_id_str)
        bot.send_message(chat_id, "Вам отказано в доступе, обратитесь за поддержкой к @DEXund_0")
        bot.answer_callback_query(call.id, "Доступ отклонен")
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"Доступ отклонен для пользователя с ID: {user_id}")

    except (ValueError, TypeError) as e:
        print(f"Ошибка при обработке запроса на доступ: {e}")
        bot.send_message(ADMIN_CHAT_ID, "Произошла ошибка при обработке запроса на доступ. Пожалуйста, попробуйте еще раз.")

def send_welcome_message(chat_id):
    global MIN_MARKET_CAP, MAX_MARKET_CAP
    update_start_message(chat_id, MIN_MARKET_CAP, MAX_MARKET_CAP)

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=10, min=1, max=60), retry=retry_if_exception_type(requests.exceptions.HTTPError))
def fetch_dexscreener_data(contract_address):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        pairs = data.get("pairs", [])
        if pairs:
            pair = pairs[0]
            websites = pair.get("info", {}).get("websites", [])
            website = websites[0].get("url", "N/A") if websites else "N/A"

            socials = pair.get("info", {}).get("socials", [])
            telegram = next((social.get("url") for social in socials if social.get("type") == "telegram"), "N/A")


            return {
                "dexscreener_url": pair.get("url"),
                "h1_buys": pair.get("txns", {}).get("h1", {}).get("buys"),
                "h1_sells": pair.get("txns", {}).get("h1", {}).get("sells"),
                "price_change_m5": pair.get("priceChange", {}).get("m5"),
                "price_change_h1": pair.get("priceChange", {}).get("h1"),
                "price_change_h6": pair.get("priceChange", {}).get("h6"),
                "price_change_h24": pair.get("priceChange", {}).get("h24"),
                "liquidity_usd": pair.get("liquidity", {}).get("usd"),
                "website": website,
                "telegram": telegram
            }
        return None

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к DexScreener API: {e}")
        return None

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=10, min=1, max=300),
      retry=retry_if_exception_type((requests.exceptions.HTTPError, ConnectionError, ChunkedEncodingError, RemoteDisconnected, Timeout)))
def fetch_with_tenacity(url, params=None, headers=None):
    try:
        response = requests.get(url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, RemoteDisconnected, Timeout) as e:
        print(f"Ошибка при запросе к API: {e}, URL: {url}, Params: {params}")
        raise

def load_non_solana_cache():
    non_solana_file = "non_solana_tokens.json"
    if os.path.exists(non_solana_file):
        try:
            with open(non_solana_file, "r") as f:
                return set(json.load(f))
        except json.JSONDecodeError:
            print(f"Ошибка чтения не-Solana кеша из файла {non_solana_file}. Создается новый кеш.")
            return set()
    return set()
def save_cache(cache, non_solana_cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=4)
        non_solana_file = "non_solana_tokens.json"
        with open(non_solana_file, "w") as f:
            json.dump(list(non_solana_cache), f, indent=4)
    except IOError as e:
        print(f"Ошибка записи кеша в файл: {e}")

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=10, min=1, max=60), retry=retry_if_exception_type(HTTPError))
def fetch_coins_markets(page=1, ids=None):
    params = {
        "vs_currency": "usd",
        "page": page,
        "per_page": 250
    }
    if ids:
        params["ids"] = ids
    headers = {"x_cg_pro_api_key": API_KEY}

    coins = fetch_with_tenacity(f"{BASE_URL}/coins/markets", params=params, headers=headers)

    if coins is None:
        print(f"Ошибка получения данных с CoinGecko API (страница {page}). Повторная попытка через {RETRY_DELAY} секунд.")
        time.sleep(RETRY_DELAY)
        return None

    return coins

def check_and_send_notifications(noti_cache_ref):
    while True:
        noti_cache = noti_cache_ref[0]

        for coin_id_in_cache, coin_data in list(noti_cache.items()):
            coin_id = coin_data.get('id')

            if coin_id is None:
                continue

            if not coin_data.get("notified", False) and coin_data.get("copied", False):
                if send_telegram_notification(coin_id, coin_data):
                    noti_cache[coin_id_in_cache]["notified"] = True
                    save_noti_cache(noti_cache)

        time.sleep(60)

def fetch_coin(id):
    headers = {"x_cg_api_key": API_KEY}
    try:
        coin_data = fetch_with_tenacity(f"{BASE_URL}/coins/{id}", headers=headers)
        if coin_data:
            name = coin_data.get("name")
            market_cap = coin_data.get("market_cap")
            contract_address = coin_data.get("platforms", {}).get("solana")

            if contract_address:
                print(f"{Fore.GREEN}Получен контракт для {name} (Market Cap: {market_cap}): {contract_address}{Style.RESET_ALL}")

            market_data = coin_data.get("market_data", {})
            current_price = market_data.get("current_price", {}).get("usd")
            price_change_24h = market_data.get("price_change_24h")
            price_change_percentage_24h = market_data.get("price_change_percentage_24h")
            total_volume = market_data.get("total_volume", {}).get("usd")

            result = {
                "id": id,
                "name": name,
                "market_cap": market_cap,
                "contract_address": contract_address,
                "current_price": current_price,
                "price_change_24h": price_change_24h,
                "price_change_percentage_24h": price_change_percentage_24h,
                "total_volume": total_volume
            }

            return result
        else:
            return None

    except requests.exceptions.HTTPError as e:
        print(f"Ошибка при запросе к API: {e}")
        return None

def send_telegram_notification(coin_id, coin_data):
    short_message = create_short_message(coin_data)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("More Info...", callback_data=f"more_info_{coin_id}"))

    success = True
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            sent_message = bot.send_message(chat_id, short_message, parse_mode='HTML', reply_markup=keyboard, disable_web_page_preview=True)
            message_states[sent_message.message_id] = "short"
            print(f"Уведомление отправлено в Telegram (чат {chat_id}) для {coin_data['name']}")
        except Exception as e:
            print(f"Ошибка отправки уведомления в Telegram (чат {chat_id}): {e}")
            success = False
    return success

def main():
    global start_messages, MIN_MARKET_CAP, MAX_MARKET_CAP

    cache = load_cache()
    non_solana_cache = load_non_solana_cache()
    dex_cache = load_dex_cache()
    noti_cache = load_noti_cache()
    noti_cache_ref = [noti_cache]
    users = load_users()

    notifications_thread = threading.Thread(target=check_and_send_notifications, args=(noti_cache_ref,))
    notifications_thread.daemon = True
    notifications_thread.start()

    bot_thread = threading.Thread(target=bot.polling, kwargs={"none_stop": True})
    bot_thread.daemon = True
    bot_thread.start()

    for chat_id in ALLOWED_CHAT_IDS:
        send_welcome_message(chat_id)

    def update_pinned_message():
        global MIN_MARKET_CAP, MAX_MARKET_CAP
        for chat_id in ALLOWED_CHAT_IDS:
            update_start_message(chat_id, MIN_MARKET_CAP, MAX_MARKET_CAP)

        timer = threading.Timer(24 * 60 * 60, update_pinned_message)
        timer.start()

    update_pinned_message()

    while True:
        print(f"DEBUG: MIN_MARKET_CAP = {MIN_MARKET_CAP}, MAX_MARKET_CAP = {MAX_MARKET_CAP}")
        candidates = []
        page = 1
        break_outer_loop = False
        while True:
            for chat_id in ALLOWED_CHAT_IDS:
                min_cap = user_ranges.get(chat_id, {}).get("min", MIN_MARKET_CAP)
                max_cap = user_ranges.get(chat_id, {}).get("max", MAX_MARKET_CAP)

            log_debug(f"Проверяется страница {page}...")
            coins = fetch_coins_markets(page)
            if coins is None:
                break

            found_on_page = False
            for coin in coins:
                market_cap = coin.get("market_cap")
                if market_cap is None:
                    continue

                log_debug(f"  Проверяется токен: {coin['name']}, Market Cap: {coin['market_cap']}")

                if market_cap < min_cap:
                    print(
                        f"{Fore.YELLOW}Итерация сбора токенов прекращена на токене {coin['name']} (Market Cap: {market_cap}), так как его рыночная капитализация ниже минимального значения.{Style.RESET_ALL}")
                    break_outer_loop = True
                    break

                if min_cap <= market_cap <= max_cap:
                    candidates.append(coin)
                    found_on_page = True

            if break_outer_loop:
                break

            if not found_on_page and len(coins) < 250:
                break

            page += 1

        new_candidates = [coin for coin in candidates if coin["id"] not in cache and coin["id"] not in non_solana_cache]
        for coin in new_candidates:
            coin_id = coin["id"]

            coin_data = fetch_coin(coin_id)
            time.sleep(1)

            if coin_data:
                if coin_data["contract_address"]:
                    if coin_id not in cache:
                        cache[coin_id] = {
                            "name": coin_data["name"],
                            "market_cap": coin_data["market_cap"],
                            "contract_address": coin_data["contract_address"],
                            "current_price": coin_data["current_price"],
                            "price_change_24h": coin_data["price_change_24h"],
                            "price_change_percentage_24h": coin_data["price_change_percentage_24h"],
                            "total_volume": coin_data["total_volume"],

                            "notified": False
                        }
                else:
                    non_solana_cache.add(coin_id)

        save_cache(cache, non_solana_cache)

        dex_cache = load_dex_cache()
        if cache:
            ids = ",".join(cache.keys())
            for _ in range(5):
                updated_coins = fetch_coins_markets(ids=ids)
                if updated_coins is None:
                    break

                for updated_coin in updated_coins:
                    coin_id = updated_coin['id']
                    if coin_id in cache:
                        cache[coin_id]["market_cap"] = updated_coin.get("market_cap")

                        for chat_id in ALLOWED_CHAT_IDS:
                            min_cap = user_ranges.get(chat_id, {}).get("min",
                                                                       MIN_MARKET_CAP)
                            max_cap = user_ranges.get(chat_id, {}).get("max",
                                                                       MAX_MARKET_CAP)

                            if updated_coin.get("market_cap", 0) > max_cap and not cache[coin_id].get("notified_chats",
                                                                                                      {}).get(chat_id,
                                                                                                              False):
                                cache[coin_id].setdefault("notified_chats", {})[
                                    chat_id] = True
                                if copy_to_dex_cache(coin_id, cache[coin_id], dex_cache):
                                    dexscreener_data = fetch_dexscreener_data(cache[coin_id]["contract_address"])

                                    if dexscreener_data:
                                        dex_cache[coin_id].update(dexscreener_data)

                                        if copy_to_noti_cache(coin_id, dex_cache[coin_id], noti_cache_ref):
                                            dex_cache[coin_id]["notified"] = True
                                            print(
                                                f"ВНИМАНИЕ! {updated_coin['name'].upper()} БЫЛ ПЕРЕКОПИРОВАН В {NOTI_CACHE_FILE.upper()} (для чата {chat_id})! Ожидает отправки уведомления.")

                                save_dex_cache(dex_cache)
                                save_noti_cache(noti_cache)
                time.sleep(DELAY)
            save_cache(cache, non_solana_cache)
        save_dex_cache(dex_cache)
        save_noti_cache(noti_cache)
        time.sleep(DELAY)

if __name__ == "__main__":
    main()