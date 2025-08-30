import asyncio
import os

from aiogram import Bot
from dotenv import load_dotenv


async def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    bot = Bot(token)
    info = await bot.get_webhook_info()
    print("Before:", info)
    await bot.delete_webhook(drop_pending_updates=True)
    info2 = await bot.get_webhook_info()
    print("After:", info2)


if __name__ == "__main__":
    asyncio.run(main())

