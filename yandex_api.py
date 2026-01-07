import requests
import logging
from config import YA_DICTIONARY_API_KEY

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_word_definition(english_word):
    """
    Получает определение и примеры использования слова из Yandex Dictionary API.
    Возвращает None в случае ошибки.
    """
    if not YA_DICTIONARY_API_KEY:
        logger.warning("Yandex Dictionary API ключ не настроен")
        return None

    if not english_word or not isinstance(english_word, str):
        logger.error(f"Неверный формат слова: {english_word}")
        return None

    url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
    params = {
        "key": YA_DICTIONARY_API_KEY,
        "lang": "en-ru",
        "text": english_word.lower().strip(),
        "ui": "ru",
    }

    try:
        logger.info(f"Запрос к Yandex API для слова: '{english_word}'")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if not data.get("def"):
            logger.info(f"Слово '{english_word}' не найдено в словаре")
            return None

        logger.info(f"Успешный ответ API для '{english_word}'")
        return parse_dictionary_response(data, english_word)

    except requests.exceptions.Timeout:
        logger.error(f"Таймаут запроса к Yandex API для слова '{english_word}'")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Ошибка подключения к Yandex API для слова '{english_word}'")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP ошибка {e.response.status_code} для слова '{english_word}'")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к Yandex API: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при обработке слова '{english_word}': {e}")
        return None


def parse_dictionary_response(data, original_word):
    """
    Парсит ответ от Yandex Dictionary API.
    Возвращает структурированные данные или None в случае ошибки.
    """
    if not data or not isinstance(data, dict):
        logger.error(f"Неверный формат ответа API для слова '{original_word}'")
        return None

    result = {
        "word": original_word,
        "definitions": [],
        "examples": [],
        "transcriptions": [],
        "parts_of_speech": [],
    }

    try:
        definitions = data.get("def", [])
        if not definitions:
            logger.info(f"Нет определений для слова '{original_word}'")
            return result

        for definition in definitions:
            # Часть речи
            pos = definition.get("pos")
            if pos and pos not in result["parts_of_speech"]:
                result["parts_of_speech"].append(pos)

            # Транскрипция
            transcription = definition.get("ts")
            if transcription and transcription not in result["transcriptions"]:
                result["transcriptions"].append(transcription)

            # Переводы
            translations = definition.get("tr", [])
            for translation in translations:
                # Основной перевод
                text = translation.get("text", "").strip()
                if text and text not in result["definitions"]:
                    result["definitions"].append(text)

                # Примеры использования
                examples = translation.get("ex", [])
                for example in examples[:2]:  # Берем только 2 примера на перевод
                    eng_example = example.get("text", "").strip()
                    tr_list = example.get("tr", [{}])
                    rus_example = tr_list[0].get("text", "").strip()

                    if eng_example and rus_example:
                        result["examples"].append(
                            {
                                "english": eng_example,
                                "russian": rus_example,
                            }
                        )

                # Синонимы
                synonyms = translation.get("syn", [])
                for synonym in synonyms[:2]:  # Берем только 2 синонима
                    syn_text = synonym.get("text", "").strip()
                    if syn_text and syn_text not in result["definitions"]:
                        result["definitions"].append(f"(син.) {syn_text}")

        # Ограничиваем количество
        result["definitions"] = result["definitions"][:5]
        result["examples"] = result["examples"][:4]
        result["transcriptions"] = result["transcriptions"][:1]
        result["parts_of_speech"] = list(set(result["parts_of_speech"]))

        return result

    except KeyError as e:
        logger.error(f"Отсутствует ключ в ответе API: {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка парсинга ответа API для '{original_word}': {e}")
        return None


def get_phrase_examples(english_phrase):
    """
    Получает примеры использования для фразы.
    Возвращает форматированную строку или сообщение об ошибке.
    """
    if not english_phrase or not isinstance(english_phrase, str):
        return "❌ Неверный формат фразы"

    english_phrase = english_phrase.strip()
    if not english_phrase:
        return "❌ Пустая фраза"

    logger.info(f"Поиск примеров для фразы: '{english_phrase}'")

    # Извлекаем первое значимое слово из фразы
    words = english_phrase.split()
    if not words:
        return "❌ Не удалось извлечь слова из фразы"

    # Ищем первое существительное/глагол/прилагательное
    search_word = words[0]
    for word in words:
        word_clean = word.strip(",.!?;:\"'")
        if len(word_clean) > 2:  # Пропускаем артикли, предлоги
            search_word = word_clean
            break

    logger.info(f"Ищем слово для примера: '{search_word}'")

    try:
        result = get_word_definition(search_word)

        if not result:
            return f"❌ Информация для слова '{search_word}' не найдена"

        # Форматируем результат
        response_parts = []

        if result.get("definitions"):
            response_parts.append("📖 *Определения:*")
            for i, definition in enumerate(result["definitions"][:3], 1):
                response_parts.append(f"{i}. {definition}")

        if result.get("examples"):
            response_parts.append("\n💡 *Примеры использования:*")
            for i, example in enumerate(result["examples"], 1):
                response_parts.append(f"{i}. {example['english']}")
                response_parts.append(f"   → {example['russian']}")

        if result.get("transcriptions"):
            response_parts.append(
                f"\n🔊 *Транскрипция:* `{result['transcriptions'][0]}`"
            )

        if result.get("parts_of_speech"):
            response_parts.append(
                f"\n🏷️ *Часть речи:* {', '.join(result['parts_of_speech'])}"
            )

        if not response_parts:
            return f"❌ Для слова '{search_word}' не найдено полезной информации"

        return "\n".join(response_parts)

    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске примеров: {e}")
        return f"❌ Ошибка при получении информации. Попробуйте позже."


def test_yandex_api():
    """Тестирование работы Yandex Dictionary API."""
    test_words = ["hello", "computer", "beautiful", "run"]

    print("🧪 Тестирование Yandex Dictionary API")
    print("=" * 50)

    for word in test_words:
        print(f"\n🔍 Поиск: '{word}'")
        result = get_word_definition(word)

        if result:
            print(f"✅ Найдено:")
            if result.get("definitions"):
                print(f"   Определения: {', '.join(result['definitions'][:2])}")
            if result.get("examples"):
                print(f"   Примеры: {len(result['examples'])} найдено")
            if result.get("transcriptions"):
                print(f"   Транскрипция: {result['transcriptions'][0]}")
        else:
            print("❌ Не найдено")


if __name__ == "__main__":
    test_yandex_api()