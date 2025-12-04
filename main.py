import random
import time
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
import atexit

import config
from database import (
    init_db, add_user, get_random_phrase_for_user,
    get_wrong_phrases, add_custom_phrase, delete_user_phrase,
    get_user_phrase_count, load_initial_phrases, update_user_progress,
    get_learned_phrases_count, debug_user_progress
)
from reminders import ReminderSystem
from yandex_api import get_phrase_examples

print('🚀 Запуск EnglishCard Bot...')

state_storage = StateMemoryStorage()
bot = TeleBot(config.BOT_TOKEN, state_storage=state_storage)

reminder_system = ReminderSystem(bot)

ADMIN_USERNAMES = ['@MrGrigorev0ne']
ADMIN_IDS = []


class Command:
    ADD_PHRASE = 'Добавить фразу ➕'
    DELETE_PHRASE = 'Удалить фразу 🔙'
    NEXT = 'Дальше ⏭'
    STATS = 'Статистика 📊'
    EXAMPLES = 'Примеры 💡'


class MyStates(StatesGroup):
    target_phrase = State()
    translate_phrase = State()
    another_phrases = State()
    add_new_phrase = State()


def is_admin(user_id, username):
    if username in ADMIN_USERNAMES:
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
        return True
    if user_id in ADMIN_IDS:
        return True
    return False


def create_learning_keyboard(phrases, target_russian):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = []

    phrase_buttons = [types.KeyboardButton(phrase['english_phrase']) for phrase in phrases]
    buttons.extend(phrase_buttons)
    random.shuffle(buttons)

    next_btn = types.KeyboardButton(Command.NEXT)
    add_phrase_btn = types.KeyboardButton(Command.ADD_PHRASE)
    delete_phrase_btn = types.KeyboardButton(Command.DELETE_PHRASE)
    stats_btn = types.KeyboardButton(Command.STATS)
    examples_btn = types.KeyboardButton(Command.EXAMPLES)

    buttons.extend([next_btn, add_phrase_btn, delete_phrase_btn, stats_btn, examples_btn])
    markup.add(*buttons)

    greeting = f"🇷🇺 Выбери перевод:\n\"{target_russian}\""
    return greeting, markup


@bot.message_handler(commands=['start', 'phrases'])
def start_bot(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    add_user(user_id, username, first_name)

    if is_admin(user_id, username):
        print(f"👑 Администратор вошел в систему: {username} (ID: {user_id})")

    welcome_text = """
🇬🇧 *Добро пожаловать в EnglishCard!* 🇺🇸

Изучайте английские фразы через интерактивные карточки.

*Команды:*
/start - Начать
/phrases - Новая фраза  
/stats - Статистика
/examples - Примеры использования

*Готовы начать?* Жмите «Дальше ⏭»!
"""

    bot.send_message(cid, welcome_text, parse_mode='Markdown')
    show_next_phrase(message)


def show_next_phrase(message):
    """
    Основная причина появления отгаданных слов по несколько раз — ошибка в формировании уникального списка вариантов ответов.
    Перепишем логику формирования distractors. Гарантируем один правильный + уникальные 3 неправильных (без дубликатов).
    """
    cid = message.chat.id
    user_id = message.from_user.id

    print(f"🔍 Пользователь {user_id} запросил следующую фразу")
    phrase_data = get_random_phrase_for_user(user_id)
    if not phrase_data:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        add_btn = types.KeyboardButton(Command.ADD_PHRASE)
        markup.add(add_btn)
        bot.send_message(cid, "У вас нет фраз для изучения. Добавьте первые фразы!", reply_markup=markup)
        return

    # Получаем варианты-отвлечения, гарантируем уникальность по phrase_id и тексту
    answers = [phrase_data]  # Первый — только правильный

    seen_phrase_ids = {phrase_data['phrase_id']}
    seen_eng = {phrase_data['english_phrase'].lower()}

    wrong_needed = 3
    max_tries = 20  # ограничим попытки, чтобы не попасть в бесконечный цикл

    attempt = 0
    while len(answers) < 4 and attempt < max_tries:
        wrongs = get_wrong_phrases(phrase_data['phrase_id'], user_id, wrong_needed * 2)
        for w in wrongs:
            if (
                w['phrase_id'] not in seen_phrase_ids
                and w['english_phrase'].lower() not in seen_eng
            ):
                answers.append(w)
                seen_phrase_ids.add(w['phrase_id'])
                seen_eng.add(w['english_phrase'].lower())
                if len(answers) == 4:
                    break
        attempt += 1
        if not wrongs:
            break

    # Сплит по случайному порядку для показа кнопок
    random.shuffle(answers)

    greeting, markup = create_learning_keyboard(answers, phrase_data['russian_translation'])
    bot.send_message(cid, greeting, reply_markup=markup)

    bot.set_state(user_id, MyStates.target_phrase, cid)
    with bot.retrieve_data(user_id, cid) as data:
        data['target_phrase'] = phrase_data['english_phrase']
        data['target_phrase_id'] = phrase_data['phrase_id']
        data['translate_phrase'] = phrase_data['russian_translation']
        data['all_phrases'] = answers
        data['current_english_phrase'] = phrase_data['english_phrase']

    # Отладочная информация — проверьте, нет ли повтора вариантов:
    print(f"✅ Показана фраза: '{phrase_data['english_phrase']}'")
    print(f"   Варианты ответов: {[p['english_phrase'] for p in answers]}")

# Остальной код не трогаем (орг логика не вызывает вопросов)

@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_phrase(message):
    show_next_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.STATS)
