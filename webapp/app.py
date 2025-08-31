import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.parse
from typing import Optional, Tuple
from datetime import datetime, date, timedelta

import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify, request, send_from_directory


BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "counter.db")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")


def setup_logging(app: Flask) -> None:
    try:
        logs_dir = os.path.join(os.path.dirname(BASE_DIR), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        file_handler = RotatingFileHandler(os.path.join(logs_dir, 'flask.log'), maxBytes=2_000_000, backupCount=2, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
        file_handler.setFormatter(formatter)

        app.logger.addHandler(file_handler)
        logging.getLogger('werkzeug').addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        logging.getLogger('werkzeug').setLevel(logging.INFO)
        app.logger.info('Flask logging configured')
    except Exception:
        # Fallback to default logging silently
        pass


def create_app() -> Flask:
    app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="")

    setup_logging(app)
    # Ensure DB and exports dir exist
    init_db()
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    @app.before_request
    def _before():
        g_start = time.perf_counter()
        # stash start time in environ to avoid importing g from Flask here
        request.environ['__t0'] = g_start
        app.logger.info(
            "REQ %s %s ct=%s qs=%s ip=%s",
            request.method,
            request.path,
            request.headers.get('Content-Type'),
            request.query_string.decode(errors='ignore'),
            request.remote_addr,
        )

    @app.after_request
    def _after(resp):
        t0 = request.environ.get('__t0')
        dt = (time.perf_counter() - t0) * 1000 if isinstance(t0, float) else -1.0
        app.logger.info(
            "RESP %s %s status=%s dur_ms=%.1f len=%s",
            request.method,
            request.path,
            resp.status,
            dt,
            resp.content_length,
        )
        return resp

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")


    # Spaced repetition API endpoints
    @app.post("/api/cards")
    def api_create_card():
        """Create a new flashcard"""
        user_id = extract_user_id_from_request()
        if user_id is None:
            app.logger.warning("CREATE_CARD unauthorized headers=%s body=%s", dict(request.headers), _safe_body())
            return jsonify({"ok": False, "error": "unauthorized"}), 401
            
        try:
            data = request.get_json()
            front = data.get("front", "").strip()
            back = data.get("back", "").strip()
            
            if not front or not back:
                return jsonify({"ok": False, "error": "front and back are required"}), 400
                
            card_id = create_card(user_id, front, back)
            app.logger.info("CREATE_CARD user_id=%s card_id=%s", user_id, card_id)
            return jsonify({"ok": True, "card_id": card_id})
            
        except Exception as e:
            app.logger.error("CREATE_CARD error user_id=%s: %s", user_id, e)
            return jsonify({"ok": False, "error": "server error"}), 500

    @app.get("/api/cards/review")
    def api_get_review_cards():
        """Get cards due for review"""
        user_id = extract_user_id_from_request()
        if user_id is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
            
        try:
            limit = int(request.args.get("limit", 10))
            cards = get_cards_for_review(user_id, limit)
            app.logger.info("GET_REVIEW_CARDS user_id=%s count=%s", user_id, len(cards))
            return jsonify({"ok": True, "cards": cards})
            
        except Exception as e:
            app.logger.error("GET_REVIEW_CARDS error user_id=%s: %s", user_id, e)
            return jsonify({"ok": False, "error": "server error"}), 500

    @app.post("/api/cards/<int:card_id>/review")
    def api_review_card(card_id: int):
        """Record a review for a card"""
        user_id = extract_user_id_from_request()
        if user_id is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
            
        try:
            data = request.get_json()
            quality = data.get("quality")
            
            if quality is None or not (1 <= quality <= 5):
                return jsonify({"ok": False, "error": "quality must be between 1 and 5"}), 400
                
            success = review_card(user_id, card_id, quality)
            app.logger.info("REVIEW_CARD user_id=%s card_id=%s quality=%s", user_id, card_id, quality)
            return jsonify({"ok": True, "reviewed": success})
            
        except Exception as e:
            app.logger.error("REVIEW_CARD error user_id=%s card_id=%s: %s", user_id, card_id, e)
            return jsonify({"ok": False, "error": "server error"}), 500

    @app.get("/api/stats")
    def api_get_stats():
        """Get user study statistics"""
        user_id = extract_user_id_from_request()
        if user_id is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
            
        try:
            stats = get_user_stats(user_id)
            app.logger.info("GET_STATS user_id=%s stats=%s", user_id, stats)
            return jsonify({"ok": True, "stats": stats})
            
        except Exception as e:
            app.logger.error("GET_STATS error user_id=%s: %s", user_id, e)
            return jsonify({"ok": False, "error": "server error"}), 500

    @app.post("/api/cards/bulk")
    def api_bulk_create_cards():
        """Bulk create cards from new_words.json file"""
        user_id = extract_user_id_from_request()
        if user_id is None:
            app.logger.warning("BULK_CREATE unauthorized headers=%s body=%s", dict(request.headers), _safe_body())
            return jsonify({"ok": False, "error": "unauthorized"}), 401
            
        try:
            words_file_path = os.path.join(os.path.dirname(BASE_DIR), "new_words.json")
            
            if not os.path.exists(words_file_path):
                return jsonify({"ok": False, "error": "new_words.json file not found"}), 404
                
            with open(words_file_path, 'r', encoding='utf-8') as f:
                words_data = json.load(f)
            
            cards = words_data.get('cards', [])
            if not cards:
                return jsonify({"ok": False, "error": "No cards found in file"}), 400
                
            created_count = 0
            ensure_user_exists(user_id)
            
            with get_db_connection() as conn:
                for card in cards:
                    # Map uz->ru format to front->back
                    front = card.get('uz', '')
                    back = card.get('ru', '')
                    note = card.get('note', '')
                    
                    if front and back:
                        # Add note to back if exists
                        if note:
                            back = f"{back}\n\n💡 {note}"
                            
                        # Check if card already exists for this user
                        existing = conn.execute(
                            "SELECT id FROM cards WHERE user_id = ? AND front = ? AND back = ?",
                            (user_id, front, back)
                        ).fetchone()
                        
                        if not existing:
                            conn.execute(
                                "INSERT INTO cards (user_id, front, back) VALUES (?, ?, ?)",
                                (user_id, front, back)
                            )
                            created_count += 1
                
                conn.commit()
            
            app.logger.info("BULK_CREATE user_id=%s created=%s total_cards=%s", user_id, created_count, len(cards))
            return jsonify({
                "ok": True, 
                "created": created_count, 
                "total_processed": len(cards),
                "skipped": len(cards) - created_count
            })
            
        except json.JSONDecodeError:
            app.logger.error("BULK_CREATE invalid JSON in new_words.json")
            return jsonify({"ok": False, "error": "Invalid JSON format"}), 400
        except Exception as e:
            app.logger.error("BULK_CREATE error user_id=%s: %s", user_id, e)
            return jsonify({"ok": False, "error": "server error"}), 500

    return app


def init_db() -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        # Users table for authentication tracking
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Spaced repetition tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                quality INTEGER NOT NULL CHECK (quality >= 1 AND quality <= 5),
                interval_days INTEGER NOT NULL DEFAULT 1,
                ease_factor REAL NOT NULL DEFAULT 2.5,
                next_review_date DATE NOT NULL,
                studied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                notifications_enabled BOOLEAN DEFAULT 1,
                study_reminder_time TEXT DEFAULT '09:00',
                timezone TEXT DEFAULT 'UTC',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
        
        conn.commit()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_exists(user_id: int) -> None:
    """Ensure user exists in users table"""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()


def calculate_sm2_interval(quality: int, interval_days: int, ease_factor: float) -> Tuple[int, float]:
    """
    SM-2 Algorithm for spaced repetition
    quality: 1-5 (how well user remembered the card)
    interval_days: current interval in days
    ease_factor: current ease factor (starts at 2.5)
    
    Returns: (new_interval_days, new_ease_factor)
    """
    if quality < 3:
        # Reset interval if quality is poor
        new_interval = 1
        new_ease_factor = ease_factor
    else:
        if interval_days == 1:
            new_interval = 6
        elif interval_days == 6:
            new_interval = 16
        else:
            new_interval = int(interval_days * ease_factor)
        
        # Update ease factor
        new_ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    
    return new_interval, new_ease_factor


def create_card(user_id: int, front: str, back: str) -> int:
    """Create a new flashcard"""
    ensure_user_exists(user_id)
    with get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO cards (user_id, front, back) VALUES (?, ?, ?)",
            (user_id, front, back)
        )
        conn.commit()
        return cur.lastrowid


