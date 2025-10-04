import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import os
import json
import time
import requests
import urllib3
import unicodedata
import threading
import logging

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

# Токен Telegram-бота
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8188530872:AAGM4vmxCZIhS-0RY47RvYzS958NGe0J-VA').strip()
if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не задан")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Set env var and restart.")

# Пути к файлам
SERMONS_FILE = 'sermons.txt'
NEEDS_FILE = 'needs.txt'
EVENTS_FILE = 'events.txt'

# Статический контент
MISSION_TEXT = """\
📜 Итак мы - посланники от имени Христова, и как бы Сам Бог увещевает через нас; от имени Христова просим: примиритесь с Богом.(2Кор.5:20)

Богослужение 💒
🗓️ Каждое воскресенье
🕙 с 10:00 до 12:00
📍 по адресу: Санкт-Петербург, Нарвский пр. 11Б, актовый зал (https://yandex.ru/maps/-/CLuSAS5Z)

📎 Ссылки на наши соц сети:

📌 Мы ВКонтакте - https://vk.com/spbprim
📌 Мы на YouTube - https://www.youtube.com/@primirenie/videos?app=desktop
📌 Мы на Twitch - https://www.twitch.tv/primirenie(тут каждое вс проходят трансляции)

Местная религиозная организация "Церковь евангельских христиан-баптистов "Примирение" ОГРН 1047831009192 Зарегистрирована Главным управлением Министерства юстиции Российской Федерации по Санкт-Петербургу и Ленинградской области 17.11.2004 г.
Руководитель (пастор): Смотров Алексей Валерьевич.

🤍Если у тебя есть вопросы, можешь писать напрямую нам @primirenie_spb или звони по номеру телефона
+7 (993) 484-25-20
"""
MISSION_IMAGE = "hi.jpg"

HOW_TO_GET_TEXT = """\
Как к нам добраться
Приходите по адресу: Санкт-Петербург, Нарвский пр. 11Б. актовый зал (https://yandex.ru/maps/-/CLuSAS5Z)
Ближайшая станция метро — Нарвская.
"""
HOW_TO_GET_IMAGE = "pyt.mp4"

HOME_GROUPS_TEXT = """\
КОГДА ?
Каждую среду в 19:00 (уточняйте у лидера группы)

ГДЕ ?
💜Пушкин
💜м. Проспект славы
💜м. Удельная
💜м. Комендантский/Нарвская
💜м. площадь Мужества
💜м. Гражданский проспект
💜Васильевский остров
💜м. Ладожская

КАК ?
Если ты хочешь присоединится к одной из домашних групп, в воскресенье обратись к пастору А.В. Смотрову!! 🤍
"""
HOME_GROUPS_IMAGES = "dom.jpg"

CONTACT_TEXT = """\
📞Связаться с нами
Пишите на @primirenie_spb или звони по номеру телефона
+7 (993) 484-25-20
"""
CONTACT_IMAGE = ""

HELP_INTRO = """\
Нужды церкви:
"""

