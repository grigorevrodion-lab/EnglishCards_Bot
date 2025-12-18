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
    delete_user_phrase,
    get_learned_phrases_count,
    get_random_phrase_for_user,
    get_user_phrase_count,
    get_wrong_phrases,
    init_db,
    load_initial_phrases,
    update_user_progress,
)
from reminders import ReminderSystem
from yandex_api import get_phrase_examples

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

print("🚀 Запуск EnglishCard Bot...")

state_storage = StateMemoryStorage()
bot = TeleBot(config.BOT_TOKEN, state_storage=state_storage)
reminder_system = ReminderSystem(bot)

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
    if username in ADMIN_USERNAMES:
        ADMIN_IDS.append(user_id)
        return True
    return user_id in ADMIN_IDS


def create_learning_keyboard(phrases, target_russian):
    """Создает клавиатуру с вариантами ответов."""
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
        unique_wrong.append({
            "phrase_id": fake_id,
            "english_phrase": fake_text,
            "russian_translation": "",
        })

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
    """Показывает следующую фразу для изучения."""
    user_id = message.from_user.id
    cid = message.chat.id

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

    # Получаем неправильные варианты
    wrong_phrases = get_wrong_phrases(phrase["phrase_id"], user_id, limit=6)

    # Собираем все варианты ответов
    all_answers = [phrase] + wrong_phrases

    # Гарантируем 4 уникальных варианта
    final_answers = ensure_unique_answers(
        all_answers,
        phrase["phrase_id"],
        phrase["english_phrase"],
        user_id
    )

    greeting, markup = create_learning_keyboard(
        final_answers,
        phrase["russian_translation"],
    )
    bot.send_message(cid, greeting, reply_markup=markup)

    bot.set_state(user_id, MyStates.target_phrase, cid)
    with bot.retrieve_data(user_id, cid) as data:
        data.update(
            {
                "target_phrase": phrase["english_phrase"],
                "target_phrase_id": phrase["phrase_id"],
                "translate_phrase": phrase["russian_translation"],
                "current_english_phrase": phrase["english_phrase"],
            }
        )


@bot.message_handler(func=lambda m: m.text == Command.NEXT)
def next_phrase(message):
    """Обработчик кнопки 'Дальше'."""
    show_next_phrase(message)


@bot.message_handler(func=lambda m: m.text == Command.STATS)
def show_stats(message):
    """Показывает статистику пользователя."""
    user_id = message.from_user.id
    total = get_user_phrase_count(user_id)
    learned = get_learned_phrases_count(user_id)

    progress = int((learned / total * 100)) if total > 0 else 0

    text = (
        "📊 *Ваша статистика:*\n\n"
        f"📚 Всего фраз: {total}\n"
        f"✅ Изучено: {learned}\n"
        f"🎯 Прогресс: {progress}%\n"
        f"📈 Соотношение: {learned}/{total}"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == Command.EXAMPLES)
def show_examples(message):
    """Показывает примеры использования текущей фразы."""
    cid = message.chat.id
    user_id = message.from_user.id

    with bot.retrieve_data(user_id, cid) as data:
        phrase = data.get("current_english_phrase")

    if not phrase:
        bot.send_message(cid, "❌ Сначала выберите фразу.")
        return

    bot.send_message(cid, "🔍 Ищу примеры использования...")
    try:
        examples = get_phrase_examples(phrase)
        if examples.startswith("❌"):
            bot.send_message(cid, examples)
        else:
            bot.send_message(
                cid,
                f"📚 *Примеры для фразы:* `{phrase}`\n\n{examples}",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"Ошибка при получении примеров: {e}")
        bot.send_message(
            cid,
            "❌ Произошла ошибка при получении примеров. Попробуйте позже.",
        )


@bot.message_handler(state=MyStates.target_phrase)
def check_answer(message):
    """Проверяет ответ пользователя."""
    user_id = message.from_user.id
    cid = message.chat.id

    # Игнорируем команды
    if message.text in [cmd for cmd in vars(Command).values()]:
        return

    with bot.retrieve_data(user_id, cid) as data:
        correct = data["target_phrase"]
        phrase_id = data["target_phrase_id"]
        translation = data["translate_phrase"]

    is_correct = message.text.lower() == correct.lower()

    try:
        update_user_progress(user_id, phrase_id, is_correct)

        if is_correct:
            bot.send_message(cid, "✅ *Правильно!* 🎉", parse_mode="Markdown")
            time.sleep(1)
            show_next_phrase(message)
        else:
            bot.send_message(
                cid,
                f"❌ *Неправильно.*\n\n"
                f"Правильный ответ: `{correct}`\n"
                f"Перевод: {translation}",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"Ошибка при обновлении прогресса: {e}")
        bot.send_message(
            cid,
            "❌ Произошла ошибка при обработке ответа. Попробуйте еще раз.",
        )


def initialize_bot():
    """Инициализирует бота и запускает все системы."""
    logger.info("Инициализация бота...")

    try:
        init_db()
        logger.info("База данных инициализирована")

        load_initial_phrases()
        logger.info("Начальные фразы загружены")

        reminder_system.start()
        logger.info("Система напоминаний запущена")

        atexit.register(reminder_system.shutdown)
        logger.info("✅ Бот готов к работе!")

    except Exception as e:
        logger.error(f"Ошибка при инициализации бота: {e}")
        raise


bot.add_custom_filter(custom_filters.StateFilter(bot))

if __name__ == "__main__":
    try:
        initialize_bot()
        bot.infinity_polling(skip_pending=True, timeout=60)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise