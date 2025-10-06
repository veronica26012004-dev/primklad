import telebot
from telebot import types
import threading
import os
import json
import time
import requests
import re
import logging
from flask import Flask, request
from datetime import datetime, timedelta
from uuid import uuid4

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение
app = Flask(__name__)

# Загрузка токена
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN не установлен. Убедитесь, что вы добавили его в настройки Render.")
    raise ValueError("BOT_TOKEN is not set. Set env var and restart.")

bot = telebot.TeleBot(TOKEN)

# Кэш для данных
items_cache = {}
events_cache = []

# Блокировка для thread-safe доступа
db_lock = threading.Lock()

EVENTS_FILE = 'events.txt'

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

# Функция для получения пути к файлу хранилища
def get_items_file(storage):
    storage_id = STORAGE_IDS.get(storage)
    if not storage_id:
        logger.error(f"Ошибка: неверный storage {storage}, доступные: {list(STORAGE_IDS.keys())}")
        return None
    return f"items_{storage_id}.txt"

# Инициализация файлов
files_initialized = False

def init_files():
    global files_initialized
    if files_initialized:
        return
    with db_lock:
        try:
            for storage in STORAGE_IDS:
                file_path = get_items_file(storage)
                if file_path and not os.path.exists(file_path):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump([], f)
            if not os.path.exists(EVENTS_FILE):
                with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f)
            files_initialized = True
            logger.info("Файлы инициализированы")
        except Exception as e:
            logger.error(f"Ошибка инициализации файлов: {e}")

# Состояния и выбор
user_states = {}
user_selections = {}
user_item_lists = {}

# Нормализация текста
def normalize_text(text):
    return ' '.join(text.strip().split()).lower()

# Функции для работы с предметами
def load_items(storage):
    start_time = time.time()
    storage_id = STORAGE_IDS.get(storage)
    if storage_id in items_cache:
        logger.info(f"Кэш предметов для {storage} использован, время: {time.time() - start_time:.2f} сек")
        return items_cache[storage_id]
    file_path = get_items_file(storage)
    if not file_path:
        logger.error(f"Ошибка: не удалось определить файл для {storage}")
        return []
    init_files()  # Проверяем инициализацию файлов
    items = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                items = json.load(f)
                items = [
                    {
                        'id': item.get('item_name', ''),
                        'item_name': item.get('item_name', ''),
                        'issued': item.get('issued', 0),
                        'owner': item.get('owner', '')
                    }
                    for item in items
                ]
        except Exception as e:
            logger.error(f"Ошибка загрузки предметов из {file_path}: {e}")
    items_cache[storage_id] = items
    logger.info(f"Загрузка предметов для {storage} выполнена за {time.time() - start_time:.2f} сек")
    return items

def save_items(items, storage):
    start_time = time.time()
    storage_id = STORAGE_IDS.get(storage)
    file_path = get_items_file(storage)
    if not file_path:
        logger.error(f"Ошибка: не удалось определить файл для {storage}")
        return False
    init_files()
    with db_lock:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            items_cache[storage_id] = items
            logger.info(f"Сохранение предметов для {storage} выполнено за {time.time() - start_time:.2f} сек")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения предметов в {file_path}: {e}")
            return False

def get_inventory(storage):
    try:
        items = load_items(storage)
        return [(item['id'], item['item_name'], item['issued'], item['owner']) for item in items]
    except Exception as e:
        logger.error(f"Ошибка получения инвентаря для {storage}: {e}")
        return []

def add_item(item_name, storage):
    start_time = time.time()
    item_name = re.sub(r'[|\\]', '', item_name.strip())[:50]
    if not item_name:
        return None
    try:
        items = load_items(storage)
        normalized_new = normalize_text(item_name)
        for item in items:
            if normalize_text(item['item_name']) == normalized_new:
                logger.info(f"Предмет {item_name} уже существует, время: {time.time() - start_time:.2f} сек")
                return None
        new_item = {
            'id': item_name,
            'item_name': item_name,
            'issued': 0,
            'owner': ""
        }
        items.append(new_item)
        if save_items(items, storage):
            logger.info(f"Предмет {item_name} добавлен за {time.time() - start_time:.2f} сек")
            return item_name
        return None
    except Exception as e:
        logger.error(f"Ошибка добавления предмета {item_name} в {storage}: {e}")
        return None

def delete_items(item_names, storage):
    start_time = time.time()
    try:
        items = load_items(storage)
        deleted_names = []
        new_items = []
        names_set = set(item_names)
        for item in items:
            if item['item_name'] in names_set:
                deleted_names.append(item['item_name'])
            else:
                new_items.append(item)
        if deleted_names:
            save_items(new_items, storage)
        logger.info(f"Удалено {len(deleted_names)} предметов за {time.time() - start_time:.2f} сек")
        return deleted_names
    except Exception as e:
        logger.error(f"Ошибка удаления предметов из {storage}: {e}")
        return []

