import pg8000
from config import DATABASE_URL
import sys
import re


def parse_database_url(url):
    """Парсит DATABASE_URL для pg8000"""
    # Формат: postgresql://username:password@host:port/database
    pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
    match = re.match(pattern, url)

    if match:
        username, password, host, port, database = match.groups()
        return {
            'user': username,
            'password': password,
            'host': host,
            'port': int(port),
            'database': database
        }
    else:
        print(f"❌ Неверный формат DATABASE_URL: {url}")
        sys.exit(1)


def get_connection():
    """Получение соединения с БД с обработкой ошибок"""
    try:
        # Парсим DATABASE_URL
        db_config = parse_database_url(DATABASE_URL)

        # Создаем соединение
        conn = pg8000.connect(**db_config)
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print("Проверьте:")
        print("1. Запущена ли служба PostgreSQL")
        print("2. Правильность данных в .env файле")
        print("3. Доступность базы данных")
        sys.exit(1)


def row_to_dict(row, columns):
    """Преобразует строку из БД в словарь"""
    if not row:
        return None
    return {columns[i]: row[i] for i in range(len(columns))}


def init_db():
    """Инициализация базы данных"""
    conn = get_connection()
    cur = conn.cursor()

    print("Создание таблиц в базе данных...")

    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(100),
            first_name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица фраз
    cur.execute("""
        CREATE TABLE IF NOT EXISTS phrases (
            phrase_id SERIAL PRIMARY KEY,
            english_phrase TEXT NOT NULL,
            russian_translation TEXT NOT NULL,
            category VARCHAR(100),
            level VARCHAR(10),
            example TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(english_phrase, russian_translation)
        )
    """)

    # Таблица прогресса пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_phrases (
            user_phrase_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            phrase_id INTEGER REFERENCES phrases(phrase_id) ON DELETE CASCADE,
            correct_answers INTEGER DEFAULT 0,
            is_learned BOOLEAN DEFAULT FALSE,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, phrase_id)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Таблицы успешно созданы!")


def add_user(user_id, username, first_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username, first_name) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, username, first_name))
    conn.commit()
    cur.close()
    conn.close()


