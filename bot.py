Я понял, что вы хотите упростить выдачу инвентаря, чтобы вместо выбора получателя и предметов через интерактивные кнопки пользователь просто вводил имя получателя, а затем предметы выдаются напрямую. Также учту, что у вас уже есть две кладовые (Гринбокс 11 и Гринбокс 12), дата вводится словами, и завершение ввода предметов происходит через кнопку "Завершить ввод". Я обновлю код, чтобы при выдаче предметов пользователь вводил только имя получателя, а затем список предметов, которые сразу выдаются этому получателю.

### Основные изменения:
1. **Упрощение выдачи предметов**:
   - При выборе действия "🎁 Выдать" бот запрашивает имя получателя.
   - После ввода имени пользователь вводит названия предметов (по одному на строку).
   - Предметы, которые уже есть в базе данных для выбранной кладовой, выдаются указанному получателю.
   - Ввод завершается кнопкой "✅ Завершить ввод".
   - Если предмет не найден в базе данных, бот сообщает об этом.

2. **Сохранение существующих функций**:
   - Поддерживаются две кладовые (Гринбокс 11 и Гринбокс 12).
   - Ввод даты события в формате "ДД месяц ГГГГ" (например, "15 января 2025").
   - Завершение ввода предметов при добавлении через кнопку "✅ Завершить ввод".

3. **Обновление состояний**:
   - Состояние `give_who` теперь переходит в `give_items`, где пользователь вводит предметы для выдачи.
   - Состояние `give_items` хранит имя получателя и кладовую.

Вот обновленный код:

```python
import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from datetime import datetime, timedelta
from uuid import uuid4
import time

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
bot = telebot.TeleBot(TOKEN)

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
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        if storage:
            cursor.execute('SELECT id, item_name, owner, issued, storage FROM items WHERE storage = ?', (storage,))
        else:
            cursor.execute('SELECT id, item_name, owner, issued, storage FROM items')
        items = cursor.fetchall()
        conn.close()
        return items

def add_item(item_name, storage):
    item_id = str(uuid4())
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO items (id, item_name, owner, issued, storage) VALUES (?, ?, ?, ?, ?)', 
                      (item_id, item_name, None, 0, storage))
        conn.commit()
        conn.close()
    return item_id

def delete_item(item_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM items WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()

def update_item_owner(item_id, owner):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE items SET owner = ?, issued = 1 WHERE id = ?', (owner, item_id))
        conn.commit()
        conn.close()

def return_item(item_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE items SET owner = NULL, issued = 0 WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()

def find_item_in_db(item_name, storage):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, item_name, issued FROM items WHERE storage = ?', (storage,))
        all_items = cursor.fetchall()
        conn.close()

        normalized_search = normalize_text(item_name)
        for item_id, db_item, issued in all_items:
            if normalize_text(db_item) == normalized_search and issued == 0:
                return item_id, db_item
        return None, None

# Функции для работы с событиями
def add_event(event_name, event_date):
    event_id = str(uuid4())
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO events (id, event_name, event_date) VALUES (?, ?, ?)',
                      (event_id, event_name, event_date))
        conn.commit()
        conn.close()
    return event_id

def get_events(period=None):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        query = 'SELECT id, event_name, event_date FROM events'
        if period == 'week':
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
            query += ' WHERE event_date BETWEEN ? AND ?'
            cursor.execute(query, (start_date, end_date))
        elif period == 'month':
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            query += ' WHERE event_date BETWEEN ? AND ?'
            cursor.execute(query, (start_date, end_date))
        else:
            cursor.execute(query)
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
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
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
        if action == 'delete':
            state = user_states.get(chat_id, ('storage', None))
            storage = state[1] if isinstance(state, tuple) else None
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                return
            if param:
                delete_item(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)

        elif action == 'return':
            state = user_states.get(chat_id, ('storage', None))
            storage = state[1] if isinstance(state, tuple) else None
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
                return
            elif param == 'all':
                inventory = get_inventory(storage)
                returned_count = 0
                for item_id, _, _, issued, _ in inventory:
                    if issued == 1:
                        return_item(item_id)
                        returned_count += 1
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
            elif param:
                return_item(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет возвращен в инвентарь!",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)

        elif action == 'view_events':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            events = get_events(param)
            if not events:
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "📅 Нет событий за выбранный период!", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            text = f"📅 *События ({param if param != 'all' else 'все'}):*\n\n"
            for _, event_name, event_date in sorted(events, key=lambda x: x[2]):
                text += f"📌 {event_name} - {event_date}\n"
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='Markdown', 
                                reply_markup=create_events_keyboard())
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
        logging.error(f"Ошибка при обработке callback от {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", 
                        reply_markup=create_main_menu_keyboard())
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
                user_states[chat_id] = ('delete', storage)
                inventory = get_inventory(storage)
                if inventory:
                    keyboard = create_item_keyboard(inventory, 'delete')
                    bot.send_message(chat_id, f"🗑️ *Выберите предмет для удаления ({storage}):*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
            elif text == '🎁 Выдать':
                user_states[chat_id] = ('give_who', storage)
                bot.send_message(chat_id, "👤 *Кому выдать предметы?*\n(напишите имя получателя)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = ('return_items', storage)
                inventory = get_inventory(storage)
                issued_items = [(item_id, item_name, owner, issued, _) for item_id, item_name, owner, issued, _ in inventory 
                               if issued == 1]
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    keyboard.add(types.InlineKeyboardButton(text="🔄 Вернуть все", callback_data="return:all"))
                    bot.send_message(chat_id, f"📦 *Выберите предмет для возврата ({storage}):*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id, storage)
            elif text == '📋 Показать инвентарь':
                show_inventory(chat_id, storage)
            elif text == '✅ Завершить ввод':
                bot.send_message(chat_id, "⚠️ Вы не находитесь в режиме добавления или выдачи предметов!", 
                               reply_markup=create_storage_keyboard())
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
            else:
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        item_id, existing_item = find_item_in_db(line, storage)
                        if existing_item is None:
                            item_name = ' '.join(line.split())
                            item_id = add_item(item_name, storage)
                            items.append((item_id, item_name))
                bot.send_message(chat_id, "📝 Продолжайте вводить предметы или нажмите 'Завершить ввод'",
                               parse_mode='Markdown', reply_markup=create_add_items_keyboard())
                user_states[chat_id] = ('add_items', items, storage)

        elif isinstance(state, tuple) and state[0] == 'give_who':
            storage = state[1]
            if text:
                recipient = ' '.join(text.strip().split())
                user_states[chat_id] = ('give_items', recipient, [], storage)
                bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Введите предметы для выдачи (по одному на строку, только доступные предметы из {storage}):*\n(нажмите 'Завершить ввод' для завершения)",
                               parse_mode='Markdown', reply_markup=create_add_items_keyboard())
            else:
                bot.send_message(chat_id, "⚠️ Имя получателя не может быть пустым!", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif isinstance(state, tuple) and state[0] == 'give_items':
            recipient, issued_items, storage = state[1], state[2], state[3]
            if text == '✅ Завершить ввод':
                if issued_items:
                    bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*: {', '.join(issued_items)}", 
                                   reply_markup=create_storage_keyboard())
                else:
                    bot.send_message(chat_id, "ℹ️ Не выдано ни одного предмета", 
                                   reply_markup=create_storage_keyboard())
                show_inventory(chat_id, storage)
            else:
                lines = text.split('\n')
                not_found_items = []
                for line in lines:
                    line = line.strip()
                    if line:
                        item_id, item_name = find_item_in_db(line, storage)
                        if item_id and item_name:
                            update_item_owner(item_id, recipient)
                            issued_items.append(item_name)
                        else:
                            not_found_items.append(line)
                if not_found_items:
                    bot.send_message(chat_id, f"⚠️ Следующие предметы не найдены или уже выданы: {', '.join(not_found_items)}",
                                   parse_mode='Markdown')
                bot.send_message(chat_id, "📝 Продолжайте вводить предметы или нажмите 'Завершить ввод'",
                               parse_mode='Markdown', reply_markup=create_add_items_keyboard())
                user_states[chat_id] = ('give_items', recipient, issued_items, storage)

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
            if text:
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
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", 
                        reply_markup=create_main_menu_keyboard())
        show_main_menu(chat_id)

# Запуск бота
if __name__ == '__main__':
    print("🤖 Бот запущен...")
    logging.info("Бот запущен")
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logging.error(f"Ошибка в polling: {e}")
            time.sleep(5)
```