def update_items_owner(item_names, owner, storage):
    start_time = time.time()
    try:
        items = load_items(storage)
        updated_names = []
        names_set = set(item_names)
        changed = False
        for item in items:
            if item['item_name'] in names_set:
                item['issued'] = 1
                item['owner'] = owner if owner else ""
                updated_names.append(item['item_name'])
                changed = True
        if changed:
            if save_items(items, storage):
                logger.info(f"Обновлено {len(updated_names)} предметов за {time.time() - start_time:.2f} сек")
                return updated_names
            return []
        return updated_names
    except Exception as e:
        logger.error(f"Ошибка обновления статуса предметов в {storage}: {e}")
        return []

def return_items(item_names, storage):
    start_time = time.time()
    try:
        items = load_items(storage)
        returned_names = []
        names_set = set(item_names)
        changed = False
        for item in items:
            if item['item_name'] in names_set and item['issued'] == 1:
                item['issued'] = 0
                item['owner'] = ""
                returned_names.append(item['item_name'])
                changed = True
        if changed:
            save_items(items, storage)
        logger.info(f"Возвращено {len(returned_names)} предметов за {time.time() - start_time:.2f} сек")
        return returned_names
    except Exception as e:
        logger.error(f"Ошибка возврата предметов в {storage}: {e}")
        return []

def find_item_in_db(item_name, storage):
    start_time = time.time()
    try:
        items = load_items(storage)
        normalized_search = normalize_text(item_name)
        for item in items:
            if normalize_text(item['item_name']) == normalized_search:
                logger.info(f"Предмет {item_name} найден за {time.time() - start_time:.2f} сек")
                return item['item_name']
        return None
    except Exception as e:
        logger.error(f"Ошибка поиска предмета {item_name} в {storage}: {e}")
        return None

# Функции для работы с событиями
def load_events():
    start_time = time.time()
    if events_cache:
        logger.info(f"Кэш событий использован, время: {time.time() - start_time:.2f} сек")
        return events_cache
    init_files()
    events = []
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                events = json.load(f)
                events = [
                    {
                        'id': item.get('id', ''),
                        'event_name': item.get('event_name', ''),
                        'event_date': item.get('event_date', '')
                    }
                    for item in events
                ]
        except Exception as e:
            logger.error(f"Ошибка загрузки событий: {e}")
    events_cache[:] = events
    logger.info(f"Загрузка событий выполнена за {time.time() - start_time:.2f} сек")
    return events

def save_events(events):
    start_time = time.time()
    with db_lock:
        try:
            with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
            events_cache[:] = events
            logger.info(f"Сохранение событий выполнено за {time.time() - start_time:.2f} сек")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения событий: {e}")
            return False

def add_event(event_name, event_date):
    start_time = time.time()
    event_id = str(uuid4())
    try:
        events = load_events()
        new_event = {
            'id': event_id,
            'event_name': event_name,
            'event_date': event_date
        }
        events.append(new_event)
        if save_events(events):
            logger.info(f"Событие {event_name} добавлено за {time.time() - start_time:.2f} сек")
            return event_id
        return None
    except Exception as e:
        logger.error(f"Ошибка добавления события {event_name}: {e}")
        return None

def get_events(period=None):
    start_time = time.time()
    try:
        events = load_events()
        now = datetime.now()
        if period == 'week':
            end = now + timedelta(days=7)
            filtered = [(ev['id'], ev['event_name'], ev['event_date']) for ev in events
                        if (ev['event_date'] >= now.strftime('%Y-%m-%d') and ev['event_date'] <= end.strftime('%Y-%m-%d'))]
        elif period == 'month':
            end = now + timedelta(days=30)
            filtered = [(ev['id'], ev['event_name'], ev['event_date']) for ev in events
                        if (ev['event_date'] >= now.strftime('%Y-%m-%d') and ev['event_date'] <= end.strftime('%Y-%m-%d'))]
        else:
            filtered = [(ev['id'], ev['event_name'], ev['event_date']) for ev in events]
        filtered.sort(key=lambda x: x[2])
        logger.info(f"Получение событий выполнено за {time.time() - start_time:.2f} сек")
        return filtered
    except Exception as e:
        logger.error(f"Ошибка получения событий: {e}")
        return []

def delete_event(event_ids):
    start_time = time.time()
    try:
        if not event_ids:
            return []
        events = load_events()
        ids_set = set(event_ids)
        events_to_delete = [ev for ev in events if ev['id'] in ids_set]
        if not events_to_delete:
            return []
        remaining_events = [ev for ev in events if ev['id'] not in ids_set]
        if not save_events(remaining_events):
            return []
        deleted_events = []
        for ev in events_to_delete:
            event_name = ev['event_name']
            event_date = ev['event_date']
            try:
                date_obj = datetime.strptime(event_date, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d %B %Y').replace(
                    date_obj.strftime('%B'),
                    MONTHS_RU[date_obj.month]
                )
                deleted_events.append(f"{event_name} ({formatted_date})")
            except ValueError:
                deleted_events.append(f"{event_name} ({event_date})")
        logger.info(f"Удалено {len(deleted_events)} событий за {time.time() - start_time:.2f} сек")
        return deleted_events
    except Exception as e:
        logger.error(f"Ошибка удаления событий: {e}, event_ids: {event_ids}")
        return []

