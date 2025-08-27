import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from dotenv import load_dotenv
import time
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Загрузка переменных окружения
load_dotenv()
TOKEN = '8464322471:AAE3QyJrHrCS8lwAj4jD8NLuOy5kYnToumM'
bot = telebot.TeleBot(TOKEN)

# Блокировка для thread-safe доступа к БД
db_lock = threading.Lock()

# Инициализация базы данных
def init_database():
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                owner TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_text TEXT NOT NULL,
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

# Функции для работы с инвентарем
def get_inventory():
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT item, owner FROM inventory ORDER BY item')
        items = cursor.fetchall()
        conn.close()
        return items

def add_item(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO inventory (item, owner) VALUES (?, ?)', (item_name, None))
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
def add_event(event_text, event_date):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO events (event_text, event_date) VALUES (?, ?)', (event_text, event_date))
        conn.commit()
        conn.close()

def get_events(period=None):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        if period == 'week':
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
            cursor.execute('SELECT event_text, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', (start_date, end_date))
        elif period == 'month':
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            cursor.execute('SELECT event_text, event_date FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date', (start_date, end_date))
        else:
            cursor.execute('SELECT event_text, event_date FROM events ORDER BY event_date')
        events = cursor.fetchall()
        conn.close()
        return events

def delete_event(event_text, event_date):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM events WHERE event_text = ? AND event_date = ?', (event_text, event_date))
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

main_menu_keyboard = create_main_menu_keyboard()

# Создаем клавиатуру кладовой
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

storage_keyboard = create_storage_keyboard()

# Создаем клавиатуру событий
def create_events_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить событие'),
        types.KeyboardButton('📋 Показать события'),
        types.KeyboardButton('➖ Удалить событие'),
        types.KeyboardButton('🔙 Назад')
    ]
    keyboard.add(*buttons)
    return keyboard

events_keyboard = create_events_keyboard()

# Функция для создания inline-клавиатуры с предметами
def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item in sorted(set(items)):
        callback_data = f"{action}:{item}"
        keyboard.add(types.InlineKeyboardButton(text=item, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="✅ Завершить выбор", callback_data=f"{action}:done"))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Функция для создания inline-клавиатуры событий