### Ключевые изменения:
1. **Упрощенная выдача предметов**:
   - При выборе "🎁 Выдать" бот запрашивает имя получателя (состояние `give_who`).
   - После ввода имени пользователь переходит в состояние `give_items`, где вводит названия предметов (по одному на строку).
   - Функция `find_item_in_db` проверяет, есть ли предмет в базе данных для выбранной кладовой и не выдан ли он (`issued == 0`).
   - Если предмет найден, он сразу выдается получателю через `update_item_owner`.
   - Если предмет не найден или уже выдан, он добавляется в список `not_found_items`, и бот сообщает об этом.
   - Ввод завершается кнопкой "✅ Завершить ввод", после чего бот подтверждает выдачу предметов или сообщает, что ничего не выдано.

2. **Обновление функции `find_item_in_db`**:
   - Теперь функция также проверяет, что предмет не выдан (`issued == 0`), чтобы выдавать только доступные предметы.

3. **Сохранение предыдущих изменений**:
   - Поддержка двух кладовых (Гринбокс 11 и Гринбокс 12) с полем `storage` в базе данных.
   - Ввод даты события в формате "ДД месяц ГГГГ" с преобразованием в `ГГГГ-ММ-ДД` для базы данных.
   - Завершение ввода предметов при добавлении через кнопку "✅ Завершить ввод".

4. **Обновление состояний**:
   - Состояние `give_who` теперь кортеж `('give_who', storage)`.
   - Состояние `give_items` теперь кортеж `('give_items', recipient, issued_items, storage)`, где `issued_items` — список выданных предметов для отображения в итоговом сообщении.

5. **Удаление ненужного кода**:
   - Удалены обработчики callback-запросов для действия `give`, так как выбор предметов через кнопки больше не используется.

### Примечания:
- Пользователь должен вводить точные названия предметов, как они записаны в базе данных (с учетом нормализации текста, т.е. лишние пробелы и регистр игнорируются).
- Если предмет не найден или уже выдан, бот добавляет его в список `not_found_items` и сообщает об этом после обработки строки.
- Бот возвращается в меню кладовой после завершения ввода предметов для выдачи.
- Все операции логируются, и обработка ошибок сохраняет стабильность бота.
- База данных хранит предметы с указанием кладовой (`storage`), и операции выполняются только для выбранной кладовой.

Если есть дополнительные пожелания или что-то нужно доработать (например, добавить проверку на частичное совпадение названий предметов или другие функции), дайте знать!
