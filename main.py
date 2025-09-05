#!/usr/bin/env python3
"""
Main entry point for deployment
Запускает Flask API, Telegram бота и scheduler одновременно
"""
import asyncio
import logging
import os
import sys
import threading
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)

# Import our modules
from bot.bot import main as bot_main
from scheduler import SpacedRepetitionScheduler
from webapp.app import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def run_flask_app():
    """Run Flask app with Gunicorn in separate thread"""
    try:
        import subprocess
        port = int(os.environ.get("PORT", 8000))
        
        # Use Gunicorn for production
        cmd = [
            "gunicorn",
            "--bind", f"0.0.0.0:{port}",
            "--workers", "1",
            "--timeout", "120",
            "--keep-alive", "5",
            "--max-requests", "1000",
            "--preload",
            "webapp.app:app"
        ]
        
        logger.info(f"Starting Gunicorn server on port {port}")
        subprocess.run(cmd, check=True)
        
    except Exception as e:
        logger.error(f"Gunicorn server crashed: {e}")
        # Fallback to Flask dev server
        logger.info("Falling back to Flask development server")
        app = create_app()
        port = int(os.environ.get("PORT", 8000))
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


async def run_scheduler(scheduler):
    """Run scheduler in background"""
    try:
        await scheduler.start()
    except Exception as e:
        logger.error(f"Scheduler crashed: {e}")
        # Restart scheduler after 60 seconds
        await asyncio.sleep(60)
        await run_scheduler(scheduler)


async def run_bot():
    """Run Telegram bot"""
    try:
        await bot_main()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        # Restart bot after 30 seconds
        await asyncio.sleep(30)
        await run_bot()


async def main_async():
    """Async part - runs bot and scheduler"""
    logger.info("Starting Telegram Bot and Scheduler...")
    
    # Validate environment
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is required")
        return
    
    # Create scheduler instance
    scheduler = SpacedRepetitionScheduler()
    
    try:
        # Run bot and scheduler concurrently
        await asyncio.gather(
            run_bot(),                    # Bot polling
            run_scheduler(scheduler)      # Scheduler background task
        )
    except KeyboardInterrupt:
        logger.info("Shutting down async services...")
        await scheduler.stop()
    except Exception as e:
        logger.error(f"Async services error: {e}")
        await scheduler.stop()


def main():
    """Main entry point"""
    logger.info("Starting all services...")
    
    # Start Flask in separate thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    logger.info("Flask API started in background thread")
    
    # Run async services in main thread
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")


if __name__ == "__main__":
    main()