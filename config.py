import os
from dotenv import load_dotenv

load_dotenv()

# Получаем переменные окружения с проверкой
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
YA_DICTIONARY_API_KEY = os.getenv("YA_DICTIONARY_API_KEY")

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен в .env файле")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не установлен в .env файле")


def debug_config():
    """Отладочная информация о конфигурации"""
    print("=== CONFIG DEBUG ===")
    print(f"BOT_TOKEN: {'✅ SET' if BOT_TOKEN else '❌ NOT SET'}")
    print(f"DATABASE_URL: {'✅ SET' if DATABASE_URL else '❌ NOT SET'}")
    print(
        f"YA_API_KEY: {'✅ SET' if YA_DICTIONARY_API_KEY else '⚠️ NOT SET (опционально)'}"
    )


if __name__ == "__main__":
    debug_config()