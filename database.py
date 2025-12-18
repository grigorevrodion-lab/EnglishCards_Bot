import re
import pg8000
from config import DATABASE_URL

LEARNED_THRESHOLD = 3


def parse_database_url(url: str) -> dict:
    """Парсит DATABASE_URL для pg8000."""
    pattern = r"postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)"
    match = re.match(pattern, url)

    if not match:
        raise RuntimeError(f"Неверный формат DATABASE_URL: {url}")

    username, password, host, port, database = match.groups()
    return {
        "user": username,
        "password": password,
        "host": host,
        "port": int(port),
        "database": database,
    }


def get_connection():
    """Создаёт соединение с базой данных."""
    db_config = parse_database_url(DATABASE_URL)

    try:
        return pg8000.connect(**db_config)
    except pg8000.Error as exc:
        raise RuntimeError("Ошибка подключения к базе данных") from exc


def row_to_dict(row, columns):
    """Преобразует строку БД в словарь."""
    return {columns[i]: row[i] for i in range(len(columns))}


def init_db():
    """Инициализация базы данных."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(100),
            first_name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS phrases (
            phrase_id SERIAL PRIMARY KEY,
            english_phrase TEXT NOT NULL,
            russian_translation TEXT NOT NULL,
            category VARCHAR(100),
            level VARCHAR(10),
            example TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (english_phrase, russian_translation)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_phrases (
            user_phrase_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            phrase_id INTEGER REFERENCES phrases(phrase_id) ON DELETE CASCADE,
            correct_answers INTEGER DEFAULT 0,
            is_learned BOOLEAN DEFAULT FALSE,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, phrase_id)
        )
        """
    )

    conn.commit()
    cur.close()
    conn.close()


def add_user(user_id, username, first_name):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (user_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id, username, first_name),
    )

    conn.commit()
    cur.close()
    conn.close()


def get_random_phrase_for_user(user_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT p.phrase_id, p.english_phrase, p.russian_translation
            FROM phrases p
            JOIN user_phrases up ON p.phrase_id = up.phrase_id
            WHERE up.user_id = %s AND up.is_learned = FALSE
            ORDER BY up.correct_answers ASC, RANDOM()
            LIMIT 1
            """,
            (user_id,),
        )

        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                SELECT phrase_id, english_phrase, russian_translation
                FROM phrases
                ORDER BY RANDOM()
                LIMIT 1
                """
            )
            row = cur.fetchone()

        return (
            row_to_dict(
                row,
                ["phrase_id", "english_phrase", "russian_translation"],
            )
            if row
            else None
        )

    finally:
        cur.close()
        conn.close()


def get_wrong_phrases(correct_phrase_id, user_id, limit=3):
    """Возвращает уникальные неправильные варианты."""
    conn = get_connection()
    cur = conn.cursor()

    try:
        # Получаем больше вариантов, чтобы гарантировать уникальность
        cur.execute(
            """
            SELECT phrase_id, english_phrase, russian_translation
            FROM phrases
            WHERE phrase_id != %s
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (correct_phrase_id, limit * 3),  # Увеличиваем лимит
        )

        rows = cur.fetchall()
        seen_ids = set()
        seen_texts = set()
        result = []

        for row in rows:
            phrase_id = row[0]
            english_text = row[1].lower().strip()

            # Проверяем уникальность по ID и тексту
            if phrase_id in seen_ids or english_text in seen_texts:
                continue

            seen_ids.add(phrase_id)
            seen_texts.add(english_text)
            result.append(
                row_to_dict(
                    row,
                    ["phrase_id", "english_phrase", "russian_translation"],
                )
            )
            if len(result) == limit:
                break

        return result

    finally:
        cur.close()
        conn.close()


def update_user_progress(user_id, phrase_id, is_correct):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT correct_answers
            FROM user_phrases
            WHERE user_id = %s AND phrase_id = %s
            """,
            (user_id, phrase_id),
        )

        row = cur.fetchone()
        current = row[0] if row else 0

        current = current + 1 if is_correct else max(0, current - 1)
        is_learned = current >= LEARNED_THRESHOLD

        cur.execute(
            """
            INSERT INTO user_phrases (user_id, phrase_id, correct_answers, is_learned)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, phrase_id)
            DO UPDATE SET correct_answers = %s, is_learned = %s
            """,
            (
                user_id,
                phrase_id,
                current,
                is_learned,
                current,
                is_learned,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def add_custom_phrase(user_id, english_phrase, russian_translation):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO phrases (english_phrase, russian_translation, category, level)
            VALUES (%s, %s, 'custom', 'B1')
            ON CONFLICT (english_phrase, russian_translation) DO NOTHING
            RETURNING phrase_id
            """,
            (english_phrase, russian_translation),
        )

        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                SELECT phrase_id
                FROM phrases
                WHERE english_phrase = %s AND russian_translation = %s
                """,
                (english_phrase, russian_translation),
            )
            row = cur.fetchone()

        if row:
            cur.execute(
                """
                INSERT INTO user_phrases (user_id, phrase_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, phrase_id) DO NOTHING
                """,
                (user_id, row[0]),
            )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def delete_user_phrase(user_id, phrase_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM user_phrases
        WHERE user_id = %s AND phrase_id = %s
        """,
        (user_id, phrase_id),
    )

    conn.commit()
    cur.close()
    conn.close()


def get_user_phrase_count(user_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM user_phrases WHERE user_id = %s",
        (user_id,),
    )

    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def get_learned_phrases_count(user_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM user_phrases
        WHERE user_id = %s AND is_learned = TRUE
        """,
        (user_id,),
    )

    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def load_initial_phrases():
    """Загружает начальные фразы в БД при запуске."""
    from phrases_loader import find_csv_file, load_phrases_from_csv

    csv_path = find_csv_file()
    if csv_path:
        print(f"🎯 Загружаем фразы из: {csv_path}")
        load_phrases_from_csv(csv_path)
    else:
        print("⚠️ CSV файл не найден, продолжаем без загрузки фраз")


def debug_user_progress(user_id):
    """Отладочная информация о прогрессе пользователя."""
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT p.phrase_id, p.english_phrase, up.correct_answers, up.is_learned
            FROM user_phrases up
            JOIN phrases p ON up.phrase_id = p.phrase_id
            WHERE up.user_id = %s
            ORDER BY up.correct_answers DESC
            LIMIT 5
            """,
            (user_id,),
        )

        rows = cur.fetchall()
        print(f"\n📊 Отладка прогресса для пользователя {user_id}:")
        for row in rows:
            print(f"  Фраза: {row[1]} | Ответов: {row[2]} | Изучено: {row[3]}")
    finally:
        cur.close()
        conn.close()