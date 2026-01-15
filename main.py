import atexit
import random
import time
import logging

from telebot import TeleBot, custom_filters, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

import config
from database import (
    add_custom_phrase,
    add_user,
    debug_user_progress,
    delete_user_phrase,
    get_learned_phrases_count,
    get_random_phrase_for_user,
    get_user_phrase_count,
    get_user_phrases_list,
    get_wrong_phrases,
    init_db,
    load_initial_phrases,
    update_user_progress,
)
from reminders import ReminderSystem
from yandex_api import get_phrase_examples
from database import get_last_phrase_id, mark_phrase_shown

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

print("🚀 Запуск EnglishCard Bot...")

# Инициализация бота
state_storage = StateMemoryStorage()
bot = TeleBot(config.BOT_TOKEN, state_storage=state_storage)

# Инициализация системы напоминаний
reminder_system = ReminderSystem(bot)

# Администраторы бота
ADMIN_USERNAMES = ["@MrGrigorev0ne"]
ADMIN_IDS = []


class Command:
    ADD_PHRASE = "Добавить фразу ➕"
    DELETE_PHRASE = "Удалить фразу 🔙"
    NEXT = "Дальше ⏭"
    STATS = "Статистика 📊"
    EXAMPLES = "Примеры 💡"


class MyStates(StatesGroup):
    target_phrase = State()
    translate_phrase = State()
    add_new_phrase = State()


def is_admin(user_id, username):
    """Проверяет, является ли пользователь администратором"""
    if username in ADMIN_USERNAMES:
        ADMIN_IDS.append(user_id)
        return True
    return user_id in ADMIN_IDS


