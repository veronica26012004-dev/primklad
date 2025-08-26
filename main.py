import sqlite3
import telebot
from telebot import types
import threading

# Токен бота
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
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем!*\n\n"
    welcome_text += "📋 *Доступные команды:*\n"
    welcome_text += "➕ Добавить - добавить новый предмет\n"
    welcome_text += "➖ Удалить - удалить предмет\n"
    welcome_text += "🎁 Выдать - выдать предмет кому-то\n"
    welcome_text += "↩️ Вернуть - вернуть предмет в инвентарь\n"
    welcome_text += "📋 Показать инвентарь - обновить список"

    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=main_keyboard)
    show_menu(message.chat.id)

# Основной обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id, 'main')

    if state == 'main':
        if text == '➕ Добавить':
            user_states[chat_id] = 'add'
            bot.send_message(chat_id, "📝 *Что вы хотите добавить?*\n(напишите 'стоп' для выхода)",
                           parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif text == '➖ Удалить':
            user_states[chat_id] = 'delete'
            bot.send_message(chat_id, "🗑️ *Что вы хотите удалить?*\n(напишите 'стоп' для выхода)",
                           parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif text == '🎁 Выдать':
            user_states[chat_id] = 'give_who'
            bot.send_message(chat_id, "👤 *Кому выдать предмет?*\n(напишите имя получателя)",
                           parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

        elif text == '↩️ Вернуть':
            user_states[chat_id] = 'return_items'
            return_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            return_keyboard.add('🔄 Вернуть все', '🚫 Отмена')
            bot.send_message(chat_id, "📦 *Какой предмет вернуть?*\n(напишите 'стоп' для выхода)",
                           parse_mode='Markdown', reply_markup=return_keyboard)

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

    elif state == 'delete':
        if normalize_text(text) == 'стоп':
            bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
            show_menu(chat_id)
        elif text:
            existing_item = find_item_in_db(text)
            if existing_item is not None:
                delete_item(existing_item)
                bot.send_message(chat_id, f"✅ *{existing_item}* удален из инвентаря!\nЧто еще удалить? (стоп для выхода)",
                               parse_mode='Markdown')
            else:
                bot.send_message(chat_id, f"❌ *{text}* не найден в инвентаре!\nЧто еще удалить? (стоп для выхода)",
                               parse_mode='Markdown')

    elif state == 'give_who':
        if normalize_text(text) == 'стоп':
            bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
            show_menu(chat_id)
        elif text:
            recipient = ' '.join(text.strip().split())
            user_states[chat_id] = ('give_items', recipient)
            bot.send_message(chat_id, f"👤 Получатель: *{recipient}*\n📦 *Какой предмет выдать?* (стоп для выхода)",
                           parse_mode='Markdown')

    elif isinstance(state, tuple) and state[0] == 'give_items':
        owner = state[1]
        if normalize_text(text) == 'стоп':
            bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
            show_menu(chat_id)
        elif text:
            existing_item = find_item_in_db(text)
            if existing_item is not None:
                inventory = get_inventory()
                if inventory[existing_item] is None:
                    update_item_owner(existing_item, owner)
                    bot.send_message(chat_id, f"✅ *{existing_item}* выдан *{owner}*!\nЧто еще выдать? (стоп для выхода)",
                                   parse_mode='Markdown')
                else:
                    bot.send_message(chat_id, f"⚠️ *{existing_item}* уже выдан *{inventory[existing_item]}*!\nЧто еще выдать? (стоп для выхода)",
                                   parse_mode='Markdown')
            else:
                bot.send_message(chat_id, f"❌ *{text}* не найден в инвентаре!\nЧто еще выдать? (стоп для выхода)",
                               parse_mode='Markdown')

    elif state == 'return_items':
        if normalize_text(text) == 'стоп' or text == '🚫 Отмена':
            bot.send_message(chat_id, "👌 Возвращаемся в меню", reply_markup=main_keyboard)
            show_menu(chat_id)
        elif text == '🔄 Вернуть все':
            inventory = get_inventory()
            returned_count = 0
            for item in inventory:
                if inventory[item] is not None:
                    update_item_owner(item, None)
                    returned_count += 1
            bot.send_message(chat_id, f"✅ Возвращено всех предметов: *{returned_count}*",
                           parse_mode='Markdown', reply_markup=main_keyboard)
            show_menu(chat_id)
        elif text:
            existing_item = find_item_in_db(text)
            if existing_item is not None:
                inventory = get_inventory()
                if inventory[existing_item] is not None:
                    update_item_owner(existing_item, None)
                    bot.send_message(chat_id, f"✅ *{existing_item}* возвращен в инвентарь!\nЧто еще вернуть? (стоп для выхода)",
                                   parse_mode='Markdown')
                else:
                    bot.send_message(chat_id, f"ℹ️ *{existing_item}* уже в инвентаре!\nЧто еще вернуть? (стоп для выхода)",
                                   parse_mode='Markdown')
            else:
                bot.send_message(chat_id, f"❌ *{text}* не найден в инвентаре!\nЧто еще вернуть? (стоп для выхода)",
                               parse_mode='Markdown')

# Запуск бота
if __name__ == '__main__':
    print("🤖 Бот запущен...")
    bot.polling(none_stop=True)
