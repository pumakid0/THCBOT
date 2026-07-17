"""THCBOT v1.0 — Vercel webhook handler (alternativo a Railway polling)"""
import os, json, logging, asyncio
from http.server import BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
import db, handlers

log   = logging.getLogger(__name__)
TOKEN = os.environ["TELEGRAM_TOKEN"]
SECRET= os.environ.get("WEBHOOK_SECRET","")

_app: Application | None = None

async def _get_app() -> Application:
    global _app
    if _app is None:
        _app = Application.builder().token(TOKEN).build()
        for cmd, fn in [
            ("start",             handlers.cmd_start),
            ("help",              handlers.cmd_help),
            ("version",           handlers.cmd_version),
            ("link",              handlers.cmd_link),
            ("balance",           handlers.cmd_balance),
            ("rate",              handlers.cmd_rate),
            ("pay",               handlers.cmd_pay),
            ("pew",               handlers.cmd_pew),
            ("rain",              handlers.cmd_rain),
            ("paylink",           handlers.cmd_paylink),
            ("mylinks",           handlers.cmd_mylinks),
            ("seal",              handlers.cmd_seal),
            ("swap",              handlers.cmd_swap),
            ("dice",              handlers.cmd_dice),
            ("flip",              handlers.cmd_flip),
            ("rps",               handlers.cmd_rps),
            ("leaderboard",       handlers.cmd_leaderboard),
            ("stats",             handlers.cmd_stats),
            ("active",            handlers.cmd_active),
            ("stream",            handlers.cmd_stream),
            ("streamers",         handlers.cmd_streamers),
            ("fund",              handlers.cmd_fund),
            ("connect_extension", handlers.cmd_connect_extension),
        ]:
            _app.add_handler(CommandHandler(cmd, fn))
        _app.add_handler(CallbackQueryHandler(handlers.cb_query_handler))
        await _app.initialize()
    return _app


class handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_POST(self):
        if SECRET and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET:
            self._send(403, {"error":"Forbidden"}); return
        length = int(self.headers.get("Content-Length",0))
        body   = self.rfile.read(length)
        try:
            data   = json.loads(body)
            update = Update.de_json(data, None)
            app    = asyncio.get_event_loop().run_until_complete(_get_app())
            asyncio.get_event_loop().run_until_complete(
                app.process_update(update)
            )
            self._send(200, {"ok":True})
        except Exception as e:
            log.exception("webhook error")
            self._send(500, {"error":str(e)})

    def do_GET(self):
        self._send(200, {"status":"THCBOT webhook active"})

    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
