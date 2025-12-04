from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from database import get_connection  # Используем нашу функцию подключения
from telebot import TeleBot
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReminderSystem:
    def __init__(self, bot: TeleBot):
        self.bot = bot
        self.scheduler = BackgroundScheduler()
        self.setup_reminders()

    def get_all_users(self):
        """Получает список всех пользователей бота"""
        conn = get_connection()
        cur = conn.cursor()

        try:
            cur.execute("SELECT user_id FROM users")
            users = [row[0] for row in cur.fetchall()]
            return users
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей: {e}")
            return []
        finally:
            cur.close()
            conn.close()

    def get_user_stats(self, user_id):
        """Получает статистику пользователя"""
        conn = get_connection()  # ИСПРАВЛЕНО: убрали self.
        cur = conn.cursor()

        try:
            # Количество изучаемых фраз
            cur.execute("SELECT COUNT(*) FROM user_phrases WHERE user_id = %s", (user_id,))
            total_phrases = cur.fetchone()[0]

            return total_phrases
        except Exception as e:
            logger.error(f"Ошибка при получении статистики пользователя {user_id}: {e}")
            return 0
        finally:
            cur.close()
            conn.close()

    def send_daily_reminder(self):
        """Отправляет ежедневное напоминание всем пользователям"""
        users = self.get_all_users()
        logger.info(f"Отправка напоминаний для {len(users)} пользователей")

        for user_id in users:
            try:
                total_phrases = self.get_user_stats(user_id)

                if total_phrases > 0:
                    message = f"📚 *Напоминание от EnglishCard!*\n\n" \
                             f"Пришло время повторить английские фразы! 🎯\n\n" \
                             f"В вашем словаре: *{total_phrases}* фраз\n" \
                             f"Не забудьте позаниматься сегодня! 💪\n\n" \
                             f"*/start* - начать занятие"
                else:
                    message = f"👋 *Привет! Это EnglishCard!*\n\n" \
                             f"Вы еще не начали изучать английские фразы.\n" \
                             f"Самое время начать! 🚀\n\n" \
                             f"*/start* - начать изучение"

                self.bot.send_message(user_id, message, parse_mode='Markdown')
                logger.info(f"Напоминание отправлено пользователю {user_id}")

            except Exception as e:
                # Игнорируем ошибки "bot was blocked by user" и подобные
                if "bot was blocked" not in str(e).lower() and "chat not found" not in str(e).lower():
                    logger.error(f"Не удалось отправить напоминание пользователю {user_id}: {e}")

    def send_motivational_reminder(self):
        """Отправляет мотивационное напоминание"""
        users = self.get_all_users()

        for user_id in users:
            try:
                total_phrases = self.get_user_stats(user_id)

                if total_phrases > 0:
                    message = f"🌟 *Мотивация от EnglishCard!*\n\n" \
                             f"Регулярность - ключ к успеху в изучении языка! 📈\n\n" \
                             f"Вы уже изучаете: *{total_phrases}* фраз\n" \
                             f"Продолжайте в том же духе! 🎉\n\n" \
                             f"*/start* - продолжить занятие"

                    self.bot.send_message(user_id, message, parse_mode='Markdown')

            except Exception as e:
                if "bot was blocked" not in str(e).lower() and "chat not found" not in str(e).lower():
                    logger.error(f"Не удалось отправить мотивационное напоминание пользователю {user_id}: {e}")

    def setup_reminders(self):
        """Настраивает расписание напоминаний"""
        try:
            # Ежедневное напоминание в 19:00
            self.scheduler.add_job(
                self.send_daily_reminder,
                trigger=CronTrigger(hour=19, minute=0),  # 19:00 каждый день
                id='daily_reminder',
                name='Ежедневное напоминание о занятиях'
            )

            # Мотивационное напоминание в субботу в 12:00
            self.scheduler.add_job(
                self.send_motivational_reminder,
                trigger=CronTrigger(day_of_week='sat', hour=12, minute=0),  # Суббота 12:00
                id='weekly_motivation',
                name='Еженедельное мотивационное напоминание'
            )

            # Для тестирования - раскомментируйте следующие строки:
            # self.scheduler.add_job(
            #     self.send_daily_reminder,
            #     trigger='interval',
            #     minutes=2,
            #     id='test_reminder',
            #     name='Тестовое напоминание'
            # )

            logger.info("⏰ Система напоминаний настроена!")

        except Exception as e:
            logger.error(f"Ошибка при настройке напоминаний: {e}")

    def start(self):
        """Запускает систему напоминаний"""
        try:
            self.scheduler.start()
            logger.info("🚀 Система напоминаний запущена!")
        except Exception as e:
            logger.error(f"Ошибка при запуске системы напоминаний: {e}")

    def shutdown(self):
        """Останавливает систему напоминаний"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("🛑 Система напоминаний остановлена")