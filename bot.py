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
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                owner TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                date TEXT NOT NULL
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
        cursor.execute('SELECT id, item, owner FROM inventory ORDER BY item')
        items = cursor.fetchall()
        conn.close()
        return items  # Возвращает список кортежей (id, item, owner)

def add_item(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO inventory (item, owner) VALUES (?, ?)', (item_name, None))
        conn.commit()
        conn.close()

def delete_item(item_id):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM inventory WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()

def update_item_owner(item_id, owner):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE inventory SET owner = ? WHERE id = ?', (owner, item_id))
        conn.commit()
        conn.close()

def find_item_in_db(item_name):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, item FROM inventory')
        all_items = cursor.fetchall()
        conn.close()

        normalized_search = normalize_text(item_name)
        for item_id, db_item in all_items:
            if normalize_text(db_item) == normalized_search:
                return item_id, db_item
        return None, None

# Функции для работы с событиями
def add_event(event, date):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO events (event, date) VALUES (?, ?)', (event, date))
        conn.commit()
        conn.close()

def get_events(period=None):
    with db_lock:
        conn = sqlite3.connect('inventory.db', check_same_thread=False)
        cursor = conn.cursor()
        today = datetime.now().date()
        
        if period == 'week':
            end_date = today + timedelta(days=7)
            cursor.execute('SELECT id, event, date FROM events WHERE date BETWEEN ? AND ? ORDER BY date',
                         (today.isoformat(), end_date.isoformat()))
        elif period == 'month':
            end_date = today + timedelta(days=30)
            cursor.execute('SELECT id, event, date FROM events WHERE date BETWEEN ? AND ? ORDER BY date',
                         (today.isoformat(), end_date.isoformat()))
        else:
            cursor.execute('SELECT id, event, date FROM events ORDER BY date')
            
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
def create_start_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('📦 Кладовая'),
        types.KeyboardButton('📅 События')
    ]
    keyboard.add(*buttons)
    return keyboard

# Создаем клавиатуру кладовой
def create_warehouse_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить'),
        types.KeyboardButton('➖ Удалить'),
        types.KeyboardButton('🎁 Выдать'),
        types.KeyboardButton('↩️ Вернуть'),
        types.KeyboardButton('📋 Показать инвентарь'),
        types.KeyboardButton('🔙 Главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

# Создаем клавиатуру событий
def create_events_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить событие'),
        types.KeyboardButton('📅 Показать события'),
        types.KeyboardButton('🗑️ Удалить событие'),
        types.KeyboardButton('🔙 Главное меню')
    ]
    keyboard.add(*buttons)
    return keyboard

# Создаем inline-клавиатуру для предметов
def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item_id, item, _ in sorted(items, key=lambda x: x[1]):
        callback_data = f"{action}:{item_id}"
        keyboard.add(types.InlineKeyboardButton(text=item, callback_data=callback_data))
    if action == 'give':
        keyboard.add(types.InlineKeyboardButton(text="✅ Выдано", callback_data=f"{action}:done"))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Создаем inline-клавиатуру для событий
def create_event_keyboard(events, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for event_id, event, date in sorted(events, key=lambda x: x[2]):
        display_text = f"{event} ({date})"
        callback_data = f"{action}:{event_id}"
        keyboard.add(types.InlineKeyboardButton(text=display_text, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data=f"{action}:cancel"))
    return keyboard

# Создаем клавиатуру для выбора периода событий
def create_period_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = [
        types.InlineKeyboardButton(text="Неделя", callback_data="show_events:week"),
        types.InlineKeyboardButton(text="Месяц", callback_data="show_events:month"),
        types.InlineKeyboardButton(text="Все", callback_data="show_events:all")
    ]
    keyboard.add(*buttons)
    keyboard.add(types.InlineKeyboardButton(text="🚫 Отмена", callback_data="show_events:cancel"))
    return keyboard

# Функция для показа главного меню
def show_start_menu(chat_id):
    bot.send_message(chat_id, "🏠 *Главное меню*", parse_mode='Markdown', reply_markup=create_start_keyboard())
    user_states[chat_id] = 'start'

# Функция для показа меню кладовой
def show_warehouse_menu(chat_id):
    inventory = get_inventory()
    text = "📦 *ИНВЕНТАРЬ:*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for _, item, owner in sorted(inventory, key=lambda x: x[1]):
            if owner is None:
                text += f"✅ **{item}** - доступен\n"
                available_count += 1
            else:
                text += f"🔸 {item} - {owner}\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"

    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
    user_states[chat_id] = 'warehouse'

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления!*\n\n"
    welcome_text += "📦 *Кладовая* - управление инвентарем\n"
    welcome_text += "📅 *События* - управление событиями"

    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_start_keyboard())
    show_start_menu(message.chat.id)