# Функции загрузки и сохранения данных
def load_sermons():
    if os.path.exists(SERMONS_FILE):
        with open(SERMONS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    normalized = []
                    for item in data:
                        if isinstance(item, dict):
                            normalized.append({
                                "link": str(item.get("link", "")),
                                "caption": str(item.get("caption", ""))
                            })
                        elif isinstance(item, (list, tuple)) and len(item) >= 2:
                            normalized.append({"link": str(item[0]), "caption": str(item[1])})
                    return normalized
            except Exception as e:
                logger.error(f"Ошибка загрузки проповедей: {e}")
                pass
            lines = [line.rstrip("\n") for line in content.splitlines()]
            sermons = []
            for i in range(0, len(lines), 2):
                link = lines[i].strip()
                caption = lines[i+1] if i+1 < len(lines) else ''
                sermons.append({"link": link, "caption": caption})
            return sermons
    return []

def save_sermons(sermons):
    normalized = []
    for item in sermons:
        if isinstance(item, dict):
            normalized.append({
                "link": str(item.get("link", "")),
                "caption": str(item.get("caption", ""))
            })
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            normalized.append({"link": str(item[0]), "caption": str(item[1])})
    try:
        with open(SERMONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        logger.info("Проповеди сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения проповедей: {e}")

def load_needs():
    if os.path.exists(NEEDS_FILE):
        with open(NEEDS_FILE, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            try:
                data = json.loads("\n".join(lines))
                if isinstance(data, list):
                    normalized = []
                    for item in data:
                        if isinstance(item, dict):
                            normalized.append({
                                "text": str(item.get("text", "")),
                                "assignee": item.get("assignee")
                            })
                        else:
                            normalized.append({"text": str(item), "assignee": None})
                    return normalized
            except Exception as e:
                logger.error(f"Ошибка загрузки нужд: {e}")
                pass
            return [{"text": line, "assignee": None} for line in lines]
    return []

def save_needs(needs):
    normalized = []
    for need in needs:
        if isinstance(need, dict):
            normalized.append({
                "text": str(need.get("text", "")),
                "assignee": need.get("assignee")
            })
        else:
            normalized.append({"text": str(need), "assignee": None})
    try:
        with open(NEEDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        logger.info("Нужды сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения нужд: {e}")

def load_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    normalized = []
                    for item in data:
                        if isinstance(item, dict):
                            normalized.append({
                                "text": str(item.get("text", "")),
                                "photo_file_id": item.get("photo_file_id")
                            })
                        else:
                            normalized.append({"text": str(item), "photo_file_id": None})
                    return normalized
            except Exception as e:
                logger.error(f"Ошибка загрузки событий: {e}")
                pass
            f.seek(0)
            lines = [line.strip() for line in f.readlines() if line.strip()]
            return [{"text": line, "photo_file_id": None} for line in lines]
    return []

def save_events(events):
    normalized = []
    for ev in events:
        if isinstance(ev, dict):
            normalized.append({
                "text": str(ev.get("text", "")),
                "photo_file_id": ev.get("photo_file_id")
            })
        else:
            normalized.append({"text": str(ev), "photo_file_id": None})
    try:
        with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        logger.info("События сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения событий: {e}")

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# Проверка прав бота в канале
def is_bot_admin(chat_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        bot_id = bot.get_me().id
        is_admin = any(admin.user.id == bot_id for admin in admins)
        logger.info(f"Проверка прав бота в чате {chat_id}: {'админ' if is_admin else 'не админ'}")
        return is_admin
    except Exception as e:
        logger.error(f"Ошибка проверки прав бота в чате {chat_id}: {e}")
        return False

# Необязательная поддержка прокси
try:
    proxy_url = os.getenv('TELEGRAM_PROXY_URL') or os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    if proxy_url:
        import telebot.apihelper as apihelper
        apihelper.proxy = {
            'http': proxy_url,
            'https': proxy_url,
        }
        logger.info(f"Прокси настроен: {proxy_url}")
except Exception as e:
    logger.error(f"Ошибка настройки прокси: {e}")

# Вспомогательные функции для метки пользователя
def make_assignee_label_from_user(user):
    username = getattr(user, 'username', None)
    if username:
        return f"@{username}"
    name = (getattr(user, 'first_name', '') or '').strip()
    return name if name else f"id:{getattr(user, 'id', '')}"

def is_current_user_assignee(assignee_value, user):
    if not assignee_value:
        return False
    stored = str(assignee_value).strip()
    uid = str(getattr(user, 'id', ''))
    uname = getattr(user, 'username', None)
    fname = (getattr(user, 'first_name', '') or '').strip()
    candidates = set()
    if uid:
        candidates.add(f"id:{uid}")
    if uname:
        candidates.add(uname)
        candidates.add(f"@{uname}")
    if fname:
        candidates.add(fname)
    return stored in candidates

# Формирование списка нужд с кнопками
def build_needs_view(current_user, needs, is_admin):
    keyboard = InlineKeyboardMarkup()
    lines = []
    current_user_label = make_assignee_label_from_user(current_user)
    for idx, need in enumerate(needs):
        if isinstance(need, dict):
            assignee = need.get('assignee') or 'свободно'
            lines.append(f"• {need.get('text', '')} — {assignee}")
            is_taken = bool(need.get('assignee'))
            need_text = need.get('text', '')
            is_mine = is_taken and (need.get('assignee') == current_user_label or is_current_user_assignee(need.get('assignee'), current_user))
        else:
            lines.append(f"• {need} — свободно")
            is_taken = False
            need_text = need
            is_mine = False

        def safe_short_label(text: str, max_len: int = 32) -> str:
            txt = (text or '').strip()
            if not txt:
                return '(без названия)'
            try:
                import regex as _re
                clusters = _re.findall(r'\X', txt)
                if len(clusters) <= max_len:
                    return txt
                return ''.join(clusters[: max_len - 1]) + '…'
            except Exception:
                if len(txt) <= max_len:
                    return txt
                cut = txt[: max_len - 1]
                while cut and (unicodedata.combining(cut[-1]) != 0 or cut[-1] in ('\u200d', '\ufe0f')):
                    cut = cut[:-1]
                return cut + '…'

        short_need = safe_short_label(need_text, 32)

        if is_admin:
            if is_taken:
                if is_mine:
                    keyboard.add(
                        InlineKeyboardButton(f"Отказаться: {short_need}", callback_data=f'release_need:{idx}'),
                        InlineKeyboardButton("❌ Освободить", callback_data=f'clear_need:{idx}'),
                        InlineKeyboardButton("🗑", callback_data=f'del_need:{idx}')
                    )
                else:
                    keyboard.add(
                        InlineKeyboardButton("❌ Освободить", callback_data=f'clear_need:{idx}'),
                        InlineKeyboardButton("🗑", callback_data=f'del_need:{idx}')
                    )
            else:
                keyboard.add(
                    InlineKeyboardButton(need_text, callback_data=f'need:{idx}'),
                    InlineKeyboardButton("🗑", callback_data=f'del_need:{idx}')
                )
        else:
            if not is_taken:
                keyboard.add(InlineKeyboardButton(need_text, callback_data=f'need:{idx}'))
            elif is_mine:
                keyboard.add(InlineKeyboardButton(f"Отказаться: {short_need}", callback_data=f'release_need:{idx}'))

    list_text = HELP_INTRO + "\n".join(lines)
    return list_text, keyboard

# Админ-режим
ADMIN_SECRET = 'Админ секрет'
admin_user_ids = set()
admin_last_activity = {}
ADMIN_TIMEOUT_SECONDS = 3600

def escape_markdown_v2(text: str) -> str:
    if text is None:
        return ''
    specials = r"_ * [ ] ( ) ~ ` > # + - = | { } . !"
    result = []
    for ch in text:
        if ch in specials or ch == '\\':
            result.append('\\' + ch)
        else:
            result.append(ch)
    return ''.join(result)

def safe_send_markdown(chat_id, text, reply_markup=None, photo_path=None, video_path=None):
    logger.info(f"Отправка сообщения в чат {chat_id}: {text[:100]}...")
    try:
        if video_path and os.path.exists(video_path):
            with open(video_path, 'rb') as video:
                bot.send_video(chat_id, video, caption=text, reply_markup=reply_markup)
        elif photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=text, reply_markup=reply_markup)
        else:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
        logger.info(f"Сообщение успешно отправлено в чат {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения в чат {chat_id}: {e}")

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Миссия церкви"))
    keyboard.add(KeyboardButton("Как к нам добраться"))
    keyboard.add(KeyboardButton("Домашние группы"))
    keyboard.add(KeyboardButton("Связаться с нами"))
    keyboard.add(KeyboardButton("Проповеди"))
    keyboard.add(KeyboardButton("Нужды церкви"))
    keyboard.add(KeyboardButton("События"))
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Проповеди"))
    keyboard.add(KeyboardButton("Нужды церкви"))
    keyboard.add(KeyboardButton("События"))
    keyboard.add(KeyboardButton("Выход"))
    return keyboard

def check_admin_timeout():
    while True:
        current_time = time.time()
        expired_admins = []
        for user_id, last_activity in admin_last_activity.items():
            if current_time - last_activity > ADMIN_TIMEOUT_SECONDS:
                expired_admins.append(user_id)

        for user_id in expired_admins:
            admin_user_ids.discard(user_id)
            admin_last_activity.pop(user_id, None)
            try:
                bot.send_message(user_id, "Вы были автоматически выведены из админ-режима из-за неактивности.", reply_markup=get_main_keyboard())
                logger.info(f"Пользователь {user_id} выведен из админ-режима")
            except Exception as e:
                logger.error(f"Ошибка при выходе пользователя {user_id} из админ-режима: {e}")
        time.sleep(60)

# Обработка команды /start
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id in admin_user_ids:
        admin_last_activity[message.from_user.id] = time.time()
        safe_send_markdown(message.chat.id, "Добро пожаловать! Админ-меню доступно:", reply_markup=get_admin_keyboard())
    else:
        safe_send_markdown(message.chat.id, "Добро пожаловать! Выберите опцию:", reply_markup=get_main_keyboard())

# Обработчик новых сообщений в канале, где бот является админом
@bot.message_handler(content_types=['text', 'photo'], func=lambda message: message.chat.type in ['channel'])
def handle_channel_message(message):
    logger.info(f"Получено сообщение из канала {message.chat.id} (username: {message.chat.username})")
    
    # Проверяем, является ли бот админом в этом канале
    if not is_bot_admin(message.chat.id):
        logger.info(f"Бот не админ в канале {message.chat.id}, сообщение игнорируется")
        return

    # Проверяем наличие хэштега #событие
    hashtag = '#событие'
    text = message.text or message.caption or ''
    
    if hashtag.lower() in text.lower():
        logger.info(f"Обнаружен хэштег #событие в сообщении из канала {message.chat.id}")
        # Извлекаем текст и фото (если есть)
        event_text = text.replace(hashtag, '').strip()
        photo_id = None
        if message.photo:
            photo_id = message.photo[-1].file_id
            logger.info(f"Фото найдено, file_id: {photo_id}")

        # Загружаем текущие события
        events = load_events()
        
        # Добавляем новое событие
        event_data = {
            "text": event_text if event_text else "📅 Событие",
            "photo_file_id": photo_id
        }
        events.append(event_data)
        
        # Сохраняем события
        save_events(events)
        logger.info(f"Событие добавлено: {event_data}")
        
        # Уведомляем в канал
        try:
            bot.send_message(
                message.chat.id,
                f"Событие добавлено в бот: {event_text or '📅 Событие'}",
                reply_to_message_id=message.message_id
            )
            logger.info(f"Уведомление отправлено в канал {message.chat.id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление в канал {message.chat.id}: {e}")

# Обработка текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id in admin_user_ids:
        admin_last_activity[user_id] = time.time()

    if text == ADMIN_SECRET:
        admin_user_ids.add(user_id)
        admin_last_activity[user_id] = time.time()
        safe_send_markdown(
            message.chat.id,
            "Админ-режим включён. Доступно админ-меню.",
            reply_markup=get_admin_keyboard()
        )
        return

    if text.lower() in ("выход", "выход админ", "выйти из админа"):
        if user_id in admin_user_ids:
            admin_user_ids.discard(user_id)
            admin_last_activity.pop(user_id, None)
            try:
                bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=None)
            except Exception:
                pass
            safe_send_markdown(
                message.chat.id,
                "Админ-режим выключен.",
                reply_markup=get_main_keyboard()
            )
        else:
            safe_send_markdown(
                message.chat.id,
                "Вы не в админ-режиме.",
                reply_markup=get_main_keyboard()
            )
        return

    if text == "Миссия церкви":
        safe_send_markdown(message.chat.id, MISSION_TEXT, photo_path=MISSION_IMAGE)

    elif text == "Как к нам добраться":
        safe_send_markdown(message.chat.id, HOW_TO_GET_TEXT, video_path=HOW_TO_GET_IMAGE)

    elif text == "Домашние группы":
        safe_send_markdown(message.chat.id, HOME_GROUPS_TEXT, photo_path=HOME_GROUPS_IMAGES)

    elif text == "Связаться с нами":
        safe_send_markdown(message.chat.id, CONTACT_TEXT, photo_path=CONTACT_IMAGE)

    elif text == "Проповеди":
        sermons = load_sermons()
        if not sermons:
            kb = InlineKeyboardMarkup() if user_id in admin_user_ids else None
            if user_id in admin_user_ids:
                kb.add(InlineKeyboardButton("➕ Добавить проповедь", callback_data='add_sermon'))
            safe_send_markdown(message.chat.id, "Пока нет доступных проповедей.", reply_markup=kb)
        else:
            for idx, s in enumerate(sermons):
                link = s.get('link', '') if isinstance(s, dict) else str(s[0])
                caption = s.get('caption', '') if isinstance(s, dict) else str(s[1])
                formatted_message = f"{caption}\n{link}" if caption else link
                kb = InlineKeyboardMarkup() if user_id in admin_user_ids else None
                if user_id in admin_user_ids:
                    kb.add(InlineKeyboardButton("🗑 Удалить", callback_data=f'del_sermon:{idx}'))
                safe_send_markdown(message.chat.id, formatted_message, reply_markup=kb)
            if user_id in admin_user_ids:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("➕ Добавить проповедь", callback_data='add_sermon'))
                safe_send_markdown(message.chat.id, "Добавить новую проповедь:", reply_markup=kb)

    elif text == "Нужды церкви":
        needs = load_needs()
        is_admin = user_id in admin_user_ids
        list_text, keyboard = build_needs_view(message.from_user, needs, is_admin)
        safe_send_markdown(message.chat.id, list_text, reply_markup=keyboard)
        if is_admin:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("➕ Добавить нужду", callback_data='add_need'))
            safe_send_markdown(message.chat.id, "Добавить новую нужду:", reply_markup=kb)

    elif text == "События":
        events = load_events()
        if not events:
            kb = InlineKeyboardMarkup() if user_id in admin_user_ids else None
            if user_id in admin_user_ids:
                kb.add(InlineKeyboardButton("📅 Новое событие", callback_data='add_event'))
            safe_send_markdown(message.chat.id, "Пока нет запланированных событий.", reply_markup=kb)
        else:
            for idx, ev in enumerate(events):
                ev_text = ev.get('text', '') if isinstance(ev, dict) else str(ev)
                photo_id = ev.get('photo_file_id') if isinstance(ev, dict) else None
                display_text = ev_text if ev_text.strip() else "📅 Событие"
                kb = InlineKeyboardMarkup() if user_id in admin_user_ids else None
                if user_id in admin_user_ids:
                    kb.add(InlineKeyboardButton("🗑 Удалить", callback_data=f'del_event:{idx}'))
                if photo_id:
                    try:
                        bot.send_photo(message.chat.id, photo_id, caption=display_text, reply_markup=kb)
                    except Exception:
                        safe_send_markdown(message.chat.id, display_text, reply_markup=kb)
                else:
                    safe_send_markdown(message.chat.id, display_text, reply_markup=kb)
            if user_id in admin_user_ids:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("📅 Новое событие", callback_data='add_event'))
                safe_send_markdown(message.chat.id, "Добавить новое событие:", reply_markup=kb)