def create_learning_keyboard(phrases, target_russian):
    """Создает клавиатуру для изучения фраз с кнопкой примеров"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)

    buttons = [types.KeyboardButton(phrase["english_phrase"]) for phrase in phrases]
    random.shuffle(buttons)

    buttons.extend(
        [
            types.KeyboardButton(Command.NEXT),
            types.KeyboardButton(Command.ADD_PHRASE),
            types.KeyboardButton(Command.DELETE_PHRASE),
            types.KeyboardButton(Command.STATS),
            types.KeyboardButton(Command.EXAMPLES),
        ]
    )

    markup.add(*buttons)
    greeting = f'🇷🇺 Выбери перевод:\n"{target_russian}"'
    return greeting, markup


def ensure_unique_answers(answers, target_phrase_id, target_text, user_id):
    """
    Гарантирует наличие 4 уникальных вариантов ответа.
    Возвращает список из 4 уникальных вариантов.
    """
    # Убедимся, что правильный ответ есть в списке
    correct_answer = None
    other_answers = []

    for answer in answers:
        if answer["phrase_id"] == target_phrase_id:
            correct_answer = answer
        else:
            other_answers.append(answer)

    # Если правильного ответа нет (не должно случиться), создаем его
    if not correct_answer:
        correct_answer = {
            "phrase_id": target_phrase_id,
            "english_phrase": target_text,
            "russian_translation": "",
        }

    # Берем до 3 уникальных неправильных ответов
    unique_wrong = []
    seen_texts = set()

    for answer in other_answers:
        text = answer["english_phrase"].lower().strip()
        if text not in seen_texts and text != target_text.lower():
            seen_texts.add(text)
            unique_wrong.append(answer)
            if len(unique_wrong) == 3:
                break

    # Если недостаточно уникальных неправильных ответов, добавляем фейковые
    while len(unique_wrong) < 3:
        fake_id = -len(unique_wrong)  # Отрицательные ID для фейковых
        fake_text = f"Вариант {len(unique_wrong) + 1}"
        unique_wrong.append(
            {
                "phrase_id": fake_id,
                "english_phrase": fake_text,
                "russian_translation": "",
            }
        )

    # Смешиваем правильный с неправильными
    final_answers = [correct_answer] + unique_wrong
    random.shuffle(final_answers)

    return final_answers


@bot.message_handler(commands=["start", "phrases"])
def start_bot(message):
    """Обработчик команды /start."""
    user = message.from_user
    add_user(user.id, user.username, user.first_name)

    welcome_text = (
        "🇬🇧 *Добро пожаловать в EnglishCard!* 🇺🇸\n\n"
        "Изучайте английские фразы через интерактивные карточки.\n\n"
        "*Команды:*\n"
        "/start — Начать\n"
        "/phrases — Новая фраза\n"
        "/stats — Статистика\n"
        "/examples — Примеры использования\n\n"
        "*Готовы начать?* Жмите «Дальше ⏭»!"
    )

    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")
    show_next_phrase(message)


def show_next_phrase(message):
    """Показывает следующую фразу для изучения без повторов подряд."""
    user_id = message.from_user.id
    cid = message.chat.id

    # последняя показанная фраза берётся из БД (работает даже после перезапуска бота)
    last_id = get_last_phrase_id(user_id)

    phrase = None
    for _ in range(5):  # до 5 попыток не повторять подряд
        candidate = get_random_phrase_for_user(user_id)
        if not candidate:
            break
        if candidate["phrase_id"] != last_id:
            phrase = candidate
            break

    if not phrase:
        phrase = get_random_phrase_for_user(user_id)

    if not phrase:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton(Command.ADD_PHRASE))
        bot.send_message(
            cid,
            "У вас нет фраз для изучения. Добавьте первую фразу.",
            reply_markup=markup,
        )
        return

    # фиксируем, что фраза была показана (важно для новых пользователей)
    mark_phrase_shown(user_id, phrase["phrase_id"])

    # неправильные варианты
    wrong_phrases = get_wrong_phrases(phrase["phrase_id"], user_id, 6)
    all_answers = [phrase] + wrong_phrases

    final_answers = ensure_unique_answers(
        all_answers,
        phrase["phrase_id"],
        phrase["english_phrase"],
        user_id,
    )

    greeting, markup = create_learning_keyboard(
        final_answers,
        phrase["russian_translation"],
    )
    bot.send_message(cid, greeting, reply_markup=markup)

    # сохраняем state для проверки ответа
    bot.set_state(user_id, MyStates.target_phrase, cid)
    with bot.retrieve_data(user_id, cid) as st:
        st.update(
            {
                "target_phrase": phrase["english_phrase"],
                "target_phrase_id": phrase["phrase_id"],
                "translate_phrase": phrase["russian_translation"],
                "current_english_phrase": phrase["english_phrase"],
            }
        )




@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_phrase(message):
    """Обработчик кнопки 'Дальше ⏭'"""
    show_next_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.STATS)
def show_stats_button(message):
    """Показывает статистику по кнопке"""
    show_stats(message)


@bot.message_handler(func=lambda message: message.text == Command.ADD_PHRASE)
def add_phrase_button(message):
    """Обработчик кнопки 'Добавить фразу ➕'"""
    add_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.DELETE_PHRASE)
def delete_phrase_button(message):
    """Обработчик кнопки 'Удалить фразу 🔙'"""
    delete_phrase(message)


@bot.message_handler(func=lambda message: message.text == Command.EXAMPLES)
def show_examples_button(message):
    """Показывает примеры использования текущей фразы"""
    cid = message.chat.id
    user_id = message.from_user.id

    # Получаем данные из состояния
    with bot.retrieve_data(user_id, cid) as data:
        if "current_english_phrase" in data and data["current_english_phrase"]:
            target_phrase = data["current_english_phrase"]
        elif "target_phrase" in data and data["target_phrase"]:
            target_phrase = data["target_phrase"]
        else:
            bot.send_message(
                cid, "❌ Сначала выберите фразу для изучения с помощью /start"
            )
            return

    bot.send_message(cid, "🔍 Ищу примеры использования...")

    examples_text = get_phrase_examples(target_phrase)

    response = f"📚 *Примеры для фразы:* `{target_phrase}`\n\n{examples_text}"
    bot.send_message(cid, response, parse_mode="Markdown")


@bot.message_handler(commands=["examples"])
def show_examples_command(message):
    """Команда для показа примеров использования"""
    cid = message.chat.id
    user_id = message.from_user.id

    # Получаем данные из состояния
    with bot.retrieve_data(user_id, cid) as data:
        if "current_english_phrase" in data and data["current_english_phrase"]:
            target_phrase = data["current_english_phrase"]
        elif "target_phrase" in data and data["target_phrase"]:
            target_phrase = data["target_phrase"]
        else:
            bot.send_message(
                cid, "❌ Сначала выберите фразу для изучения с помощью /start"
            )
            return

    bot.send_message(cid, "🔍 Ищу примеры использования...")

    examples_text = get_phrase_examples(target_phrase)

    response = f"📚 *Примеры для фразы:* `{target_phrase}`\n\n{examples_text}"
    bot.send_message(cid, response, parse_mode="Markdown")


@bot.message_handler(func=lambda message: True, state=MyStates.target_phrase)
def check_answer(message):
    """Проверяет ответ пользователя"""
    cid = message.chat.id
    user_id = message.from_user.id

    with bot.retrieve_data(user_id, cid) as data:
        target_phrase = data["target_phrase"]
        target_phrase_id = data["target_phrase_id"]

    user_answer = message.text.strip()

    # Проверяем, является ли ответ одной из кнопок команд
    if user_answer in [
        Command.NEXT,
        Command.ADD_PHRASE,
        Command.DELETE_PHRASE,
        Command.STATS,
        Command.EXAMPLES,
    ]:
        return  # Игнорируем нажатия командных кнопок

    # Проверяем правильность ответа
    if user_answer.lower() == target_phrase.lower():
        # Правильный ответ
        update_user_progress(user_id, target_phrase_id, True)
        bot.send_message(
            cid, "✅ *Правильно!* Отличная работа! 🎉", parse_mode="Markdown"
        )

        # Показываем следующий вопрос через 1 секунду
        time.sleep(1)
        show_next_phrase(message)
    else:
        # Неправильный ответ
        update_user_progress(user_id, target_phrase_id, False)

        # Показываем правильный ответ
        with bot.retrieve_data(user_id, cid) as data:
            correct_translation = data["translate_phrase"]

        bot.send_message(
            cid,
            f"❌ *Неправильно.*\n\nПравильный ответ: `{target_phrase}`\nПеревод: {correct_translation}",
            parse_mode="Markdown",
        )

        # Предлагаем продолжить
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        next_btn = types.KeyboardButton(Command.NEXT)
        markup.add(next_btn)
        bot.send_message(
            cid, "Нажмите 'Дальше ⏭' для продолжения", reply_markup=markup
        )


@bot.message_handler(commands=["stats"])
def show_stats(message):
    """Показывает статистику пользователя"""
    cid = message.chat.id
    user_id = message.from_user.id

    total_phrases = get_user_phrase_count(user_id)
    learned_phrases = get_learned_phrases_count(user_id)
    progress = int((learned_phrases / total_phrases * 100)) if total_phrases > 0 else 0

    stats_text = (
        f"📊 *Ваша статистика:*\n\n"
        f"📚 Всего фраз: {total_phrases}\n"
        f"✅ Изучено: {learned_phrases}\n"
        f"🎯 Прогресс: {progress}%\n"
        f"📈 Соотношение: {learned_phrases}/{total_phrases}"
    )

    bot.send_message(cid, stats_text, parse_mode="Markdown")


def add_phrase(message):
    """Начинает процесс добавления новой фразы"""
    cid = message.chat.id
    user_id = message.from_user.id

    bot.set_state(user_id, MyStates.add_new_phrase, cid)

    # Создаем клавиатуру с кнопкой отмены
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_btn = types.KeyboardButton("❌ Отмена")
    markup.add(cancel_btn)

    bot.send_message(
        cid,
        "📝 *Добавление новой фразы*\n\n"
        "Введите английскую фразу:\n\n"
        "Или нажмите '❌ Отмена' для отмены операции",
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.message_handler(state=MyStates.add_new_phrase)
def save_new_phrase(message):
    """Сохраняет новую фразу"""
    cid = message.chat.id
    user_id = message.from_user.id

    user_input = message.text.strip()

    # Проверка на отмену
    if user_input == "❌ Отмена" or user_input.lower() in [
        "отмена",
        "cancel",
        "отменить",
    ]:
        bot.delete_state(user_id, cid)
        bot.send_message(
            cid,
            "❌ Добавление фразы отменено.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        show_next_phrase(message)
        return

    if not user_input:
        bot.send_message(
            cid,
            "❌ Фраза не может быть пустой. Попробуйте еще раз или нажмите '❌ Отмена':",
        )
        return

    with bot.retrieve_data(user_id, cid) as data:
        data["new_english_phrase"] = user_input

    # Создаем клавиатуру с кнопкой отмены
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_btn = types.KeyboardButton("❌ Отмена")
    markup.add(cancel_btn)

    bot.send_message(
        cid,
        f"✅ Английская фраза: `{user_input}`\n\n"
        "Теперь введите русский перевод:\n\n"
        "Или нажмите '❌ Отмена' для отмены операции",
        reply_markup=markup,
        parse_mode="Markdown",
    )

    # Меняем состояние на ожидание перевода
    bot.set_state(user_id, MyStates.translate_phrase, cid)


@bot.message_handler(state=MyStates.translate_phrase)
def save_translation(message):
    """Сохраняет перевод и добавляет фразу"""
    cid = message.chat.id
    user_id = message.from_user.id

    user_input = message.text.strip()

    # Проверка на отмену
    if user_input == "❌ Отмена" or user_input.lower() in [
        "отмена",
        "cancel",
        "отменить",
    ]:
        bot.delete_state(user_id, cid)
        bot.send_message(
            cid,
            "❌ Добавление фразы отменено.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        show_next_phrase(message)
        return

    if not user_input:
        bot.send_message(
            cid,
            "❌ Перевод не может быть пустым. Попробуйте еще раз или нажмите '❌ Отмена':",
        )
        return

    with bot.retrieve_data(user_id, cid) as data:
        english_phrase = data["new_english_phrase"]

    # Добавляем фразу в базу
    success = add_custom_phrase(user_id, english_phrase, user_input)

    if success:
        bot.send_message(
            cid,
            f"✅ *Фраза добавлена!*\n\n"
            f"🇬🇧 `{english_phrase}`\n"
            f"🇷🇺 `{user_input}`\n\n"
            f"Теперь она будет появляться в ваших занятиях!",
            parse_mode="Markdown",
        )
    else:
        bot.send_message(
            cid,
            "❌ Не удалось добавить фразу. Возможно, она уже существует.",
            parse_mode="Markdown",
        )

    # Сбрасываем состояние и показываем следующую фразу
    bot.delete_state(user_id, cid)
    show_next_phrase(message)


def delete_phrase(message):
    """Показывает список фраз пользователя для удаления"""
    cid = message.chat.id
    user_id = message.from_user.id

    # Получаем список фраз пользователя
    user_phrases = get_user_phrases_list(user_id)

    if not user_phrases:
        bot.send_message(
            cid,
            "❌ У вас нет фраз для удаления. Добавьте фразы с помощью кнопки 'Добавить фразу ➕'",
            parse_mode="Markdown",
        )
        return

    # Создаем inline-клавиатуру с фразами
    markup = types.InlineKeyboardMarkup(row_width=1)

    # Ограничиваем количество фраз для отображения (чтобы не было слишком длинного списка)
    display_phrases = user_phrases[:20]  # Показываем первые 20 фраз

    for phrase in display_phrases:
        phrase_text = phrase["english_phrase"]
        # Обрезаем длинные фразы для кнопки
        button_text = phrase_text[:40] + "..." if len(phrase_text) > 40 else phrase_text
        status_icon = "✅" if phrase["is_learned"] else "📖"
        button_text = f"{status_icon} {button_text}"

        callback_data = f"delete_phrase_{phrase['phrase_id']}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    # Добавляем кнопку отмены
    cancel_btn = types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    markup.add(cancel_btn)

    phrases_text = "🗑️ *Выберите фразу для удаления:*\n\n"
    if len(user_phrases) > 20:
        phrases_text += f"*Показано первых 20 из {len(user_phrases)} фраз*\n\n"

    bot.send_message(
        cid,
        phrases_text,
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["debug"])
def debug_user(message):
    """Команда для отладки прогресса пользователя"""
    cid = message.chat.id
    user_id = message.from_user.id

    # Только для администраторов или самого пользователя
    username = message.from_user.username
    if not is_admin(user_id, username) and user_id != message.from_user.id:
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return

    debug_user_progress(user_id)
    bot.send_message(cid, "🔍 Информация о прогрессе выведена в консоль сервера")


# ==================== АДМИНИСТРАТИВНЫЕ КОМАНДЫ ====================


@bot.message_handler(commands=["admin"])
def admin_panel(message):
    """
    Панель администратора для управления напоминаниями
    """
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    # Проверяем, является ли пользователь администратором
    if not is_admin(user_id, username):
        bot.send_message(cid, "❌ Эта команда доступна только администраторам")
        return

    markup = types.InlineKeyboardMarkup()

    # Кнопки для управления напоминаниями
    test_reminder_btn = types.InlineKeyboardButton(
        "📨 Тестовое напоминание", callback_data="test_reminder"
    )
    status_btn = types.InlineKeyboardButton(
        "📊 Статус напоминаний", callback_data="reminder_status"
    )
    send_to_all_btn = types.InlineKeyboardButton(
        "📢 Сообщение всем", callback_data="send_to_all"
    )
    user_stats_btn = types.InlineKeyboardButton(
        "👥 Статистика пользователей", callback_data="user_stats"
    )

    markup.add(test_reminder_btn, status_btn)
    markup.add(send_to_all_btn, user_stats_btn)

    admin_info = (
        f"👑 *Панель администратора*\n\n"
        f"Приветствую, {message.from_user.first_name}!\n"
        f"Username: @{username}\n"
        f"ID: {user_id}\n\n"
        f"Выберите действие:"
    )

    bot.send_message(
        cid,
        admin_info,
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["broadcast"])
def broadcast_message(message):
    """
    Рассылка сообщения всем пользователям (только для администратора)
    """
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
        parse_mode="Markdown",
    )

    bot.register_next_step_handler(message, process_broadcast_message)


def process_broadcast_message(message):
    """
    Обрабатывает сообщение для рассылки
    """
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
                bot.send_message(
                    user_id,
                    f"📢 *Сообщение от администратора:*\n\n{broadcast_text}",
                    parse_mode="Markdown",
                )
                success_count += 1
            except Exception:
                fail_count += 1

        # Отправляем отчет администратору
        report = (
            f"📊 *Отчет о рассылке:*\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Не удалось: {fail_count}\n"
            f"📨 Всего пользователей: {len(users)}"
        )

        bot.send_message(cid, report, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(cid, f"❌ Ошибка при рассылке: {e}")
    finally:
        cur.close()
        conn.close()


@bot.message_handler(commands=["myid"])
def get_my_id(message):
    """Показывает user_id пользователя"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    is_user_admin = is_admin(user_id, username)

    admin_status = "👑 АДМИНИСТРАТОР" if is_user_admin else "👤 ПОЛЬЗОВАТЕЛЬ"

    response = (
        f"🆔 *Ваши данные:*\n\n"
        f"Имя: {first_name}\n"
        f"Username: @{username}\n"
        f"User ID: `{user_id}`\n"
        f"Статус: {admin_status}"
    )

    bot.send_message(message.chat.id, response, parse_mode="Markdown")