# UI / клавиатуры
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
        types.KeyboardButton('➕ Добавить предмет'),
        types.KeyboardButton('➖ Удалить предмет'),
        types.KeyboardButton('🎁 Выдать предмет'),
        types.KeyboardButton('↩️ Вернуть предмет'),
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

def create_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(types.KeyboardButton('❌ Отмена'))
    return keyboard

def create_items_keyboard(chat_id, storage, action):
    start_time = time.time()
    if storage is None or storage not in STORAGE_IDS:
        logger.error(f"Ошибка: неверное хранилище {storage} при создании клавиатуры")
        return None
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    if chat_id in user_item_lists:
        filtered_items = user_item_lists[chat_id]['items']
    else:
        items = get_inventory(storage)
        storage_id = STORAGE_IDS.get(storage)
        if not storage_id:
            logger.error(f"Ошибка: не удалось получить storage_id для {storage}")
            return None
        key = f"{storage_id}_{action}"
        filtered_items = []
        for item_id, item_name, issued, owner in sorted(items, key=lambda x: x[1]):
            if action == 'give' and issued != 0:
                continue
            if action == 'return' and issued != 1:
                continue
            filtered_items.append((item_id, item_name, issued, owner))
        user_item_lists[chat_id] = {
            'key': key,
            'items': filtered_items,
            'storage_id': storage_id,
            'storage_name': storage
        }
    buttons = []
    for idx, (item_id, item_name, issued, owner) in enumerate(filtered_items):
        display_name = item_name[:30] + '...' if len(item_name) > 30 else item_name
        callback_data = f"select_{idx}_{action}_{user_item_lists[chat_id]['storage_id']}"
        buttons.append(types.InlineKeyboardButton(text=display_name, callback_data=callback_data))
    selected = user_selections.get(chat_id, [])
    if selected or buttons:
        confirm_data = f"confirm_{action}_{user_item_lists[chat_id]['storage_id']}"
        clear_data = f"clear_{action}_{user_item_lists[chat_id]['storage_id']}"
        buttons.append(types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data))
        buttons.append(types.InlineKeyboardButton(text="🗑️ Очистить выбор", callback_data=clear_data))
    if not buttons:
        logger.info(f"Клавиатура предметов для {storage} пуста, время: {time.time() - start_time:.2f} сек")
        return None
    keyboard.add(*buttons)
    logger.info(f"Клавиатура предметов для {storage} создана за {time.time() - start_time:.2f} сек")
    return keyboard

def create_events_delete_keyboard(chat_id):
    start_time = time.time()
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    events = get_events()
    if not events:
        return None
    buttons = []
    for event_id, event_name, event_date in sorted(events, key=lambda x: x[2]):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d %B %Y').replace(
                date_obj.strftime('%B'),
                MONTHS_RU[date_obj.month]
            )
            display_str = f"{event_name} ({formatted_date})"
        except ValueError:
            display_str = f"{event_name} ({event_date})"
        display_name = display_str[:35] + '...' if len(display_str) > 35 else display_str
        is_selected = event_id in user_selections.get(chat_id, [])
        prefix = "✅ " if is_selected else "◻️ "
        callback_data = f"select_event_{event_id}_delete"
        buttons.append(types.InlineKeyboardButton(
            text=prefix + display_name,
            callback_data=callback_data
        ))
    if buttons:
        buttons.append(types.InlineKeyboardButton(
            text="🗑️ Удалить выбранные",
            callback_data="confirm_event_delete"
        ))
        buttons.append(types.InlineKeyboardButton(
            text="❌ Очистить выбор",
            callback_data="clear_event_delete"
        ))
        buttons.append(types.InlineKeyboardButton(
            text="🔙 Назад в меню",
            callback_data="back_to_events"
        ))
    keyboard.add(*buttons)
    logger.info(f"Клавиатура удаления событий создана за {time.time() - start_time:.2f} сек")
    return keyboard

# Функции отображения
def show_main_menu(chat_id):
    text = "📋 *Главное меню*\n\nВыберите раздел:"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[chat_id] = 'main_menu'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_storage_selection(chat_id):
    text = "📦 *Выберите кладовую:*"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_selection_keyboard())
    user_states[chat_id] = 'storage_selection'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_storage_menu(chat_id, storage, message_text=None):
    if message_text:
        bot.send_message(chat_id, message_text, parse_mode='Markdown', reply_markup=create_storage_keyboard())
    else:
        bot.send_message(chat_id, f"📦 *Кладовая: {storage}*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=create_storage_keyboard())
    user_states[chat_id] = ('storage', storage)
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_inventory(chat_id, storage):
    start_time = time.time()
    if storage not in STORAGE_IDS:
        logger.error(f"Ошибка: неверная кладовая {storage} в show_inventory")
        bot.send_message(chat_id, "❌ Не удалось выбрать кладовую, попробуйте снова")
        show_storage_selection(chat_id)
        return
    file_path = get_items_file(storage)
    if not file_path or not os.path.exists(file_path):
        logger.error(f"Ошибка: файл {file_path} не найден для {storage}")
        bot.send_message(chat_id, f"❌ Ошибка: файл для {storage} не найден, попробуйте снова")
        show_storage_selection(chat_id)
        return
    inventory = get_inventory(storage)
    text = f"📦 *ИНВЕНТАРЬ ({storage}):*\n\n"
    if not inventory:
        text += "📭 Пусто\n"
    else:
        available_count = 0
        given_count = 0
        for _, item_name, issued, owner in sorted(inventory, key=lambda x: x[1]):
            if issued == 0:
                text += f"✅ **{item_name}**\n"
                available_count += 1
            else:
                text += f"🔸 {item_name} - выдано ({owner})\n"
                given_count += 1
        text += f"\n📊 Статистика: {available_count} доступно, {given_count} выдано"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_storage_keyboard())
    user_states[chat_id] = ('storage', storage)
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)
    logger.info(f"Инвентарь для {storage} показан за {time.time() - start_time:.2f} сек")

