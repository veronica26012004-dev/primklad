import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from dotenv import load_dotenv
import time
from datetime import datetime, timedelta
from uuid import uuid4

# Настройка логирования
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN не найден в переменных окружения")
    raise ValueError("BOT_TOKEN не установлен")

bot = telebot.TeleBot(TOKEN)

# Блокировка для thread-safe доступа к БД
db_lock = threading.Lock()

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
                issued INTEGER DEFAULT 0
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
def get_inventory():
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, item_name, owner, issued FROM items')
        items = cursor.fetchall()
        conn.close()
        return items

def add_item(item_name):
    item_id = str(uuid4())
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO items (id, item_name, owner, issued) VALUES (?, ?, ?, ?)', 
                      (item_id, item_name, None, 0))
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

def mark_item_issued(item_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE items SET issued = 1 WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()

def return_item(item_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE items SET owner = NULL, issued = 0 WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()

def find_item_in_db(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, item_name FROM items')
        all_items = cursor.fetchall()
        conn.close()

        normalized_search = normalize_text(item_name)
        for item_id, db_item in all_items:
            if normalize_text(db_item) == normalized_search:
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

# Создаем клавиатуру главного меню
def create_main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📦 Кладовая'),
        types.KeyboardButton('📅 События')
    ]
    keyboard.add(*buttons)
    return keyboard

# Создаем клавиатуру кладовой
def create_storage_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить'),
        types.KeyboardButton('➖ Удалить'),
        types.KeyboardButton('🎁 Выдать'),
        types.KeyboardButton('↩️ Вернуть'),
        types.KeyboardButton('📋 Показать инвентарь'),
        types.KeyboardButton('🔙 В главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

# Создаем клавиатуру событий
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

# Создаем inline-клавиатуру для предметов
def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item_id, item_name, _, _ in sorted(items, key=lambda x: x[1]):
        callback_data = f"{action}:{item_id}"
        keyboard.add(types.InlineKeyboardButton(text=item_name, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    if action == 'give':
        keyboard.add(types.InlineKeyboardButton(text="✅ Выдано", callback_data=f"{action}:done"))
    return keyboard

# Создаем inline-клавиатуру для событий
def create_event_keyboard(events, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for event_id, event_name, event_date in sorted(events, key=lambda x: x[2]):
        display_text = f"{event_name} ({event_date})"
        callback_data = f"{action}:{event_id}"
        keyboard.add(types.InlineKeyboardButton(text=display_text, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Создаем inline-клавиатуру для выбора периода событий
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

# Функция для показа главного меню
def show_main_menu(chat_id):
    text = "📋 *Главное меню*\n\nВыберите раздел:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[chat_id] = 'main_menu'

# Функция для показа инвентаря
def show_inventory(chat_id):
    inventory = get_inventory()
    text = "📦 *ИНВЕНТАРЬ:*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for _, item_name, owner, issued in sorted(inventory, key=lambda x: x[1]):
            if owner is None and issued == 0:
                text += f"✅ **{item_name}** - доступен\n"
                available_count += 1
            else:
                text += f"🔸 {item_name} - {owner or 'не указано'}\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_keyboard())
    user_states[chat_id] = 'storage'

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
        if action == 'give':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id)
                return
            elif param == 'done':
                state = user_states.get(chat_id, 'storage')
                if isinstance(state, tuple) and state[0] == 'give_items':
                    recipient = state[1]
                    selected_items = state[2]
                    for item_id in selected_items:
                        mark_item_issued(item_id)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*!",
                                   parse_mode='Markdown', reply_markup=create_storage_keyboard())
                    show_inventory(chat_id)
                    user_states[chat_id] = 'storage'
                    return
            state = user_states.get(chat_id, 'storage')
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient = state[1]
                selected_items = state[2]
                if param not in selected_items:
                    selected_items.append(param)
                user_states[chat_id] = ('give_items', recipient, selected_items)
                inventory = get_inventory()
                available_items = [(item_id, item_name, owner, issued) for item_id, item_name, owner, issued in inventory 
                                 if issued == 0 and item_id not in selected_items]
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'give')
                    selected_text = ", ".join([item_name for item_id, item_name, _, _ in inventory 
                                             if item_id in selected_items]) or "ничего не выбрано"
                    bot.edit_message_text(
                        f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи* (выбрано: {selected_text}):",
                        chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, "⚠️ Больше нет доступных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id)

        elif action == 'delete':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id)
                return
            if param:
                delete_item(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id)

        elif action == 'return':
            if param == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_storage_keyboard())
                show_inventory(chat_id)
                return
            elif param == 'all':
                inventory = get_inventory()
                returned_count = 0
                for item_id, _, _, issued in inventory:
                    if issued == 1:
                        return_item(item_id)
                        returned_count += 1
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id)
            elif param:
                return_item(param)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет возвращен в инвентарь!",
                               parse_mode='Markdown', reply_markup=create_storage_keyboard())
                show_inventory(chat_id)

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
                user_states[chat_id] = 'storage'
                show_inventory(chat_id)
            elif text == '📅 События':
                user_states[chat_id] = 'events'
                bot.send_message(chat_id, "📅 *События*\n\nВыберите действие:", 
                               parse_mode='Markdown', reply_markup=create_events_keyboard())
            else:
                show_main_menu(chat_id)

        elif state == 'storage':
            if text == '🔙 В главное меню':
                show_main_menu(chat_id)
            elif text == '➕ Добавить':
                user_states[chat_id] = ('add_items', [])
                bot.send_message(chat_id, "📝 *Введите предметы (по одному на строку):*\n(отправьте пустое сообщение для завершения)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '➖ Удалить':
                user_states[chat_id] = 'delete'
                inventory = get_inventory()
                if inventory:
                    keyboard = create_item_keyboard(inventory, 'delete')
                    bot.send_message(chat_id, "🗑️ *Выберите предмет для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id)
            elif text == '🎁 Выдать':
                user_states[chat_id] = 'give_who'
                bot.send_message(chat_id, "👤 *Кому выдать предметы?*\n(напишите имя получателя)",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = 'return_items'
                inventory = get_inventory()
                issued_items = [(item_id, item_name, owner, issued) for item_id, item_name, owner, issued in inventory 
                               if issued == 1]
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    keyboard.add(types.InlineKeyboardButton(text="🔄 Вернуть все", callback_data="return:all"))
                    bot.send_message(chat_id, "📦 *Выберите предмет для возврата:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=create_storage_keyboard())
                    show_inventory(chat_id)
            elif text == '📋 Показать инвентарь':
                show_inventory(chat_id)

        elif isinstance(state, tuple) and state[0] == 'add_items':
            items = state[1]
            if text:
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        item_id, existing_item = find_item_in_db(line)
                        if existing_item is None:
                            item_name = ' '.join(line.split())
                            item_id = add_item(item_name)
                            items.append((item_id, item_name))
                bot.send_message(chat_id, "📝 Продолжайте вводить предметы или отправьте пустое сообщение для завершения",
                               parse_mode='Markdown')
                user_states[chat_id] = ('add_items', items)
            else:
                if items:
                    bot.send_message(chat_id, f"✅ Добавлено предметов: {len(items)}", 
                                   reply_markup=create_storage_keyboard())
                else:
                    bot.send_message(chat_id, "ℹ️ Не добавлено ни одного предмета", 
                                   reply_markup=create_storage_keyboard())
                show_inventory(chat_id)

        elif state == 'give_who':
            if text:
                recipient = ' '.join(text.strip().split())
                user_states[chat_id] = ('give_items', recipient, [])
                inventory = get_inventory()
                available_items = [(item_id, item_name, owner, issued) for item_id, item_name, owner, issued in inventory 
                                 if issued == 0]
                if available_items:
                    keyboard = create_item_keyboard(available_items, 'give')
                    bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет доступных предметов для выдачи!", 
                                   reply_markup=create_storage_keyboard())
                    show_inventory(chat_id)

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
                bot.send_message(chat_id, "📅 *Введите дату события (ГГГГ-ММ-ДД):*", 
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            else:
                bot.send_message(chat_id, "⚠️ Название события не может быть пустым!", 
                               parse_mode='Markdown')
                user_states[chat_id] = 'add_event_name'

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            event_name = state[1]
            try:
                datetime.strptime(text, '%Y-%m-%d')
                add_event(event_name, text)
                bot.send_message(chat_id, f"✅ Событие *{event_name}* на {text} добавлено!", 
                               parse_mode='Markdown', reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
            except ValueError:
                bot.send_message(chat_id, "⚠️ Неверный формат даты! Используйте ГГГГ-ММ-ДД", 
                               parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", 
                        reply_markup=create_main_menu_keyboard())
        show_main_menu(chat_id)

# Очистка старых состояний
def clean_old_states():
    while True:
        time.sleep(3600)
        current_time = time.time()
        for chat_id in list(user_states.keys()):
            if current_time - user_states.get(chat_id, {}).get('last_activity', 0) > 3600:
                del user_states[chat_id]

# Запуск потока для очистки состояний
threading.Thread(target=clean_old_states, daemon=True).start()

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
