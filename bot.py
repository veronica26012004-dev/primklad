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

MONTHS_RU = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня',
    7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
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
            deleted_events = []
            
            # Сначала получаем информацию о событиях
            placeholders = ','.join('?' * len(event_ids))
            cursor.execute(f'SELECT id, event_name, event_date FROM events WHERE id IN ({placeholders})', event_ids)
            events_to_delete = cursor.fetchall()
            
            if not events_to_delete:
                logging.warning(f"No events found with ids: {event_ids}")
                return []
            
            # Удаляем события
            cursor.execute(f'DELETE FROM events WHERE id IN ({placeholders})', event_ids)
            conn.commit()
            
            # Формируем список удаленных событий
            for event_id, event_name, event_date in events_to_delete:
                try:
                    date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                    formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
                    deleted_events.append(f"{event_name} ({formatted_date})")
                except ValueError:
                    deleted_events.append(f"{event_name} ({event_date})")
                
                logging.info(f"Deleted event: id={event_id}, name={event_name}, date={event_date}")
            
            logging.info(f"Successfully deleted {len(deleted_events)} events")
            return deleted_events
            
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
    for event_id, event_name, event_date in sorted(events, key=lambda x: x[2]):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
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

def show_events_menu(chat_id):
    text = "📅 *Управление событиями*\n\nВыберите действие:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_events_keyboard())
    user_states[chat_id] = 'events_menu'
    user_selections.pop(chat_id, None)

# Обработчики текстовых сообщений
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем и событиями!*\n\n"
    welcome_text += "📋 *Доступные разделы:*\n"
    welcome_text += "• 📦 Кладовая - управление инвентарем\n"
    welcome_text += "• 📅 События - управление мероприятиями\n\n"
    welcome_text += "Выберите нужный раздел в меню ниже 👇"
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[message.chat.id] = 'main_menu'

@bot.message_handler(func=lambda message: message.text == '🔙 В главное меню')
def back_to_main_menu(message):
    show_main_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '📦 Кладовая')
def handle_storage(message):
    show_storage_selection(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '📅 События')
def handle_events(message):
    show_events_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '🔙 Назад')
def back_to_storage_selection(message):
    show_storage_selection(message.chat.id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'storage_selection')
def handle_storage_selection(message):
    if message.text in ['📍 Гринбокс 11', '📍 Гринбокс 12']:
        storage = message.text
        show_inventory(message.chat.id, storage)
    elif message.text == '🔙 В главное меню':
        show_main_menu(message.chat.id)

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'storage')
def handle_storage_actions(message):
    chat_id = message.chat.id
    storage = user_states[chat_id][1]
    
    if message.text == '➕ Добавить':
        bot.send_message(chat_id, "📝 Введите название предмета для добавления:", reply_markup=types.ReplyKeyboardRemove())
        user_states[chat_id] = ('adding_item', storage)
    
    elif message.text == '➖ Удалить':
        keyboard = create_items_keyboard(chat_id, storage, 'delete')
        if keyboard:
            bot.send_message(chat_id, "🗑️ Выберите предметы для удаления:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 В кладовой нет предметов для удаления")
    
    elif message.text == '🎁 Выдать':
        keyboard = create_items_keyboard(chat_id, storage, 'give')
        if keyboard:
            bot.send_message(chat_id, "🎁 Выберите предметы для выдачи:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 В кладовой нет доступных предметов для выдачи")
    
    elif message.text == '↩️ Вернуть':
        keyboard = create_items_keyboard(chat_id, storage, 'return')
        if keyboard:
            bot.send_message(chat_id, "↩️ Выберите предметы для возврата:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 Нет выданных предметов для возврата")
    
    elif message.text == '📋 Показать инвентарь':
        show_inventory(chat_id, storage)
    
    elif message.text == '🔙 Назад':
        show_storage_selection(chat_id)

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'adding_item')
def handle_adding_item(message):
    chat_id = message.chat.id
    storage = user_states[chat_id][1]
    item_name = message.text.strip()
    
    if item_name:
        existing_item = find_item_in_db(item_name, storage)
        if existing_item:
            bot.send_message(chat_id, f"⚠️ Предмет '{existing_item}' уже существует в этой кладовой")
        else:
            item_id = add_item(item_name, storage)
            if item_id:
                bot.send_message(chat_id, f"✅ Предмет '{item_name}' добавлен в {storage}")
            else:
                bot.send_message(chat_id, "❌ Ошибка при добавлении предмета")
    else:
        bot.send_message(chat_id, "❌ Название предмета не может быть пустым")
    
    show_inventory(chat_id, storage)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'events_menu')
