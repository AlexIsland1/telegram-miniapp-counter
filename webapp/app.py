import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.parse
from typing import Optional, Tuple
from datetime import datetime

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

    @app.post("/api/count")
    def api_count():
        user_id = extract_user_id_from_request()
        if user_id is None:
            app.logger.warning("COUNT unauthorized headers=%s body=%s", dict(request.headers), _safe_body())
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        count = get_count(user_id)
        app.logger.info("COUNT user_id=%s -> %s", user_id, count)
        return jsonify({"ok": True, "user_id": user_id, "count": count})

    @app.post("/api/click")
    def api_click():
        user_id = extract_user_id_from_request()
        if user_id is None:
            app.logger.warning("CLICK unauthorized headers=%s body=%s", dict(request.headers), _safe_body())
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        count = increment_count(user_id)
        app.logger.info("CLICK user_id=%s -> %s", user_id, count)
        return jsonify({"ok": True, "user_id": user_id, "count": count})

    @app.get("/api/export/<int:user_id>")
    def api_export_user(user_id: int):
        """Download user data as JSON file"""
        filename = f"user_{user_id}_data.json"
        filepath = os.path.join(EXPORTS_DIR, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"ok": False, "error": "No data found for this user"}), 404
            
        return send_from_directory(EXPORTS_DIR, filename, as_attachment=True)

    return app


def init_db() -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counts (
                user_id INTEGER PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_count(user_id: int) -> int:
    with get_db_connection() as conn:
        row = conn.execute("SELECT count FROM counts WHERE user_id=?", (user_id,)).fetchone()
        return int(row["count"]) if row else 0


def increment_count(user_id: int) -> int:
    with get_db_connection() as conn:
        cur = conn.execute("SELECT count FROM counts WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO counts(user_id, count) VALUES(?, 1)", (user_id,))
            conn.commit()
            new_val = 1
        else:
            new_val = int(row["count"]) + 1
            conn.execute("UPDATE counts SET count=? WHERE user_id=?", (new_val, user_id))
            conn.commit()
        
        # Auto-save to JSON after each click
        save_user_data_to_json(user_id, new_val)
        return new_val


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


def save_user_data_to_json(user_id: int, count: int) -> None:
    """Save user click count to individual JSON file"""
    try:
        filename = f"user_{user_id}_data.json"
        filepath = os.path.join(EXPORTS_DIR, filename)
        
        data = {
            "user_id": user_id,
            "count": count,
            "last_updated": datetime.now().isoformat(),
            "export_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        logging.getLogger(__name__).info("Saved user data to JSON: user_id=%s, count=%s", user_id, count)
    except Exception as e:
        logging.getLogger(__name__).error("Failed to save user data to JSON: %s", e)


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
