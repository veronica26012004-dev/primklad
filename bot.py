import sqlite3
import telebot
from telebot import types
import threading
import logging
import os
from dotenv import load_dotenv
import time

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
                item TEXT PRIMARY KEY,
                owner TEXT
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

# Функции для работы с базой данных
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

# Создаем кастомную клавиатуру главного меню с эмодзи
def create_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('➕ Добавить'),
        types.KeyboardButton('➖ Удалить'),
        types.KeyboardButton('🎁 Выдать'),
        types.KeyboardButton('↩️ Вернуть'),
        types.KeyboardButton('📋 Показать инвентарь')
    ]
    keyboard.add(*buttons)
    return keyboard

main_keyboard = create_main_keyboard()

# Функция для создания inline-клавиатуры с предметами
def create_item_keyboard(items, action):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for item in sorted(items):
        callback_data = f"{action}:{item}"
        keyboard.add(types.InlineKeyboardButton(text=item, callback_data=callback_data))
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

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"User {message.chat.id} started bot")
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем!*\n\n"
    welcome_text += "📋 *Доступные команды:*\n"
    welcome_text += "➕ Добавить - добавить новый предмет\n"
    welcome_text += "➖ Удалить - удалить предмет\n"
    welcome_text += "🎁 Выдать - выдать предмет кому-то\n"
    welcome_text += "↩️ Вернуть - вернуть предмет в инвентарь\n"
    welcome_text += "📋 Показать инвентарь - обновить список"

    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=main_keyboard)
    show_menu(message.chat.id)

# Обработчик callback-запросов от inline-кнопок
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    data = call.data.split(':')
    action = data[0]
    item_name = data[1] if len(data) > 1 else None

    try:
        if action == 'give':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return

            state = user_states.get(chat_id, 'main')
            if isinstance(state, tuple) and state[0] == 'give_items':
                recipient = state[1]
                inventory = get_inventory()
                if item_name in inventory:
                    if inventory[item_name] is None:
                        update_item_owner(item_name, recipient)
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"✅ *{item_name}* выдан *{recipient}*!",
                                       parse_mode='Markdown', reply_markup=main_keyboard)
                        show_menu(chat_id)
                    else:
                        bot.delete_message(chat_id, call.message.message_id)
                        bot.send_message(chat_id, f"⚠️ *{item_name}* уже выдан *{inventory[item_name]}*!",
                                       parse_mode='Markdown', reply_markup=main_keyboard)
                        show_menu(chat_id)

        elif action == 'delete':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return

            if item_name:
                delete_item(item_name)
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, f"✅ *{item_name}* удален из инвентаря!",
                               parse_mode='Markdown', reply_markup=main_keyboard)
                show_menu(chat_id)

        elif action == 'return':
            if item_name == 'cancel':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
                show_menu(chat_id)
                return
            elif item_name == 'all':
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
            elif item_name:
                inventory = get_inventory()
                if item_name in inventory and inventory[item_name] is not None:
                    update_item_owner(item_name, None)
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"✅ *{item_name}* возвращен в инвентарь!",
                                   parse_mode='Markdown', reply_markup=main_keyboard)
                    show_menu(chat_id)
                else:
                    bot.delete_message(chat_id, call.message.message_id)
                    bot.send_message(chat_id, f"ℹ️ *{item_name}* уже в инвентаре!",
                                   parse_mode='Markdown', reply_markup=main_keyboard)
                    show_menu(chat_id)

    except Exception as e:
        logging.error(f"Ошибка при обработке callback от {chat_id}: {e}")
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_keyboard)
        show_menu(chat_id)

# Основной обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'main')

    try:
        if state == 'main':
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

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения от {chat_id}: {e}")
        bot.send_message(chat_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.", reply_markup=main_keyboard)
        show_menu(chat_id)

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