def show_stats_button(message):
    show_stats(message)


@bot.message_handler(func=lambda message: message.text == Command.ADD_PHRASE)
def add_phrase_button(message):
    add_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.DELETE_PHRASE)
def delete_phrase_button(message):
    delete_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.EXAMPLES)
def show_examples_button(message):
    cid = message.chat.id
    user_id = message.from_user.id
    with bot.retrieve_data(user_id, cid) as data:
        if 'current_english_phrase' in data and data['current_english_phrase']:
            target_phrase = data['current_english_phrase']
        elif 'target_phrase' in data and data['target_phrase']:
            target_phrase = data['target_phrase']
        else:
            bot.send_message(cid, "❌ Сначала выберите фразу для изучения с помощью /start")
            return
    bot.send_message(cid, "🔍 Ищу примеры использования...")
    examples_text = get_phrase_examples(target_phrase)
    response = f"📚 *Примеры для фразы:* `{target_phrase}`\n\n{examples_text}"
    bot.send_message(cid, response, parse_mode='Markdown')


@bot.message_handler(commands=['examples'])
def show_examples_command(message):
    cid = message.chat.id
    user_id = message.from_user.id
    with bot.retrieve_data(user_id, cid) as data:
        if 'current_english_phrase' in data and data['current_english_phrase']:
            target_phrase = data['current_english_phrase']
        elif 'target_phrase' in data and data['target_phrase']:
            target_phrase = data['target_phrase']
        else:
            bot.send_message(cid, "❌ Сначала выберите фразу для изучения с помощью /start")
            return
    bot.send_message(cid, "🔍 Ищу примеры использования...")
    examples_text = get_phrase_examples(target_phrase)
    response = f"📚 *Примеры для фразы:* `{target_phrase}`\n\n{examples_text}"
    bot.send_message(cid, response, parse_mode='Markdown')


@bot.message_handler(func=lambda message: True, state=MyStates.target_phrase)
def check_answer(message):
    cid = message.chat.id
    user_id = message.from_user.id
    with bot.retrieve_data(user_id, cid) as data:
        target_phrase = data['target_phrase']
        target_phrase_id = data['target_phrase_id']

    user_answer = message.text.strip()

    if user_answer in [Command.NEXT, Command.ADD_PHRASE, Command.DELETE_PHRASE, Command.STATS, Command.EXAMPLES]:
        return

    if user_answer.lower() == target_phrase.lower():
        update_user_progress(user_id, target_phrase_id, True)
        bot.send_message(cid, "✅ *Правильно!* Отличная работа! 🎉", parse_mode='Markdown')
        time.sleep(1)
        show_next_phrase(message)
    else:
        update_user_progress(user_id, target_phrase_id, False)
        with bot.retrieve_data(user_id, cid) as data:
            correct_translation = data['translate_phrase']
        bot.send_message(
            cid,
            f"❌ *Неправильно.*\n\nПравильный ответ: `{target_phrase}`\nПеревод: {correct_translation}",
            parse_mode='Markdown'
        )
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        next_btn = types.KeyboardButton(Command.NEXT)
        markup.add(next_btn)
        bot.send_message(cid, "Нажмите 'Дальше ⏭' для продолжения", reply_markup=markup)


