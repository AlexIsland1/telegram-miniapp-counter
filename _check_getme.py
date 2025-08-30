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
    me = await bot.get_me()
    print("GETME_OK", me.id, me.username)


if __name__ == "__main__":
    asyncio.run(main())

