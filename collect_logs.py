import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib import request as urlrequest

from dotenv import load_dotenv


def tail_file(path: Path, lines: int = 200) -> str:
    try:
        if not path.exists():
            return f"<no file: {path}>"
        with path.open('r', encoding='utf-8', errors='ignore') as f:
            data = f.readlines()
        chunk = ''.join(data[-lines:])
        return chunk if chunk.strip() else f"<empty: {path}>"
    except Exception as e:
        return f"<error reading {path}: {e}>"


async def check_bot():
    try:
        from aiogram import Bot
    except Exception as e:
        return {"ok": False, "error": f"aiogram import failed: {e}"}

    token = os.getenv("BOT_TOKEN")
    if not token:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    try:
        async with Bot(token) as bot:
            me = await bot.get_me()
            wh = await bot.get_webhook_info()
            return {
                "ok": True,
                "bot_id": me.id,
                "username": me.username,
                "webhook_url": wh.url,
                "pending_updates": wh.pending_update_count,
            }
    except Exception as e:
        return {"ok": False, "error": repr(e)}


def http_post_json(url: str, body: dict, timeout: float = 2.0):
    data = json.dumps(body).encode('utf-8')
    req = urlrequest.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))


def check_flask(base: str = "http://127.0.0.1:8000"):
    out = {}
    try:
        code, js = http_post_json(base + "/api/count", {"user_id": 123})
        out["count_before"] = {"status": code, "json": js}
    except Exception as e:
        out["count_before"] = {"error": repr(e)}
    try:
        code, js = http_post_json(base + "/api/click", {"user_id": 123})
        out["click_once"] = {"status": code, "json": js}
    except Exception as e:
        out["click_once"] = {"error": repr(e)}
    try:
        code, js = http_post_json(base + "/api/count", {"user_id": 123})
        out["count_after"] = {"status": code, "json": js}
    except Exception as e:
        out["count_after"] = {"error": repr(e)}
    return out


def main():
    load_dotenv()
    root = Path(__file__).resolve().parent
    logs = root / "logs"
    print("ENV:")
    print("  APP_URL:", os.getenv("APP_URL"))
    print("  BOT_TOKEN set:", bool(os.getenv("BOT_TOKEN")))
    print("  DEV_MODE:", os.getenv("DEV_MODE"))
    print("LOG FILES:")
    print("  ", logs)

    print("\n=== Flask health ===")
    f = check_flask()
    print(json.dumps(f, ensure_ascii=False, indent=2))

    print("\n=== Bot health ===")
    b = asyncio.run(check_bot())
    print(json.dumps(b, ensure_ascii=False, indent=2))

    print("\n=== Tail flask.log ===")
    print(tail_file(logs / 'flask.log', 200))

    print("\n=== Tail bot.log ===")
    print(tail_file(logs / 'bot.log', 200))


if __name__ == '__main__':
    main()