@bot.message_handler(commands=['stats'])
def show_stats(message):
    cid = message.chat.id
    user_id = message.from_user.id
    total_phrases = get_user_phrase_count(user_id)
    learned_phrases = get_learned_phrases_count(user_id)
    stats_text = f"📊 *Ваша статистика:*\n\n" \
                 f"📚 Всего фраз: {total_phrases}\n" \
                 f"✅ Изучено: {learned_phrases}\n" \
                 f"🎯 Прогресс: {learned_phrases}/{total_phrases}"
    bot.send_message(cid, stats_text, parse_mode='Markdown')


def add_phrase(message):
    cid = message.chat.id
    user_id = message.from_user.id
    bot.set_state(user_id, MyStates.add_new_phrase, cid)
    bot.send_message(
        cid,
        "📝 *Добавление новой фразы*\n\n"
        "Введите английскую фразу:",
        parse_mode='Markdown'
    )


@bot.message_handler(state=MyStates.add_new_phrase)
def save_new_phrase(message):
    cid = message.chat.id
    user_id = message.from_user.id
    english_phrase = message.text.strip()
    if not english_phrase:
        bot.send_message(cid, "❌ Фраза не может быть пустой. Попробуйте еще раз:")
        return
    with bot.retrieve_data(user_id, cid) as data:
        data['new_english_phrase'] = english_phrase
    bot.send_message(
        cid,
        f"✅ Английская фраза: `{english_phrase}`\n\n"
        "Теперь введите русский перевод:",
        parse_mode='Markdown'
    )
    bot.set_state(user_id, MyStates.translate_phrase, cid)


@bot.message_handler(state=MyStates.translate_phrase)
def save_translation(message):
    cid = message.chat.id
    user_id = message.from_user.id
    russian_translation = message.text.strip()
    if not russian_translation:
        bot.send_message(cid, "❌ Перевод не может быть пустым. Попробуйте еще раз:")
        return
    with bot.retrieve_data(user_id, cid) as data:
        english_phrase = data['new_english_phrase']
    success = add_custom_phrase(user_id, english_phrase, russian_translation)
    if success:
        bot.send_message(
            cid,
            f"✅ *Фраза добавлена!*\n\n"
            f"🇬🇧 `{english_phrase}`\n"
            f"🇷🇺 `{russian_translation}`\n\n"
            f"Теперь она будет появляться в ваших занятиях!",
            parse_mode='Markdown'
        )
    else:
        bot.send_message(
            cid,
            "❌ Не удалось добавить фразу. Возможно, она уже существует.",
            parse_mode='Markdown'
        )
    bot.delete_state(user_id, cid)
    show_next_phrase(message)


def delete_phrase(message):
    cid = message.chat.id
    user_id = message.from_user.id
    with bot.retrieve_data(user_id, cid) as data:
        if 'target_phrase_id' not in data:
            bot.send_message(cid, "❌ Сначала выберите фразу для изучения")
            return
        phrase_id = data['target_phrase_id']
        english_phrase = data['target_phrase']
    delete_user_phrase(user_id, phrase_id)
    bot.send_message(
        cid,
        f"🗑️ Фраза \"{english_phrase}\" удалена из вашего набора.\n\n"
        f"Переходим к следующей фразе...",
        parse_mode='Markdown'
    )
    show_next_phrase(message)