def create_event_keyboard(events, action):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for event_text, event_date in events:
        callback_data = f"{action}:{event_text}:{event_date}"
        keyboard.add(types.InlineKeyboardButton(text=f"{event_text} ({event_date})", callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Функция для показа инвентаря
def show_inventory(chat_id):
    inventory = get_inventory()
    text = "📦 *ИНВЕНТАРЬ:*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for item, owner in sorted(inventory):
            if owner is None:
                text += f"✅ **{item}** - доступен\n"
                available_count += 1
            else:
                text += f"🔸 {item} - {owner}\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=storage_keyboard)
    user_states[chat_id] = 'storage'

# Функция для показа главного меню
def show_main_menu(chat_id):
    bot.send_message(chat_id, "📋 *Главное меню:*", parse_mode='Markdown', reply_markup=main_menu_keyboard)
    user_states[chat_id] = 'main_menu'

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем!*\n\n"
    welcome_text += "📋 Выберите раздел в меню ниже:"
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=main_menu_keyboard)
    show_main_menu(message.chat.id)

# Обработчик callback-запросов от inline-кнопок
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data.split(':')
    action = data[0]
    item_name = data[1] if len(data) > 1 else None

    try:
        if action == 'give':
            state = user_states.get(chat_id, 'main_menu')
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient, selected_items = state[1], state[2]
                if item_name == 'cancel':
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=storage_keyboard)
                    show_inventory(chat_id)
                    return
                elif item_name == 'done':
                    if selected_items:
                        for item in selected_items:
                            update_item_owner(item, recipient)
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*: {', '.join(selected_items)}",
                                       parse_mode='Markdown', reply_markup=storage_keyboard)
                        show_inventory(chat_id)
                    else:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, "⚠️ Не выбрано ни одного предмета!", reply_markup=storage_keyboard)
                        show_inventory(chat_id)
                    return
                if item_name and item_name not in selected_items:
                    inventory = get_inventory()
                    if any(i[0] == item_name and i[1] is None for i in inventory):
                        selected_items.append(item_name)
                        user_states[chat_id] = ('give_items', recipient, selected_items)
                        available_items = [i[0] for i in inventory if i[1] is None and i[0] not in selected_items]
                        if available_items:
                            keyboard = create_item_keyboard(available_items, 'give')
                            bot.edit_message_text(f"👤 Получатель: *{recipient}*\n📦 Выбрано: {', '.join(selected_items) if selected_items else 'ничего'}\nВыберите еще предмет или завершите:",
                                                chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
                        else:
                            for item in selected_items:
                                update_item_owner(item, recipient)
                            bot.delete_message(chat_id, call.message.message_id)
                            bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*: {', '.join(selected_items)}",
                                           parse_mode='Markdown', reply_markup=storage_keyboard)
                            show_inventory(chat_id)
                    else:
                        bot.answer_callback_query(call.id, f"⚠️ {item_name} уже выдан или недоступен!")

        elif action == 'delete':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=storage_keyboard)
                show_inventory(chat_id)
                return
            if item_name:
                delete_item(item_name)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ *{item_name}* удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=storage_keyboard)
                show_inventory(chat_id)

        elif action == 'return':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=storage_keyboard)
                show_inventory(chat_id)
                return
            elif item_name == 'all':
                inventory = get_inventory()
                returned_count = 0
                for item, owner in inventory:
                    if owner is not None:
                        update_item_owner(item, None)
                        returned_count += 1
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                               parse_mode='Markdown', reply_markup=storage_keyboard)
                show_inventory(chat_id)
            elif item_name:
                inventory = get_inventory()
                if any(i[0] == item_name and i[1] is not None for i in inventory):
                    update_item_owner(item_name, None)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ *{item_name}* возвращен в инвентарь!",
                                   parse_mode='Markdown', reply_markup=storage_keyboard)
                    show_inventory(chat_id)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"ℹ️ *{item_name}* уже в инвентаре!",
                                   parse_mode='Markdown', reply_markup=storage_keyboard)
                    show_inventory(chat_id)

        elif action == 'show_events':
            period = item_name
            events = get_events(period)
            bot.delete_message(chat_id, call.message.message_id)
            if events:
                text = f"📅 *События ({period if period else 'все'}):*\n\n"
                for event_text, event_date in events:
                    text += f"📌 {event_text} - {event_date}\n"
                bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=events_keyboard)
            else:
                bot.send_message(chat_id, f"📭 Нет событий для {period if period else 'всех'}!", reply_markup=events_keyboard)
            user_states[chat_id] = 'events'

        elif action == 'delete_event':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=events_keyboard)
                user_states[chat_id] = 'events'
                return
            event_text, event_date = item_name, data[2]
            delete_event(event_text, event_date)
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, f"✅ Событие *{event_text}* ({event_date}) удалено!",
                           parse_mode='Markdown', reply_markup=events_keyboard)
            user_states[chat_id] = 'events'

    except Exception as e:
        logging.error(f"Ошибка при обработке callback от {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_menu_keyboard)
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
                bot.send_message(chat_id, "📅 *Меню событий:*", parse_mode='Markdown', reply_markup=events_keyboard)

        elif state == 'storage':
            if text == '🔙 Назад':
                show_main_menu(chat_id)
            elif text == '➕ Добавить':
                user_states[chat_id] = 'add'
                bot.send_message(chat_id, "📝 *Введите список предметов (каждый с новой строки):*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '➖ Удалить':
                user_states[chat_id] = 'delete'
                inventory = get_inventory()
                if inventory:
                    keyboard = create_item_keyboard([i[0] for i in inventory], 'delete')
                    bot.send_message(chat_id, "🗑️ *Выберите предмет для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=storage_keyboard)
                    show_inventory(chat_id)
            elif text == '🎁 Выдать':
                user_states[chat_id] = 'give_who'
                bot.send_message(chat_id, "👤 *Кому выдать предметы?*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = 'return_items'
                inventory = get_inventory()
                issued_items = [i[0] for i in inventory if i[1] is not None]
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    keyboard.add(types.InlineKeyboardButton(text="🔄 Вернуть все", callback_data="return:all"))
                    bot.send_message(chat_id, "📦 *Выберите предмет для возврата:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=storage_keyboard)
                    show_inventory(chat_id)
            elif text == '📋 Показать инвентарь':
                show_inventory(chat_id)

        elif state == 'events':
            if text == '🔙 Назад':
                show_main_menu(chat_id)
            elif text == '➕ Добавить событие':
                user_states[chat_id] = 'add_event_text'
                bot.send_message(chat_id, "📝 *Введите описание события:*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '📋 Показать события':
                keyboard = types.InlineKeyboardMarkup(row_width=3)
                keyboard.add(
                    types.InlineKeyboardButton(text="Неделя", callback_data="show_events:week"),
                    types.InlineKeyboardButton(text="Месяц", callback_data="show_events:month"),
                    types.InlineKeyboardButton(text="Все", callback_data="show_events:all")
                )
                bot.send_message(chat_id, "📅 *Выберите период для просмотра событий:*",
                               parse_mode='Markdown', reply_markup=keyboard)
            elif text == '➖ Удалить событие':
                user_states[chat_id] = 'delete_event'
                events = get_events()
                if events:
                    keyboard = create_event_keyboard(events, 'delete_event')
                    bot.send_message(chat_id, "🗑️ *Выберите событие для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "📭 Нет событий для удаления!", reply_markup=events_keyboard)
                    user_states[chat_id] = 'events'

        elif state == 'add':
            items = text.split('\n')
            added_items = []
            for item in items:
                item = item.strip()
                if item:
                    existing_item = find_item_in_db(item)
                    if existing_item is None:
                        add_item(item)
                        added_items.append(item)
            if added_items:
                bot.send_message(chat_id, f"✅ Добавлены предметы: {', '.join(added_items)}",
                               parse_mode='Markdown', reply_markup=storage_keyboard)
            else:
                bot.send_message(chat_id, "⚠️ Ни один предмет не добавлен (возможно, они уже есть или список пуст)!",
                               parse_mode='Markdown', reply_markup=storage_keyboard)
            show_inventory(chat_id)

        elif state == 'give_who':
            recipient = ' '.join(text.strip().split())
            user_states[chat_id] = ('give_items', recipient, [])
            inventory = get_inventory()
            available_items = [i[0] for i in inventory if i[1] is None]
            if available_items:
                keyboard = create_item_keyboard(available_items, 'give')
                bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи (можно несколько):*",
                               parse_mode='Markdown', reply_markup=keyboard)
            else:
                bot.send_message(chat_id, "⚠️ Нет доступных предметов для выдачи!", reply_markup=storage_keyboard)
                show_inventory(chat_id)

        elif state == 'add_event_text':
            user_states[chat_id] = ('add_event_date', text)
            bot.send_message(chat_id, "📅 *Введите дату события (ГГГГ-ММ-ДД):*",
                           parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            try:
                event_date = datetime.strptime(text, '%Y-%m-%d').strftime('%Y-%m-%d')
                event_text = state[1]
                add_event(event_text, event_date)
                bot.send_message(chat_id, f"✅ Событие *{event_text}* ({event_date}) добавлено!",
                               parse_mode='Markdown', reply_markup=events_keyboard)
                user_states[chat_id] = 'events'
            except ValueError:
                bot.send_message(chat_id, "⚠️ Неверный формат даты! Используйте ГГГГ-ММ-ДД.",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_menu_keyboard)
        show_main_menu(chat_id)

# Очистка старых состояний пользователей
def clean_old_states():
    while True:
        time.sleep(3600)  # Каждые 60 минут
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
            time.sleep(5)  # Пауза перед перезапуском
