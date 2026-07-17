"""
THCBOT v1.0 — Bot de Telegram completo (BSV / BTC / LTC / MNEE / EUR)
Archivo único: main.py — modo polling, pensado para Railway.

Requiere variables de entorno:
  TELEGRAM_TOKEN   -> token de BotFather
  SUPABASE_URL     -> connection string de Postgres (Supabase)
  OWNER_TG_ID      -> tu ID numérico de Telegram (opcional, para /fund y stats admin)
  FRONTEND_URL     -> URL del frontend en Vercel (opcional, usado en /connect_extension)

requirements.txt necesario:
  python-telegram-bot==20.7
  psycopg2-binary==2.9.9
  httpx==0.27.0
  python-dotenv==1.0.1
"""

import os
import time
import random
import string
import hashlib
import logging
from decimal import Decimal, ROUND_DOWN

import httpx
import psycopg2
import psycopg2.extras

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("thcbot")

TOKEN = os.environ["TELEGRAM_TOKEN"]
DB_URL = os.environ["SUPABASE_URL"]
OWNER_TG_ID = int(os.environ.get("OWNER_TG_ID", "0") or 0)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "")

if "?" not in DB_URL:
    DB_URL = DB_URL + "?sslmode=require&connect_timeout=5"

ASSETS = ("BSV", "BTC", "LTC", "MNEE", "EUR")
CG_IDS = {
    "BSV": "bitcoin-sv",
    "BTC": "bitcoin",
    "LTC": "litecoin",
    "MNEE": "mnee",
}

_rate_cache: dict = {}
_cache_ts: float = 0.0
CACHE_TTL = 60  # segundos


# ══════════════════════════════════════════════════════════════════
# DB LAYER
# ══════════════════════════════════════════════════════════════════
def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def ensure_user(tg_id: int, username: str = "", first_name: str = "") -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE users SET username=%s, first_name=%s, updated_at=NOW() WHERE tg_id=%s",
            (username, first_name, tg_id),
        )
        conn.commit()
        conn.close()
        return row
    cur.execute(
        """INSERT INTO users (tg_id, username, first_name)
           VALUES (%s, %s, %s) RETURNING *""",
        (tg_id, username, first_name),
    )
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return row