def handle_events_actions(message):
    chat_id = message.chat.id
    
    if message.text == '➕ Добавить событие':
        bot.send_message(chat_id, "📝 Введите название события:", reply_markup=types.ReplyKeyboardRemove())
        user_states[chat_id] = 'adding_event_name'
    
    elif message.text == '📅 Посмотреть события':
        events = get_events()
        if not events:
            bot.send_message(chat_id, "📅 Нет запланированных событий")
            return
        
        text = "📅 *Все события:*\n\n"
        for _, event_name, event_date in sorted(events, key=lambda x: x[2]):
            try:
                date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
                text += f"• {event_name} - {formatted_date}\n"
            except ValueError:
                text += f"• {event_name} - {event_date}\n"
        
        bot.send_message(chat_id, text, parse_mode='Markdown')
    
    elif message.text == '🗑️ Удалить событие':
        keyboard = create_events_delete_keyboard(chat_id)
        if keyboard:
            bot.send_message(chat_id, "🗑️ Выберите события для удаления:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 Нет событий для удаления")
    
    elif message.text == '🔙 В главное меню':
        show_main_menu(chat_id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'adding_event_name')
def handle_adding_event_name(message):
    chat_id = message.chat.id
    event_name = message.text.strip()
    
    if event_name:
        user_states[chat_id] = ('adding_event_date', event_name)
        bot.send_message(chat_id, "📅 Введите дату события в формате ДД.ММ.ГГГГ (например, 25.12.2024):")
    else:
        bot.send_message(chat_id, "❌ Название события не может быть пустым")
        show_events_menu(chat_id)

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'adding_event_date')
def handle_adding_event_date(message):
    chat_id = message.chat.id
    event_name = user_states[chat_id][1]
    date_str = message.text.strip()
    
    try:
        date_obj = datetime.strptime(date_str, '%d.%m.%Y')
        event_date = date_obj.strftime('%Y-%m-%d')
        
        event_id = add_event(event_name, event_date)
        if event_id:
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            bot.send_message(chat_id, f"✅ Событие '{event_name}' на {formatted_date} добавлено")
        else:
            bot.send_message(chat_id, "❌ Ошибка при добавлении события")
    except ValueError:
        bot.send_message(chat_id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 25.12.2024)")
        return
    
    show_events_menu(chat_id)

