import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from dotenv import load_dotenv
from flask import Flask, request
from datetime import datetime, timedelta
import urllib.parse

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN не найден в переменных окружения")
    raise ValueError("BOT_TOKEN не установлен")

WEBHOOK_URL = os.getenv('WEBHOOK_URL')
if not WEBHOOK_URL:
    logging.error("WEBHOOK_URL не установлен")
    raise ValueError("WEBHOOK_URL не установлен")

# Инициализация бота и Flask
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Блокировка для thread-safe доступа к БД
db_lock = threading.Lock()

# Инициализация базы данных
def init_database():
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                item TEXT PRIMARY KEY,
                owner TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_date DATE NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

init_database()

# Состояния пользователей
user_states = {}

# Функция для нормализации текста
def normalize_text(text):
    return ' '.join(text.strip().split()).lower()

# Функции для работы с инвентарем
def get_inventory():
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT item, owner FROM inventory ORDER BY item')
        items = cursor.fetchall()
        conn.close()
        return {item: owner for item, owner in items}

def add_item(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO inventory (item, owner) VALUES (?, ?)', (item_name, None))
        conn.commit()
        conn.close()

def delete_item(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM inventory WHERE item = ?', (item_name,))
        conn.commit()
        conn.close()

def update_item_owner(item_name, owner):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE inventory SET owner = ? WHERE item = ?', (owner, item_name))
        conn.commit()
        conn.close()

def find_item_in_db(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT item FROM inventory')
        all_items = cursor.fetchall()
        conn.close()
        normalized_search = normalize_text(item_name)
        for (db_item,) in all_items:
            if normalize_text(db_item) == normalized_search:
                return db_item
        return None

# Функции для работы с событиями
def add_event(event_name, event_date):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO events (event_name, event_date) VALUES (?, ?)', (event_name, event_date))
        conn.commit()
        conn.close()

def get_events(start_date=None, end_date=None):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        if start_date and end_date:
            cursor.execute('SELECT id, event_name, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date',
                           (start_date, end_date))
        else:
            cursor.execute('SELECT id, event_name, event_date FROM events ORDER BY event_date')
        events = cursor.fetchall()
        conn.close()
        return events

def delete_event(event_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
        conn.commit()
        conn.close()

# Создаем клавиатуру стартового меню
def create_start_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(types.KeyboardButton('📦 Войти в инвентарь'))
    return keyboard

start_keyboard = create_start_keyboard()

# Создаем кастомную клавиатуру главного меню
def create_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить'),
        types.KeyboardButton('➖ Удалить'),
        types.KeyboardButton('🎁 Выдать'),
        types.KeyboardButton('↩️ Вернуть'),
        types.KeyboardButton('📋 Показать инвентарь'),
        types.KeyboardButton('🗓️ События')
    ]
    keyboard.add(*buttons)
    return keyboard

main_keyboard = create_main_keyboard()

# Создаем клавиатуру меню событий
def create_events_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить событие'),
        types.KeyboardButton('🗑️ Удалить событие'),
        types.KeyboardButton('📅 Посмотреть события'),
        types.KeyboardButton('🔙 Назад в меню')
    ]
    keyboard.add(*buttons)
    return keyboard

events_keyboard = create_events_keyboard()

# Функция для создания inline-клавиатуры с предметами
def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item in sorted(items):
        callback_data = f"{action}:{item}"
        keyboard.add(types.InlineKeyboardButton(text=item, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Функция для создания inline-клавиатуры с событиями
def create_event_keyboard(events, action):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for event_id, event_name, event_date in events:
        text = f"{event_name} ({event_date})"
        callback_data = f"{action}:{event_id}"
        keyboard.add(types.InlineKeyboardButton(text=text, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Функция для показа главного меню
def show_menu(chat_id):
    inventory = get_inventory()
    text = "📦 *ИНВЕНТАРЬ:*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for item, owner in sorted(inventory.items()):
            if owner is None:
                text += f"✅ **{item}** - доступен\n"
                available_count += 1
            else:
                text += f"🔸 {item} - {owner}\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=main_keyboard)
    user_states[chat_id] = 'main'

# Функция для показа меню событий
def show_events_menu(chat_id):
    bot.send_message(chat_id, "🗓️ *Меню событий*", parse_mode='Markdown', reply_markup=events_keyboard)
    user_states[chat_id] = 'events_main'

# Функция для показа событий
def show_events(chat_id, period='all'):
    today = datetime.now().date()
    if period == 'week':
        start_date = today
        end_date = today + timedelta(days=7)
    elif period == 'month':
        start_date = today
        end_date = today + timedelta(days=30)
    else:
        start_date = None
        end_date = None
    events = get_events(start_date, end_date)
    text = "🗓️ *События:*\n\n"
    if not events:
        text += "📭 Нет событий\n"
    else:
        for _, event_name, event_date in events:
            text += f"📅 {event_name} - {event_date}\n"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=events_keyboard)

# Обработчик сообщений
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'start')

    try:
        if state == 'start':
            if text == '📦 Войти в инвентарь':
                user_states[chat_id] = 'main'
                start_message = "👋 *Добро пожаловать в систему управления инвентарем!*\n\n"
                start_message += "📋 *Доступные команды:*\n"
                start_message += "➕ Добавить - добавить новый предмет\n"
                start_message += "➖ Удалить - удалить предмет\n"
                start_message += "🎁 Выдать - выдать предмет кому-то\n"
                start_message += "↩️ Вернуть - вернуть предмет в инвентарь\n"
                start_message += "📋 Показать инвентарь - обновить список\n"
                start_message += "🗓️ События - управление событиями"
                bot.send_message(chat_id, start_message, parse_mode='Markdown', reply_markup=main_keyboard)
                show_menu(chat_id)
            else:
                bot.send_message(chat_id, "Пожалуйста, используйте кнопку для входа.", reply_markup=start_keyboard)

        elif state == 'main':
            if text == '➕ Добавить':
                user_states[chat_id] = 'add'
                bot.send_message(chat_id, "📝 *Что вы хотите добавить?*\n(напишите 'стоп' для выхода)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '➖ Удалить':
                user_states[chat_id] = 'delete'
                inventory = get_inventory()
                if inventory:
                    keyboard = create_item_keyboard(inventory.keys(), 'delete')
                    bot.send_message(chat_id, "🗑️ *Выберите предмет для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=main_keyboard)
                    show_menu(chat_id)
            elif text == '🎁 Выдать':
                user_states[chat_id] = 'give_who'
                bot.send_message(chat_id, "👤 *Кому выдать предмет?*\n(напишите имя получателя или 'стоп' для выхода)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = 'return_items'
                inventory = get_inventory()
                issued_items = [item for item, owner in inventory.items() if owner is not None]
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    keyboard.add(types.InlineKeyboardButton(text="🔄 Вернуть все", callback_data="return:all"))
                    bot.send_message(chat_id, "📦 *Выберите предмет для возврата:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=main_keyboard)
                    show_menu(chat_id)
            elif text == '📋 Показать инвентарь':
                show_menu(chat_id)
            elif text == '🗓️ События':
                show_events_menu(chat_id)
            else:
                show_menu(chat_id)

        elif state == 'add':
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
            elif text:
                existing_item = find_item_in_db(text)
                if existing_item is None:
                    item_name = ' '.join(text.strip().split())
                    add_item(item_name)
                    bot.send_message(chat_id, f"✅ *{item_name}* добавлен в инвентарь!\nЧто еще добавить? (стоп для выхода)",
                                   parse_mode='Markdown')
                else:
                    bot.send_message(chat_id, f"⚠️ *{existing_item}* уже есть в инвентаре!\nЧто еще добавить? (стоп для выхода)",
                                   parse_mode='Markdown')

        elif state == 'give_who':
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
            elif text:
                recipient = ' '.join(text.strip().split())
                user_states[chat_id] = ('give_items', recipient)
                inventory = get_inventory()
                available_items = [item for item, owner in inventory.items() if owner is None]
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'give')
                    bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предмет для выдачи:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет доступных предметов для выдачи!", reply_markup=main_keyboard)
                    show_menu(chat_id)

        elif state == 'events_main':
            if text == '➕ Добавить событие':
                user_states[chat_id] = 'add_event_name'
                bot.send_message(chat_id, "📝 *Введите название события:* (стоп для выхода)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '🗑️ Удалить событие':
                user_states[chat_id] = 'delete_event'
                events = get_events()
                if events:
                    keyboard = create_event_keyboard(events, 'delete_event')
                    bot.send_message(chat_id, "🗑️ *Выберите событие для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет событий!", reply_markup=events_keyboard)
                    show_events_menu(chat_id)
            elif text == '📅 Посмотреть события':
                keyboard = types.InlineKeyboardMarkup(row_width=3)
                keyboard.add(
                    types.InlineKeyboardButton("На неделю", callback_data="view_events:week"),
                    types.InlineKeyboardButton("На месяц", callback_data="view_events:month"),
                    types.InlineKeyboardButton("Все", callback_data="view_events:all")
                )
                bot.send_message(chat_id, "📅 *Выберите период:*",
                               parse_mode='Markdown', reply_markup=keyboard)
            elif text == '🔙 Назад в меню':
                bot.send_message(chat_id, "👌 Возвращаемся в главное меню", reply_markup=main_keyboard)
                show_menu(chat_id)
            else:
                show_events_menu(chat_id)

        elif state == 'add_event_name':
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню событий", reply_markup=events_keyboard)
                show_events_menu(chat_id)
            elif text:
                event_name = ' '.join(text.strip().split())
                user_states[chat_id] = ('add_event_date', event_name)
                bot.send_message(chat_id, f"📅 *Введите дату события* (формат: YYYY-MM-DD):",
                               parse_mode='Markdown')

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню событий", reply_markup=events_keyboard)
                show_events_menu(chat_id)
            elif text:
                try:
                    event_date = datetime.strptime(text, '%Y-%m-%d').date()
                    event_name = state[1]
                    add_event(event_name, event_date)
                    bot.send_message(chat_id, f"✅ Событие *{event_name}* на {event_date} добавлено!",
                                   parse_mode='Markdown', reply_markup=events_keyboard)
                    show_events_menu(chat_id)
                except ValueError:
                    bot.send_message(chat_id, "⚠️ Неправильный формат даты! Попробуйте снова (YYYY-MM-DD).")

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_keyboard)
        show_menu(chat_id)

# Обработчик callback-запросов
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data.split(':')
    action = data[0]
    item_or_id = data[1] if len(data) > 1 else None

    try:
        if action == 'give':
            if item_or_id == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return
            state = user_states.get(chat_id, 'main')
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient = state[1]
                inventory = get_inventory()
                if item_or_id in inventory:
                    if inventory[item_or_id] is None:
                        update_item_owner(item_or_id, recipient)
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"✅ *{item_or_id}* выдан *{recipient}*!",
                                       parse_mode='Markdown', reply_markup=main_keyboard)
                        show_menu(chat_id)
                    else:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"⚠️ *{item_or_id}* уже выдан *{inventory[item_or_id]}*!",
                                       parse_mode='Markdown', reply_markup=main_keyboard)
                        show_menu(chat_id)
        elif action == 'delete':
            if item_or_id == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return
            if item_or_id:
                delete_item(item_or_id)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ *{item_or_id}* удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=main_keyboard)
                show_menu(chat_id)
        elif action == 'return':
            if item_or_id == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return
            elif item_or_id == 'all':
                inventory = get_inventory()
                returned_count = 0
                for item in inventory:
                    if inventory[item] is not None:
                        update_item_owner(item, None)
                        returned_count += 1
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                               parse_mode='Markdown', reply_markup=main_keyboard)
                show_menu(chat_id)
            elif item_or_id:
                inventory = get_inventory()
                if item_or_id in inventory and inventory[item_or_id] is not None:
                    update_item_owner(item_or_id, None)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ *{item_or_id}* возвращен в инвентарь!",
                                   parse_mode='Markdown', reply_markup=main_keyboard)
                    show_menu(chat_id)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"ℹ️ *{item_or_id}* уже в инвентаре!",
                                   parse_mode='Markdown', reply_markup=main_keyboard)
                    show_menu(chat_id)
        elif action == 'delete_event':
            if item_or_id == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню событий", reply_markup=events_keyboard)
                show_events_menu(chat_id)
                return
            if item_or_id:
                delete_event(int(item_or_id))
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Событие удалено!",
                               parse_mode='Markdown', reply_markup=events_keyboard)
                show_events_menu(chat_id)
        elif action == 'view_events':
            bot.delete_message(chat_id, call.message.message_id)
            period = item_or_id
            show_events(chat_id, period)
            show_events_menu(chat_id)

    except Exception as e:
        logging.error(f"Ошибка при обработке callback от {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_keyboard)
        show_menu(chat_id)

# Flask-роут для обработки webhook
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_json())
        if update.message:
            handle_message(update.message)
        if update.callback_query:
            handle_callback_query(update.callback_query)
        return 'OK', 200
    except Exception as e:
        logging.error(f"Ошибка в webhook: {e}")
        return 'Error', 500

# Роут для проверки работоспособности
@app.route('/')
def index():
    return 'Bot is running', 200

# Настройка webhook при запуске
def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
    bot.remove_webhook()
    success = bot.set_webhook(url=webhook_url)
    if success:
        logging.info(f"Webhook успешно установлен: {webhook_url}")
    else:
        logging.error("Не удалось установить webhook")
        raise ValueError("Не удалось установить webhook")

# Очистка старых состояний пользователей
def clean_old_states():
    while True:
        time.sleep(3600)  # Каждые 60 минут
        current_time = time.time()
        for chat_id in list(user_states.keys()):
            if isinstance(user_states[chat_id], dict) and current_time - user_states[chat_id].get('last_activity', 0) > 3600:
                del user_states[chat_id]

# Запуск приложения
if __name__ == '__main__':
    logging.info("Запуск бота...")
    threading.Thread(target=clean_old_states, daemon=True).start()
    set_webhook()
    port = int(os.getenv('PORT', 8443))  # Используем PORT из окружения или 8443
    logging.info(f"Запуск Flask на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
