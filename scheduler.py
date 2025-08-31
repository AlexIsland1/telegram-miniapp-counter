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
CHECK_INTERVAL = 300  # Check every 5 minutes
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
        users_to_remind = self._get_users_needing_reminders()
        
        if not users_to_remind:
            logger.debug("No users need reminders at this time")
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
        """Get list of users who need reminders"""
        current_time = datetime.now()
        current_date = date.today().isoformat()
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                
                # Get users with their settings and card stats
                users = conn.execute("""
                    SELECT DISTINCT u.user_id,
                           COALESCE(us.notifications_enabled, 1) as notifications_enabled,
                           COALESCE(us.study_reminder_time, '09:00') as reminder_time,
                           COALESCE(us.timezone, 'UTC') as timezone
                    FROM users u
                    LEFT JOIN user_settings us ON u.user_id = us.user_id
                    LEFT JOIN cards c ON u.user_id = c.user_id
                    WHERE COALESCE(us.notifications_enabled, 1) = 1
                    AND c.id IS NOT NULL  -- Only users with cards
                """).fetchall()
                
                users_to_remind = []
                
                for user_row in users:
                    user_id = user_row['user_id']
                    reminder_time_str = user_row['reminder_time']
                    
                    # Skip if notifications disabled
                    if not user_row['notifications_enabled']:
                        continue
                    
                    # Check if it's time for this user's reminder
                    if not self._is_reminder_time(reminder_time_str, current_time):
                        continue
                    
                    # Check if already reminded today
                    if self._was_reminded_today(user_id):
                        continue
                    
                    # Get due and new card counts
                    due_count = self._get_due_cards_count(conn, user_id, current_date)
                    new_count = self._get_new_cards_count(conn, user_id)
                    
                    # Only remind if there are cards to study
                    if due_count > 0 or new_count > 0:
                        users_to_remind.append(UserReminder(
                            user_id=user_id,
                            due_count=due_count,
                            new_count=new_count,
                            last_reminder=None,
                            reminder_time=reminder_time_str,
                            notifications_enabled=True
                        ))
                
                return users_to_remind
                
        except Exception as e:
            logger.error(f"Error getting users for reminders: {e}")
            return []
    
    def _is_reminder_time(self, reminder_time_str: str, current_time: datetime) -> bool:
        """Check if current time matches user's reminder time"""
        try:
            # Parse reminder time (HH:MM format)
            reminder_time = datetime.strptime(reminder_time_str, '%H:%M').time()
            current_time_only = current_time.time()
            
            # Check if current time is within 5 minutes of reminder time
            reminder_datetime = datetime.combine(date.today(), reminder_time)
            current_datetime = datetime.combine(date.today(), current_time_only)
            
            time_diff = abs((current_datetime - reminder_datetime).total_seconds())
            
            # Remind if within CHECK_INTERVAL seconds of reminder time
            return time_diff <= CHECK_INTERVAL
            
        except ValueError:
            logger.warning(f"Invalid reminder time format: {reminder_time_str}")
            return False
    
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
        """Send reminder message via Telegram"""
        if not BOT_TOKEN:
            logger.error("BOT_TOKEN not configured")
            return
        
        # Create reminder message
        message = self._create_reminder_message(user)
        
        # Send via Telegram Bot API
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
        payload = {
            "chat_id": user.user_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": False
        }
        
        async with self.session.post(url, json=payload) as resp:
            if resp.status == 200:
                logger.debug(f"Reminder sent successfully to user {user.user_id}")
            else:
                error_text = await resp.text()
                logger.error(f"Failed to send reminder to user {user.user_id}: {resp.status} - {error_text}")
    
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