# Обработчики callback-запросов
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    callback_data = call.data
    chat_id = call.message.chat.id
    
    logging.info(f"Callback received: {callback_data} from chat_id: {chat_id}")
    
    if callback_data.startswith('select_'):
        # Обработка выбора предметов
        parts = callback_data.split('_')
        if len(parts) >= 4:
            item_id = parts[1]
            action = parts[2]
            storage_id = parts[3]
            storage = REVERSE_STORAGE_IDS.get(storage_id)
            
            if chat_id not in user_selections:
                user_selections[chat_id] = []
            
            if item_id not in user_selections[chat_id]:
                user_selections[chat_id].append(item_id)
                bot.answer_callback_query(call.id, "Предмет добавлен в выбор")
            else:
                user_selections[chat_id].remove(item_id)
                bot.answer_callback_query(call.id, "Предмет удален из выбора")
            
            # Обновляем клавиатуру
            try:
                keyboard = create_items_keyboard(chat_id, storage, action)
                if keyboard:
                    bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=keyboard
                    )
            except Exception as e:
                logging.error(f"Error updating keyboard: {e}")
        else:
            logging.error(f"Invalid callback_data format: {callback_data}")
    
    elif callback_data.startswith('select_event_'):
        # Обработка выбора события для удаления
        parts = callback_data.split('_')
        if len(parts) >= 4:
            event_id = parts[2]
            
            if chat_id not in user_selections:
                user_selections[chat_id] = []
            
            if event_id not in user_selections[chat_id]:
                user_selections[chat_id].append(event_id)
                bot.answer_callback_query(call.id, "Событие добавлено в выбор")
            else:
                user_selections[chat_id].remove(event_id)
                bot.answer_callback_query(call.id, "Событие удалено из выбора")
            
            # Обновляем клавиатуру
            try:
                keyboard = create_events_delete_keyboard(chat_id)
                if keyboard:
                    bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=keyboard
                    )
                else:
                    bot.answer_callback_query(call.id, "Нет событий для удаления")
            except Exception as e:
                logging.error(f"Error updating events keyboard: {e}")
        else:
            logging.error(f"Invalid callback_data format: {callback_data}")
    
    elif callback_data.startswith('confirm_'):
        # Подтверждение действий с предметами
        parts = callback_data.split('_')
        if len(parts) >= 3:
            action = parts[1]
            storage_id = parts[2]
            storage = REVERSE_STORAGE_IDS.get(storage_id)
            
            selected_items = user_selections.get(chat_id, [])
            if not selected_items:
                bot.answer_callback_query(call.id, "❌ Не выбрано ни одного предмета")
                return
            
            if action == 'delete':
                deleted_names = delete_items(selected_items, storage)
                if deleted_names:
                    items_list = "\n".join([f"• {name}" for name in deleted_names])
                    bot.send_message(chat_id, f"✅ Удалены предметы:\n{items_list}")
                else:
                    bot.answer_callback_query(call.id, "❌ Ошибка при удалении предметов")
            
            elif action == 'give':
                bot.send_message(chat_id, "👤 Введите имя получателя:", reply_markup=types.ReplyKeyboardRemove())
                user_states[chat_id] = ('giving_items', storage, selected_items)
            
            elif action == 'return':
                returned_names = return_items(selected_items, storage)
                if returned_names:
                    items_list = "\n".join([f"• {name}" for name in returned_names])
                    bot.send_message(chat_id, f"✅ Возвращены предметы:\n{items_list}")
                else:
                    bot.answer_callback_query(call.id, "❌ Ошибка при возврате предметов")
            
            # Удаляем сообщение с клавиатурой и очищаем выбор
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            user_selections.pop(chat_id, None)
            show_inventory(chat_id, storage)
    
    elif callback_data == 'confirm_event_delete':
        selected_events = user_selections.get(chat_id, [])
        
        if not selected_events:
            bot.answer_callback_query(call.id, "❌ Не выбрано ни одного события")
            return
        
        # Удаляем события
        deleted_events = delete_event(selected_events)
        
        if deleted_events:
            event_list = "\n".join([f"• {event}" for event in deleted_events])
            bot.send_message(chat_id, f"✅ Удалены события:\n{event_list}")
            
            # Удаляем сообщение с клавиатурой
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении событий")
        
        # Очищаем выбор и показываем меню событий
        user_selections.pop(chat_id, None)
        user_states[chat_id] = 'events_menu'
        show_events_menu(chat_id)
    
    elif callback_data.startswith('clear_'):
        # Очистка выбора предметов
        parts = callback_data.split('_')
        if len(parts) >= 3:
            action = parts[1]
            storage_id = parts[2]
            storage = REVERSE_STORAGE_IDS.get(storage_id)
            
            user_selections.pop(chat_id, None)
            bot.answer_callback_query(call.id, "🗑️ Выбор очищен")
            
            # Обновляем клавиатуру
            try:
                keyboard = create_items_keyboard(chat_id, storage, action)
                if keyboard:
                    bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=keyboard
                    )
            except Exception as e:
                logging.error(f"Error updating keyboard: {e}")
    
    elif callback_data == 'clear_event_delete':
        user_selections.pop(chat_id, None)
        bot.answer_callback_query(call.id, "🗑️ Выбор очищен")
        
        # Обновляем клавиатуру
        try:
            keyboard = create_events_delete_keyboard(chat_id)
            if keyboard:
                bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    reply_markup=keyboard
                )
            else:
                bot.answer_callback_query(call.id, "Нет событий для удаления")
        except Exception as e:
            logging.error(f"Error updating events keyboard: {e}")

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'giving_items')
def handle_giving_items(message):
    chat_id = message.chat.id
    storage = user_states[chat_id][1]
    selected_items = user_states[chat_id][2]
    owner = message.text.strip()
    
    if owner:
        updated_names = update_items_owner(selected_items, owner, storage)
        if updated_names:
            items_list = "\n".join([f"• {name}" for name in updated_names])
            bot.send_message(chat_id, f"✅ Выданы предметы {owner}:\n{items_list}")
        else:
            bot.send_message(chat_id, "❌ Ошибка при выдаче предметов")
    else:
        bot.send_message(chat_id, "❌ Имя получателя не может быть пустым")
    
    show_inventory(chat_id, storage)

# Запуск бота
if __name__ == '__main__':
    logging.info("Starting bot...")
    bot.infinity_polling()