def get_user(tg_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    conn.close()
    return row


def set_paymail(tg_id: int, paymail: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET paymail=%s, updated_at=NOW() WHERE tg_id=%s",
        (paymail, tg_id),
    )
    conn.commit()
    conn.close()


def toggle_active(tg_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_active FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    new_val = not (row and row["is_active"])
    cur.execute(
        "UPDATE users SET is_active=%s, updated_at=NOW() WHERE tg_id=%s",
        (new_val, tg_id),
    )
    conn.commit()
    conn.close()
    return new_val


def get_active_users(exclude_tg_id: int | None = None, limit: int = 500) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if exclude_tg_id:
        cur.execute(
            "SELECT tg_id FROM users WHERE is_active=TRUE AND tg_id<>%s LIMIT %s",
            (exclude_tg_id, limit),
        )
    else:
        cur.execute("SELECT tg_id FROM users WHERE is_active=TRUE LIMIT %s", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [r["tg_id"] for r in rows]


def _asset_column(asset: str) -> str:
    return {
        "BSV": "bsv_balance",
        "BTC": "btc_balance",
        "LTC": "ltc_balance",
        "MNEE": "mnee_balance",
        "EUR": "eur_balance",
    }[asset]


def get_balance(tg_id: int, asset: str) -> float:
    col = _asset_column(asset)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {col} FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return float(row[col]) if row else 0.0


def transfer(sender_id: int, receiver_id: int, amount: float, asset: str,
             tx_type: str = "TRANSFER", meta: dict | None = None) -> None:
    col = _asset_column(asset)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {col} FROM users WHERE tg_id=%s FOR UPDATE", (sender_id,))
    row = cur.fetchone()
    if not row or float(row[col]) < amount:
        conn.close()
        raise ValueError(f"Saldo {asset} insuficiente")
    cur.execute(
        f"UPDATE users SET {col} = {col} - %s, updated_at=NOW() WHERE tg_id=%s",
        (amount, sender_id),
    )
    cur.execute(
        f"UPDATE users SET {col} = {col} + %s, updated_at=NOW() WHERE tg_id=%s",
        (amount, receiver_id),
    )
    import json as _json
    cur.execute(
        """INSERT INTO transactions (sender_id, receiver_id, amount, asset, type, meta)
           VALUES (%s,%s,%s,%s,%s,%s::jsonb)""",
        (sender_id, receiver_id, amount, asset, tx_type, _json.dumps(meta or {})),
    )
    conn.commit()
    conn.close()


def credit(tg_id: int, amount: float, asset: str, tx_type: str = "CREDIT") -> None:
    col = _asset_column(asset)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE users SET {col} = {col} + %s, updated_at=NOW() WHERE tg_id=%s",
        (amount, tg_id),
    )
    cur.execute(
        """INSERT INTO transactions (sender_id, receiver_id, amount, asset, type)
           VALUES (-1,%s,%s,%s,%s)""",
        (tg_id, amount, asset, tx_type),
    )
    conn.commit()
    conn.close()


def create_paylink(link_id: str, owner_id: int, amount: float, asset: str,
                    description: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO paylinks (id, owner_id, amount, asset, description)
           VALUES (%s,%s,%s,%s,%s)""",
        (link_id, owner_id, amount, asset, description),
    )
    conn.commit()
    conn.close()


def get_paylink(link_id: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM paylinks WHERE id=%s", (link_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_paylinks(owner_id: int, limit: int = 10) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM paylinks WHERE owner_id=%s ORDER BY created_at DESC LIMIT %s",
        (owner_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def pay_paylink(link_id: str, payer_id: int) -> dict:
    link = get_paylink(link_id)
    if not link:
        raise ValueError("Enlace no encontrado")
    if link["paid"]:
        raise ValueError("Este enlace ya fue pagado")
    transfer(payer_id, link["owner_id"], float(link["amount"]), link["asset"],
              tx_type="PAYLINK", meta={"link_id": link_id})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE paylinks SET paid=TRUE, payer_id=%s WHERE id=%s",
        (payer_id, link_id),
    )
    conn.commit()
    conn.close()
    return {"amount": str(link["amount"]), "asset": link["asset"]}


def create_stream(sender_id: int, receiver_id: int, rate_per_sec: float, asset: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO streams (sender_id, receiver_id, rate_per_sec, asset)
           VALUES (%s,%s,%s,%s) RETURNING id""",
        (sender_id, receiver_id, rate_per_sec, asset),
    )
    stream_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return stream_id


def get_active_streams() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM streams WHERE active=TRUE")
    rows = cur.fetchall()
    conn.close()
    return rows


def tick_stream(stream_id: int, amount: float, asset: str,
                 sender_id: int, receiver_id: int) -> None:
    try:
        transfer(sender_id, receiver_id, amount, asset, tx_type="STREAM_TICK")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE streams SET last_tick=NOW() WHERE id=%s", (stream_id,))
        conn.commit()
        conn.close()
    except ValueError:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE streams SET active=FALSE WHERE id=%s", (stream_id,))
        conn.commit()
        conn.close()


def get_leaderboard(limit: int = 10) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, first_name, bsv_balance FROM users "
        "WHERE tg_id > 0 ORDER BY bsv_balance DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_stats() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM users WHERE tg_id > 0")
    total_users = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM transactions")
    total_tx = cur.fetchone()["n"]
    cur.execute("SELECT COALESCE(SUM(bsv_balance),0) AS s FROM users WHERE tg_id > 0")
    total_bsv = float(cur.fetchone()["s"])
    conn.close()
    return {"users": total_users, "transactions": total_tx, "total_bsv": total_bsv}


def create_otp(sender_id: int) -> str:
    code = "".join(random.choices(string.digits, k=6))
    conn = get_conn()
    cur = conn.cursor()
    import json as _json
    cur.execute(
        """INSERT INTO transactions (sender_id, receiver_id, amount, asset, type, meta)
           VALUES (%s,-1,0,'BSV','EXTENSION_OTP',%s::jsonb)""",
        (sender_id, _json.dumps({"code": code, "used": False})),
    )
    conn.commit()
    conn.close()
    return code


# ══════════════════════════════════════════════════════════════════
# UTILS — tasas y parseo de importes
# ══════════════════════════════════════════════════════════════════
async def get_rates() -> dict:
    global _rate_cache, _cache_ts
    if time.time() - _cache_ts < CACHE_TTL and _rate_cache:
        return _rate_cache
    ids = ",".join(CG_IDS.values())
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={ids}&vs_currencies=usd"
            )
            data = r.json()
        rates = {
            "BSV": data.get("bitcoin-sv", {}).get("usd", 60),
            "BTC": data.get("bitcoin", {}).get("usd", 70000),
            "LTC": data.get("litecoin", {}).get("usd", 80),
            "MNEE": data.get("mnee", {}).get("usd", 1),
            "EUR": 1.08,
        }
    except Exception as e:
        log.warning("get_rates fallback: %s", e)
        rates = {"BSV": 60, "BTC": 70000, "LTC": 80, "MNEE": 1, "EUR": 1.08}
    _rate_cache, _cache_ts = rates, time.time()
    return rates


