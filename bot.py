import telebot
from telebot import types
import threading
import os
import json
import time
import requests
import re
import logging
from datetime import datetime, timedelta
from uuid import uuid4
import sqlite3

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Загрузка токена из переменных окружения
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN не установлен.")
    raise ValueError("BOT_TOKEN is not set")

bot = telebot.TeleBot(TOKEN)

# Настройки базы данных
DB_FILE = '/data/inventory_bot.db' if os.environ.get('RENDER') else 'inventory_bot.db'

# Кэш для данных
items_cache = {}
events_cache = []
admins_cache = []

# Блокировка для thread-safe доступа
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

# Сопоставление хранилищ
STORAGE_IDS = {
    'Гринбокс 11': 'gb11',
    'Гринбокс 12': 'gb12'
}
REVERSE_STORAGE_IDS = {v: k for k, v in STORAGE_IDS.items()}

# Режим админа
SECRET_WORD = "админ123"

# Нормализация текста
def normalize_text(text):
    return ' '.join(text.strip().split()).lower()

# Функции для работы с базой данных
def init_database():
    """Инициализация базы данных и создание таблиц"""
    # Создаем директорию для данных если её нет
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    
    with db_lock:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cursor = conn.cursor()
        # Таблица предметов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                storage_id TEXT NOT NULL,
                issued INTEGER DEFAULT 0,
                owner TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(item_name, storage_id)
            )
        ''')
        # Таблица событий
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Таблица администраторов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    logger.info("База данных инициализирована")

def get_db_connection():
    """Получение соединения с базой данных"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# Инициализация базы данных при запуске
init_database()

# Функции для работы с администраторами
def load_admins():
    """Загрузка списка администраторов из базы данных"""
    global admins_cache
    if admins_cache:
        return admins_cache
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT username, chat_id FROM admins')
        admins_data = cursor.fetchall()
        admins_cache = []
        for row in admins_data:
            admin_data = {
                'username': row['username'],
                'chat_id': row['chat_id']
            }
            admins_cache.append(admin_data)
        logger.info(f"Загружено {len(admins_cache)} администраторов")
        return admins_cache
    except Exception as e:
        logger.error(f"Ошибка загрузки администраторов: {e}")
        return []
    finally:
        conn.close()

def is_admin(chat_id):
    """Проверка, является ли пользователь администратором"""
    for admin in admins_cache:
        if admin['chat_id'] == chat_id:
            return True
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT 1 FROM admins WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        if result:
            username = get_username_by_chat_id(chat_id)
            if username:
                admins_cache.append({
                    'username': username,
                    'chat_id': chat_id
                })
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки администратора: {e}")
        return False
    finally:
        conn.close()

def get_username_by_chat_id(chat_id):
    """Получение username по chat_id"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT username FROM admins WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        return result['username'] if result else None
    except Exception as e:
        logger.error(f"Ошибка получения username: {e}")
        return None
    finally:
        conn.close()

def add_admin(username, chat_id=None):
    """Добавление нового администратора"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        username = username.lstrip('@')
        
        cursor.execute('SELECT 1 FROM admins WHERE username = ?', (username,))
        if cursor.fetchone():
            logger.warning(f"Администратор {username} уже существует")
            return False
            
        cursor.execute(
            'INSERT INTO admins (username, chat_id) VALUES (?, ?)',
            (username, chat_id)
        )
        conn.commit()
        
        admin_data = {
            'username': username,
            'chat_id': chat_id
        }
        admins_cache.append(admin_data)
        
        logger.info(f"Администратор {username} добавлен")
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления администратора {username}: {e}")
        return False
    finally:
        conn.close()

def remove_admin(username):
    """Удаление администратора"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        username = username.lstrip('@')
        cursor.execute('DELETE FROM admins WHERE username = ?', (username,))
        conn.commit()
        
        global admins_cache
        admins_cache = [admin for admin in admins_cache if admin['username'] != username]
        
        logger.info(f"Администратор {username} удален")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления администратора {username}: {e}")
        return False
    finally:
        conn.close()

def get_all_admins():
    """Получение списка всех администраторов"""
    return load_admins()

# Функции для работы с предметами
def load_items(storage):
    storage_id = STORAGE_IDS.get(storage)
    if storage_id in items_cache:
        return items_cache[storage_id]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT item_name, issued, owner FROM items WHERE storage_id = ?', (storage_id,))
        items_data = cursor.fetchall()
        items = []
        for row in items_data:
            items.append({
                'id': row['item_name'],
                'item_name': row['item_name'],
                'issued': row['issued'],
                'owner': row['owner']
            })
        items_cache[storage_id] = items
        return items
    except Exception as e:
        logger.error(f"Ошибка загрузки предметов из БД для {storage}: {e}")
        return []
    finally:
        conn.close()

def get_inventory(storage):
    try:
        items = load_items(storage)
        return [(item['id'], item['item_name'], item['issued'], item['owner']) for item in items]
    except Exception as e:
        logger.error(f"Ошибка получения инвентаря для {storage}: {e}")
        return []

def add_item(item_name, storage):
    item_name = re.sub(r'[|\\]', '', item_name.strip())[:50]
    if not item_name:
        return None
        
    storage_id = STORAGE_IDS.get(storage)
    if not storage_id:
        return None
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        normalized_new = normalize_text(item_name)
        cursor.execute('SELECT item_name FROM items WHERE storage_id = ?', (storage_id,))
        existing_items = cursor.fetchall()
        for existing_item in existing_items:
            if normalize_text(existing_item['item_name']) == normalized_new:
                return None
                
        cursor.execute(
            'INSERT INTO items (item_name, storage_id, issued, owner) VALUES (?, ?, 0, "")',
            (item_name, storage_id)
        )
        conn.commit()
        
        if storage_id in items_cache:
            items_cache[storage_id].append({
                'id': item_name,
                'item_name': item_name,
                'issued': 0,
                'owner': ""
            })
            
        return item_name
    except Exception as e:
        logger.error(f"Ошибка добавления предмета {item_name} в {storage}: {e}")
        return None
    finally:
        conn.close()

def delete_items(item_names, storage):
    storage_id = STORAGE_IDS.get(storage)
    if not storage_id:
        return []
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        deleted_names = []
        for item_name in item_names:
            cursor.execute('DELETE FROM items WHERE item_name = ? AND storage_id = ?', (item_name, storage_id))
            if cursor.rowcount > 0:
                deleted_names.append(item_name)
        conn.commit()
        
        if storage_id in items_cache:
            items_cache[storage_id] = [item for item in items_cache[storage_id] if item['item_name'] not in item_names]
            
        return deleted_names
    except Exception as e:
        logger.error(f"Ошибка удаления предметов из {storage}: {e}")
        return []
    finally:
        conn.close()

def update_items_owner(item_names, owner, storage):
    storage_id = STORAGE_IDS.get(storage)
    if not storage_id:
        return []
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        updated_names = []
        for item_name in item_names:
            cursor.execute(
                'UPDATE items SET issued = 1, owner = ? WHERE item_name = ? AND storage_id = ?',
                (owner, item_name, storage_id)
            )
            if cursor.rowcount > 0:
                updated_names.append(item_name)
        conn.commit()
        
        if storage_id in items_cache:
            for item in items_cache[storage_id]:
                if item['item_name'] in item_names:
                    item['issued'] = 1
                    item['owner'] = owner
                    
        return updated_names
    except Exception as e:
        logger.error(f"Ошибка обновления статуса предметов в {storage}: {e}")
        return []
    finally:
        conn.close()

def return_items(item_names, storage):
    storage_id = STORAGE_IDS.get(storage)
    if not storage_id:
        return []
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        returned_names = []
        for item_name in item_names:
            cursor.execute(
                'UPDATE items SET issued = 0, owner = "" WHERE item_name = ? AND storage_id = ? AND issued = 1',
                (item_name, storage_id)
            )
            if cursor.rowcount > 0:
                returned_names.append(item_name)
        conn.commit()
        
        if storage_id in items_cache:
            for item in items_cache[storage_id]:
                if item['item_name'] in item_names:
                    item['issued'] = 0
                    item['owner'] = ""
                    
        return returned_names
    except Exception as e:
        logger.error(f"Ошибка возврата предметов в {storage}: {e}")
        return []
    finally:
        conn.close()

# Функции для работы с событиями
def load_events():
    if events_cache:
        return events_cache
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id, event_name, event_date FROM events')
        events_data = cursor.fetchall()
        events = []
        for row in events_data:
            events.append({
                'id': row['id'],
                'event_name': row['event_name'],
                'event_date': row['event_date']
            })
        events_cache[:] = events
        return events
    except Exception as e:
        logger.error(f"Ошибка загрузки событий: {e}")
        return []
    finally:
        conn.close()

def add_event(event_name, event_date):
    event_id = str(uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO events (id, event_name, event_date) VALUES (?, ?, ?)',
            (event_id, event_name, event_date)
        )
        conn.commit()
        
        events_cache.append({
            'id': event_id,
            'event_name': event_name,
            'event_date': event_date
        })
        
        return event_id
    except Exception as e:
        logger.error(f"Ошибка добавления события {event_name}: {e}")
        return None
    finally:
        conn.close()

def get_events(period=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if period == 'week':
            end_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
            cursor.execute(
                'SELECT id, event_name, event_date FROM events WHERE event_date BETWEEN date("now") AND ? ORDER BY event_date',
                (end_date,)
            )
        elif period == 'month':
            end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            cursor.execute(
                'SELECT id, event_name, event_date FROM events WHERE event_date BETWEEN date("now") AND ? ORDER BY event_date',
                (end_date,)
            )
        else:
            cursor.execute('SELECT id, event_name, event_date FROM events ORDER BY event_date')
        events_data = cursor.fetchall()
        events = [(row['id'], row['event_name'], row['event_date']) for row in events_data]
        return events
    except Exception as e:
        logger.error(f"Ошибка получения событий: {e}")
        return []
    finally:
        conn.close()

def delete_event(event_ids):
    if not event_ids:
        return []
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        placeholders = ','.join(['?'] * len(event_ids))
        cursor.execute(f'SELECT id, event_name, event_date FROM events WHERE id IN ({placeholders})', event_ids)
        events_to_delete = cursor.fetchall()
        
        cursor.execute(f'DELETE FROM events WHERE id IN ({placeholders})', event_ids)
        conn.commit()
        
        events_cache[:] = [ev for ev in events_cache if ev['id'] not in event_ids]
        
        deleted_events = []
        for event in events_to_delete:
            event_name = event['event_name']
            event_date = event['event_date']
            try:
                date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d %B %Y').replace(
                    date_obj.strftime('%B'),
                    MONTHS_RU[date_obj.month]
                )
                deleted_events.append(f"{event_name} ({formatted_date})")
            except ValueError:
                deleted_events.append(f"{event_name} ({event_date})")
                
        return deleted_events
    except Exception as e:
        logger.error(f"Ошибка удаления событий: {e}, event_ids: {event_ids}")
        return []
    finally:
        conn.close()

# UI / клавиатуры
def create_main_menu_keyboard(chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📦 Кладовая'),
        types.KeyboardButton('📅 События')
    ]
    if is_admin(chat_id):
        buttons.append(types.KeyboardButton('👑 Админы'))
    keyboard.add(*buttons)
    return keyboard

def create_storage_selection_keyboard(chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📍 Гринбокс 11'),
        types.KeyboardButton('📍 Гринбокс 12'),
        types.KeyboardButton('🔙 В главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_storage_keyboard(chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = []
    if is_admin(chat_id):
        buttons.extend([
            types.KeyboardButton('➕ Добавить предмет'),
            types.KeyboardButton('➖ Удалить предмет'),
            types.KeyboardButton('🎁 Выдать предмет'),
            types.KeyboardButton('↩️ Вернуть предмет')
        ])
    buttons.append(types.KeyboardButton('🔙 Назад'))
    keyboard.add(*buttons)
    return keyboard

def create_events_keyboard(chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = []
    if is_admin(chat_id):
        buttons.extend([
            types.KeyboardButton('➕ Добавить событие'),
            types.KeyboardButton('🗑️ Удалить событие')
        ])
    buttons.append(types.KeyboardButton('🔙 В главное меню'))
    keyboard.add(*buttons)
    return keyboard

def create_admins_keyboard(chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить админа'),
        types.KeyboardButton('➖ Удалить админа'),
        types.KeyboardButton('📋 Список админов'),
        types.KeyboardButton('🔙 В главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(types.KeyboardButton('❌ Отмена'))
    return keyboard

# Функции отображения
def show_main_menu(chat_id):
    admin_status = "👑 Режим админа активирован\n\n" if is_admin(chat_id) else ""
    text = f"{admin_status}📋 Главное меню\n\nВыберите раздел:"
    bot.send_message(chat_id, text, reply_markup=create_main_menu_keyboard(chat_id))
    user_states[chat_id] = 'main_menu'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_storage_selection(chat_id):
    text = "📦 Выберите кладовую:"
    bot.send_message(chat_id, text, reply_markup=create_storage_selection_keyboard(chat_id))
    user_states[chat_id] = 'storage_selection'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_storage_menu(chat_id, storage, message_text=None):
    if message_text:
        bot.send_message(chat_id, message_text, reply_markup=create_storage_keyboard(chat_id))
    else:
        admin_status = " 👑" if is_admin(chat_id) else ""
        bot.send_message(chat_id, f"📦 Кладовая: {storage}{admin_status}\n\nВыберите действие:", reply_markup=create_storage_keyboard(chat_id))
    user_states[chat_id] = ('storage', storage)
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_inventory(chat_id, storage):
    if storage not in STORAGE_IDS:
        bot.send_message(chat_id, "❌ Не удалось выбрать кладовую, попробуйте снова")
        show_storage_selection(chat_id)
        return
        
    inventory = get_inventory(storage)
    text = f"📦 ИНВЕНТАРЬ ({storage}):\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for _, item_name, issued, owner in sorted(inventory, key=lambda x: x[1]):
            if issued == 0:
                text += f"✅ {item_name}\n"
                available_count += 1
            else:
                text += f"🔸 {item_name} - выдано ({owner})\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
        
    bot.send_message(chat_id, text, reply_markup=create_storage_keyboard(chat_id))
    user_states[chat_id] = ('storage', storage)
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_events_menu(chat_id, message_text=None):
    if message_text:
        bot.send_message(chat_id, message_text, reply_markup=create_events_keyboard(chat_id))
    else:
        admin_status = " 👑" if is_admin(chat_id) else ""
        text = f"📅 Управление событиями{admin_status}\n\nВыберите действие:"
        bot.send_message(chat_id, text, reply_markup=create_events_keyboard(chat_id))
    user_states[chat_id] = 'events_menu'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_events_list(chat_id):
    events = get_events()
    if not events:
        bot.send_message(chat_id, "📅 Нет запланированных событий")
        show_events_menu(chat_id)
        return
        
    text = "📅 Все события:\n\n"
    for _, event_name, event_date in sorted(events, key=lambda x: x[2]):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            text += f"• {formatted_date} — {event_name}\n"
        except ValueError:
            text += f"• {event_date} — {event_name}\n"
            
    bot.send_message(chat_id, text, reply_markup=create_events_keyboard(chat_id))
    user_states[chat_id] = 'events_menu'

def show_admins_menu(chat_id, message_text=None):
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут управлять админами.")
        show_main_menu(chat_id)
        return
        
    if message_text:
        bot.send_message(chat_id, message_text, reply_markup=create_admins_keyboard(chat_id))
    else:
        text = "👑 Управление администраторами\n\nВыберите действие:"
        bot.send_message(chat_id, text, reply_markup=create_admins_keyboard(chat_id))
    user_states[chat_id] = 'admins_menu'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_admins_list(chat_id):
    admins = get_all_admins()
    if not admins:
        bot.send_message(chat_id, "📭 Нет добавленных администраторов")
        show_admins_menu(chat_id)
        return
        
    text = "👑 Список администраторов:\n\n"
    for i, admin in enumerate(admins, 1):
        chat_id_info = f" (chat_id: {admin['chat_id']})" if admin['chat_id'] else " (не активирован)"
        text += f"{i}. @{admin['username']}{chat_id_info}\n"
        
    bot.send_message(chat_id, text, reply_markup=create_admins_keyboard(chat_id))

# Обработчики сообщений
@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = "👋 Добро пожаловать в систему управления инвентарем и событиями!\n\n"
    welcome_text += "📋 Доступные разделы:\n"
    welcome_text += "• 📦 Кладовая - управление инвентарем\n"
    welcome_text += "• 📅 События - управление мероприятиями\n\n"
    if is_admin(message.chat.id):
        welcome_text += "👑 Режим админа активирован\n"
        welcome_text += "• 👑 Админы - управление администраторами\n\n"
    else:
        welcome_text += "💡 Для доступа к функциям управления введите секретное слово"
    welcome_text += "\nВыберите нужный раздел в меню ниже 👇"
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=create_main_menu_keyboard(message.chat.id))
    user_states[message.chat.id] = 'main_menu'
    user_selections.pop(message.chat.id, None)
    user_item_lists.pop(message.chat.id, None)

@bot.message_handler(func=lambda message: normalize_text(message.text) == normalize_text(SECRET_WORD))
def handle_secret_word(message):
    chat_id = message.chat.id
    username = message.from_user.username
    
    if not is_admin(chat_id):
        if username:
            if add_admin(username, chat_id):
                bot.send_message(chat_id, "✅ Режим админа активирован! Теперь вам доступны все функции управления, включая управление администраторами.")
                show_main_menu(chat_id)
            else:
                bot.send_message(chat_id, "❌ Ошибка при активации режима админа.")
        else:
            bot.send_message(chat_id, "❌ У вас не установлен username в Telegram. Пожалуйста, установите username в настройках Telegram и попробуйте снова.")
    else:
        bot.send_message(chat_id, "👑 Режим админа уже активирован.")

# Основные обработчики кнопок
@bot.message_handler(func=lambda message: message.text == '🔙 В главное меню')
def back_to_main_menu(message):
    show_main_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '📦 Кладовая')
def handle_storage(message):
    show_storage_selection(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '📅 События')
def handle_events(message):
    show_events_list(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '👑 Админы')
def handle_admins(message):
    show_admins_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '🔙 Назад')
def back_to_storage_selection(message):
    show_storage_selection(message.chat.id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'storage_selection')
def handle_storage_selection(message):
    chat_id = message.chat.id
    storage = message.text.replace('📍 ', '').strip()
    
    if storage in STORAGE_IDS:
        show_inventory(chat_id, storage)
    elif message.text == '🔙 В главное меню':
        show_main_menu(chat_id)
    else:
        bot.send_message(chat_id, "❌ Не удалось выбрать кладовую, используйте кнопки меню")
        show_storage_selection(chat_id)

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'storage')
def handle_storage_actions(message):
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    if len(state_data) >= 2:
        storage = state_data[1]
    else:
        bot.send_message(chat_id, "❌ Ошибка состояния, выберите кладовую снова")
        show_storage_selection(chat_id)
        return
        
    if message.text == '➕ Добавить предмет':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут добавлять предметы.")
            return
        bot.send_message(chat_id, "📝 Введите названия предметов для добавления (каждый предмет с новой строки) или нажмите '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = ('adding_item', storage)
    elif message.text == '➖ Удалить предмет':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут удалять предметы.")
            return
        bot.send_message(chat_id, "🗑️ Введите названия предметов для удаления (каждый предмет с новой строки) или нажмите '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = ('deleting_item', storage)
    elif message.text == '🎁 Выдать предмет':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут выдавать предметы.")
            return
        bot.send_message(chat_id, "🎁 Введите названия предметов для выдачи (каждый предмет с новой строки) или нажмите '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = ('issuing_item', storage)
    elif message.text == '↩️ Вернуть предмет':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут возвращать предметы.")
            return
        bot.send_message(chat_id, "↩️ Введите названия предметов для возврата (каждый предмет с новой строки) или нажмите '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = ('returning_item', storage)
    elif message.text == '🔙 Назад':
        show_storage_selection(chat_id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'events_menu')
def handle_events_actions(message):
    chat_id = message.chat.id
    if message.text == '➕ Добавить событие':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут добавлять события.")
            return
        bot.send_message(chat_id, "📝 Введите название события или '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = 'adding_event_name'
    elif message.text == '🗑️ Удалить событие':
        if not is_admin(chat_id):
            bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут удалять события.")
            return
        show_events_list_for_deletion(chat_id)
    elif message.text == '🔙 В главное меню':
        show_main_menu(chat_id)

def show_events_list_for_deletion(chat_id):
    events = get_events()
    if not events:
        bot.send_message(chat_id, "📅 Нет событий для удаления")
        show_events_menu(chat_id)
        return
        
    text = "🗑️ Выберите события для удаления:\n\n"
    event_dict = {}
    for i, (event_id, event_name, event_date) in enumerate(events, 1):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            text += f"{i}. {formatted_date} — {event_name}\n"
            event_dict[str(i)] = event_id
        except ValueError:
            text += f"{i}. {event_date} — {event_name}\n"
            event_dict[str(i)] = event_id
            
    text += "\nВведите номера событий для удаления через запятую (например: 1,3,5) или '❌ Отмена':"
    
    user_selections[chat_id] = event_dict
    user_states[chat_id] = 'deleting_event'
    bot.send_message(chat_id, text, reply_markup=create_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'admins_menu')
def handle_admins_actions(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут управлять админами.")
        show_main_menu(chat_id)
        return
        
    if message.text == '➕ Добавить админа':
        bot.send_message(chat_id, "👤 Введите username нового администратора (например, @username или просто username):", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = 'adding_admin'
    elif message.text == '➖ Удалить админа':
        admins = get_all_admins()
        if not admins:
            bot.send_message(chat_id, "📭 Нет администраторов для удаления")
            return
            
        text = "🗑️ Список администраторов для удаления:\n\n"
        for i, admin in enumerate(admins, 1):
            chat_id_info = f" (chat_id: {admin['chat_id']})" if admin['chat_id'] else " (не активирован)"
            text += f"{i}. @{admin['username']}{chat_id_info}\n"
        text += "\nВведите username администратора для удаления (например, @username или просто username):"
        bot.send_message(chat_id, text, reply_markup=create_cancel_keyboard())
        user_states[chat_id] = 'removing_admin'
    elif message.text == '📋 Список админов':
        show_admins_list(chat_id)
    elif message.text == '🔙 В главное меню':
        show_main_menu(chat_id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'adding_admin')
def handle_adding_admin(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут добавлять админов.")
        show_main_menu(chat_id)
        return
        
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление администратора отменено")
        show_admins_menu(chat_id)
        return
        
    username = message.text.strip()
    if not username:
        bot.send_message(chat_id, "❌ Username не может быть пустым. Попробуйте еще раз:")
        return
        
    if add_admin(username):
        bot.send_message(chat_id, f"✅ Администратор @{username.lstrip('@')} добавлен")
    else:
        bot.send_message(chat_id, f"❌ Ошибка при добавлении администратора @{username.lstrip('@')}. Возможно, такой администратор уже существует.")
    show_admins_menu(chat_id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'removing_admin')
def handle_removing_admin(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Недостаточно прав. Только администраторы могут удалять админов.")
        show_main_menu(chat_id)
        return
        
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Удаление администратора отменено")
        show_admins_menu(chat_id)
        return
        
    username = message.text.strip()
    if not username:
        bot.send_message(chat_id, "❌ Username не может быть пустым. Попробуйте еще раз:")
        return
        
    if remove_admin(username):
        bot.send_message(chat_id, f"✅ Администратор @{username.lstrip('@')} удален")
    else:
        bot.send_message(chat_id, f"❌ Ошибка при удалении администратора @{username.lstrip('@')} или администратор не найден")
    show_admins_menu(chat_id)

# Обработчики состояний
@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'adding_item')
def handle_adding_item(message):
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    storage = state_data[1]
    
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление предметов отменено")
        show_storage_menu(chat_id, storage)
        return
        
    item_names = [name.strip() for name in message.text.split('\n') if name.strip()]
    added_items = []
    
    for item_name in item_names:
        result = add_item(item_name, storage)
        if result:
            added_items.append(result)
            
    if added_items:
        text = f"✅ Добавлено предметов: {len(added_items)}\n\n"
        text += "\n".join(f"• {item}" for item in added_items)
    else:
        text = "❌ Не удалось добавить предметы (возможно, они уже существуют)"
        
    show_storage_menu(chat_id, storage, text)

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'deleting_item')
def handle_deleting_item(message):
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    storage = state_data[1]
    
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Удаление предметов отменено")
        show_storage_menu(chat_id, storage)
        return
        
    item_names = [name.strip() for name in message.text.split('\n') if name.strip()]
    deleted_items = delete_items(item_names, storage)
    
    if deleted_items:
        text = f"✅ Удалено предметов: {len(deleted_items)}\n\n"
        text += "\n".join(f"• {item}" for item in deleted_items)
    else:
        text = "❌ Не удалось удалить предметы (возможно, они не найдены)"
        
    show_storage_menu(chat_id, storage, text)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'adding_event_name')
def handle_adding_event_name(message):
    chat_id = message.chat.id
    
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление события отменено")
        show_events_menu(chat_id)
        return
        
    user_selections[chat_id] = {'event_name': message.text}
    bot.send_message(chat_id, "📅 Введите дату события в формате ДД.ММ.ГГГГ (например, 25.12.2024) или '❌ Отмена':", reply_markup=create_cancel_keyboard())
    user_states[chat_id] = 'adding_event_date'

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'adding_event_date')
def handle_adding_event_date(message):
    chat_id = message.chat.id
    
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление события отменено")
        show_events_menu(chat_id)
        return
        
    try:
        date_obj = datetime.strptime(message.text, '%d.%m.%Y')
        event_date = date_obj.strftime('%Y-%m-%d')
        event_name = user_selections[chat_id]['event_name']
        
        if add_event(event_name, event_date):
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            bot.send_message(chat_id, f"✅ Событие '{event_name}' на {formatted_date} добавлено")
        else:
            bot.send_message(chat_id, "❌ Ошибка при добавлении события")
            
    except ValueError:
        bot.send_message(chat_id, "❌ Неверный формат даты. Используйте формат ДД.ММ.ГГГГ (например, 25.12.2024)")
        return
        
    show_events_menu(chat_id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'deleting_event')
def handle_deleting_event(message):
    chat_id = message.chat.id
    
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Удаление событий отменено")
        show_events_menu(chat_id)
        return
        
    event_dict = user_selections.get(chat_id, {})
    numbers = [num.strip() for num in message.text.split(',')]
    event_ids_to_delete = []
    
    for num in numbers:
        if num in event_dict:
            event_ids_to_delete.append(event_dict[num])
            
    if event_ids_to_delete:
        deleted_events = delete_event(event_ids_to_delete)
        if deleted_events:
            text = f"✅ Удалено событий: {len(deleted_events)}\n\n"
            text += "\n".join(f"• {event}" for event in deleted_events)
        else:
            text = "❌ Не удалось удалить события"
    else:
        text = "❌ Неверно указаны номера событий"
        
    show_events_menu(chat_id, text)

# Состояния и выбор
user_states = {}
user_selections = {}
user_item_lists = {}

# Инициализация списка администраторов при запуске
load_admins()

# Webhook для Render
@app.route('/')
def index():
    return "Бот управления инвентарем работает!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Invalid content type', 403

if __name__ == '__main__':
    # Проверяем, запущено ли на Render
    if os.environ.get('RENDER'):
        # Настройка webhook для production
        webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        print(f"Webhook установлен: {webhook_url}")
        
        # Запуск Flask приложения
        app.run(host='0.0.0.0', port=10000)
    else:
        # Локальный запуск с polling
        print("Бот запущен в режиме polling...")
        bot.remove_webhook()
        bot.polling(none_stop=True)