@bot.message_handler(commands=["users"])
def show_users_stats(message):
    """Показывает статистику по пользователям (только для администратора)"""
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
        # Общее количество пользователей
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        # Количество активных пользователей (с фразами)
        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) 
            FROM user_phrases 
            WHERE correct_answers > 0
        """
        )
        active_users = cur.fetchone()[0]

        # Общее количество фраз
        cur.execute("SELECT COUNT(*) FROM phrases")
        total_phrases = cur.fetchone()[0]

        # Количество пользовательских фраз
        cur.execute("SELECT COUNT(*) FROM user_phrases")
        user_phrases_count = cur.fetchone()[0]

        stats_text = (
            f"📈 *Статистика бота:*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎯 Активных пользователей: {active_users}\n"
            f"📚 Всего фраз в базе: {total_phrases}\n"
            f"💾 Пользовательских связей: {user_phrases_count}"
        )

        bot.send_message(cid, stats_text, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(cid, f"❌ Ошибка при получении статистики: {e}")
    finally:
        cur.close()
        conn.close()


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """
    Обработчик callback-запросов от inline кнопок
    """
    cid = call.message.chat.id
    user_id = call.from_user.id
    username = call.from_user.username

    # Проверяем права администратора для некоторых действий
    if call.data in ["test_reminder", "reminder_status", "send_to_all", "user_stats"]:
        if not is_admin(user_id, username):
            bot.answer_callback_query(call.id, "❌ Недостаточно прав!")
            return

    if call.data == "test_reminder":
        # Отправляем тестовое напоминание
        try:
            reminder_system.send_daily_reminder()
            bot.answer_callback_query(call.id, "✅ Тестовое напоминание отправлено!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {e}")

    elif call.data == "reminder_status":
        # Показываем статус напоминаний
        jobs = reminder_system.scheduler.get_jobs()
        status_text = "📊 *Статус напоминаний:*\n\n"

        for job in jobs:
            next_run = (
                job.next_run_time.strftime("%d.%m.%Y %H:%M")
                if job.next_run_time
                else "Не запланировано"
            )
            status_text += f"• {job.name}:\n   Следующий запуск: {next_run}\n\n"

        bot.answer_callback_query(call.id)
        bot.send_message(cid, status_text, parse_mode="Markdown")

    elif call.data == "send_to_all":
        # Запрашиваем сообщение для рассылки
        bot.answer_callback_query(call.id)
        bot.register_next_step_handler(call.message, process_broadcast_message)

    elif call.data == "user_stats":
        # Показываем статистику пользователей
        bot.answer_callback_query(call.id)
        show_users_stats(call.message)

    elif call.data.startswith("delete_phrase_"):
        # Обработка удаления фразы
        try:
            phrase_id = int(call.data.split("_")[2])

            # Получаем информацию о фразе перед удалением
            user_phrases = get_user_phrases_list(user_id, limit=1000)
            phrase_info = next(
                (p for p in user_phrases if p["phrase_id"] == phrase_id), None
            )

            if phrase_info:
                english_phrase = phrase_info["english_phrase"]
                russian_translation = phrase_info["russian_translation"]

                # Удаляем фразу
                delete_user_phrase(user_id, phrase_id)

                bot.answer_callback_query(call.id, "✅ Фраза удалена")
                bot.edit_message_text(
                    f"🗑️ *Фраза удалена из вашего набора:*\n\n"
                    f"🇬🇧 `{english_phrase}`\n"
                    f"🇷🇺 `{russian_translation}`",
                    cid,
                    call.message.message_id,
                    parse_mode="Markdown",
                )
            else:
                bot.answer_callback_query(call.id, "❌ Фраза не найдена")
        except (ValueError, IndexError) as e:
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении")
            print(f"Ошибка при удалении фразы: {e}")

    elif call.data == "cancel_delete":
        # Отмена удаления
        bot.answer_callback_query(call.id, "Отменено")
        bot.edit_message_text(
            "❌ Удаление отменено",
            cid,
            call.message.message_id,
        )


def initialize_bot():
    """
    Инициализирует бота - создает БД, загружает данные и запускает напоминания
    """
    print("🔄 Инициализация базы данных...")
    init_db()

    print("📥 Загрузка начальных фраз...")
    load_initial_phrases()

    print("⏰ Запуск системы напоминаний...")
    reminder_system.start()

    print(f"👑 Администраторы: {ADMIN_USERNAMES}")

    # Регистрируем функцию остановки при завершении работы
    atexit.register(reminder_system.shutdown)

    print("✅ Бот готов к работе!")
    print("🤖 Запуск бота...")


# Добавляем кастомные фильтры для работы с состояниями
bot.add_custom_filter(custom_filters.StateFilter(bot))

# Инициализация и запуск
if __name__ == "__main__":
    initialize_bot()
    bot.infinity_polling(skip_pending=True)