def get_random_phrase_for_user(user_id):
    """Получает случайную фразу для пользователя с учетом прогресса"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        # Сначала пытаемся получить НЕИЗУЧЕННЫЕ фразы из пользовательского набора
        cur.execute("""
            SELECT p.phrase_id, p.english_phrase, p.russian_translation, p.example, p.category,
                   up.correct_answers, up.is_learned
            FROM phrases p
            JOIN user_phrases up ON p.phrase_id = up.phrase_id
            WHERE up.user_id = %s AND up.is_learned = FALSE
            ORDER BY up.correct_answers ASC, RANDOM()
            LIMIT 1
        """, (user_id,))

        phrase = cur.fetchone()
        columns = ['phrase_id', 'english_phrase', 'russian_translation', 'example', 'category', 'correct_answers',
                   'is_learned']

        # Если у пользователя нет невыученных фраз, берем фразы которые он еще не добавлял
        if not phrase:
            cur.execute("""
                SELECT p.phrase_id, p.english_phrase, p.russian_translation, p.example, p.category
                FROM phrases p
                WHERE p.phrase_id NOT IN (
                    SELECT phrase_id FROM user_phrases WHERE user_id = %s
                )
                ORDER BY RANDOM()
                LIMIT 1
            """, (user_id,))
            phrase = cur.fetchone()
            columns = ['phrase_id', 'english_phrase', 'russian_translation', 'example', 'category']

        # Если все фразы изучены или их нет вообще, берем любую случайную
        if not phrase:
            cur.execute("""
                SELECT phrase_id, english_phrase, russian_translation, example, category
                FROM phrases
                ORDER BY RANDOM()
                LIMIT 1
            """)
            phrase = cur.fetchone()
            columns = ['phrase_id', 'english_phrase', 'russian_translation', 'example', 'category']

        cur.close()
        conn.close()

        if phrase:
            return row_to_dict(phrase, columns)
        return None

    except Exception as e:
        print(f"❌ Ошибка при получении случайной фразы: {e}")
        cur.close()
        conn.close()
        return None


def get_wrong_phrases(correct_phrase_id, user_id, limit=3):
    """Получает неправильные варианты фраз, исключая текущую и изученные"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT phrase_id, english_phrase, russian_translation
            FROM phrases
            WHERE phrase_id != %s 
            AND phrase_id NOT IN (
                SELECT phrase_id FROM user_phrases 
                WHERE user_id = %s AND is_learned = TRUE
            )
            ORDER BY RANDOM()
            LIMIT %s
        """, (correct_phrase_id, user_id, limit))

        wrong_phrases = cur.fetchall()
        columns = ['phrase_id', 'english_phrase', 'russian_translation']

        # Если не хватает неправильных вариантов, добавляем любые другие фразы
        if len(wrong_phrases) < limit:
            additional_limit = limit - len(wrong_phrases)
            cur.execute("""
                SELECT phrase_id, english_phrase, russian_translation
                FROM phrases
                WHERE phrase_id != %s
                AND phrase_id NOT IN (
                    SELECT phrase_id FROM user_phrases 
                    WHERE user_id = %s
                )
                ORDER BY RANDOM()
                LIMIT %s
            """, (correct_phrase_id, user_id, additional_limit))

            additional_phrases = cur.fetchall()
            wrong_phrases.extend(additional_phrases)

        cur.close()
        conn.close()

        return [
            row_to_dict(row, columns)
            for row in wrong_phrases
        ]

    except Exception as e:
        print(f"❌ Ошибка при получении неправильных фраз: {e}")
        cur.close()
        conn.close()
        return []


def update_user_progress(user_id, phrase_id, is_correct):
    """Обновляет прогресс пользователя"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        # Проверяем, есть ли уже запись
        cur.execute("""
            SELECT correct_answers FROM user_phrases 
            WHERE user_id = %s AND phrase_id = %s
        """, (user_id, phrase_id))

        existing = cur.fetchone()

        if existing:
            current_answers = existing[0]
            if is_correct:
                new_count = current_answers + 1
                # Фраза считается изученной после 3 правильных ответов
                is_learned = new_count >= 3
                cur.execute("""
                    UPDATE user_phrases 
                    SET correct_answers = %s, is_learned = %s
                    WHERE user_id = %s AND phrase_id = %s
                """, (new_count, is_learned, user_id, phrase_id))
            else:
                # При неправильном ответе сбрасываем прогресс, но не помечаем как изученную
                cur.execute("""
                    UPDATE user_phrases 
                    SET correct_answers = GREATEST(0, %s - 1), is_learned = FALSE
                    WHERE user_id = %s AND phrase_id = %s
                """, (current_answers, user_id, phrase_id))
        else:
            # Создаем новую запись
            if is_correct:
                cur.execute("""
                    INSERT INTO user_phrases (user_id, phrase_id, correct_answers, is_learned)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, phrase_id, 1, False))
            else:
                cur.execute("""
                    INSERT INTO user_phrases (user_id, phrase_id, correct_answers, is_learned)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, phrase_id, 0, False))

        conn.commit()

        # Логируем изменение прогресса
        cur.execute("""
            SELECT correct_answers, is_learned FROM user_phrases 
            WHERE user_id = %s AND phrase_id = %s
        """, (user_id, phrase_id))
        updated = cur.fetchone()
        if updated:
            print(f"📊 Прогресс обновлен: user_id={user_id}, phrase_id={phrase_id}, "
                  f"correct_answers={updated[0]}, is_learned={updated[1]}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Ошибка при обновлении прогресса: {e}")
    finally:
        cur.close()
        conn.close()


