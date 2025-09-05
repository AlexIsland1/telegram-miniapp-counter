#!/usr/bin/env python3
"""
Spaced Repetition Scheduler
Фоновая служба для отправки напоминаний о изучении карточек
"""

import asyncio
import logging
import sqlite3
import json
import os
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DB_PATH = os.path.join(os.path.dirname(__file__), "webapp", "counter.db")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHECK_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "3600"))  # Check every hour by default (configurable)
LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "scheduler.log")

# Ensure logs directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class UserReminder:
    """User reminder data"""
    user_id: int
    due_count: int
    new_count: int
    last_reminder: Optional[datetime]
    reminder_time: str
    notifications_enabled: bool


class SpacedRepetitionScheduler:
    """Scheduler for spaced repetition reminders"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        
    async def start(self):
        """Start the scheduler"""
        logger.info("Starting Spaced Repetition Scheduler...")
        self.running = True
        self.session = aiohttp.ClientSession()
        
        try:
            await self._run_scheduler()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the scheduler"""
        logger.info("Stopping scheduler...")
        self.running = False
        if self.session:
            await self.session.close()
    
    async def _run_scheduler(self):
        """Main scheduler loop"""
        logger.info(f"Scheduler running, checking every {CHECK_INTERVAL} seconds")
        
        while self.running:
            try:
                await self._check_and_send_reminders()
                await asyncio.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _check_and_send_reminders(self):
        """Check for users needing reminders and send them"""
        logger.info("Checking for users needing reminders...")
        users_to_remind = self._get_users_needing_reminders()
        
        if not users_to_remind:
            logger.info("No users need reminders at this time")
            return
        
        logger.info(f"Found {len(users_to_remind)} users needing reminders")
        
        for user in users_to_remind:
            try:
                await self._send_reminder(user)
                self._update_last_reminder(user.user_id)
                logger.info(f"Sent reminder to user {user.user_id}")
            except Exception as e:
                logger.error(f"Failed to send reminder to user {user.user_id}: {e}")
    
    def _get_users_needing_reminders(self) -> List[UserReminder]:
        """Get users who have cards due for review TODAY (Spaced Repetition logic)"""
        current_date = date.today().isoformat()
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                
                # Database diagnostics
                total_users = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()['count']
                total_cards = conn.execute("SELECT COUNT(*) as count FROM cards").fetchone()['count']
                total_sessions = conn.execute("SELECT COUNT(*) as count FROM study_sessions").fetchone()['count']
                
                logger.info(f"DATABASE: {total_users} users, {total_cards} cards, {total_sessions} sessions")
                
                # Get users who have cards due TODAY or new cards to study
                users = conn.execute("""
                    SELECT DISTINCT u.user_id,
                           COALESCE(us.notifications_enabled, 1) as notifications_enabled
                    FROM users u
                    LEFT JOIN user_settings us ON u.user_id = us.user_id
                    WHERE COALESCE(us.notifications_enabled, 1) = 1
                    AND (
                        -- User has cards due today
                        EXISTS (
                            SELECT 1 FROM cards c
                            JOIN study_sessions s ON c.id = s.card_id
                            WHERE c.user_id = u.user_id 
                            AND s.next_review_date <= ?
                            AND s.id = (SELECT MAX(id) FROM study_sessions WHERE card_id = c.id)
                        )
                        OR
                        -- User has new cards (never studied)
                        EXISTS (
                            SELECT 1 FROM cards c
                            LEFT JOIN study_sessions s ON c.id = s.card_id
                            WHERE c.user_id = u.user_id AND s.card_id IS NULL
                        )
                    )
                """, (current_date,)).fetchall()
                
                logger.info(f"Found {len(users)} users with cards due today or new cards")
                
                users_to_remind = []
                
                for user_row in users:
                    user_id = user_row['user_id']
                    
                    # Skip if notifications disabled
                    if not user_row['notifications_enabled']:
                        continue
                    
                    # Check if already reminded today (avoid spam)
                    if self._was_reminded_today(user_id):
                        logger.info(f"User {user_id} already reminded today, skipping")
                        continue
                    
                    # Get due and new card counts
                    due_count = self._get_due_cards_count(conn, user_id, current_date)
                    new_count = self._get_new_cards_count(conn, user_id)
                    
                    logger.info(f"User {user_id}: {due_count} due cards, {new_count} new cards")
                    
                    # Only remind if there are cards to study
                    if due_count > 0 or new_count > 0:
                        users_to_remind.append(UserReminder(
                            user_id=user_id,
                            due_count=due_count,
                            new_count=new_count,
                            last_reminder=None,
                            reminder_time="any_time",  # Spaced repetition doesn't depend on time
                            notifications_enabled=True
                        ))
                
                return users_to_remind
                
        except Exception as e:
            logger.error(f"Error getting users for reminders: {e}")
            return []
    
    # NOTE: Time-based reminders removed - Spaced Repetition works by card due dates, not time
    
    def _was_reminded_today(self, user_id: int) -> bool:
        """Check if user was already reminded today"""
        try:
            reminder_file = os.path.join(os.path.dirname(__file__), "logs", "reminders.log")
            today_str = date.today().isoformat()
            
            if not os.path.exists(reminder_file):
                return False
            
            with open(reminder_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if f"{today_str}:{user_id}" in line:
                        return True
            return False
            
        except Exception as e:
            logger.error(f"Error checking reminder history: {e}")
            return False
    
    def _get_due_cards_count(self, conn: sqlite3.Connection, user_id: int, current_date: str) -> int:
        """Get count of cards due for review"""
        result = conn.execute("""
            SELECT COUNT(DISTINCT c.id) as count
            FROM cards c
            JOIN study_sessions s ON c.id = s.card_id
            WHERE c.user_id = ? AND s.next_review_date <= ?
            AND s.id IN (
                SELECT MAX(id) FROM study_sessions 
                WHERE card_id = c.id GROUP BY card_id
            )
        """, (user_id, current_date)).fetchone()
        
        return result['count'] if result else 0
    
    def _get_new_cards_count(self, conn: sqlite3.Connection, user_id: int) -> int:
        """Get count of new cards (never studied)"""
        result = conn.execute("""
            SELECT COUNT(*) as count FROM cards c 
            LEFT JOIN study_sessions s ON c.id = s.card_id 
            WHERE c.user_id = ? AND s.card_id IS NULL
        """, (user_id,)).fetchone()
        
        return result['count'] if result else 0
    
    async def _send_reminder(self, user: UserReminder):
        """Send reminder message via Telegram with interactive cards"""
        if not BOT_TOKEN:
            logger.error("BOT_TOKEN not configured")
            return
        
        # Get specific cards to study
        due_cards = self._get_due_cards_for_user(user.user_id, limit=5)
        
        if not due_cards:
            # No specific cards, send general reminder
            await self._send_general_reminder(user)
            return
        
        # Send individual card reminders
        for card in due_cards:
            await self._send_card_reminder(user.user_id, card)
            await asyncio.sleep(0.5)  # Prevent rate limiting
    
    async def _send_general_reminder(self, user: UserReminder):
        """Send general reminder without specific cards"""
        message = self._create_reminder_message(user)
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
        payload = {
            "chat_id": user.user_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": False
        }
        
        async with self.session.post(url, json=payload) as resp:
            if resp.status == 200:
                logger.debug(f"General reminder sent successfully to user {user.user_id}")
            else:
                error_text = await resp.text()
                logger.error(f"Failed to send general reminder to user {user.user_id}: {resp.status} - {error_text}")
    
    async def _send_card_reminder(self, user_id: int, card: dict):
        """Send reminder for specific card with interactive button"""
        message = self._create_card_reminder_message(card)
        inline_keyboard = self._create_card_keyboard(card)
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
        payload = {
            "chat_id": user_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": False,
            "reply_markup": inline_keyboard
        }
        
        async with self.session.post(url, json=payload) as resp:
            if resp.status == 200:
                logger.debug(f"Card reminder sent successfully to user {user_id}, card {card['id']}")
            else:
                error_text = await resp.text()
                logger.error(f"Failed to send card reminder to user {user_id}: {resp.status} - {error_text}")
    
    def _create_reminder_message(self, user: UserReminder) -> str:
        """Create personalized reminder message"""
        total_cards = user.due_count + user.new_count
        
        if user.due_count > 0 and user.new_count > 0:
            cards_info = f"📚 {user.due_count} к повторению • ✨ {user.new_count} новых"
        elif user.due_count > 0:
            cards_info = f"📚 {user.due_count} карточек к повторению"
        else:
            cards_info = f"✨ {user.new_count} новых карточек"
        
        message = f"""🧠 <b>Время изучения!</b>

{cards_info}

💡 <i>Интервальное повторение работает лучше всего при регулярном изучении. Всего 5-10 минут в день помогут вам надолго запомнить материал!</i>

🚀 Начните изучение в Mini App"""
        
        return message
    
    def _get_due_cards_for_user(self, user_id: int, limit: int = 5) -> List[dict]:
        """Get specific cards that are due for review"""
        current_date = date.today().isoformat()
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                
                # Get due cards with details
                due_cards = conn.execute("""
                    SELECT DISTINCT c.id, c.front, c.back, c.created_at,
                           s.quality, s.next_review_date, s.repetitions
                    FROM cards c
                    JOIN study_sessions s ON c.id = s.card_id
                    WHERE c.user_id = ? AND s.next_review_date <= ?
                    AND s.id IN (
                        SELECT MAX(id) FROM study_sessions 
                        WHERE card_id = c.id GROUP BY card_id
                    )
                    ORDER BY s.next_review_date ASC
                    LIMIT ?
                """, (user_id, current_date, limit)).fetchall()
                
                # Convert to list of dicts
                cards = []
                for row in due_cards:
                    cards.append({
                        'id': row['id'],
                        'front': row['front'],
                        'back': row['back'],
                        'quality': row['quality'],
                        'repetitions': row['repetitions'],
                        'next_review_date': row['next_review_date']
                    })
                
                return cards
                
        except Exception as e:
            logger.error(f"Error getting due cards for user {user_id}: {e}")
            return []
    
    def _create_card_reminder_message(self, card: dict) -> str:
        """Create message for specific card reminder"""
        repetitions = card.get('repetitions', 0)
        if repetitions == 0:
            status = "✨ Новая карточка"
        elif repetitions == 1:
            status = "🔄 Первое повторение"
        elif repetitions <= 3:
            status = f"📚 {repetitions}-е повторение"
        else:
            status = f"🎯 Повторение #{repetitions}"
        
        message = f"""📖 <b>Время повторить карточку!</b>

<b>{status}</b>

<b>Слово:</b> <code>{card['front']}</code>
<b>Перевод:</b> <i>{card['back']}</i>

💡 <i>Нажмите кнопку ниже, чтобы изучить эту карточку</i>"""
        
        return message
    
    def _create_card_keyboard(self, card: dict) -> dict:
        """Create inline keyboard for card interaction"""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "🚀 Изучить карточку",
                        "callback_data": f"study_card_{card['id']}"
                    }
                ],
                [
                    {
                        "text": "📚 Открыть все карточки",
                        "url": f"{os.getenv('APP_URL', 'http://localhost:8000')}/study.html"
                    }
                ]
            ]
        }
    
    def _update_last_reminder(self, user_id: int):
        """Update last reminder timestamp for spam protection"""
        try:
            reminder_file = os.path.join(os.path.dirname(__file__), "logs", "reminders.log")
            timestamp = datetime.now().isoformat()
            
            with open(reminder_file, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp}:{user_id}\n")
                
        except Exception as e:
            logger.error(f"Error updating reminder log: {e}")


async def main():
    """Main function"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is required")
        return
    
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at {DB_PATH}")
        return
    
    scheduler = SpacedRepetitionScheduler()
    await scheduler.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")