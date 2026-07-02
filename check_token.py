import os

from dotenv import load_dotenv


load_dotenv()
token = os.getenv("BOT_TOKEN")
admin_chat_id = os.getenv("ADMIN_CHAT_ID")

if not token:
    print("BOT_TOKEN не знайдено. Перевірте файл .env")
elif token == "put_your_telegram_bot_token_here":
    print("BOT_TOKEN знайдено, але зараз там тестова заглушка.")
    print("Відкрийте файл .env і вставте справжній токен після BOT_TOKEN=")
else:
    hidden_token = token[:6] + "..." + token[-4:]
    print("BOT_TOKEN знайдено.")
    print(f"Бот зможе прочитати токен: {hidden_token}")

if admin_chat_id:
    print(f"ADMIN_CHAT_ID налаштовано: {admin_chat_id}")
else:
    print("ADMIN_CHAT_ID не налаштовано. Адмін-сповіщення поки не надсилатимуться.")
    print("Щоб дізнатися свій ID, напишіть боту команду /myid")
