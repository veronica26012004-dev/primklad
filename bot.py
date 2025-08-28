import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from datetime import datetime, timedelta
from uuid import uuid4
import time
from flask import Flask, request

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Загрузка токена из переменной окружения
TOKEN = os.getenv('BOT_TOKEN', '8464322471:AAE3QyJrHrCS8lwAj4jD8NLuOy5kYnToumM')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')  # URL вашего приложения на Render
PORT = int(os.getenv('PORT', 10000))  # Порт для Render

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Блокировка для thread-safe доступа к БД
db_lock = threading.Lock()

# Словарь для преобразования названий месяцев в числа
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

def delete_item(item_ids):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            if isinstance(item_ids, list):
                cursor.executemany('DELETE FROM items WHERE id = ?', [(item_id,) for item_id in item_ids])
            else:
                cursor.execute('DELETE FROM items WHERE id = ?', (item_ids,))
            conn.commit()
            logging.info(f"Deleted items with ids: {item_ids}")
            conn.close()
        except Exception as e:
            logging.error(f"Error deleting items {item_ids}: {e}")

def update_item_owner(item_id, owner):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('UPDATE items SET owner = ?, issued = 1 WHERE id = ?', (owner, item_id))
            conn.commit()
            logging.info(f"Updated item {item_id} to owner: {owner}")
            conn.close()
        except Exception as e:
            logging.error(f"Error updating item {item_id} owner: {e}")

def return_item(item_ids):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            if isinstance(item_ids, list):
                cursor.executemany('UPDATE items SET owner = NULL, issued = 0 WHERE id = ?', [(item_id,) for item_id in item_ids])
            else:
                cursor.execute('UPDATE items SET owner = NULL, issued = 0 WHERE id = ?', (item_ids,))
            conn.commit()
            logging.info(f"Returned items with ids: {item_ids}")
            conn.close()
        except Exception as e:
            logging.error(f"Error returning items {item_ids}: {e}")

def find_item_in_db(item_name, storage):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT id, item_name FROM items WHERE storage = ?', (storage,))
            all_items = cursor.fetchall()
            conn.close()
            normalized_search = normalize_text(item_name)
            for item_id, db_item in all_items:
                if normalize_text(db_item) == normalized_search:
                    return item_id, db_item
            return None, None
        except Exception as e:
            logging.error(f"Error finding item {item_name} in storage {storage}: {e}")
            return None, None

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
            
            # Получаем текущую дату для фильтрации
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
                # Для 'all' показываем все события, отсортированные по дате
                cursor.execute('SELECT id, event_name, event_date FROM events ORDER BY event_date')
            
            events = cursor.fetchall()
            
            # Валидация и фильтрация событий
            validated_events = []
            for event in events:
                try:
                    event_id, event_name, event_date = event
                    # Проверяем корректность даты
                    datetime.strptime(event_date, '%Y-%m-%d')
                    validated_events.append(event)
                except ValueError:
                    logging.warning(f"Invalid date format for event {event_name}: {event_date}")
            
            logging.info(f"Fetched {len(validated_events)} events for period '{period}'")
            conn.close()
            return validated_events
            
        except Exception as e:
            logging.error(f"Error fetching events: {e}")
            return []