# Обработчик callback-запросов
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data.split(':')
    action = data[0]
    value = data[1] if len(data) > 1 else None

    try:
        if action == 'give':
            if value == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)
                return
            elif value == 'done':
                state = user_states.get(chat_id, 'warehouse')
                if isinstance(state, tuple) and state[0] == 'give_items':
                    recipient, selected_items = state[1], state[2]
                    for item_id in selected_items:
                        update_item_owner(item_id, recipient)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Предметы выданы *{recipient}*!",
                                   parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
                    show_warehouse_menu(chat_id)
                return

            state = user_states.get(chat_id, 'warehouse')
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient, selected_items = state[1], state[2]
                if int(value) not in selected_items:
                    selected_items.add(int(value))
                else:
                    selected_items.remove(int(value))
                user_states[chat_id] = ('give_items', recipient, selected_items)
                
                inventory = get_inventory()
                available_items = [(id, item, owner) for id, item, owner in inventory if owner is None]
                keyboard = create_item_keyboard(available_items, 'give')
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи (выбрано: {len(selected_items)}):*",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )

        elif action == 'delete':
            if value == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)
                return

            if value:
                delete_item(int(value))
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Предмет удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)

        elif action == 'return':
            if value == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)
                return
            elif value == 'all':
                inventory = get_inventory()
                returned_count = 0
                for item_id, _, owner in inventory:
                    if owner is not None:
                        update_item_owner(item_id, None)
                        returned_count += 1
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                               parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)
            elif value:
                inventory = get_inventory()
                item = next((i for i in inventory if str(i[0]) == value), None)
                if item and item[2] is not None:
                    update_item_owner(item[0], None)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ Предмет возвращен в инвентарь!",
                                   parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
                    show_warehouse_menu(chat_id)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"ℹ️ Предмет уже в инвентаре!",
                                   parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
                    show_warehouse_menu(chat_id)

        elif action == 'show_events':
            if value == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            events = get_events(value)
            text = f"📅 *События ({value if value != 'all' else 'все'}):*\n\n"
            if not events:
                text += "📭 Нет событий\n"
            else:
                for _, event, date in events:
                    text += f"📅 {event} - {date}\n"
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_events_keyboard())
            user_states[chat_id] = 'events'

        elif action == 'delete_event':
            if value == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
                return
            if value:
                delete_event(int(value))
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ Событие удалено!", parse_mode='Markdown', reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'

    except Exception as e:
        logging.error(f"Ошибка при обработке callback от {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=create_start_keyboard())
        show_start_menu(chat_id)

# Основной обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'start')

    try:
        if state == 'start':
            if text == '📦 Кладовая':
                show_warehouse_menu(chat_id)
            elif text == '📅 События':
                bot.send_message(chat_id, "📅 *Меню событий*", parse_mode='Markdown', reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'

        elif state == 'warehouse':
            if text == '🔙 Главное меню':
                show_start_menu(chat_id)
            elif text == '➕ Добавить':
                user_states[chat_id] = 'add'
                bot.send_message(chat_id, "📝 *Введите предметы (каждый с новой строки):*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '➖ Удалить':
                user_states[chat_id] = 'delete'
                inventory = get_inventory()
                if inventory:
                    keyboard = create_item_keyboard(inventory, 'delete')
                    bot.send_message(chat_id, "🗑️ *Выберите предмет для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Инвентарь пуст!", reply_markup=create_warehouse_keyboard())
                    show_warehouse_menu(chat_id)
            elif text == '🎁 Выдать':
                user_states[chat_id] = 'give_who'
                bot.send_message(chat_id, "👤 *Кому выдать предметы?*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '↩️ Вернуть':
                user_states[chat_id] = 'return_items'
                inventory = get_inventory()
                issued_items = [(id, item, owner) for id, item, owner in inventory if owner is not None]
                if issued_items:
                    keyboard = create_item_keyboard(issued_items, 'return')
                    keyboard.add(types.InlineKeyboardButton(text="🔄 Вернуть все", callback_data="return:all"))
                    bot.send_message(chat_id, "📦 *Выберите предмет для возврата:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет выданных предметов!", reply_markup=create_warehouse_keyboard())
                    show_warehouse_menu(chat_id)
            elif text == '📋 Показать инвентарь':
                show_warehouse_menu(chat_id)

        elif state == 'events':
            if text == '🔙 Главное меню':
                show_start_menu(chat_id)
            elif text == '➕ Добавить событие':
                user_states[chat_id] = 'add_event_name'
                bot.send_message(chat_id, "📝 *Введите название события:*",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
            elif text == '📅 Показать события':
                bot.send_message(chat_id, "📅 *Выберите период:*", parse_mode='Markdown', reply_markup=create_period_keyboard())
            elif text == '🗑️ Удалить событие':
                events = get_events()
                if events:
                    keyboard = create_event_keyboard(events, 'delete_event')
                    bot.send_message(chat_id, "🗑️ *Выберите событие для удаления:*",
                                   parse_mode='Markdown', reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, "⚠️ Нет событий!", reply_markup=create_events_keyboard())
                    user_states[chat_id] = 'events'

        elif state == 'add':
            items = text.split('\n')
            added_items = []
            for item in items:
                item = item.strip()
                if item:
                    item_id, existing_item = find_item_in_db(item)
                    if existing_item is None:
                        item_name = ' '.join(item.split())
                        add_item(item_name)
                        added_items.append(item_name)
            if added_items:
                bot.send_message(chat_id, f"✅ Добавлены предметы: *{', '.join(added_items)}*!",
                               parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
            else:
                bot.send_message(chat_id, "⚠️ Все предметы уже в инвентаре или список пуст!",
                               parse_mode='Markdown', reply_markup=create_warehouse_keyboard())
            show_warehouse_menu(chat_id)

        elif state == 'give_who':
            recipient = ' '.join(text.strip().split())
            user_states[chat_id] = ('give_items', recipient, set())
            inventory = get_inventory()
            available_items = [(id, item, owner) for id, item, owner in inventory if owner is None]
            if available_items:
                keyboard = create_item_keyboard(available_items, 'give')
                bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Выберите предметы для выдачи:*",
                               parse_mode='Markdown', reply_markup=keyboard)
            else:
                bot.send_message(chat_id, "⚠️ Нет доступных предметов для выдачи!", reply_markup=create_warehouse_keyboard())
                show_warehouse_menu(chat_id)

        elif state == 'add_event_name':
            user_states[chat_id] = ('add_event_date', text.strip())
            bot.send_message(chat_id, "📅 *Введите дату события (ГГГГ-ММ-ДД):*",
                           parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif isinstance(state, tuple) and state[0] == 'add_event_date':
            try:
                datetime.strptime(text, '%Y-%m-%d')
                add_event(state[1], text)
                bot.send_message(chat_id, f"✅ Событие *{state[1]}* на {text} добавлено!",
                               parse_mode='Markdown', reply_markup=create_events_keyboard())
                user_states[chat_id] = 'events'
            except ValueError:
                bot.send_message(chat_id, "⚠️ Неверный формат даты! Используйте ГГГГ-ММ-ДД",
                               parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=create_start_keyboard())
        show_start_menu(chat_id)

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
            time.sleep(5)