def show_events_menu(chat_id, message_text=None):
    if message_text:
        bot.send_message(chat_id, message_text, parse_mode='Markdown', reply_markup=create_events_keyboard())
    else:
        text = "📅 *Управление событиями*\n\nВыберите действие:"
        bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_events_keyboard())
    user_states[chat_id] = 'events_menu'
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)

def show_events_list(chat_id):
    start_time = time.time()
    events = get_events()
    if not events:
        bot.send_message(chat_id, "📅 Нет запланированных событий")
        show_events_menu(chat_id)
        logger.info(f"Список событий пуст, время: {time.time() - start_time:.2f} сек")
        return
    text = "📅 *Все события:*\n\n"
    for _, event_name, event_date in sorted(events, key=lambda x: x[2]):
        try:
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            text += f"• {event_name} - {formatted_date}\n"
        except ValueError:
            text += f"• {event_name} - {event_date}\n"
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=create_events_keyboard())
    user_states[chat_id] = 'events_menu'
    logger.info(f"Список событий показан за {time.time() - start_time:.2f} сек")

# Обработчики
@bot.message_handler(commands=['start'])
def start(message):
    start_time = time.time()
    welcome_text = "👋 *Добро пожаловать в систему управления инвентарем и событиями!*\n\n"
    welcome_text += "📋 *Доступные разделы:*\n"
    welcome_text += "• 📦 Кладовая - управление инвентарем\n"
    welcome_text += "• 📅 События - управление мероприятиями\n\n"
    welcome_text += "Выберите нужный раздел в меню ниже 👇"
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu_keyboard())
    user_states[message.chat.id] = 'main_menu'
    user_selections.pop(message.chat.id, None)
    user_item_lists.pop(message.chat.id, None)
    logger.info(f"Команда /start обработана за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: message.text == '🔙 В главное меню')
def back_to_main_menu(message):
    start_time = time.time()
    show_main_menu(message.chat.id)
    logger.info(f"Возврат в главное меню за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: message.text == '📦 Кладовая')
def handle_storage(message):
    start_time = time.time()
    logger.info(f"Переход в выбор кладовой для chat_id {message.chat.id}")
    show_storage_selection(message.chat.id)
    logger.info(f"Обработка кладовой за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: message.text == '📅 События')
def handle_events(message):
    start_time = time.time()
    show_events_menu(message.chat.id)
    logger.info(f"Обработка событий за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: message.text == '🔙 Назад')
def back_to_storage_selection(message):
    start_time = time.time()
    logger.info(f"Возврат к выбору кладовой для chat_id {message.chat.id}")
    show_storage_selection(message.chat.id)
    logger.info(f"Возврат назад за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'storage_selection')
def handle_storage_selection(message):
    start_time = time.time()
    chat_id = message.chat.id
    logger.info(f"Обработка выбора кладовой: message.text='{message.text}', chat_id={chat_id}")
    storage = message.text.replace('📍 ', '').strip()
    logger.info(f"Нормализованная кладовая: {storage}")
    if storage in STORAGE_IDS:
        show_storage_menu(chat_id, storage)
    elif message.text == '🔙 В главное меню':
        logger.info(f"Возврат в главное меню для chat_id {chat_id}")
        show_main_menu(chat_id)
    else:
        logger.warning(f"Неверный выбор кладовой: {message.text}")
        bot.send_message(chat_id, "❌ Не удалось выбрать кладовую, используйте кнопки меню")
        show_storage_selection(chat_id)
    logger.info(f"Обработка выбора кладовой за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'storage')
def handle_storage_actions(message):
    start_time = time.time()
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    if len(state_data) >= 2:
        storage = state_data[1]
    else:
        logger.error(f"Ошибка: неверное состояние для chat_id {chat_id}: {state_data}")
        bot.send_message(chat_id, "❌ Ошибка состояния, выберите кладовую снова")
        show_storage_selection(chat_id)
        return
    logger.info(f"Обработка действия в кладовой {storage} для chat_id {chat_id}: {message.text}")
    if message.text == '➕ Добавить предмет':
        bot.send_message(chat_id, "📝 Введите названия предметов для добавления (каждый предмет с новой строки) или нажмите '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = ('adding_item', storage)
    elif message.text == '➖ Удалить предмет':
        keyboard = create_items_keyboard(chat_id, storage, 'delete')
        if keyboard:
            bot.send_message(chat_id, "🗑️ Выберите предметы для удаления:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 В кладовой нет предметов для удаления")
            show_storage_menu(chat_id, storage)
    elif message.text == '🎁 Выдать предмет':
        keyboard = create_items_keyboard(chat_id, storage, 'give')
        if keyboard:
            selected_count = len(user_selections.get(chat_id, []))
            message_text = f"🎁 Выберите предметы для выдачи:\n\n✅ Выбрано: {selected_count} предмет(ов)"
            bot.send_message(chat_id, message_text, reply_markup=keyboard)
            user_states[chat_id] = ('selecting_items_to_give', storage)
        else:
            bot.send_message(chat_id, "📭 В кладовой нет доступных предметов для выдачи")
            show_storage_menu(chat_id, storage)
    elif message.text == '↩️ Вернуть предмет':
        keyboard = create_items_keyboard(chat_id, storage, 'return')
        if keyboard:
            bot.send_message(chat_id, "↩️ Выберите предметы для возврата:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "📭 Нет выданных предметов для возврата")
            show_storage_menu(chat_id, storage)
    elif message.text == '📋 Показать инвентарь':
        show_inventory(chat_id, storage)
    elif message.text == '🔙 Назад':
        logger.info(f"Возврат к выбору кладовой из storage для chat_id {chat_id}")
        show_storage_selection(chat_id)
    logger.info(f"Обработка действий в кладовой за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'adding_item')
def handle_adding_item(message):
    start_time = time.time()
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    if len(state_data) >= 2:
        storage = state_data[1]
    else:
        logger.error(f"Ошибка: неверное состояние для chat_id {chat_id}: {state_data}")
        bot.send_message(chat_id, "❌ Ошибка состояния, выберите кладовую снова")
        show_storage_selection(chat_id)
        return
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление предметов отменено")
        show_storage_menu(chat_id, storage)
        return
    item_names = message.text.strip().split('\n')
    if not item_names or all(not name.strip() for name in item_names):
        bot.send_message(chat_id, "❌ Список предметов не может быть пустым. Добавление отменено")
        show_storage_menu(chat_id, storage)
        return
    added_items = []
    existing_items = []
    failed_items = []
    for item_name in item_names:
        item_name = item_name.strip()
        if not item_name:
            continue
        existing_item = find_item_in_db(item_name, storage)
        if existing_item:
            existing_items.append(item_name)
        else:
            item_id = add_item(item_name, storage)
            if item_id:
                added_items.append(item_name)
            else:
                failed_items.append(item_name)
    response = ""
    if added_items:
        response += f"✅ Добавлены предметы:\n" + "\n".join(f"• {name}" for name in added_items) + "\n"
    if existing_items:
        response += f"⚠️ Эти предметы уже существуют:\n" + "\n".join(f"• {name}" for name in existing_items) + "\n"
    if failed_items:
        response += f"❌ Не удалось добавить:\n" + "\n".join(f"• {name}" for name in failed_items) + "\n"
    bot.send_message(chat_id, response.strip() or "❌ Не удалось добавить ни один предмет")
    show_storage_menu(chat_id, storage)
    logger.info(f"Добавление предметов обработано за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'events_menu')
def handle_events_actions(message):
    start_time = time.time()
    chat_id = message.chat.id
    if message.text == '➕ Добавить событие':
        bot.send_message(chat_id, "📝 Введите название события или '❌ Отмена':", reply_markup=create_cancel_keyboard())
        user_states[chat_id] = 'adding_event_name'
    elif message.text == '📅 Посмотреть события':
        show_events_list(chat_id)
    elif message.text == '🗑️ Удалить событие':
        keyboard = create_events_delete_keyboard(chat_id)
        if keyboard:
            bot.send_message(chat_id, "🗑️ Выберите события для удаления:", reply_markup=keyboard)
            user_states[chat_id] = 'deleting_event'
        else:
            bot.send_message(chat_id, "📭 Нет событий для удаления")
            show_events_menu(chat_id)
    elif message.text == '🔙 В главное меню':
        show_main_menu(chat_id)
    logger.info(f"Обработка действий с событиями за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'adding_event_name')
def handle_adding_event_name(message):
    start_time = time.time()
    chat_id = message.chat.id
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление события отменено")
        show_events_menu(chat_id)
        return
    event_name = message.text.strip()
    if event_name:
        user_states[chat_id] = ('adding_event_date', event_name)
        bot.send_message(chat_id, "📅 Введите дату события в формате 'ДД Месяц ГГГГ' (например, '30 января 2025') или 'ДД.ММ.ГГГГ' (например, '30.01.2025') или '❌ Отмена':", reply_markup=create_cancel_keyboard())
    else:
        bot.send_message(chat_id, "❌ Название события не может быть пустым. Добавление отменено")
        show_events_menu(chat_id)
    logger.info(f"Обработка названия события за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'adding_event_date')
def handle_adding_event_date(message):
    start_time = time.time()
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    if len(state_data) >= 2:
        event_name = state_data[1]
    else:
        show_events_menu(chat_id)
        return
    if message.text == '❌ Отмена':
        bot.send_message(chat_id, "❌ Добавление события отменено")
        show_events_menu(chat_id)
        return
    date_str = message.text.strip().lower()
    try:
        match = re.match(r'^(\d{1,2})\s+([а-яё]+)\s+(\d{4})$', date_str)
        if match:
            day, month_str, year = match.groups()
            month = MONTHS.get(month_str)
            if not month:
                raise ValueError("Неверное название месяца")
            day = int(day)
            year = int(year)
            if not (1 <= day <= 31):
                raise ValueError("Неверный день")
            date_obj = datetime(year, month, day)
        else:
            date_obj = datetime.strptime(date_str, '%d.%m.%Y')
        event_date = date_obj.strftime('%Y-%m-%d')
        event_id = add_event(event_name, event_date)
        if event_id:
            formatted_date = date_obj.strftime('%d %B %Y').replace(date_obj.strftime('%B'), MONTHS_RU[date_obj.month])
            bot.send_message(chat_id, f"✅ Событие '{event_name}' на {formatted_date} добавлено")
        else:
            bot.send_message(chat_id, "❌ Ошибка при добавлении события")
    except ValueError as e:
        bot.send_message(chat_id, f"❌ Неверный формат даты: {e}. Попробуйте еще раз или '❌ Отмена'")
        return
    show_events_menu(chat_id)
    logger.info(f"Добавление даты события обработано за {time.time() - start_time:.2f} сек")

@bot.message_handler(func=lambda message: isinstance(user_states.get(message.chat.id), tuple) and user_states.get(message.chat.id)[0] == 'entering_owner_name')
def handle_entering_owner_name(message):
    start_time = time.time()
    chat_id = message.chat.id
    state_data = user_states[chat_id]
    if len(state_data) >= 3:
        storage = state_data[1]
        selected_items = state_data[2]
    else:
        logger.error(f"Ошибка: неверное состояние entering_owner_name для chat_id {chat_id}: {state_data}")
        bot.send_message(chat_id, "❌ Ошибка состояния, выберите кладовую снова")
        show_storage_selection(chat_id)
        return
    owner = message.text.strip()
    if not owner:
        bot.send_message(chat_id, "❌ Имя получателя не может быть пустым. Введите имя еще раз:")
        return
    updated_names = update_items_owner(selected_items, owner, storage)
    if updated_names:
        items_list = "\n".join([f"• {name}" for name in updated_names])
        bot.send_message(chat_id, f"✅ Предметы выданы {owner}:\n{items_list}", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, "❌ Ошибка при выдаче предметов")
        logger.error(f"Не удалось выдать предметы: {selected_items} для {owner}")
    user_states.pop(chat_id, None)
    user_selections.pop(chat_id, None)
    user_item_lists.pop(chat_id, None)
    show_storage_menu(chat_id, storage)
    logger.info(f"Обработка выдачи предметов за {time.time() - start_time:.2f} сек")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    start_time = time.time()
    callback_data = call.data
    chat_id = call.message.chat.id
    logger.info(f"Callback data: {callback_data}, chat_id: {chat_id}")
    try:
        if callback_data.startswith('select_'):
            if callback_data.startswith('select_event_'):
                parts = callback_data.split('_')
                if len(parts) < 4 or parts[3] != 'delete':
                    bot.answer_callback_query(call.id, "❌ Ошибка: неверный формат callback для события")
                    logger.error(f"Неверный формат callback_data для события: {callback_data}")
                    show_events_menu(chat_id)
                    return
                event_id = parts[2]
                events = get_events()
                if not any(ev[0] == event_id for ev in events):
                    bot.answer_callback_query(call.id, "❌ Ошибка: событие не найдено")
                    logger.error(f"Не найден event_id: {event_id}")
                    show_events_menu(chat_id)
                    return
                if chat_id not in user_selections:
                    user_selections[chat_id] = []
                if event_id not in user_selections[chat_id]:
                    user_selections[chat_id].append(event_id)
                    bot.answer_callback_query(call.id, "✅ Событие добавлено в выбор")
                else:
                    user_selections[chat_id].remove(event_id)
                    bot.answer_callback_query(call.id, "❌ Событие удалено из выбора")
                try:
                    keyboard = create_events_delete_keyboard(chat_id)
                    selected_count = len(user_selections.get(chat_id, []))
                    if keyboard:
                        bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            text=f"🗑️ Выберите события для удаления:\n\n✅ Выбрано: {selected_count} событие(й)",
                            reply_markup=keyboard
                        )
                    else:
                        bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            text="📭 Нет событий для удаления",
                            reply_markup=None
                        )
                except Exception as e:
                    if "message is not modified" not in str(e):
                        logger.error(f"Ошибка обновления сообщения: {e}")
                        show_events_menu(chat_id)
            else:
                parts = callback_data.split('_')
                if len(parts) < 4:
                    bot.answer_callback_query(call.id, "❌ Ошибка: неверный формат callback")
                    logger.error(f"Неверный формат callback_data: {callback_data}")
                    show_storage_selection(chat_id)
                    return
                item_index, action, storage_id = parts[1], parts[2], parts[3]
                storage = REVERSE_STORAGE_IDS.get(storage_id)
                if not storage:
                    bot.answer_callback_query(call.id, "❌ Ошибка: не определена кладовая")
                    logger.error(f"Не найден storage_id: {storage_id} в REVERSE_STORAGE_IDS")
                    show_storage_selection(chat_id)
                    return
                if chat_id not in user_item_lists:
                    bot.answer_callback_query(call.id, "❌ Ошибка: список предметов устарел")
                    logger.error(f"Нет user_item_lists для chat_id {chat_id}")
                    show_storage_selection(chat_id)
                    return
                item_list_data = user_item_lists[chat_id]
                expected_key = f"{storage_id}_{action}"
                if item_list_data['key'] != expected_key:
                    bot.answer_callback_query(call.id, "❌ Ошибка: неверный список предметов")
                    logger.error(f"Несоответствие ключей: expected {expected_key}, got {item_list_data['key']}")
                    show_storage_selection(chat_id)
                    return
                try:
                    item_index = int(item_index)
                    if item_index < 0 or item_index >= len(item_list_data['items']):
                        bot.answer_callback_query(call.id, "❌ Ошибка: неверный индекс предмета")
                        logger.error(f"Неверный item_index: {item_index}, items: {len(item_list_data['items'])}")
                        return
                    item_id, item_name, issued, owner = item_list_data['items'][item_index]
                except (ValueError, IndexError) as e:
                    bot.answer_callback_query(call.id, "❌ Ошибка: неверный индекс предмета")
                    logger.error(f"Ошибка индекса предмета: {e}, item_index: {item_index}")
                    return
                if action == 'give' and issued != 0:
                    bot.answer_callback_query(call.id, "❌ Этот предмет уже выдан")
                    return
                if chat_id not in user_selections:
                    user_selections[chat_id] = []
                if item_name not in user_selections[chat_id]:
                    user_selections[chat_id].append(item_name)
                    bot.answer_callback_query(call.id, f"Предмет добавлен в выбор: {item_name}")
                    item_list_data['items'].pop(item_index)
                else:
                    user_selections[chat_id].remove(item_name)
                    bot.answer_callback_query(call.id, f"Предмет удален из выбора: {item_name}")
                    item_list_data['items'].insert(0, (item_id, item_name, issued, owner))
                try:
                    selected_count = len(user_selections.get(chat_id, []))
                    message_text = f"Выберите предметы для {'выдачи' if action == 'give' else action}:\n\n✅ Выбрано: {selected_count} предмет(ов)"
                    keyboard = create_items_keyboard(chat_id, storage, action)
                    if keyboard:
                        bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            text=message_text,
                            reply_markup=keyboard
                        )
                    else:
                        bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            text=f"{message_text}\n\n📭 Больше нет доступных предметов для выбора",
                            reply_markup=None
                        )
                except Exception as e:
                    if "message is not modified" not in str(e):
                        logger.error(f"Ошибка обновления клавиатуры предметов: {e}, callback_data: {callback_data}")
                        bot.answer_callback_query(call.id, "❌ Ошибка при обновлении списка предметов")
                        show_storage_menu(chat_id, storage)
        elif callback_data == 'confirm_event_delete':
            selected_events = user_selections.get(chat_id, [])
            if not selected_events:
                bot.answer_callback_query(call.id, "❌ Не выбрано ни одного события")
                return
            deleted_events = delete_event(selected_events)
            if deleted_events:
                event_list = "\n".join([f"• {event}" for event in deleted_events])
                success_text = f"✅ Удалены события:\n{event_list}"
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except:
                    pass
                bot.send_message(chat_id, success_text, parse_mode='Markdown')
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка при удалении событий")
                return
            user_selections.pop(chat_id, None)
            show_events_menu(chat_id)
        elif callback_data == 'clear_event_delete':
            user_selections.pop(chat_id, None)
            bot.answer_callback_query(call.id, "🗑️ Выбор очищен")
            try:
                keyboard = create_events_delete_keyboard(chat_id)
                if keyboard:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text="🗑️ Выберите события для удаления:\n\n✅ Выбрано: 0 событие(й)",
                        reply_markup=keyboard
                    )
                else:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text="📭 Нет событий для удаления",
                        reply_markup=None
                    )
            except Exception as e:
                if "message is not modified" not in str(e):
                    logger.error(f"Ошибка обновления сообщения: {e}")
                    show_events_menu(chat_id)
        elif callback_data == 'back_to_events':
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            show_events_menu(chat_id)
        elif callback_data.startswith('confirm_'):
            parts = callback_data.split('_')
            if len(parts) < 3:
                bot.answer_callback_query(call.id, "❌ Ошибка: неверный формат callback")
                logger.error(f"Неверный формат confirm callback_data: {callback_data}")
                show_storage_selection(chat_id)
                return
            action, storage_id = parts[1], parts[2]
            storage = REVERSE_STORAGE_IDS.get(storage_id)
            if not storage:
                bot.answer_callback_query(call.id, "❌ Ошибка: не определена кладовая")
                logger.error(f"Не найден storage_id: {storage_id} в REVERSE_STORAGE_IDS")
                show_storage_selection(chat_id)
                return
            selected_items = user_selections.get(chat_id, [])
            if not selected_items:
                bot.answer_callback_query(call.id, "❌ Не выбрано ни одного предмета")
                logger.error(f"Нет выбранных предметов для chat_id {chat_id}")
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except Exception as e:
                    logger.error(f"Ошибка удаления сообщения: {e}")
                show_storage_menu(chat_id, storage)
                return
            if action == 'delete':
                deleted_names = delete_items(selected_items, storage)
                if deleted_names:
                    items_list = "\n".join([f"• {name}" for name in deleted_names])
                    bot.send_message(chat_id, f"✅ Удалены предметы:\n{items_list}", parse_mode='Markdown')
                else:
                    bot.answer_callback_query(call.id, "❌ Ошибка при удалении предметов")
                    logger.error(f"Не удалось удалить предметы: {selected_items}")
            elif action == 'give':
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "👤 Введите имя получателя:", reply_markup=types.ReplyKeyboardRemove())
                user_states[chat_id] = ('entering_owner_name', storage, selected_items)
                return
            elif action == 'return':
                returned_names = return_items(selected_items, storage)
                if returned_names:
                    items_list = "\n".join([f"• {name}" for name in returned_names])
                    bot.send_message(chat_id, f"✅ Возвращены предметы:\n{items_list}", parse_mode='Markdown')
                else:
                    bot.answer_callback_query(call.id, "❌ Ошибка при возврате предметов")
                    logger.error(f"Не удалось вернуть предметы: {selected_items}")
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception as e:
                logger.error(f"Ошибка удаления сообщения: {e}")
            user_selections.pop(chat_id, None)
            user_item_lists.pop(chat_id, None)
            show_storage_menu(chat_id, storage)
        elif callback_data.startswith('clear_'):
            parts = callback_data.split('_')
            if len(parts) < 3:
                bot.answer_callback_query(call.id, "❌ Ошибка: неверный формат callback")
                logger.error(f"Неверный формат clear callback_data: {callback_data}")
                show_storage_selection(chat_id)
                return
            action, storage_id = parts[1], parts[2]
            storage = REVERSE_STORAGE_IDS.get(storage_id)
            if not storage:
                bot.answer_callback_query(call.id, "❌ Ошибка: не определена кладовая")
                logger.error(f"Не найден storage_id: {storage_id} в REVERSE_STORAGE_IDS")
                show_storage_selection(chat_id)
                return
            if chat_id in user_item_lists and chat_id in user_selections:
                full_items = get_inventory(storage)
                storage_id = STORAGE_IDS.get(storage)
                filtered_full_items = []
                for item_id, item_name, issued, owner in sorted(full_items, key=lambda x: x[1]):
                    if action == 'give' and issued != 0:
                        continue
                    if action == 'return' and issued != 1:
                        continue
                    filtered_full_items.append((item_id, item_name, issued, owner))
                user_item_lists[chat_id]['items'] = filtered_full_items
            user_selections.pop(chat_id, None)
            bot.answer_callback_query(call.id, "🗑️ Выбор очищен")
            try:
                keyboard = create_items_keyboard(chat_id, storage, action)
                if keyboard:
                    message_text = f"Выберите предметы для {'выдачи' if action == 'give' else action}:\n\n✅ Выбрано: 0 предмет(ов)"
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text=message_text,
                        reply_markup=keyboard
                    )
                else:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text=f"📭 Нет предметов для выбора",
                        reply_markup=None
                    )
                    show_storage_menu(chat_id, storage)
            except Exception as e:
                if "message is not modified" not in str(e):
                    logger.error(f"Ошибка обновления клавиатуры предметов: {e}, callback_data: {callback_data}")
                    bot.answer_callback_query(call.id, "❌ Ошибка при очистке выбора")
                    show_storage_menu(chat_id, storage)
    except Exception as e:
        logger.error(f"Общая ошибка обработки callback: {e}, callback_data: {callback_data}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка, попробуйте снова")
        if callback_data.startswith('select_event_') or callback_data in ['confirm_event_delete', 'clear_event_delete', 'back_to_events']:
            show_events_menu(chat_id)
        else:
            show_storage_selection(chat_id)
    logger.info(f"Callback обработан за {time.time() - start_time:.2f} сек")

# Вебхук
@app.route('/webhook', methods=['POST'])
def webhook():
    start_time = time.time()
    logger.info("Получен запрос вебхука")
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            if update:
                bot.process_new_updates([update])
            logger.info(f"Вебхук обработан за {time.time() - start_time:.2f} секунд")
            return '', 200
        logger.info(f"Неверный тип запроса, обработка заняла {time.time() - start_time:.2f} секунд")
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}")
        return 'Error', 500

@app.route('/')
def index():
    return "Бот управления инвентарем работает!", 200

# Keep-Alive
def keep_alive():
    while True:
        try:
            url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', '')}/"
            r = requests.get(url, timeout=10)
            logger.info(f"[KeepAlive] ping {url} -> {r.status_code}")
        except Exception as e:
            logger.warning(f"[KeepAlive] ошибка: {e}")
        time.sleep(30)

if __name__ == '__main__':
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', '')}/webhook"
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
