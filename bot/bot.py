import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
import aiohttp
import json
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")


async def get_card_for_study(user_id: int, card_id: str) -> dict:
    """Get card details for study via API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{APP_URL}/api/cards/{card_id}",
                json={"user_id": user_id},
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("ok"):
                        return result.get("card")
                return None
    except Exception as e:
        logging.error(f"Error getting card {card_id} for user {user_id}: {e}")
        return None


async def submit_card_quality(user_id: int, card_id: str, quality: int) -> bool:
    """Submit card quality rating via API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{APP_URL}/api/cards/{card_id}/review",
                json={"user_id": user_id, "quality": quality},
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("ok", False)
                return False
    except Exception as e:
        logging.error(f"Error submitting quality for card {card_id}: {e}")
        return False


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

    @dp.message(Command("load_words"))
    async def on_load_words(message: types.Message):
        """Load words from new_words.json file via API"""
        try:
            user_id = message.from_user.id
            logging.info("LOAD_WORDS command from user_id=%s", user_id)
            
            # Send loading message
            loading_msg = await message.answer("⏳ Загружаю слова из файла...")
            
            # Prepare API request data
            api_data = {
                "user_id": user_id
            }
            
            # Make request to bulk create API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{APP_URL}/api/cards/bulk",
                    json=api_data,
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("ok"):
                            created = result.get("created", 0)
                            total = result.get("total_processed", 0)
                            skipped = result.get("skipped", 0)
                            
                            await loading_msg.edit_text(
                                f"✅ Успешно загружено!\n\n"
                                f"📥 Создано новых карточек: {created}\n"
                                f"📊 Всего обработано: {total}\n"
                                f"⏭️ Пропущено дубликатов: {skipped}\n\n"
                                f"Теперь можете изучать новые слова! 🚀"
                            )
                        else:
                            error = result.get("error", "неизвестная ошибка")
                            await loading_msg.edit_text(f"❌ Ошибка API: {error}")
                    else:
                        await loading_msg.edit_text(f"❌ Ошибка сервера: HTTP {resp.status}")
                        
        except aiohttp.ClientError as e:
            logging.error("LOAD_WORDS network error: %s", e)
            await message.answer("❌ Ошибка сети. Проверьте подключение к серверу.")
        except Exception as e:
            logging.exception("LOAD_WORDS error: %s", e)
            await message.answer("❌ Произошла ошибка при загрузке слов.")

    @dp.message(Command("notifications"))
    async def on_notifications(message: types.Message):
        """Manage notification settings"""
        try:
            user_id = message.from_user.id
            
            # Get current settings
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{APP_URL}/api/settings",
                    json={"user_id": user_id},
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("ok"):
                            settings = result["settings"]
                            enabled = settings["notifications_enabled"]
                            time_str = settings["study_reminder_time"]
                            
                            status = "✅ Включены" if enabled else "❌ Отключены"
                            
                            await message.answer(
                                f"🔔 <b>Настройки уведомлений</b>\n\n"
                                f"Статус: {status}\n"
                                f"Время: {time_str}\n\n"
                                f"Команды:\n"
                                f"📅 <code>/set_time HH:MM</code> - изменить время\n"
                                f"🔕 <code>/notifications_off</code> - отключить\n"
                                f"🔔 <code>/notifications_on</code> - включить",
                                parse_mode="HTML"
                            )
                        else:
                            await message.answer("❌ Ошибка получения настроек")
                    else:
                        await message.answer("❌ Ошибка сервера")
                        
        except Exception as e:
            logging.exception("NOTIFICATIONS error: %s", e)
            await message.answer("❌ Произошла ошибка")

    @dp.message(Command("set_time"))
    async def on_set_time(message: types.Message):
        """Set notification time"""
        try:
            # Parse time from command
            args = message.text.split()
            if len(args) < 2:
                await message.answer(
                    "⏰ Укажите время в формате HH:MM\n"
                    "Пример: <code>/set_time 09:30</code>",
                    parse_mode="HTML"
                )
                return
            
            time_str = args[1]
            
            # Validate time format
            try:
                datetime.strptime(time_str, '%H:%M')
            except ValueError:
                await message.answer("❌ Неверный формат времени. Используйте HH:MM (например: 09:30)")
                return
            
            user_id = message.from_user.id
            
            # Update settings
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{APP_URL}/api/settings",
                    json={
                        "user_id": user_id,
                        "study_reminder_time": time_str,
                        "notifications_enabled": True
                    },
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("ok"):
                            await message.answer(f"✅ Время напоминаний установлено на {time_str}")
                        else:
                            await message.answer("❌ Ошибка обновления настроек")
                    else:
                        await message.answer("❌ Ошибка сервера")
                        
        except Exception as e:
            logging.exception("SET_TIME error: %s", e)
            await message.answer("❌ Произошла ошибка")

    @dp.message(Command("notifications_on"))
    async def on_notifications_on(message: types.Message):
        """Enable notifications"""
        await _toggle_notifications(message, True)

    @dp.message(Command("notifications_off"))
    async def on_notifications_off(message: types.Message):
        """Disable notifications"""
        await _toggle_notifications(message, False)

    async def _toggle_notifications(message: types.Message, enabled: bool):
        """Helper to toggle notifications"""
        try:
            user_id = message.from_user.id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{APP_URL}/api/settings",
                    json={
                        "user_id": user_id,
                        "notifications_enabled": enabled
                    },
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("ok"):
                            status = "включены" if enabled else "отключены"
                            emoji = "🔔" if enabled else "🔕"
                            await message.answer(f"{emoji} Уведомления {status}")
                        else:
                            await message.answer("❌ Ошибка обновления настроек")
                    else:
                        await message.answer("❌ Ошибка сервера")
                        
        except Exception as e:
            logging.exception("TOGGLE_NOTIFICATIONS error: %s", e)
            await message.answer("❌ Произошла ошибка")

    @dp.callback_query(F.data.startswith("study_card_"))
    async def on_study_card(callback: types.CallbackQuery):
        """Handle study card button clicks"""
        try:
            await callback.answer()
            
            # Extract card ID from callback data
            card_id = callback.data.split("_")[-1]
            user_id = callback.from_user.id
            
            logging.info("STUDY_CARD callback from user_id=%s card_id=%s", user_id, card_id)
            
            # Get card details
            card_data = await get_card_for_study(user_id, card_id)
            
            if not card_data:
                await callback.message.edit_text("❌ Карточка не найдена или недоступна")
                return
            
            # Create study interface
            study_message = f"""📖 <b>Изучение карточки</b>

<b>Слово:</b> <code>{card_data['front']}</code>

🤔 <i>Попробуйте вспомнить перевод, затем нажмите "Показать ответ"</i>"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👁‍🗨 Показать ответ", callback_data=f"show_answer_{card_id}")],
                [InlineKeyboardButton(text="📚 Открыть все карточки", url=f"{APP_URL}/study.html")]
            ])
            
            await callback.message.edit_text(study_message, parse_mode="HTML", reply_markup=keyboard)
            
        except Exception as e:
            logging.exception("STUDY_CARD callback error: %s", e)
            await callback.message.edit_text("❌ Произошла ошибка при загрузке карточки")
    
    @dp.callback_query(F.data.startswith("show_answer_"))
    async def on_show_answer(callback: types.CallbackQuery):
        """Show answer and quality buttons"""
        try:
            await callback.answer()
            
            card_id = callback.data.split("_")[-1]
            user_id = callback.from_user.id
            
            # Get card details
            card_data = await get_card_for_study(user_id, card_id)
            
            if not card_data:
                await callback.message.edit_text("❌ Карточка не найдена")
                return
            
            answer_message = f"""📖 <b>Карточка с ответом</b>