def add_custom_phrase(user_id, english_phrase, russian_translation):
    """Добавляет пользовательскую фразу"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        # Добавляем фразу в общую таблицу
        cur.execute("""
            INSERT INTO phrases (english_phrase, russian_translation, category, level)
            VALUES (%s, %s, 'custom', 'B1')
            ON CONFLICT (english_phrase, russian_translation) DO NOTHING
            RETURNING phrase_id
        """, (english_phrase, russian_translation))

        result = cur.fetchone()
        if result:
            phrase_id = result[0]
        else:
            # Если фраза уже существует, находим её ID
            cur.execute("""
                SELECT phrase_id FROM phrases 
                WHERE english_phrase = %s AND russian_translation = %s
            """, (english_phrase, russian_translation))
            result = cur.fetchone()
            phrase_id = result[0] if result else None

        if phrase_id:
            # Связываем фразу с пользователем
            cur.execute("""
                INSERT INTO user_phrases (user_id, phrase_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, phrase_id) DO NOTHING
            """, (user_id, phrase_id))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error adding custom phrase: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def delete_user_phrase(user_id, phrase_id):
    """Удаляет фразу из пользовательского набора"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM user_phrases 
        WHERE user_id = %s AND phrase_id = %s
    """, (user_id, phrase_id))

    conn.commit()
    cur.close()
    conn.close()


def get_user_phrase_count(user_id):
    """Возвращает количество фраз пользователя"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM user_phrases WHERE user_id = %s
    """, (user_id,))

    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def get_user_phrases_list(user_id, limit=50):
    """Возвращает список фраз пользователя для выбора при удалении"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT p.phrase_id, p.english_phrase, p.russian_translation, 
                   up.correct_answers, up.is_learned
            FROM user_phrases up
            JOIN phrases p ON up.phrase_id = p.phrase_id
            WHERE up.user_id = %s
            ORDER BY up.added_at DESC
            LIMIT %s
        """, (user_id, limit))

        phrases = cur.fetchall()
        columns = ['phrase_id', 'english_phrase', 'russian_translation', 'correct_answers', 'is_learned']
        
        cur.close()
        conn.close()
        
        return [
            row_to_dict(row, columns)
            for row in phrases
        ]
    except Exception as e:
        print(f"❌ Ошибка при получении списка фраз пользователя: {e}")
        cur.close()
        conn.close()
        return []


def get_learned_phrases_count(user_id):
    """Возвращает количество изученных фраз"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM user_phrases 
        WHERE user_id = %s AND is_learned = TRUE
    """, (user_id,))

    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def load_initial_phrases():
    """Загружает начальные фразы в базу данных"""
    initial_phrases = [
        ("How are you doing?", "Как твои дела?", "greetings", "A2"),
        ("What's up?", "Как дела? (неформально)", "greetings", "A2"),
        ("Long time no see.", "Давно не виделись.", "greetings", "A2"),
        ("I don't understand.", "Я не понимаю.", "communication", "A2"),
        ("Could you repeat that?", "Не могли бы вы повторить?", "communication", "A2"),
        ("What does this word mean?", "Что означает это слово?", "communication", "A2"),
        ("I agree with you.", "Я согласен с тобой.", "communication", "A2"),
        ("Let me think about it.", "Дай мне подумать об этом.", "communication", "A2"),
        ("In my opinion...", "По моему мнению...", "opinions", "A2"),
        ("That's a good idea.", "Это хорошая идея.", "opinions", "A2")
    ]

    conn = get_connection()
    cur = conn.cursor()

    phrases_loaded = 0
    for english_phrase, russian_translation, category, level in initial_phrases:
        try:
            cur.execute("""
                INSERT INTO phrases (english_phrase, russian_translation, category, level)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (english_phrase, russian_translation) DO NOTHING
            """, (english_phrase, russian_translation, category, level))

            if cur.rowcount > 0:
                phrases_loaded += 1

        except Exception as e:
            print(f"Ошибка при добавлении фразы '{english_phrase}': {e}")

    conn.commit()
    cur.close()
    conn.close()

    print(f"Загружено {phrases_loaded} начальных фраз")


def debug_user_progress(user_id):
    """Отладочная функция для просмотра прогресса пользователя"""
    conn = get_connection()
    cur = conn.cursor()

    print(f"🔍 ДЕБАГ: Прогресс пользователя {user_id}")
    print("=" * 60)

    try:
        # Все фразы пользователя
        cur.execute("""
            SELECT p.phrase_id, p.english_phrase, up.correct_answers, up.is_learned
            FROM user_phrases up
            JOIN phrases p ON up.phrase_id = p.phrase_id
            WHERE up.user_id = %s
            ORDER BY up.correct_answers DESC
        """, (user_id,))

        user_phrases = cur.fetchall()
        print(f"📚 Фраз пользователя: {len(user_phrases)}")

        for phrase_id, english_phrase, correct_answers, is_learned in user_phrases:
            status = "✅ ВЫУЧЕНА" if is_learned else f"📖 Учат ({correct_answers}/3)"
            print(f"   {phrase_id}. '{english_phrase}' - {status}")

        # Следующая фраза, которую получит пользователь
        next_phrase = get_random_phrase_for_user(user_id)
        if next_phrase:
            print(f"\n🎯 Следующая фраза: '{next_phrase['english_phrase']}'")
        else:
            print(f"\n❌ Не удалось получить следующую фразу")

    except Exception as e:
        print(f"❌ Ошибка при отладке: {e}")
    finally:
        cur.close()
        conn.close()


def debug_phrases():
    """Функция для отладки - показывает случайные фразы"""
    conn = get_connection()
    cur = conn.cursor()

    print("🔍 ДЕБАГ: Проверка случайных фраз")

    # Получаем 5 случайных фраз
    cur.execute("""
        SELECT english_phrase, russian_translation 
        FROM phrases 
        ORDER BY RANDOM() 
        LIMIT 5
    """)

    phrases = cur.fetchall()
    print("📝 Случайные фразы из базы:")
    for i, (eng, rus) in enumerate(phrases, 1):
        print(f"   {i}. '{eng}' -> '{rus}'")

    cur.close()
    conn.close()


if __name__ == "__main__":
    debug_phrases()