import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")


async def main():
    # Configure logging to console + file
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(logs_dir, 'bot.log'), maxBytes=2_000_000, backupCount=2, encoding='utf-8')
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logging.getLogger().addHandler(fh)
        logging.info('Bot file logging configured: %s', fh.baseFilename)
    except Exception:
        pass

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    logging.info("APP_URL=%s (https=%s)", APP_URL, str(APP_URL).startswith("https://"))

    @dp.message(CommandStart())
    async def on_start(message: types.Message):
        try:
            logging.info("/start from id=%s username=%s", message.from_user.id, message.from_user.username)
            text = "Нажми кнопку, чтобы открыть мини‑приложение со счётчиком."
            
            if APP_URL and APP_URL.startswith("https://"):
                # Use inline keyboard with WebApp button
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🚀 Открыть мини‑приложение", web_app=WebAppInfo(url=APP_URL))
                ]])
                try:
                    await message.answer(text, reply_markup=kb)
                    return
                except TelegramBadRequest as e:
                    logging.warning("inline web_app button failed: %s", e)

            # Fallback for non-HTTPS APP_URL: use callback button
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🚀 Получить ссылку", callback_data="get_link")
            ]])
            await message.answer(
                "Нажми кнопку, чтобы получить ссылку на мини‑приложение.",
                reply_markup=kb
            )
        except Exception as e:
            logging.exception("/start handler failed: %s", e)

    @dp.callback_query(F.data == "get_link")
    async def on_get_link(callback: types.CallbackQuery):
        try:
            await callback.answer()
            await callback.message.answer(
                f"🚀 Мини‑приложение:\n{APP_URL or 'http://localhost:8000'}\n\n"
                "💡 Нажми на ссылку выше, чтобы открыть приложение в браузере."
            )
            logging.info("Link sent to user id=%s", callback.from_user.id)
        except Exception as e:
            logging.exception("get_link callback failed: %s", e)

    @dp.message(Command("health"))
    async def on_health(message: types.Message):
        await message.answer("ok: polling active")

    # Ensure polling works (remove webhook if previously set)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook deleted (drop_pending_updates=True)")
    except Exception as e:
        logging.warning("delete_webhook failed: %s", e)

    logging.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