# Обработка ввода ссылки на проповедь
def add_sermon_link(message):
    link = message.text.strip()
    safe_send_markdown(message.chat.id, "Введите подпись к видео:")
    bot.register_next_step_handler(message, lambda m: add_sermon_caption(m, link))

def add_sermon_caption(message, link):
    caption = message.text.strip()
    sermons = load_sermons()
    sermons.append({"link": link, "caption": caption})
    save_sermons(sermons)
    safe_send_markdown(message.chat.id, "Проповедь успешно добавлена.")

def add_need(message):
    need = message.text.strip()
    needs = load_needs()
    needs.append({"text": need, "assignee": None})
    save_needs(needs)
    safe_send_markdown(message.chat.id, "Нужда успешно добавлена.")

def add_event_start(message):
    ev_text = (message.text or '').strip()
    temp = {"text": ev_text, "photo_file_id": None}
    safe_send_markdown(message.chat.id, "Теперь отправьте фото для события (или напишите 'пропустить').")
    bot.register_next_step_handler(message, lambda m: add_event_finish(m, temp))

def add_event_finish(message, temp):
    photo_id = None
    if message.content_type == 'photo' and message.photo:
        try:
            photo_id = message.photo[-1].file_id
        except Exception:
            photo_id = None
    elif isinstance(message.text, str) and message.text.strip().lower() == 'пропустить':
        photo_id = None
    else:
        photo_id = None
    events = load_events()
    events.append({"text": temp.get("text", ""), "photo_file_id": photo_id})
    save_events(events)
    safe_send_markdown(message.chat.id, "Событие успешно добавлено.")

