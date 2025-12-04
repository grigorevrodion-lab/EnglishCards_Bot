import requests
import logging
from config import YA_DICTIONARY_API_KEY

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_word_definition(english_word):
    """
    Получает определение и примеры использования слова из Yandex Dictionary API
    """
    if not YA_DICTIONARY_API_KEY:
        logger.warning("Yandex Dictionary API ключ не настроен")
        return None

    url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
    params = {
        'key': YA_DICTIONARY_API_KEY,
        'lang': 'en-ru',
        'text': english_word.lower().strip(),
        'ui': 'ru'
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if not data.get('def'):
            logger.info(f"Слово '{english_word}' не найдено в словаре")
            return None

        return parse_dictionary_response(data, english_word)

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к Yandex Dictionary API: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None


def parse_dictionary_response(data, original_word):
    """
    Парсит ответ от Yandex Dictionary API
    """
    result = {
        'word': original_word,
        'definitions': [],
        'examples': [],
        'transcriptions': [],
        'parts_of_speech': []
    }

    try:
        for definition in data['def']:
            # Часть речи
            pos = definition.get('pos')
            if pos:
                result['parts_of_speech'].append(pos)

            # Транскрипция
            transcription = definition.get('ts')
            if transcription:
                result['transcriptions'].append(transcription)

            # Переводы
            for translation in definition.get('tr', []):
                # Основной перевод
                text = translation.get('text', '').strip()
                if text and text not in result['definitions']:
                    result['definitions'].append(text)

                # Примеры использования
                for example in translation.get('ex', []):
                    eng_example = example.get('text', '').strip()
                    rus_example = example.get('tr', [{}])[0].get('text', '').strip()

                    if eng_example and rus_example:
                        result['examples'].append({
                            'english': eng_example,
                            'russian': rus_example
                        })

                # Синонимы
                for synonym in translation.get('syn', []):
                    syn_text = synonym.get('text', '').strip()
                    if syn_text and syn_text not in result['definitions']:
                        result['definitions'].append(f"(син.) {syn_text}")

        # Ограничиваем количество примеров
        result['examples'] = result['examples'][:3]

        return result

    except Exception as e:
        logger.error(f"Ошибка парсинга ответа API: {e}")
        return None


def get_phrase_examples(english_phrase):
    """
    Получает примеры использования для фразы
    """
    print(f"🔍 Поиск примеров для фразы: '{english_phrase}'")  # Отладочная информация

    if not english_phrase or not isinstance(english_phrase, str):
        return "❌ Неверный формат фразы"

    # Извлекаем первое значимое слово из фразы
    words = english_phrase.split()
    if not words:
        return "❌ Не удалось извлечь слова из фразы"

    # Ищем первое существительное/глагол/прилагательное
    search_word = words[0]
    for word in words:
        if len(word) > 2:  # Пропускаем артикли, предлоги
            search_word = word
            break

    print(f"🔍 Ищем слово: '{search_word}'")  # Отладочная информация

    result = get_word_definition(search_word)

    if not result:
        return f"❌ Примеры использования для '{search_word}' не найдены"

    # Форматируем результат
    response_parts = []

    if result['definitions']:
        response_parts.append("📖 *Определения:*")
        for i, definition in enumerate(result['definitions'][:3], 1):
            response_parts.append(f"{i}. {definition}")

    if result['examples']:
        response_parts.append("\n💡 *Примеры использования:*")
        for i, example in enumerate(result['examples'], 1):
            response_parts.append(f"{i}. {example['english']}")
            response_parts.append(f"   → {example['russian']}")

    if result['transcriptions']:
        response_parts.append(f"\n🔊 *Транскрипция:* `{result['transcriptions'][0]}`")

    if result['parts_of_speech']:
        response_parts.append(f"\n🏷️ *Часть речи:* {', '.join(set(result['parts_of_speech']))}")

    return "\n".join(response_parts) if response_parts else "❌ Информация не найдена"


def test_yandex_api():
    """Тестирование работы Yandex Dictionary API"""
    test_words = ['hello', 'computer', 'beautiful', 'run']

    print("🧪 Тестирование Yandex Dictionary API")
    print("=" * 50)

    for word in test_words:
        print(f"\n🔍 Поиск: '{word}'")
        result = get_word_definition(word)

        if result:
            print(f"✅ Найдено:")
            if result['definitions']:
                print(f"   Определения: {', '.join(result['definitions'][:2])}")
            if result['examples']:
                print(f"   Примеры: {len(result['examples'])}")
            if result['transcriptions']:
                print(f"   Транскрипция: {result['transcriptions'][0]}")
        else:
            print("❌ Не найдено")


if __name__ == "__main__":
    test_yandex_api()