<b>Слово:</b> <code>{card_data['front']}</code>
<b>Перевод:</b> <i>{card_data['back']}</i>

❓ <b>Насколько хорошо вы помните эту карточку?</b>"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="😞 Плохо (1)", callback_data=f"quality_{card_id}_1"),
                    InlineKeyboardButton(text="🤔 Слабо (2)", callback_data=f"quality_{card_id}_2")
                ],
                [
                    InlineKeyboardButton(text="😐 Нормально (3)", callback_data=f"quality_{card_id}_3"),
                    InlineKeyboardButton(text="😊 Хорошо (4)", callback_data=f"quality_{card_id}_4")
                ],
                [
                    InlineKeyboardButton(text="🎯 Отлично (5)", callback_data=f"quality_{card_id}_5")
                ],
                [
                    InlineKeyboardButton(text="📚 Все карточки", url=f"{APP_URL}/study.html")
                ]
            ])
            
            await callback.message.edit_text(answer_message, parse_mode="HTML", reply_markup=keyboard)
            
        except Exception as e:
            logging.exception("SHOW_ANSWER callback error: %s", e)
            await callback.message.edit_text("❌ Произошла ошибка")
    
    @dp.callback_query(F.data.startswith("quality_"))
    async def on_quality_rating(callback: types.CallbackQuery):
        """Handle quality rating submission"""
        try:
            await callback.answer("✅ Оценка сохранена!")
            
            # Parse callback data
            parts = callback.data.split("_")
            card_id = parts[1]
            quality = int(parts[2])
            user_id = callback.from_user.id
            
            logging.info("QUALITY_RATING from user_id=%s card_id=%s quality=%s", user_id, card_id, quality)
            
            # Submit quality rating via API
            success = await submit_card_quality(user_id, card_id, quality)
            
            if success:
                quality_text = ["", "😞 Плохо", "🤔 Слабо", "😐 Нормально", "😊 Хорошо", "🎯 Отлично"][quality]
                
                final_message = f"""✅ <b>Карточка изучена!</b>

<b>Ваша оценка:</b> {quality_text}

🎉 <i>Отлично! Карточка добавлена в систему интервального повторения. Увидимся в следующий раз!</i>

📚 Продолжайте изучение в приложении."""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📚 Изучать дальше", url=f"{APP_URL}/study.html")]
                ])
                
                await callback.message.edit_text(final_message, parse_mode="HTML", reply_markup=keyboard)
            else:
                await callback.message.edit_text("❌ Ошибка при сохранении оценки. Попробуйте позже.")
            
        except Exception as e:
            logging.exception("QUALITY_RATING error: %s", e)
            await callback.message.edit_text("❌ Произошла ошибка при сохранении оценки")

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