def get_cards_for_review(user_id: int, limit: int = 10) -> list:
    """Get cards that are due for review"""
    today = date.today().isoformat()
    
    with get_db_connection() as conn:
        # Get new cards (never studied)
        new_cards = conn.execute("""
            SELECT c.id, c.front, c.back, 'new' as status
            FROM cards c 
            LEFT JOIN study_sessions s ON c.id = s.card_id 
            WHERE c.user_id = ? AND s.card_id IS NULL
            LIMIT ?
        """, (user_id, limit // 2)).fetchall()
        
        # Get due cards
        due_cards = conn.execute("""
            SELECT DISTINCT c.id, c.front, c.back, 'due' as status
            FROM cards c
            JOIN study_sessions s ON c.id = s.card_id
            WHERE c.user_id = ? 
            AND s.next_review_date <= ?
            AND s.id IN (
                SELECT MAX(id) FROM study_sessions 
                WHERE card_id = c.id GROUP BY card_id
            )
            LIMIT ?
        """, (user_id, today, limit - len(new_cards))).fetchall()
        
        return [dict(row) for row in new_cards + due_cards]


def review_card(user_id: int, card_id: int, quality: int) -> bool:
    """Record a review session for a card"""
    with get_db_connection() as conn:
        # Get the last review session for this card
        last_session = conn.execute("""
            SELECT interval_days, ease_factor FROM study_sessions 
            WHERE card_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT 1
        """, (card_id, user_id)).fetchone()
        
        if last_session:
            interval_days, ease_factor = last_session["interval_days"], last_session["ease_factor"]
        else:
            interval_days, ease_factor = 1, 2.5
        
        # Calculate new interval using SM-2
        new_interval, new_ease_factor = calculate_sm2_interval(quality, interval_days, ease_factor)
        next_review_date = (date.today() + timedelta(days=new_interval)).isoformat()
        
        # Insert new review session
        conn.execute("""
            INSERT INTO study_sessions 
            (card_id, user_id, quality, interval_days, ease_factor, next_review_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (card_id, user_id, quality, new_interval, new_ease_factor, next_review_date))
        
        conn.commit()
        return True


def get_user_stats(user_id: int) -> dict:
    """Get user study statistics"""
    with get_db_connection() as conn:
        total_cards = conn.execute("SELECT COUNT(*) as count FROM cards WHERE user_id = ?", (user_id,)).fetchone()["count"]
        
        today = date.today().isoformat()
        due_today = conn.execute("""
            SELECT COUNT(DISTINCT c.id) as count
            FROM cards c
            JOIN study_sessions s ON c.id = s.card_id
            WHERE c.user_id = ? AND s.next_review_date <= ?
            AND s.id IN (
                SELECT MAX(id) FROM study_sessions 
                WHERE card_id = c.id GROUP BY card_id
            )
        """, (user_id, today)).fetchone()["count"]
        
        new_cards = conn.execute("""
            SELECT COUNT(*) as count FROM cards c 
            LEFT JOIN study_sessions s ON c.id = s.card_id 
            WHERE c.user_id = ? AND s.card_id IS NULL
        """, (user_id,)).fetchone()["count"]
        
        return {
            "total_cards": total_cards,
            "due_today": due_today,
            "new_cards": new_cards
        }


def extract_user_id_from_request() -> Optional[int]:
    # Prefer Telegram initData validation if provided
    content_type = (request.headers.get("Content-Type") or "").lower()
    payload = {}
    if "application/json" in content_type:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
    else:
        payload = request.form.to_dict() if request.form else {}

    init_data = request.headers.get("X-Telegram-Init-Data") or payload.get("initData")
    bot_token = os.getenv("BOT_TOKEN")
    dev_mode = (os.getenv("DEV_MODE", "true").lower() == "true")

    if init_data and bot_token:
        ok, user_id = validate_and_get_user_id(init_data, bot_token)
        if ok and user_id is not None:
            logging.getLogger(__name__).info("Auth via initData user_id=%s", user_id)
            return user_id

    # Dev fallback: allow ?user_id=... or body.user_id, with default fallback
    if dev_mode:
        uid = request.args.get("user_id") or payload.get("user_id")
        try:
            val = int(uid) if uid is not None else 234195742  # Default dev user ID
            logging.getLogger(__name__).info("Auth via DEV user_id=%s", val)
            return val
        except (TypeError, ValueError):
            logging.getLogger(__name__).warning("Invalid DEV user_id=%r, using default", uid)
            return 234195742

    return None


def validate_and_get_user_id(init_data: str, bot_token: str) -> Tuple[bool, Optional[int]]:
    try:
        # Parse URL-encoded initData, extract hash, build data_check_string
        parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)
        data = {k: v[0] for k, v in parsed.items()}
        recv_hash = data.pop("hash", None)
        if not recv_hash:
            return False, None

        pairs = [f"{k}={data[k]}" for k in sorted(data.keys())]
        data_check_string = "\n".join(pairs)

        secret_key = hashlib.sha256(bot_token.encode()).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calc_hash != recv_hash:
            return False, None

        user_json = data.get("user")
        if not user_json:
            return False, None
        user = json.loads(user_json)
        uid = int(user.get("id"))
        return True, uid
    except Exception:
        return False, None




# Create app instance for WSGI servers like gunicorn
app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)


def _safe_body():
    try:
        data = request.get_json(silent=True)
        if data is None:
            return None
        data = dict(data)
        data.pop('initData', None)
        return data
    except Exception:
        return None
