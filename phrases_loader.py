import csv
import os
import psycopg2
from config import DATABASE_URL


def find_csv_file():
    """Поиск CSV файла в различных возможных местах"""
    possible_paths = [
        "data/english_phrases.csv",
        "english_phrases.csv",
        "phrases.csv",
        "data/phrases.csv",
        "../data/english_phrases.csv",
        "C:/Users/Admin/EnglishCards_Bot/data/english_phrases.csv"
    ]

    for path in possible_paths:
        if os.path.exists(path):
            print(f"✅ Файл найден: {path}")
            return path

    print("❌ CSV файл не найден. Проверьте следующие места:")
    for path in possible_paths:
        print(f"   📍 {path}")

    return None


def preview_csv_file(csv_file_path):
    """Предпросмотр CSV файла"""
    print(f"\n🔍 Анализ файла: {csv_file_path}")

    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            # Пробуем разные кодировки
            for encoding in ['utf-8', 'utf-8-sig', 'cp1251']:
                try:
                    file.seek(0)
                    content = file.read(1024)
                    file.seek(0)

                    # Определяем разделитель
                    for delimiter in [',', ';', '\t']:
                        if delimiter in content:
                            break
                    else:
                        delimiter = ','

                    reader = csv.DictReader(file, delimiter=delimiter)
                    fieldnames = reader.fieldnames

                    print(f"✅ Кодировка: {encoding}")
                    print(f"✅ Разделитель: '{delimiter}'")
                    print(f"✅ Колонки: {fieldnames}")

                    # Читаем первые 2 строки для предпросмотра
                    print("\n📋 Первые 2 строки:")
                    file.seek(0)
                    reader = csv.DictReader(file, delimiter=delimiter)

                    for i, row in enumerate(reader):
                        if i >= 2:
                            break
                        print(f"Строка {i + 1}:")
                        for key, value in row.items():
                            print(f"   {key}: '{value}'")
                        print()

                    return fieldnames, delimiter, encoding

                except UnicodeDecodeError:
                    continue

        return None, ',', 'utf-8'

    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
        return None, ',', 'utf-8'


def load_phrases_from_csv(csv_file_path):
    """Загрузка фраз из CSV файла в базу данных"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    phrases_loaded = 0
    errors = 0

    # Анализ файла
    fieldnames, delimiter, encoding = preview_csv_file(csv_file_path)

    if not fieldnames:
        print("❌ Не удалось прочитать CSV файл")
        return

    print("=" * 60)

    try:
        with open(csv_file_path, 'r', encoding=encoding) as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            total_rows = 0

            for row_num, row in enumerate(reader, 1):
                total_rows = row_num
                try:
                    # Обрабатываем разные возможные названия колонок
                    english_phrase = (
                        row.get('phrase') or row.get('english') or
                        row.get('english_phrase') or row.get('English') or
                        list(row.values())[0] if row else ''
                    )

                    russian_translation = (
                        row.get('correct') or row.get('russian') or
                        row.get('translation') or row.get('Russian') or
                        row.get(' correct') or  # с пробелом!
                        list(row.values())[1] if len(row.values()) > 1 else ''
                    )

                    # Очистка данных
                    english_phrase = str(english_phrase).strip()
                    russian_translation = str(russian_translation).strip()

                    # Пропускаем пустые строки
                    if not english_phrase or not russian_translation:
                        continue

                    # Добавляем фразу в базу
                    cur.execute("""
                        INSERT INTO phrases (english_phrase, russian_translation, category, level)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (english_phrase, russian_translation) DO NOTHING
                    """, (english_phrase, russian_translation, 'general', 'A2'))

                    if cur.rowcount > 0:
                        phrases_loaded += 1
                        if phrases_loaded <= 3:  # Показываем первые 3 для подтверждения
                            print(f"✅ [{phrases_loaded}] '{english_phrase}' -> '{russian_translation}'")

                except Exception as e:
                    errors += 1
                    if errors <= 2:  # Показываем только первые 2 ошибки
                        print(f"❌ Ошибка в строке {row_num}: {e}")
                    continue

        conn.commit()

        print("\n" + "=" * 60)
        print(f"📊 РЕЗУЛЬТАТ:")
        print(f"✅ Успешно загружено: {phrases_loaded} фраз")
        print(f"📁 Обработано строк: {total_rows}")
        print(f"❌ Ошибок: {errors}")

        if phrases_loaded == 0:
            print("\n💡 ВОЗМОЖНЫЕ ПРИЧИНЫ:")
            print("   • Фразы уже есть в базе данных")
            print("   • Неправильный формат CSV файла")
            print("   • Проблемы с кодировкой файла")
            print("   • Несоответствие названий колонок")

    except Exception as e:
        conn.rollback()
        print(f"❌ Критическая ошибка: {e}")
    finally:
        cur.close()
        conn.close()


def check_database_phrases():
    """Проверка фраз уже находящихся в базе"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM phrases")
        count = cur.fetchone()[0]
        print(f"\n📊 В базе данных сейчас: {count} фраз")

        if count > 0:
            cur.execute("SELECT english_phrase, russian_translation FROM phrases LIMIT 3")
            print("📝 Примеры фраз в базе:")
            for eng, rus in cur.fetchall():
                print(f"   '{eng}' -> '{rus}'")

    except Exception as e:
        print(f"❌ Ошибка при проверке базы: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("🚀 Загрузчик фраз EnglishCard Bot")
    print("=" * 60)

    # Проверяем базу данных
    check_database_phrases()

    # Ищем CSV файл
    csv_path = find_csv_file()

    if csv_path:
        print(f"\n🎯 Загружаем фразы из: {csv_path}")
        load_phrases_from_csv(csv_path)
    else:
        print("\n❌ Файл не найден. Создайте файл data/english_phrases.csv")
        print("💡 Или укажите правильный путь к файлу в коде")