async def parse_amount(amount_str: str, asset_str: str, rates: dict):
    asset = asset_str.upper()
    if asset not in ASSETS:
        raise ValueError(f"Asset no soportado: {asset}. Usa BSV, BTC, LTC, MNEE o EUR.")
    try:
        amount = float(amount_str.replace(",", "."))
    except ValueError:
        raise ValueError(f"Importe no válido: {amount_str}")
    if amount <= 0:
        raise ValueError("El importe debe ser positivo")

    if asset == "BSV":
        bsv_amount = amount
    else:
        usd_amount = amount * rates.get(asset, 1)
        bsv_amount = usd_amount / rates.get("BSV", 60)

    bsv_amount = float(
        Decimal(str(bsv_amount)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    )
    return bsv_amount, asset, amount_str


def fmt_bsv(amount: float) -> str:
    return f"{amount:.8f} BSV"


# ══════════════════════════════════════════════════════════════════
# HANDLERS — 23 comandos
# ══════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username or "", u.first_name or "")
    text = (
        "⚡ *THCBOT* — Bitcoin as a Computer\n\n"
        "Envía BSV, BTC, LTC, MNEE y EUR. Crea paylinks. Juega. "
        "Haz streams de micropagos.\n\n"
        "Escribe /help para ver todos los comandos."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Comandos disponibles:*\n"
        "/balance — Ver saldo\n"
        "/link paymail — Vincular wallet\n"
        "/rate BSV — Precio spot\n"
        "/pay 5 EUR @user — Enviar pago\n"
        "/pew 0.1 BSV — Enviar a todos los activos\n"
        "/rain 1 BSV 10 — Lluvia a usuarios random\n"
        "/paylink 25 EUR Cena — Crear enlace de cobro\n"
        "/mylinks — Ver mis paylinks\n"
        "/seal texto — Notaría BSV\n"
        "/swap 0.1 BSV LTC — Intercambiar assets\n"
        "/dice 0.01 BSV — Dados\n"
        "/flip 0.01 BSV — Cara/Cruz\n"
        "/rps 0.01 BSV — Piedra Papel Tijera\n"
        "/leaderboard — Top 10\n"
        "/stats — Estadísticas\n"
        "/active — Activar/desactivar\n"
        "/stream @user 0.000001 BSV — Micropago/seg\n"
        "/streamers — Streams activos\n"
        "/fund — Donar al proyecto\n"
        "/version — Versión\n"
        "/connect_extension — Vincular extensión Chrome"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    await update.message.reply_text(
        f"⚡ THCBOT v1.0\nUsuarios: {stats['users']}\n"
        f"Transacciones: {stats['transactions']}\n"
        f"BSV en circulación: {stats['total_bsv']:.8f}"
    )


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not context.args:
        await update.message.reply_text("Uso: /link tu_paymail@handcash.io")
        return
    paymail = context.args[0]
    set_paymail(u.id, paymail)
    await update.message.reply_text(f"✅ Paymail vinculado: {paymail}")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = ensure_user(u.id, u.username or "", u.first_name or "")
    rates = await get_rates()
    text = "💰 *Tu saldo:*\n\n"
    for asset in ASSETS:
        bal = get_balance(u.id, asset)
        usd = bal * rates.get(asset, 1) if asset != "EUR" else bal
        text += f"{asset}: `{bal:.8f}` (~${usd:.2f})\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asset = (context.args[0].upper() if context.args else "BSV")
    rates = await get_rates()
    if asset not in rates:
        await update.message.reply_text("Asset no soportado.")
        return
    await update.message.reply_text(f"💱 1 {asset} = ${rates[asset]:.4f} USD")


async def cmd_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 3:
        await update.message.reply_text("Uso: /pay 5 EUR @usuario")
        return
    amount_str, asset_str, target = context.args[0], context.args[1], context.args[2]
    target_user = get_user_by_username(target)
    if not target_user:
        await update.message.reply_text("Usuario no encontrado (debe haber usado /start).")
        return
    rates = await get_rates()
    try:
        bsv_amount, asset, _ = await parse_amount(amount_str, asset_str, rates)
        transfer(u.id, target_user["tg_id"], bsv_amount, "BSV", tx_type="TRANSFER")
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await update.message.reply_text(
        f"✅ Enviados {fmt_bsv(bsv_amount)} a @{target.lstrip('@')}"
    )


async def cmd_pew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /pew 0.1 BSV")
        return
    rates = await get_rates()
    try:
        bsv_amount, asset, _ = await parse_amount(context.args[0], context.args[1], rates)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    targets = get_active_users(exclude_tg_id=u.id)
    if not targets:
        await update.message.reply_text("No hay usuarios activos.")
        return
    per_user = bsv_amount / len(targets)
    sent = 0
    for t in targets:
        try:
            transfer(u.id, t, per_user, "BSV", tx_type="PEW")
            sent += 1
        except ValueError:
            break
    await update.message.reply_text(f"📤 Enviado a {sent} usuarios ({fmt_bsv(per_user)} c/u)")


async def cmd_rain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 3:
        await update.message.reply_text("Uso: /rain 1 BSV 10")
        return
    rates = await get_rates()
    try:
        bsv_amount, asset, _ = await parse_amount(context.args[0], context.args[1], rates)
        n = int(context.args[2])
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    targets = get_active_users(exclude_tg_id=u.id)
    random.shuffle(targets)
    targets = targets[:n]
    if not targets:
        await update.message.reply_text("No hay suficientes usuarios activos.")
        return
    per_user = bsv_amount / len(targets)
    sent = 0
    for t in targets:
        try:
            transfer(u.id, t, per_user, "BSV", tx_type="RAIN")
            sent += 1
        except ValueError:
            break
    await update.message.reply_text(f"🌧 Lluvia enviada a {sent} usuarios ({fmt_bsv(per_user)} c/u)")


async def cmd_paylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /paylink 25 EUR Descripción opcional")
        return
    amount_str, asset_str = context.args[0], context.args[1]
    description = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    rates = await get_rates()
    try:
        bsv_amount, asset, _ = await parse_amount(amount_str, asset_str, rates)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    link_id = hashlib.sha256(f"{u.id}{time.time()}".encode()).hexdigest()[:10]
    create_paylink(link_id, u.id, bsv_amount, "BSV", description)
    url = f"{FRONTEND_URL}/pay?id={link_id}" if FRONTEND_URL else link_id
    await update.message.reply_text(f"🔗 Paylink creado:\n{url}")


async def cmd_mylinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    links = get_user_paylinks(u.id)
    if not links:
        await update.message.reply_text("No tienes paylinks creados.")
        return
    text = "🔗 *Tus paylinks:*\n\n"
    for l in links:
        status = "✅ Pagado" if l["paid"] else "⏳ Pendiente"
        text += f"`{l['id']}` — {l['amount']} {l['asset']} — {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_seal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /seal tu texto aquí")
        return
    text_to_seal = " ".join(context.args)
    h = hashlib.sha256(text_to_seal.encode()).hexdigest()
    await update.message.reply_text(f"🔒 Hash SHA-256 sellado:\n`{h}`", parse_mode="Markdown")


async def cmd_swap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 3:
        await update.message.reply_text("Uso: /swap 0.1 BSV LTC")
        return
    amount_str, from_asset, to_asset = context.args[0], context.args[1].upper(), context.args[2].upper()
    if from_asset not in ASSETS or to_asset not in ASSETS:
        await update.message.reply_text("Asset no soportado.")
        return
    rates = await get_rates()
    try:
        amount = float(amount_str.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Importe no válido.")
        return
    bal = get_balance(u.id, from_asset)
    if bal < amount:
        await update.message.reply_text(f"❌ Saldo {from_asset} insuficiente")
        return
    usd_value = amount * rates.get(from_asset, 1)
    to_amount = usd_value / rates.get(to_asset, 1)
    conn = get_conn()
    cur = conn.cursor()
    col_from, col_to = _asset_column(from_asset), _asset_column(to_asset)
    cur.execute(
        f"UPDATE users SET {col_from}={col_from}-%s, {col_to}={col_to}+%s, "
        f"updated_at=NOW() WHERE tg_id=%s",
        (amount, to_amount, u.id),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"🔄 Swap: {amount} {from_asset} → {to_amount:.8f} {to_asset}"
    )


async def _bet_game(update, context, win_prob: float, multiplier: float, emoji: str, name: str):
    u = update.effective_user
    if len(context.args) < 1:
        await update.message.reply_text(f"Uso: /{name.lower()} 0.01 BSV")
        return
    amount_str = context.args[0]
    asset_str = context.args[1] if len(context.args) > 1 else "BSV"
    rates = await get_rates()
    try:
        bsv_amount, asset, _ = await parse_amount(amount_str, asset_str, rates)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    bal = get_balance(u.id, "BSV")
    if bal < bsv_amount:
        await update.message.reply_text("❌ Saldo BSV insuficiente")
        return
    won = random.random() < win_prob
    try:
        transfer(u.id, -1, bsv_amount, "BSV", tx_type=f"{name}_BET")
    except ValueError:
        await update.message.reply_text("❌ Error al procesar la apuesta")
        return
    if won:
        payout = bsv_amount * multiplier
        credit(u.id, payout, "BSV", tx_type=f"{name}_WIN")
        await update.message.reply_text(
            f"{emoji} ¡Ganaste! +{fmt_bsv(payout)}"
        )
    else:
        await update.message.reply_text(f"{emoji} Perdiste {fmt_bsv(bsv_amount)}")


async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _bet_game(update, context, win_prob=0.48, multiplier=1.9, emoji="🎲", name="DICE")


async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _bet_game(update, context, win_prob=0.49, multiplier=1.94, emoji="🪙", name="FLIP")


async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _bet_game(update, context, win_prob=0.49, multiplier=1.94, emoji="✂️", name="RPS")


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard()
    if not rows:
        await update.message.reply_text("Todavía no hay datos.")
        return
    text = "🏆 *Top 10 BSV holders:*\n\n"
    for i, r in enumerate(rows, 1):
        name = r["username"] or r["first_name"] or "Anon"
        text += f"{i}. {name} — {float(r['bsv_balance']):.8f} BSV\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_stats()
    await update.message.reply_text(
        f"📊 *Estadísticas THCBOT*\n\n"
        f"Usuarios: {s['users']}\n"
        f"Transacciones: {s['transactions']}\n"
        f"BSV en circulación: {s['total_bsv']:.8f}",
        parse_mode="Markdown",
    )


async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    new_val = toggle_active(u.id)
    state = "activado ✅" if new_val else "desactivado ❌"
    await update.message.reply_text(f"Recepción de rain/pew: {state}")


async def cmd_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 3:
        await update.message.reply_text("Uso: /stream @usuario 0.000001 BSV")
        return
    target, rate_str, asset_str = context.args[0], context.args[1], context.args[2]
    target_user = get_user_by_username(target)
    if not target_user:
        await update.message.reply_text("Usuario no encontrado.")
        return
    try:
        rate = float(rate_str.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Tasa no válida.")
        return
    stream_id = create_stream(u.id, target_user["tg_id"], rate, asset_str.upper())
    await update.message.reply_text(f"🌊 Stream #{stream_id} iniciado hacia @{target.lstrip('@')}")


async def cmd_streamers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    streams = get_active_streams()
    if not streams:
        await update.message.reply_text("No hay streams activos.")
        return
    text = "🌊 *Streams activos:*\n\n"
    for s in streams:
        text += f"#{s['id']} — {s['rate_per_sec']} {s['asset']}/seg\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💚 Gracias por apoyar THCBOT.\n"
        "Usa /pay <monto> BSV @thcbot_owner para donar."
    )


async def cmd_connect_extension(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    code = create_otp(u.id)
    await update.message.reply_text(
        f"🔌 Código de vinculación: `{code}`\n"
        f"Introdúcelo en la extensión Chrome THCBOT Pay (expira en 5 min).",
        parse_mode="Markdown",
    )


async def cb_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()


# ══════════════════════════════════════════════════════════════════
# MAIN — arranque en modo polling (Railway)
# ══════════════════════════════════════════════════════════════════
def build_app() -> Application:
    app = Application.builder().token(TOKEN).build()

    commands = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("version", cmd_version),
        ("link", cmd_link),
        ("balance", cmd_balance),
        ("rate", cmd_rate),
        ("pay", cmd_pay),
        ("pew", cmd_pew),
        ("rain", cmd_rain),
        ("paylink", cmd_paylink),
        ("mylinks", cmd_mylinks),
        ("seal", cmd_seal),
        ("swap", cmd_swap),
        ("dice", cmd_dice),
        ("flip", cmd_flip),
        ("rps", cmd_rps),
        ("leaderboard", cmd_leaderboard),
        ("stats", cmd_stats),
        ("active", cmd_active),
        ("stream", cmd_stream),
        ("streamers", cmd_streamers),
        ("fund", cmd_fund),
        ("connect_extension", cmd_connect_extension),
    ]

    for cmd, fn in commands:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(cb_query_handler))

    return app


def main():
    log.info("THCBOT v1.0 — arrancando en modo polling...")
    app = build_app()
    log.info("Bot listo. Escuchando actualizaciones de Telegram...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