def delete_event(event_id):
    with db_lock:
        try:
            conn = sqlite3.connect('inventory.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
            conn.commit()
            logging.info(f"Deleted event with id: {event_id}")
            conn.close()
        except Exception as e:
            logging.error(f"Error deleting event {event_id}: {e}")

# Создаем клавиатуры
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

def create_add_items_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    buttons = [
        types.KeyboardButton('✅ Завершить ввод')
    ]
    keyboard.add(*buttons)
    return keyboard

def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item_id, item_name, _, _, _ in sorted(items, key=lambda x: x[1]):
        callback_data = f"{action}:{item_id}"
        keyboard.add(types.InlineKeyboardButton(text=item_name, callback_data=callback_data))
    
    # Добавляем кнопку "Вернуть все" только для возврата
    if action == 'return':
        keyboard.add(types.InlineKeyboardButton(text="✅ Вернуть все", callback_data="return:all"))
    
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    
    if action in ['give', 'delete', 'return']:
        keyboard.add(types.InlineKeyboardButton(
            text=f"✅ Завершить {'выдачу' if action == 'give' else 'удаление' if action == 'delete' else 'возврат'}", 
            callback_data=f"{action}:done"))
    
    return keyboard

def create_event_keyboard(events, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for event_id, event_name, event_date in sorted(events, key=lambda x: x[2]):
        display_text = f"{event_name} ({event_date})"
        callback_data = f"{action}:{event_id}"
        keyboard.add(types.InlineKeyboardButton(text=display_text, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

def create_period_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = [
        types.InlineKeyboardButton(text="Неделя", callback_data="view_events:week"),
        types.InlineKeyboardButton(text="Месяц", callback_data="view_events:month"),
        types.InlineKeyboardButton(text="Все", callback_data="view_events:all")
    ]
    keyboard.add(*buttons)
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data="view_events:cancel"))
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

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем и событиями!*\n\n"
    welcome_text += "📋 *Доступные разделы:*\n"
    welcome_text += "📦 Кладовая - управление инвентарем\n"
    welcome_text += "📅 События - управление событиями"
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    show_main_menu(message.chat.id)

# Обработчик callback-запросов
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data.split(':')
    action = data[0]
    param = data[1] if len(data) > 1 else None

    try:
        state = user_states.get(chat_id, ('storage', None))
        if isinstance(state, tuple) and len(state) > 1:
            storage = state[1]
        else:
            storage = None
            logging.warning(f"No storage found in state for user {chat_id}: {state}")

        if action == 'give':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                user_states[chat_id] = ('storage', storage)
                return
            elif param == 'done':
                if isinstance(state, tuple) and state[0] == 'give_items':
                    recipient, selected_items, storage = state[1], state[2], state[3]
                    if not selected_items:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, "⚠️ Вы не выбрали ни одного предмета!", 
                                       parse_mode='Markdown', reply_markup=create_storage_keyboard())
                        show_inventory(chat_id, storage)
                        user_states[chat_id] = ('storage', storage)
                        return
                    for item_id in selected_items:
                        update_item_owner(item_id, recipient)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*!",
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
                    return
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient, selected_items, storage = state[1], state[2], state[3]
                if param and param not in selected_items:
                    selected_items.append(param)
                user_states[chat_id] = ('give_items', recipient, selected_items, storage)
                inventory = get_inventory(storage)
                available_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                                 if issued == 0 and item_id not in selected_items]
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'give')
                    selected_text = ", ".join([item_name for item_id, item_name, _, _, _ in inventory 
                                             if item_id in selected_items]) or "ничего не выбрано"
                    bot.edit_message_text(
                        f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи ({storage}):* (выбрано: {selected_text}):",
                        chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, "⚠️ Больше нет доступных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)

        elif action == 'delete':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                user_states[chat_id] = ('storage', storage)
                return
            elif param == 'done':
                if isinstance(state, tuple) and state[0] == 'delete_items':
                    selected_items, storage = state[1], state[2]
                    if not selected_items:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, "⚠️ Вы не выбрали ни одного предмета!", 
                                       parse_mode='Markdown', reply_markup=create_storage_keyboard())
                        show_inventory(chat_id, storage)
                        user_states[chat_id] = ('storage', storage)
                        return
                    delete_item(selected_items)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Удалено предметов: *{len(selected_items)}*",
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
                    return
            if isinstance(state, tuple) and state[0] == 'delete_items':
                selected_items, storage = state[1], state[2]
                if param and param not in selected_items:
                    selected_items.append(param)
                user_states[chat_id] = ('delete_items', selected_items, storage)
                inventory = get_inventory(storage)
                available_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                                 if item_id not in selected_items]
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'delete')
                    selected_text = ", ".join([item_name for item_id, item_name, _, _, _ in inventory 
                                             if item_id in selected_items]) or "ничего не выбрано"
                    bot.edit_message_text(
                        f"🗑️ *Выберите предметы для удаления ({storage}):* (выбрано: {selected_text}):",
                        chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, "⚠️ Больше нет предметов для удаления!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)

        elif action == 'return':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                user_states[chat_id] = ('storage', storage)
                return
            elif param == 'done':
                if isinstance(state, tuple) and state[0] == 'return_items':
                    selected_items, storage = state[1], state[2]
                    if not selected_items:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, "⚠️ Вы не выбрали ни одного предмета!", 
                                       parse_mode='Markdown', reply_markup=create_storage_keyboard())
                        show_inventory(chat_id, storage)
                        user_states[chat_id] = ('storage', storage)
                        return
                    return_item(selected_items)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Возвращено предметов: *{len(selected_items)}*",
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
                    return
            elif param == 'all':
                inventory = get_inventory(storage)
                selected_items = [item_id for item_id, _, _, issued, _ in inventory if issued == 1]
                if selected_items:
                    return_item(selected_items)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{len(selected_items)}*",
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
                return
            
            # Обработка возврата единственного предмета
            if isinstance(state, tuple) and state[0] == 'return_items':
                selected_items, storage = state[1], state[2]
                if param and param not in selected_items:
                    selected_items.append(param)
                user_states[chat_id] = ('return_items', selected_items, storage)
                inventory = get_inventory(storage)
                issued_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                               if issued == 1 and item_id not in selected_items]
                logging.info(f"Issued items for return in {storage}: {issued_items}")
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    selected_text = ", ".join([item_name for item_id, item_name, _, _, _ in inventory 
                                             if item_id in selected_items]) or "ничего не выбрано"
                    bot.edit_message_text(
                        f"📦 *Выберите предметы для возврата ({storage}):* (выбрано: {selected_text}):",
                        chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    # Если больше нет выданных предметов, завершаем возврат
                    if selected_items:
                        return_item(selected_items)
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"✅ Возвращено предметов: *{len(selected_items)}*",
                                       parse_mode='Markdown', reply_markup=create_storage_keyboard())
                        show_inventory(chat_id, storage)
                        user_states[chat_id] = ('storage', storage)
                    else:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, "⚠️ Больше нет выданных предметов!", reply_markup=create_storage_keyboard())
                        show_inventory(chat_id, storage)
                        user_states[chat_id] = ('storage', storage)
                return
            
            # Прямой возврат предмета (без множественного выбора)
            if param:
                return_item(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет возвращен в инвентарь!",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                user_states[chat_id] = ('storage', storage)

        elif action == 'view_events':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            
            events = get_events(param)
            if not events:
                bot.delete_message(chat_id, call.message.message_id)
                
                period_text = {
                    'week': 'на неделю',
                    'month': 'на месяц', 
                    'all': 'вообще'
                }.get(param, '')
                
                bot.send_message(chat_id, f"📅 Нет событий {period_text}!", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            
            # Форматируем текст для отображения
            period_text = {
                'week': 'на неделю',
                'month': 'на месяц',
                'all': 'все'
            }.get(param, param)
            
            text = f"📅 *События ({period_text}):*\n\n"
            for _, event_name, event_date in sorted(events, key=lambda x: x[2]):  # Сортируем по дате
                # Преобразуем дату в более читаемый формат
                try:
                    date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                    formatted_date = date_obj.strftime('%d.%m.%Y')
                    text += f"📌 *{event_name}* - {formatted_date}\n"
                except ValueError:
                    text += f"📌 *{event_name}* - {event_date} (некорректный формат)\n"
            
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='Markdown')
            user_states[chat_id] = 'events'

        elif action == 'delete_event':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            if param:
                delete_event(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Событие удалено!", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'

    except Exception as e:
        logging.error(f"Error in callback_query from {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", 
                        parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
        show_main_menu(chat_id)

# Основной обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'main_menu')

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
                user_states[chat_id] = ('add_items', [], storage)
                bot.send_message(chat_id, "📝 *Введите предметы (по одному на строку):*\n(нажмите 'Завершить ввод' для завершения)",
                               parse_mode='Markdown', reply_markup=create_add_items_keyboard())
            elif text == '➖ Удалить':
                user_states[chat_id] = ('delete_items', [], storage)
                inventory = get_inventory(storage)
                if inventory:
                    keyboard = create_item_keyboard(inventory, 'delete')
                    bot.send_message(chat_id, f"🗑️ *Выберите предметы для удаления ({storage}):*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
            elif text == '🎁 Выдать':
                user_states[chat_id] = ('give_who', storage)
                bot.send_message(chat_id, "👤 *Кому выдать предметы?*\n(напишите имя получателя)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = ('return_items', [], storage)
                inventory = get_inventory(storage)
                issued_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                               if issued == 1]
                logging.info(f"Issued items for return in {storage}: {issued_items}")
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    bot.send_message(chat_id, f"📦 *Выберите предметы для возврата ({storage}):*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
            elif text == '📋 Показать инвентарь':
                show_inventory(chat_id, storage)
            elif text == '✅ Завершить ввод':
                bot.send_message(chat_id, "⚠️ Вы не находитесь в режиме добавления предметов!", 
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)

        elif isinstance(state, tuple) and state[0] == 'add_items':
            items, storage = state[1], state[2]
            if text == '✅ Завершить ввод':
                if items:
                    bot.send_message(chat_id, f"✅ Добавлено предметов: {len(items)}", 
                                   reply_markup=create_storage_keyboard())
                else:
                    bot.send_message(chat_id, "ℹ️ Не добавлено ни одного предмета", 
                                   reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                user_states[chat_id] = ('storage', storage)
            else:
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        item_id, existing_item = find_item_in_db(line, storage)
                        if existing_item is None:
                            item_name = ' '.join(line.split())
                            item_id = add_item(item_name, storage)
                            if item_id:
                                items.append((item_id, item_name))
                bot.send_message(chat_id, "📝 Продолжайте вводить предметы или нажмите 'Завершить ввод'",
                               parse_mode='Markdown', reply_markup=create_add_items_keyboard())
                user_states[chat_id] = ('add_items', items, storage)

        elif isinstance(state, tuple) and state[0] == 'give_who':
            storage = state[1]
            if text and text.strip():
                recipient = ' '.join(text.strip().split())
                if len(recipient) > 50:
                    bot.send_message(chat_id, "⚠️ Имя получателя слишком длинное! Максимум 50 символов.", 
                                   parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
                    return
                user_states[chat_id] = ('give_items', recipient, [], storage)
                inventory = get_inventory(storage)
                available_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                                 if issued == 0]
                logging.info(f"Available items for {recipient} in {storage}: {available_items}")
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'give')
                    bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи ({storage}):*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет доступных предметов для выдачи!", 
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
                    user_states[chat_id] = ('storage', storage)
            else:
                bot.send_message(chat_id, "⚠️ Имя получателя не может быть пустым!", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif state == 'events':
            if text == '🔙 В главное меню':
                show_main_menu(chat_id)
            elif text == '➕ Добавить событие':
                user_states[chat_id] = 'add_event_name'
                bot.send_message(chat_id, "📝 *Введите название события:*", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '📅 Посмотреть события':
                bot.send_message(chat_id, "📅 *Выберите период:*", 
                               parse_mode='Markdown', reply_markup=create_period_keyboard())
            elif text == '🗑️ Удалить событие':
                events = get_events()
                if events:
                    keyboard = create_event_keyboard(events, 'delete_event')
                    bot.send_message(chat_id, "🗑️ *Выберите событие для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет событий для удаления!", reply_markup=create_events_keyboard())
                    user_states[chat_id] = 'events'

        elif state == 'add_event_name':
            if text and text.strip():
                user_states[chat_id] = ('add_event_date', text)
                bot.send_message(chat_id, "📅 *Введите дату события (например, 15 января 2025):*", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            else:
                bot.send_message(chat_id, "⚠️ Название события не может быть пустым!", 
                               parse_mode='Markdown')
                user_states[chat_id] = 'add_event_name'

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            event_name = state[1]
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
                bot.send_message(chat_id, f"⚠️ Неверный формат даты! Используйте формат 'ДД месяц ГГГГ' (например, 15 января 2025): {str(e)}", 
                               parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error processing message from {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", 
                        parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
        show_main_menu(chat_id)

# Webhook обработчики для Render
@app.route('/')
def index():
    return "🤖 Telegram Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Invalid content type', 403

# Запуск бота на Render
if __name__ == '__main__':
    # Удаляем предыдущие webhook'и
    bot.remove_webhook()
    time.sleep(1)
    
    # Устанавливаем webhook
    if WEBHOOK_URL:
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        logging.info(f"Webhook set to: {WEBHOOK_URL}/webhook")
    
    # Запускаем Flask приложение
    app.run(host='0.0.0.0', port=PORT, debug=False)