@bot.message_handler(commands=['debug'])
def debug_user(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username
    if not is_admin(user_id, username) and user_id != message.from_user.id:
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return
    debug_user_progress(user_id)
    bot.send_message(cid, "🔍 Информация о прогрессе выведена в консоль сервера")


@bot.message_handler(commands=['admin'])
def admin_panel(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    if not is_admin(user_id, username):
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return

    markup = types.InlineKeyboardMarkup()

    test_reminder_btn = types.InlineKeyboardButton(
        "📨 Тестовое напоминание",
        callback_data="test_reminder"
    )
    status_btn = types.InlineKeyboardButton(
        "📊 Статус напоминаний",
        callback_data="reminder_status"
    )
    send_to_all_btn = types.InlineKeyboardButton(
        "📢 Сообщение всем",
        callback_data="send_to_all"
    )
    user_stats_btn = types.InlineKeyboardButton(
        "👥 Статистика пользователей",
        callback_data="user_stats"
    )
    markup.add(test_reminder_btn, status_btn)
    markup.add(send_to_all_btn, user_stats_btn)

    admin_info = f"👑 *Панель администратора*\n\n" \
                 f"Приветствую, {message.from_user.first_name}!\n" \
                 f"Username: @{username}\n" \
                 f"ID: {user_id}\n\n" \
                 f"Выберите действие:"

    bot.send_message(
        cid,
        admin_info,
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    if not is_admin(user_id, username):
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return

    bot.send_message(
        cid,
        "📢 *Режим рассылки*\n\n"
        "Отправьте сообщение, которое будет разослано всем пользователям:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(message, process_broadcast_message)


def process_broadcast_message(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    if not is_admin(user_id, username):
        return

    broadcast_text = message.text

    from database import get_connection
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        success_count = 0
        fail_count = 0
        bot.send_message(cid, "🔄 Начинаю рассылку...")
        for user_id in users:
            try:
                bot.send_message(user_id, f"📢 *Сообщение от администратора:*\n\n{broadcast_text}", parse_mode='Markdown')
                success_count += 1
            except Exception as e:
                fail_count += 1

        report = f"📊 *Отчет о рассылке:*\n\n" \
                 f"✅ Успешно: {success_count}\n" \
                 f"❌ Не удалось: {fail_count}\n" \
                 f"📨 Всего пользователей: {len(users)}"
        bot.send_message(cid, report, parse_mode='Markdown')

    except Exception as e:
        bot.send_message(cid, f"❌ Ошибка при рассылке: {e}")
    finally:
        cur.close()
        conn.close()


@bot.message_handler(commands=['myid'])
def get_my_id(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    is_user_admin = is_admin(user_id, username)
    admin_status = "👑 АДМИНИСТРАТОР" if is_user_admin else "👤 ПОЛЬЗОВАТЕЛЬ"
    response = f"🆔 *Ваши данные:*\n\n" \
               f"Имя: {first_name}\n" \
               f"Username: @{username}\n" \
               f"User ID: `{user_id}`\n" \
               f"Статус: {admin_status}"
    bot.send_message(message.chat.id, response, parse_mode='Markdown')


@bot.message_handler(commands=['users'])
def show_users_stats(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    if not is_admin(user_id, username):
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return

    from database import get_connection
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM user_phrases 
            WHERE correct_answers > 0
        """)
        active_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM phrases")
        total_phrases = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_phrases")
        user_phrases_count = cur.fetchone()[0]

        stats_text = f"📈 *Статистика бота:*\n\n" \
                     f"👥 Всего пользователей: {total_users}\n" \
                     f"🎯 Активных пользователей: {active_users}\n" \
                     f"📚 Всего фраз в базе: {total_phrases}\n" \
                     f"💾 Пользовательских связей: {user_phrases_count}"

        bot.send_message(cid, stats_text, parse_mode='Markdown')

    except Exception as e:
        bot.send_message(cid, f"❌ Ошибка при получении статистики: {e}")
    finally:
        cur.close()
        conn.close()


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    cid = call.message.chat.id
    user_id = call.from_user.id
    username = call.from_user.username
    if call.data in ["test_reminder", "reminder_status", "send_to_all", "user_stats"]:
        if not is_admin(user_id, username):
            bot.answer_callback_query(call.id, "❌ Недостаточно прав!")
            return

    if call.data == "test_reminder":
        try:
            reminder_system.send_daily_reminder()
            bot.answer_callback_query(call.id, "✅ Тестовое напоминание отправлено!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {e}")

    elif call.data == "reminder_status":
        jobs = reminder_system.scheduler.get_jobs()
        status_text = "📊 *Статус напоминаний:*\n\n"
        for job in jobs:
            next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M") if job.next_run_time else "Не запланировано"
            status_text += f"• {job.name}:\n   Следующий запуск: {next_run}\n\n"
        bot.answer_callback_query(call.id)
        bot.send_message(cid, status_text, parse_mode='Markdown')

    elif call.data == "send_to_all":
        bot.answer_callback_query(call.id)
        bot.send_message(
            cid,
            "📢 *Режим рассылки*\n\n"
            "Отправьте сообщение, которое будет разослано всем пользователям:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(call.message, process_broadcast_message)

    elif call.data == "user_stats":
        bot.answer_callback_query(call.id)
        show_users_stats(call.message)


def initialize_bot():
    print("🔄 Инициализация базы данных...")
    init_db()
    print("📥 Загрузка начальных фраз...")
    load_initial_phrases()
    print("⏰ Запуск системы напоминаний...")
    reminder_system.start()
    print(f"👑 Администраторы: {ADMIN_USERNAMES}")
    atexit.register(reminder_system.shutdown)
    print("✅ Бот готов к работе!")
    print("🤖 Запуск бота...")


bot.add_custom_filter(custom_filters.StateFilter(bot))

if __name__ == '__main__':
    initialize_bot()
    bot.infinity_polling(skip_pending=True)