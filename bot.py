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

# Сопоставление хранилищ и их коротких идентификаторов
STORAGE_IDS = {
    'Гринбокс 11': 'gb11',
    'Гринбокс 12': 'gb12'
}
REVERSE_STORAGE_IDS = {v: k for k, v in STORAGE_IDS.items()}

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

# Состояния пользователей и выбор предметов/событий
user_states = {}
user_selections = {}  # Хранит выбранные id предметов или событий для каждого chat_id

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
            logging.info(f"Fetched inventory for storage {storage}: {len(items)} items")
            conn.close()
            return items
        except Exception as e:
            logging.error(f"Error fetching inventory: {e}")
            return []

def add_item(item_name, storage):
    item_id = str(uuid4())
    item_name = re.sub(r'[^\w\s-]', '', item_name.strip())[:50]  # Очистка и ограничение длины
    if not item_name:
        return None
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

def delete_items(item_ids, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            deleted_names = []
            for item_id in item_ids:
                cursor.execute('SELECT item_name FROM items WHERE id = ? AND storage = ?', (item_id, storage))
                item = cursor.fetchone()
                if item:
                    cursor.execute('DELETE FROM items WHERE id = ? AND storage = ?', (item_id, storage))
                    deleted_names.append(item[0])
            conn.commit()
            logging.info(f"Deleted items: {deleted_names} from storage: {storage}")
            conn.close()
            return deleted_names
        except Exception as e:
            logging.error(f"Error deleting items: {e}")
            return []

def update_items_owner(item_ids, owner, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            updated_names = []
            for item_id in item_ids:
                cursor.execute('SELECT item_name, owner, issued FROM items WHERE id = ? AND storage = ?', (item_id, storage))
                item = cursor.fetchone()
                if item and item[1] is None and item[2] == 0:
                    cursor.execute('UPDATE items SET owner = ?, issued = 1 WHERE id = ? AND storage = ?', 
                                  (owner, item_id, storage))
                    updated_names.append(item[0])
            conn.commit()
            logging.info(f"Updated items {updated_names} in {storage} to owner: {owner}")
            conn.close()
            return updated_names
        except Exception as e:
            logging.error(f"Error updating items owner: {e}")
            return []

def return_items(item_ids, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            returned_names = []
            for item_id in item_ids:
                cursor.execute('SELECT item_name, issued FROM items WHERE id = ? AND storage = ?', (item_id, storage))
                item = cursor.fetchone()
                if item and item[1] == 1:
                    cursor.execute('UPDATE items SET owner = NULL, issued = 0 WHERE id = ? AND storage = ?', 
                                  (item_id, storage))
                    returned_names.append(item[0])
            conn.commit()
            logging.info(f"Returned items: {returned_names} in {storage}")
            conn.close()
            return returned_names
        except Exception as e:
            logging.error(f"Error returning items: {e}")
            return []

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
            logging.info(f"Added event: {event_name}, date: {event_date}, id: {event_id}")
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
                cursor.execute('SELECT id, event_name, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', 
                              (current_date, end_date))
            elif period == 'month':
                end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                cursor.execute('SELECT id, event_name, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', 
                              (current_date, end_date))
            else:
                cursor.execute('SELECT id, event_name, event_date FROM events ORDER BY event_date')
            events = cursor.fetchall()
            logging.info(f"Fetched {len(events)} events for period '{period}'")
            conn.close()
            return events
        except Exception as e:
            logging.error(f"Error fetching events: {e}")
            return []

def delete_event(event_ids):
    with db_lock:
        conn = None
        try:
            if not event_ids:
                logging.warning("No event_ids provided for deletion")
                return []
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            deleted_names = []
            for event_id in event_ids:
                cursor.execute('SELECT id, event_name, event_date FROM events WHERE id = ?', (event_id,))
                event = cursor.fetchone()
                if event:
                    event_id, event_name, event_date = event
                    cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
                    try:
                        date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                        formatted_date = date_obj.strftime('%d.%m.%Y')
                        deleted_names.append(f"{event_name} ({formatted_date})")
                    except ValueError:
                        deleted_names.append(f"{event_name} ({event_date})")
                    logging.info(f"Deleted event: id={event_id}, name={event_name}, date={event_date}")
                else:
                    logging.warning(f"Event not found: id={event_id}")
            conn.commit()
            logging.info(f"Successfully deleted events: {deleted_names}")
            return deleted_names
        except Exception as e:
            logging.error(f"Error deleting events: {e}, event_ids: {event_ids}")
            return []
        finally:
            if conn:
                conn.close()

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

def create_items_keyboard(chat_id, storage, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    items = get_inventory(storage)
    buttons = []
    storage_id = STORAGE_IDS.get(storage, 'unknown')
    for item_id, item_name, owner, issued, _ in sorted(items, key=lambda x: x[1]):
        display_name = item_name[:30] + '...' if len(item_name) > 30 else item_name
        callback_data = f"select_{item_id}_{action}_{storage_id}"
        if len(callback_data.encode('utf-8')) > 64:
            logging.warning(f"Callback data too long for item {item_name}: {callback_data}")
            continue
        if action == 'delete':
            buttons.append(types.InlineKeyboardButton(text=display_name, callback_data=callback_data))
        elif action == 'give' and owner is None and issued == 0:
            buttons.append(types.InlineKeyboardButton(text=display_name, callback_data=callback_data))
        elif action == 'return' and issued == 1:
            buttons.append(types.InlineKeyboardButton(text=display_name, callback_data=callback_data))
    selected = user_selections.get(chat_id, [])
    if selected:
        confirm_data = f"confirm_{action}_{storage_id}"
        clear_data = f"clear_{action}_{storage_id}"
        if len(confirm_data.encode('utf-8')) <= 64 and len(clear_data.encode('utf-8')) <= 64:
            buttons.append(types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data))
            buttons.append(types.InlineKeyboardButton(text="🗑️ Очистить выбор", callback_data=clear_data))
    keyboard.add(*buttons)
    logging.info(f"Created items keyboard for chat_id={chat_id}, storage={storage}, action={action}, buttons={len(buttons)}")
    return keyboard if buttons else None

def create_events_delete_keyboard(chat_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    events = get_events()
    if not events:
        logging.info(f"No events found for deletion by chat_id={chat_id}")
        return None
    buttons = []
    for event_id, event_name, event_date in sorted(events, key=lambda x: x[1]):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m.%Y')
            display_name = f"{event_name} ({formatted_date})"[:30] + '...' if len(f"{event_name} ({formatted_date})") > 30 else f"{event_name} ({formatted_date})"
        except ValueError:
            display_name = f"{event_name} ({event_date})"[:30] + '...' if len(f"{event_name} ({event_date})") > 30 else f"{event_name} ({event_date})"
        callback_data = f"select_event_{event_id}_delete"
        if len(callback_data.encode('utf-8')) > 64:
            logging.warning(f"Callback data too long for event {event_name}: {callback_data}")
            continue
        buttons.append(types.InlineKeyboardButton(text=display_name, callback_data=callback_data))
        logging.info(f"Created button for event: id={event_id}, name={event_name}, date={event_date}")
    selected = user_selections.get(chat_id, [])
    if selected:
        confirm_data = "confirm_event_delete"
        clear_data = "clear_event_delete"
        if len(confirm_data.encode('utf-8')) <= 64 and len(clear_data.encode('utf-8')) <= 64:
            buttons.append(types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data))
            buttons.append(types.InlineKeyboardButton(text="🗑️ Очистить выбор", callback_data=clear_data))
            logging.info(f"Added confirm and clear buttons for event deletion, chat_id={chat_id}")
    keyboard.add(*buttons)
    logging.info(f"Created events delete keyboard with {len(buttons)} buttons for chat_id={chat_id}")
    return keyboard if buttons else None

# Функции отображения
def show_main_menu(chat_id):
    text = "📋 *Главное меню*\n\nВыберите раздел:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[chat_id] = 'main_menu'
    user_selections.pop(chat_id, None)

def show_storage_selection(chat_id):
    text = "📦 *Выберите кладовую:*"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_selection_keyboard())
    user_states[chat_id] = 'storage_selection'
    user_selections.pop(chat_id, None)

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
    user_selections.pop(chat_id, None)

# Обработчики текстовых сообщений
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем и событиями!*\n\n"
    welcome_text += "📋 *Доступные разделы:*\n"
-such as "Invalid callback_data format" or "Invalid state".
