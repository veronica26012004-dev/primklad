import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from datetime import datetime, timedelta
from uuid import uuid4
import re

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Загрузка токена
TOKEN = os.getenv('BOT_TOKEN', '8464322471:AAE3QyJrHrCS8lwAj4jD8NLuOy5kYnToumM')
bot = telebot.TeleBot(TOKEN)

# Блокировка для thread-safe доступа к БД
db_lock = threading.Lock()

# Словарь для месяцев
MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
    'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}

# Инициализация базы данных
def init_database():
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    owner TEXT,
                    issued INTEGER DEFAULT 0,
                    storage TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    event_date TEXT NOT NULL
                )
            ''')
            conn.commit()
            logging.info("Database initialized successfully")
        except Exception as e:
            logging.error(f"Error initializing database: {e}")
        finally:
            conn.close()

init_database()

# Состояния пользователей
user_states = {}

# Функция для нормализации текста
def normalize_text(text):
    return ' '.join(text.strip().split()).lower()

# Функции для работы с предметами
def get_inventory(storage=None):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            if storage:
                cursor.execute('SELECT id, item_name, owner, issued, storage FROM items WHERE storage = ?', (storage,))
            else:
                cursor.execute('SELECT id, item_name, owner, issued, storage FROM items')
            items = cursor.fetchall()
            logging.info(f"Fetched inventory for storage {storage}: {items}")
            conn.close()
            return items
        except Exception as e:
            logging.error(f"Error fetching inventory: {e}")
            return []

def add_item(item_name, storage):
    item_id = str(uuid4())
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO items (id, item_name, owner, issued, storage) VALUES (?, ?, ?, ?, ?)', 
                          (item_id, item_name, None, 0, storage))
            conn.commit()
            logging.info(f"Added item: {item_name}, storage: {storage}, id: {item_id}")
            conn.close()
            return item_id
        except Exception as e:
            logging.error(f"Error adding item {item_name}: {e}")
            conn.close()
            return None

def delete_item(item_name, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM items WHERE item_name = ? AND storage = ?', (item_name, storage))
            conn.commit()
            logging.info(f"Deleted item: {item_name} from storage: {storage}")
            conn.close()
        except Exception as e:
            logging.error(f"Error deleting item {item_name}: {e}")

def update_item_owner(item_name, owner, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT item_name FROM items WHERE storage = ?', (storage,))
            all_items = cursor.fetchall()
            normalized_search = normalize_text(item_name)
            for (db_item,) in all_items:
                if normalize_text(db_item) == normalized_search:
                    cursor.execute('UPDATE items SET owner = ?, issued = 1 WHERE item_name = ? AND storage = ?', 
                                  (owner, db_item, storage))
                    conn.commit()
                    logging.info(f"Updated item {db_item} in {storage} to owner: {owner}")
                    conn.close()
                    return
            logging.warning(f"Item {item_name} not found in {storage}")
            conn.close()
        except Exception as e:
            logging.error(f"Error updating item {item_name} owner: {e}")
            conn.close()

def return_item(item_name, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT item_name FROM items WHERE storage = ?', (storage,))
            all_items = cursor.fetchall()
            normalized_search = normalize_text(item_name)
            for (db_item,) in all_items:
                if normalize_text(db_item) == normalized_search:
                    cursor.execute('UPDATE items SET owner = NULL, issued = 0 WHERE item_name = ? AND storage = ?', 
                                  (db_item, storage))
                    conn.commit()
                    logging.info(f"Returned item: {db_item} in {storage}")
                    conn.close()
                    return
            logging.warning(f"Item {item_name} not found in {storage}")
            conn.close()
        except Exception as e:
            logging.error(f"Error returning item {item_name}: {e}")

def find_item_in_db(item_name, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT item_name FROM items WHERE storage = ?', (storage,))
            all_items = cursor.fetchall()
            conn.close()
            normalized_search = normalize_text(item_name)
            for (db_item,) in all_items:
                if normalize_text(db_item) == normalized_search:
                    return db_item
            return None
        except Exception as e:
            logging.error(f"Error finding item {item_name} in storage {storage}: {e}")
            return None

# Функции для работы с событиями
def add_event(event_name, event_date):
    event_id = str(uuid4())
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO events (id, event_name, event_date) VALUES (?, ?, ?)',
                          (event_id, event_name, event_date))
            conn.commit()
            logging.info(f"Added event: {event_name}, date: {event_date}")
            conn.close()
            return event_id
        except Exception as e:
            logging.error(f"Error adding event {event_name}: {e}")
            conn.close()
            return None

def get_events(period=None):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            current_date = datetime.now().strftime('%Y-%m-%d')
            if period == 'week':
                end_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
                cursor.execute('SELECT event_name, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', 
                              (current_date, end_date))
            elif period == 'month':
                end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                cursor.execute('SELECT event_name, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', 
                              (current_date, end_date))
            else:
                cursor.execute('SELECT event_name, event_date FROM events ORDER BY event_date')
            events = cursor.fetchall()
            logging.info(f"Fetched {len(events)} events for period '{period}'")
            conn.close()
            return events
        except Exception as e:
            logging.error(f"Error fetching events: {e}")
            return []

def delete_event(event_name, event_date):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM events WHERE event_name = ? AND event_date = ?', (event_name, event_date))
            conn.commit()
            logging.info(f"Deleted event: {event_name}, {event_date}")
            conn.close()
        except Exception as e:
            logging.error(f"Error deleting event {event_name}: {e}")

# Клавиатуры
def create_main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📦 Кладовая'),
        types.KeyboardButton('📅 События')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_storage_selection_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📍 Гринбокс 11'),
        types.KeyboardButton('📍 Гринбокс 12'),
        types.KeyboardButton('🔙 В главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_storage_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить'),
        types.KeyboardButton('➖ Удалить'),
        types.KeyboardButton('🎁 Выдать'),
        types.KeyboardButton('↩️ Вернуть'),
        types.KeyboardButton('📋 Показать инвентарь'),
        types.KeyboardButton('🔙 Назад')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_events_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить событие'),
        types.KeyboardButton('📅 Посмотреть события'),
        types.KeyboardButton('🗑️ Удалить событие'),
        types.KeyboardButton('🔙 В главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_items_keyboard(storage, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    items = get_inventory(storage)
    buttons = []
    for _, item_name, owner, issued, _ in sorted(items, key=lambda x: x[1]):
        safe_item_name = re.sub(r'[^\w\s-]', '', item_name).replace(' ', '-').replace('_', '-')
        max_item_length = 64 - len(action) - len(storage) - 2
        safe_item_name = safe_item_name[:max_item_length]
        callback_data = f"{action}_{safe_item_name}_{storage}"
        if len(callback_data.encode('utf-8')) > 64:
            logging.warning(f"Callback data too long for item '{item_name}' in {storage}: {callback_data}")
            continue
        if action == 'delete':
            buttons.append(types.InlineKeyboardButton(text=item_name, callback_data=callback_data))
        elif action == 'give' and owner is None and issued == 0:
            buttons.append(types.InlineKeyboardButton(text=item_name, callback_data=callback_data))
        elif action == 'return' and issued == 1:
            buttons.append(types.InlineKeyboardButton(text=item_name, callback_data=callback_data))
    keyboard.add(*buttons)
    if not buttons:
        logging.info(f"No valid buttons created for {action} in {storage}")
        return None
    return keyboard

# Функции отображения
def show_main_menu(chat_id):
    text = "📋 *Главное меню*\n\nВыберите раздел:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[chat_id] = 'main_menu'

def show_storage_selection(chat_id):
    text = "📦 *Выберите кладовую:*"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_selection_keyboard())
    user_states[chat_id] = 'storage_selection'

def show_inventory(chat_id, storage):
    inventory = get_inventory(storage)
    text = f"📦 *ИНВЕНТАРЬ ({storage}):*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for _, item_name, owner, issued, _ in sorted(inventory, key=lambda x: x[1]):
            if owner is None and issued == 0:
                text += f"✅ **{item_name}** - доступен\n"
                available_count += 1
            else:
                text += f"🔸 {item_name} - {owner or 'не указано'}\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_keyboard())
    user_states[chat_id] = ('storage', storage)

# Обработчики текстовых сообщений
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем и событиями!*\n\n"
    welcome_text += "📋 *Доступные разделы:*\n"
    welcome_text += "📦 Кладовая - управление инвентарем\n"
    welcome_text += "📅 События - управление событиями"
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    show_main_menu(message.chat.id)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'main_menu')
    logging.info(f"Received message from {chat_id}: {text}, state: {state}")

    try:
        if state == 'main_menu':
            if text == '📦 Кладовая':
                show_storage_selection(chat_id)
            elif text == '📅 События':
                user_states[chat_id] = 'events'
                bot.send_message(chat_id, "📅 *События*\n\nВыберите действие:", 
                               parse_mode='Markdown', reply_markup=create_events_keyboard())
            else:
                show_main_menu(chat_id)

        elif state == 'storage_selection':
            if text == '📍 Гринбокс 11':
                show_inventory(chat_id, 'Гринбокс 11')
            elif text == '📍 Гринбокс 12':
                show_inventory(chat_id, 'Гринбокс 12')
            elif text == '🔙 В главное меню':
                show_main_menu(chat_id)
            else:
                show_storage_selection(chat_id)

        elif isinstance(state, tuple) and state[0] == 'storage':
            storage = state[1]
            if text == '🔙 Назад':
                show_storage_selection(chat_id)
            elif text == '➕ Добавить':
                user_states[chat_id] = ('add', storage)
                bot.send_message(chat_id, "📝 *Введите предметы (каждый с новой строки) или 'стоп' для выхода:*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '➖ Удалить':
                keyboard = create_items_keyboard(storage, 'delete')
                if keyboard:
                    user_states[chat_id] = ('delete', storage)
                    bot.send_message(chat_id, "🗑️ *Выберите предмет для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "📭 Нет предметов для удаления!", 
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
            elif text == '🎁 Выдать':
                user_states[chat_id] = ('give_who', storage)
                bot.send_message(chat_id, "👤 *Кому выдать предмет?*\n(напишите имя получателя или 'стоп' для выхода)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                keyboard = create_items_keyboard(storage, 'return')
                if keyboard:
                    user_states[chat_id] = ('return', storage)
                    bot.send_message(chat_id, "📦 *Выберите предмет для возврата:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "📭 Нет выданных предметов для возврата!", 
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
            elif text == '📋 Показать инвентарь':
                show_inventory(chat_id, storage)

        elif isinstance(state, tuple) and state[0] == 'add':
            storage = state[1]
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
            elif text:
                items = [item.strip() for item in text.split('\n') if item.strip()]
                if not items:
                    bot.send_message(chat_id, "⚠️ Введите хотя бы один предмет!", parse_mode='Markdown')
                    return
                added_items = []
                existing_items = []
                for item_name in items:
                    existing_item = find_item_in_db(item_name, storage)
                    if existing_item is None:
                        add_item(item_name, storage)
                        added_items.append(item_name)
                    else:
                        existing_items.append(existing_item)
                response = ""
                if added_items:
                    response += f"✅ Добавлены предметы: {', '.join(added_items)}\n"
                if existing_items:
                    response += f"⚠️ Уже существуют: {', '.join(existing_items)}\n"
                response += "📝 Введите еще предметы (каждый с новой строки) или 'стоп' для выхода:"
                bot.send_message(chat_id, response, parse_mode='Markdown')

        elif isinstance(state, tuple) and state[0] == 'give_who':
            storage = state[1]
            logging.info(f"Processing 'give_who' for storage: {storage}, input: {text}")
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
            elif text.strip():
                recipient = ' '.join(text.strip().split())
                user_states[chat_id] = ('give_items', recipient, storage)
                logging.info(f"Set state to ('give_items', {recipient}, {storage})")
                keyboard = create_items_keyboard(storage, 'give')
                logging.info(f"Keyboard for 'give' action: {keyboard}")
                if keyboard:
                    bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предмет для выдачи:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "📭 Нет доступных предметов для выдачи!", 
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
            else:
                bot.send_message(chat_id, "⚠️ Имя получателя не может быть пустым!", parse_mode='Markdown')

        elif state == 'events':
            if text == '🔙 В главное меню':
                show_main_menu(chat_id)
            elif text == '➕ Добавить событие':
                user_states[chat_id] = 'add_event_name'
                bot.send_message(chat_id, "📝 *Введите название события:*", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '📅 Посмотреть события':
                events = get_events()
                if not events:
                    bot.send_message(chat_id, "📅 Нет событий!", reply_markup=create_events_keyboard())
                else:
                    text = "📅 *События:*\n\n"
                    for event_name, event_date in events:
                        try:
                            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                            formatted_date = date_obj.strftime('%d.%m.%Y')
                            text += f"📌 *{event_name}* - {formatted_date}\n"
                        except ValueError:
                            text += f"📌 *{event_name}* - {event_date} (некорректный формат)\n"
                    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_events_keyboard())
            elif text == '🗑️ Удалить событие':
                user_states[chat_id] = 'delete_event'
                bot.send_message(chat_id, "🗑️ *Введите название события для удаления:*\n(напишите 'стоп' для выхода)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif state == 'add_event_name':
            if text and text.strip():
                user_states[chat_id] = ('add_event_date', text)
                bot.send_message(chat_id, "📅 *Введите дату события (например, 15 января 2025):*", 
                               parse_mode='Markdown')
            else:
                bot.send_message(chat_id, "⚠️ Название события не может быть пустым!", 
                               parse_mode='Markdown')

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            event_name = state[1]
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
            else:
                try:
                    parts = text.strip().split()
                    if len(parts) != 3:
                        raise ValueError("Неверный формат даты")
                    day, month_str, year = parts
                    day = int(day)
                    month = MONTHS.get(month_str.lower())
                    if not month:
                        raise ValueError("Неверное название месяца")
                    year = int(year)
                    event_date = f"{year}-{month:02d}-{day:02d}"
                    datetime.strptime(event_date, '%Y-%m-%d')
                    add_event(event_name, event_date)
                    bot.send_message(chat_id, f"✅ Событие *{event_name}* на {event_date} добавлено!", 
                                   parse_mode='Markdown', reply_markup=create_events_keyboard())
                    user_states[chat_id] = 'events'
                except ValueError as e:
                    bot.send_message(chat_id, f"⚠️ Неверный формат даты! Используйте 'ДД месяц ГГГГ' (например, 15 января 2025): {str(e)}", 
                                   parse_mode='Markdown')

        elif state == 'delete_event':
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
            elif text:
                user_states[chat_id] = ('delete_event_date', text)
                bot.send_message(chat_id, "📅 *Введите дату события (например, 15 января 2025):*", 
                               parse_mode='Markdown')

        elif isinstance(state, tuple) and state[0] == 'delete_event_date':
            event_name = state[1]
            if normalize_text(text) == 'стоп':
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
            else:
                try:
                    parts = text.strip().split()
                    if len(parts) != 3:
                        raise ValueError("Неверный формат даты")
                    day, month_str, year = parts
                    day = int(day)
                    month = MONTHS.get(month_str.lower())
                    if not month:
                        raise ValueError("Неверное название месяца")
                    year = int(year)
                    event_date = f"{year}-{month:02d}-{day:02d}"
                    datetime.strptime(event_date, '%Y-%m-%d')
                    delete_event(event_name, event_date)
                    bot.send_message(chat_id, f"✅ Событие *{event_name}* на {event_date} удалено!", 
                                   parse_mode='Markdown', reply_markup=create_events_keyboard())
                    user_states[chat_id] = 'events'
                except ValueError as e:
                    bot.send_message(chat_id, f"⚠️ Неверный формат даты! Используйте 'ДД месяц ГГГГ' (например, 15 января 2025): {str(e)}", 
                                   parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error processing message from {chat_id}: {e}")
        bot.send_message(chat_id, f"⚠️ Произошла ошибка: {str(e)}. Пожалуйста, попробуйте снова.", 
                        parse_mode='Markdown')
        if isinstance(state, tuple) and state[0] == 'storage':
            show_inventory(chat_id, state[1])
        elif state == 'storage_selection':
            show_storage_selection(chat_id)
        elif state == 'events':
            bot.send_message(chat_id, "📅 *События*\n\nВыберите действие:", 
                            parse_mode='Markdown', reply_markup=create_events_keyboard())
        else:
            show_main_menu(chat_id)

# Обработчик инлайн-кнопок
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data
    logging.info(f"Received callback query from {chat_id}: {data}")

    try:
        parts = data.split('_', 2)
        if len(parts) != 3:
            bot.answer_callback_query(call.id, "⚠️ Неверный формат данных!")
            return
        action, safe_item_name, storage = parts
        item_name = safe_item_name.replace('-', ' ')  # Восстанавливаем пробелы
        logging.info(f"Processing {action} callback: item_name={item_name}, storage={storage}")

        if action == 'delete':
            delete_item(item_name, storage)
            bot.answer_callback_query(call.id)
            bot.edit_message_text(f"✅ *{item_name}* удален из инвентаря!", 
                                chat_id=chat_id, message_id=call.message.message_id, parse_mode='Markdown')
            show_inventory(chat_id, storage)

        elif action == 'give':
            state = user_states.get(chat_id)
            logging.info(f"Current state: {state}")
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient = state[1]
                inventory = get_inventory(storage)
                logging.info(f"Inventory for {storage}: {inventory}")
                for _, db_item, owner, issued, _ in inventory:
                    if normalize_text(db_item) == normalize_text(item_name) and owner is None and issued == 0:
                        update_item_owner(db_item, recipient, storage)
                        bot.answer_callback_query(call.id)
                        bot.edit_message_text(f"✅ *{db_item}* выдан *{recipient}*!", 
                                            chat_id=chat_id, message_id=call.message.message_id, parse_mode='Markdown')
                        show_inventory(chat_id, storage)
                        break
                else:
                    bot.answer_callback_query(call.id, "⚠️ Предмет уже выдан или недоступен!")
                    show_inventory(chat_id, storage)
            else:
                bot.answer_callback_query(call.id, "⚠️ Ошибка: выберите получателя заново.")
                show_inventory(chat_id, storage)

        elif action == 'return':
            inventory = get_inventory(storage)
            for _, db_item, _, issued, _ in inventory:
                if normalize_text(db_item) == normalize_text(item_name) and issued == 1:
                    return_item(db_item, storage)
                    bot.answer_callback_query(call.id)
                    bot.edit_message_text(f"✅ *{db_item}* возвращен в инвентарь!", 
                                        chat_id=chat_id, message_id=call.message.message_id, parse_mode='Markdown')
                    show_inventory(chat_id, storage)
                    break
            else:
                bot.answer_callback_query(call.id, "⚠️ Предмет не выдан или недоступен!")
                show_inventory(chat_id, storage)

    except Exception as e:
        logging.error(f"Error processing callback query from {chat_id}: {e}")
        bot.answer_callback_query(call.id, f"⚠️ Ошибка: {str(e)}")
        state = user_states.get(chat_id)
        if isinstance(state, tuple) and state[0] == 'storage':
            show_inventory(chat_id, state[1])
        elif isinstance(state, tuple) and state[0] in ('give_items', 'give_who'):
            show_inventory(chat_id, state[-1])
        else:
            show_main_menu(chat_id)

# Запуск бота в режиме polling
if __name__ == '__main__':
    logging.info("🤖 Бот запущен в режиме polling...")
    bot.polling(none_stop=True)