# Обработка callback-запросов
@bot.callback_query_handler(func=lambda call: True)
def handle_help_callback(call):
    user_id = call.from_user.id
    if user_id in admin_user_ids:
        admin_last_activity[user_id] = time.time()

    data = call.data
    try:
        if data.startswith('del_sermon:'):
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            idx = int(data.split(':', 1)[1])
            sermons = load_sermons()
            if 0 <= idx < len(sermons):
                removed = sermons.pop(idx)
                save_sermons(sermons)
                bot.answer_callback_query(call.id, "Проповедь удалена")
                bot.edit_message_text("Удалено", call.message.chat.id, call.message.message_id, parse_mode='MarkdownV2')
            else:
                bot.answer_callback_query(call.id, "Неверный индекс")
        elif data == 'add_sermon':
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            bot.answer_callback_query(call.id)
            safe_send_markdown(call.message.chat.id, "Введите ссылку на видео проповеди:")
            bot.register_next_step_handler(call.message, add_sermon_link)
        elif data.startswith('del_event:'):
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            idx = int(data.split(':', 1)[1])
            events = load_events()
            if 0 <= idx < len(events):
                events.pop(idx)
                save_events(events)
                bot.answer_callback_query(call.id, "Событие удалено")
                try:
                    bot.edit_message_text("Удалено", call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
            else:
                bot.answer_callback_query(call.id, "Неверный индекс")
        elif data == 'add_event':
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            bot.answer_callback_query(call.id)
            safe_send_markdown(call.message.chat.id, "Отправьте текст события одним сообщением. Затем отправьте фото (необязательно) следующим сообщением — я прикреплю его.")
            bot.register_next_step_handler(call.message, add_event_start)
        elif data.startswith('del_need:'):
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            idx = int(data.split(':', 1)[1])
            needs = load_needs()
            if 0 <= idx < len(needs):
                removed = needs.pop(idx)
                save_needs(needs)
                bot.answer_callback_query(call.id, "Нужда удалена")
                list_text, keyboard = build_needs_view(call.from_user, needs, user_id in admin_user_ids)
                try:
                    bot.edit_message_text(list_text, call.message.chat.id, call.message.message_id)
                    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
                except Exception:
                    pass
            else:
                bot.answer_callback_query(call.id, "Неверный индекс")
        elif data == 'add_need':
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            bot.answer_callback_query(call.id)
            safe_send_markdown(call.message.chat.id, "Введите текст новой нужды:")
            bot.register_next_step_handler(call.message, add_need)
        elif data.startswith('need:'):
            idx = int(data.split(':', 1)[1])
            needs = load_needs()
            if 0 <= idx < len(needs):
                if isinstance(needs[idx], dict):
                    need_obj = needs[idx]
                    if need_obj.get('assignee'):
                        bot.answer_callback_query(call.id, "Эта нужда уже занята")
                        return
                    assignee_label = make_assignee_label_from_user(call.from_user)
                    need_obj['assignee'] = assignee_label
                    needs[idx] = need_obj
                else:
                    assignee_label = make_assignee_label_from_user(call.from_user)
                    need_text = str(needs[idx])
                    needs[idx] = {"text": need_text, "assignee": assignee_label}
                save_needs(needs)
                bot.answer_callback_query(call.id, "Вы взяли эту нужду. Спасибо!")
                list_text, keyboard = build_needs_view(call.from_user, needs, user_id in admin_user_ids)
                try:
                    bot.edit_message_text(list_text, call.message.chat.id, call.message.message_id)
                    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
                except Exception:
                    pass
            else:
                bot.answer_callback_query(call.id, "Элемент не найден")
        elif data.startswith('clear_need:'):
            if user_id not in admin_user_ids:
                bot.answer_callback_query(call.id, "Только для админа")
                return
            idx = int(data.split(':', 1)[1])
            needs = load_needs()
            if 0 <= idx < len(needs):
                if isinstance(needs[idx], dict):
                    needs[idx]['assignee'] = None
                save_needs(needs)
                bot.answer_callback_query(call.id, "Исполнитель удалён")
                list_text, keyboard = build_needs_view(call.from_user, needs, user_id in admin_user_ids)
                try:
                    bot.edit_message_text(list_text, call.message.chat.id, call.message.message_id)
                    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
                except Exception:
                    pass
            else:
                bot.answer_callback_query(call.id, "Неверный индекс")
        elif data.startswith('release_need:'):
            idx = int(data.split(':', 1)[1])
            needs = load_needs()
            if 0 <= idx < len(needs):
                if isinstance(needs[idx], dict) and needs[idx].get('assignee'):
                    current_label = make_assignee_label_from_user(call.from_user)
                    if needs[idx]['assignee'] == current_label:
                        needs[idx]['assignee'] = None
                        save_needs(needs)
                        bot.answer_callback_query(call.id, "Вы отказались от этой нужды.")
                        list_text, keyboard = build_needs_view(call.from_user, needs, user_id in admin_user_ids)
                        try:
                            bot.edit_message_text(list_text, call.message.chat.id, call.message.message_id)
                            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
                        except Exception:
                            pass
                    else:
                        bot.answer_callback_query(call.id, "Вы не являетесь исполнителем этой нужды")
                else:
                    bot.answer_callback_query(call.id, "Нечего освобождать")
            else:
                bot.answer_callback_query(call.id, "Неверный индекс")
        else:
            bot.answer_callback_query(call.id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)}")
        logger.error(f"Ошибка в callback-запросе: {e}")

from flask import Flask, request

app = Flask(__name__)

@app.route("/" + TOKEN, methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "Бот работает!", 200

def keep_alive():
    while True:
        try:
            url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/"
            r = requests.get(url, timeout=10)
            logger.info(f"[KeepAlive] ping {url} -> {r.status_code}")
        except Exception as e:
            logger.error(f"[KeepAlive] ошибка: {e}")
        time.sleep(60)

if __name__ == "__main__":
    # Запускаем поток проверки таймаута админов
    timeout_thread = threading.Thread(target=check_admin_timeout, daemon=True)
    timeout_thread.start()

    # Запускаем keep-alive поток
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()

    # Устанавливаем webhook
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    bot.remove_webhook()
    try:
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
