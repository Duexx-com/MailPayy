"""
💎 MAILPAYY BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Users create Gmail accounts from bot-provided details and
sell them for cash. Firebase Realtime Database backend.
Public proof channel posts ONLY on withdrawal paid.

Render Free Tier + UptimeRobot friendly:
  • Webhook mode auto-enabled when RENDER_EXTERNAL_URL is set
  • Polling mode for local development
  • Simple webhook path (/tg-hook) — no colon, Render-safe

Install : pip install -r requirements.txt
Env     : BOT_TOKEN, ADMIN_IDS, SUPPORT_USERNAME,
          FIREBASE_DB_URL, FIREBASE_CREDENTIALS
Optional: REQUIRED_CHANNEL, PROOF_CHANNEL
          (Render auto-sets RENDER_EXTERNAL_URL and PORT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import html
import json
import logging
import os
import random
import secrets
import string
import time

import firebase_admin
from firebase_admin import credentials, db as rtdb
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

# ═══════════════════════════════════════════════════════════
#  ⚙️  CONFIG
# ═══════════════════════════════════════════════════════════

BOT_NAME          = "MailPayy"

BOT_TOKEN         = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS         = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
SUPPORT_USERNAME  = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
REQUIRED_CHANNEL  = os.getenv("REQUIRED_CHANNEL", "").strip()
PROOF_CHANNEL     = os.getenv("PROOF_CHANNEL", "").strip()
FIREBASE_DB_URL   = os.getenv("FIREBASE_DB_URL", "").strip()
FIREBASE_CRED_STR = os.getenv("FIREBASE_CREDENTIALS", "").strip()

RENDER_URL        = os.getenv("RENDER_EXTERNAL_URL", "").strip()
PORT              = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH      = "tg-hook"    # ✅ simple path — no colon, Render-safe

CUR              = "BDT"
WITHDRAW_METHODS = ["bKash", "Nagad", "Binance"]
DEFAULTS         = {"rate": 5.0, "min_withdraw": 50.0, "ref_bonus": 1.0}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
)
log = logging.getLogger("mailpayy")


def _validate_env():
    missing = []
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN":
        missing.append("BOT_TOKEN")
    if not ADMIN_IDS:
        missing.append("ADMIN_IDS")
    if not FIREBASE_DB_URL:
        missing.append("FIREBASE_DB_URL")
    if missing:
        raise SystemExit(f"❌ Missing required env vars: {', '.join(missing)}")
    if not SUPPORT_USERNAME:
        log.warning("⚠️ SUPPORT_USERNAME not set — placeholder shown to users.")
    if PROOF_CHANNEL:
        log.info("📢 Proof channel configured: %s", PROOF_CHANNEL)
    if RENDER_URL:
        log.info("🌐 Webhook mode — public URL: %s", RENDER_URL)


_validate_env()

# ═══════════════════════════════════════════════════════════
#  ✨  ANIMATED EMOJI SUPPORT
# ═══════════════════════════════════════════════════════════
#  Get real IDs with @JsonDumpBot — empty = plain emoji fallback.

ANIMATED: dict[str, str] = {
    "✨": "", "🔥": "", "💎": "", "👑": "", "⚡": "",
    "🎯": "", "🎉": "", "🚀": "", "🛡": "", "📊": "",
    "📜": "", "🎁": "", "💰": "", "💳": "", "🔔": "",
    "👋": "", "✅": "", "❌": "", "⏳": "", "⚠": "",
    "🔒": "", "📧": "", "👤": "", "🔑": "", "🏆": "",
    "💫": "",
}


def _emoji(char: str) -> str:
    eid = ANIMATED.get(char, "")
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
    return char


# ═══════════════════════════════════════════════════════════
#  🎨  STYLE / EMOJI CONSTANTS
# ═══════════════════════════════════════════════════════════

DIV    = "━━━━━━━━━━━━━━━━━━━━"
SUBDIV = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
ARROW  = "➤"
DOT    = "•"

STAR   = _emoji("✨")
FIRE   = _emoji("🔥")
GEM    = _emoji("💎")
CROWN  = _emoji("👑")
BOLT   = _emoji("⚡")
TARGET = _emoji("🎯")
PARTY  = _emoji("🎉")
ROCKET = _emoji("🚀")
SHIELD = _emoji("🛡")
CHART  = _emoji("📊")
SCROLL = _emoji("📜")
GIFT   = _emoji("🎁")
BAG    = _emoji("💰")
CARD   = _emoji("💳")
BELL   = _emoji("🔔")
WAVE   = _emoji("👋")
CHECK  = _emoji("✅")
CROSS  = _emoji("❌")
CLOCK  = _emoji("⏳")
WARN   = _emoji("⚠")
LOCK   = _emoji("🔒")
MAIL   = _emoji("📧")
USER   = _emoji("👤")
KEY    = _emoji("🔑")
TROPHY = _emoji("🏆")
SPARK  = _emoji("💫")


def money(x) -> str:
    return f"<b>{float(x):,.2f}</b> {CUR}"


def esc(s) -> str:
    return html.escape(str(s or ""))


def mono(s) -> str:
    return f"<code>{esc(s)}</code>"


def mask_name(name: str) -> str:
    if not name:
        return "Anonymous"
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0][:3] + "***"
    return parts[0] + " " + "".join(p[0] + "." for p in parts[1:] if p)


def mask_addr(addr: str) -> str:
    if not addr:
        return "***"
    a = str(addr).strip()
    if len(a) <= 4:
        return "***"
    return "***" + a[-4:]


# ═══════════════════════════════════════════════════════════
#  🔌  FIREBASE
# ═══════════════════════════════════════════════════════════

_cred = credentials.Certificate(
    json.loads(FIREBASE_CRED_STR) if FIREBASE_CRED_STR else "serviceAccountKey.json"
)
firebase_admin.initialize_app(_cred, {"databaseURL": FIREBASE_DB_URL})
R = rtdb.reference
A = asyncio.to_thread


def load_settings():
    cur = R("settings").get() or {}
    for k, v in DEFAULTS.items():
        if k not in cur:
            R(f"settings/{k}").set(v)
            cur[k] = v
    return {k: float(v) for k, v in cur.items()}


SETTINGS = load_settings()


def cfg(key):
    return SETTINGS[key]


def add_num(path, amt):
    R(path).transaction(lambda cur: (cur or 0) + amt)


def claim(path, old, new):
    got = {"v": False}

    def fn(cur):
        if cur == old:
            got["v"] = True
            return new
        got["v"] = False
        return cur

    R(path).transaction(fn)
    return got["v"]


_issue_locks: dict[int, asyncio.Lock] = {}


def _lock_for(uid: int) -> asyncio.Lock:
    lock = _issue_locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _issue_locks[uid] = lock
    return lock


# ═══════════════════════════════════════════════════════════
#  🧬  IDENTITY GENERATOR
# ═══════════════════════════════════════════════════════════

FIRST = ["Rafiq", "Tanvir", "Nusrat", "Sabbir", "Mim", "Arif", "Jannat", "Hasan",
         "Rumana", "Imran", "Sadia", "Fahim", "Tasnim", "Rakib", "Mitu", "Shuvo",
         "Farhana", "Nayeem", "Lamia", "Sohan"]
LAST  = ["Ahmed", "Hossain", "Rahman", "Khan", "Islam", "Akter", "Chowdhury",
         "Uddin", "Sarker", "Mia", "Begum", "Mahmud", "Karim", "Sultana",
         "Biswas", "Talukdar", "Haque", "Sheikh", "Mondal", "Roy"]


def gen_password():
    chars = string.ascii_letters + string.digits
    pw = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("@#$%*"),
    ]
    pw += [secrets.choice(chars) for _ in range(8)]
    random.shuffle(pw)
    return "".join(pw)


def gen_identity():
    while True:
        first, last = random.choice(FIRST), random.choice(LAST)
        email = f"{first}{last}{random.randint(1000, 99999)}".lower()
        if R(f"emails/{email}").get() is None:
            R(f"emails/{email}").set(True)
            return first, last, email, gen_password()


# ═══════════════════════════════════════════════════════════
#  🗄  DATABASE HELPERS
# ═══════════════════════════════════════════════════════════

def get_user(uid):
    return R(f"users/{uid}").get()


def ensure_user_sync(u, ref=None):
    user = get_user(u.id)
    if user is None:
        ref_by = ref if ref and ref != u.id and get_user(ref) else 0
        R(f"users/{u.id}").set({
            "name": u.full_name, "username": u.username or "",
            "balance": 0, "total_earned": 0, "banned": False,
            "ref_by": ref_by, "ref_count": 0, "joined": int(time.time()),
        })
        if ref_by:
            add_num(f"users/{ref_by}/ref_count", 1)
        user = get_user(u.id)
    return user


def issue_sync(uid, regenerate):
    accs = R(f"accounts/{uid}").get() or {}
    issued = [(k, v) for k, v in accs.items() if v.get("status") == "issued"]
    if issued and regenerate:
        for k, _ in issued:
            R(f"accounts/{uid}/{k}").delete()
        issued = []
    if issued:
        k, v = issued[0]
        v["id"] = k
        return v
    first, last, email, pw = gen_identity()
    rec = {
        "first": first, "last": last, "email": email, "password": pw,
        "status": "issued", "rate": cfg("rate"), "created": int(time.time()),
    }
    rec["id"] = R(f"accounts/{uid}").push(rec).key
    return rec


def cancel_sync(uid, aid):
    if R(f"accounts/{uid}/{aid}/status").get() == "issued":
        R(f"accounts/{uid}/{aid}").delete()


def submit_sync(uid, aid):
    if not claim(f"accounts/{uid}/{aid}/status", "issued", "pending"):
        return None
    add_num("stats/pending_acc", 1)
    acc = R(f"accounts/{uid}/{aid}").get()
    acc["id"] = aid
    return acc


def decide_acc_sync(uid, aid, approve):
    if not claim(f"accounts/{uid}/{aid}/status",
                 "pending", "approved" if approve else "rejected"):
        return None
    add_num("stats/pending_acc", -1)
    acc = R(f"accounts/{uid}/{aid}").get()
    if approve and acc:
        add_num("stats/approved_acc", 1)
        add_num(f"users/{uid}/balance", acc["rate"])
        add_num(f"users/{uid}/total_earned", acc["rate"])

        ref = (get_user(uid) or {}).get("ref_by")
        if ref:
            got = {"v": False}

            def fn(cur):
                if cur:
                    return cur
                got["v"] = True
                return True

            R(f"users/{uid}/ref_bonus_paid").transaction(fn)
            if got["v"]:
                add_num(f"users/{ref}/balance", cfg("ref_bonus"))
                add_num(f"users/{ref}/total_earned", cfg("ref_bonus"))
    return acc


def count_status(uid):
    c = {}
    for v in (R(f"accounts/{uid}").get() or {}).values():
        c[v.get("status")] = c.get(v.get("status"), 0) + 1
    return c


def history_sync(uid):
    accs = [v for v in (R(f"accounts/{uid}").get() or {}).values()
            if v.get("status") != "issued"]
    wds = list((R(f"withdrawals/{uid}").get() or {}).items())
    accs.sort(key=lambda x: x.get("created", 0), reverse=True)
    wds.sort(key=lambda x: x[1].get("created", 0), reverse=True)
    return accs[:10], wds[:5]


def deduct_sync(uid, amt):
    ok = {"v": False}

    def fn(cur):
        cur = cur or 0
        if cur < amt:
            ok["v"] = False
            return cur
        ok["v"] = True
        return cur - amt

    R(f"users/{uid}/balance").transaction(fn)
    return ok["v"]


def create_wd_sync(uid, method, addr, amt):
    if not deduct_sync(uid, amt):
        return None
    try:
        key = R(f"withdrawals/{uid}").push({
            "method": method, "address": addr, "amount": amt,
            "status": "pending", "created": int(time.time()),
        }).key
    except Exception:
        log.exception("withdrawal push failed — refunding user")
        add_num(f"users/{uid}/balance", amt)
        return None
    add_num("stats/pending_wd", 1)
    return key


def decide_wd_sync(uid, wid, paid):
    if not claim(f"withdrawals/{uid}/{wid}/status",
                 "pending", "paid" if paid else "rejected"):
        return None
    add_num("stats/pending_wd", -1)
    w = R(f"withdrawals/{uid}/{wid}").get()
    if not paid and w:
        add_num(f"users/{uid}/balance", w["amount"])
    return w


def stats_sync():
    users = R("users").get(shallow=True) or {}
    return len(users), (R("stats").get() or {})


def set_cfg_sync(key, val):
    R(f"settings/{key}").set(val)
    SETTINGS[key] = val


def set_ban_sync(uid, banned):
    if get_user(uid) is None:
        return False
    R(f"users/{uid}/banned").set(banned)
    return True


def add_balance_sync(uid, amt):
    if get_user(uid) is None:
        return False
    add_num(f"users/{uid}/balance", amt)
    return True


def all_user_ids_sync():
    return [k for k, v in (R("users").get() or {}).items() if not v.get("banned")]


# ═══════════════════════════════════════════════════════════
#  📢  PROOF CHANNEL
# ═══════════════════════════════════════════════════════════

async def post_payout_proof(ctx, user_name: str, method: str, addr: str, amount: float):
    if not PROOF_CHANNEL:
        return
    text = (
        f"{ROCKET} <b>WITHDRAWAL PAID</b> {ROCKET}\n"
        f"{DIV}\n"
        f"{USER} <b>User:</b> {esc(mask_name(user_name))}\n"
        f"{CARD} <b>Method:</b> {esc(method)}\n"
        f"{MAIL} <b>Account:</b> {mono(mask_addr(addr))}\n"
        f"{BAG} <b>Amount:</b> {money(amount)}\n"
        f"{CLOCK} <b>Time:</b> {time.strftime('%d %b %Y • %H:%M')}\n"
        f"{DIV}\n"
        f"{FIRE} <i>Instant payout — verified & paid.</i>"
    )
    try:
        await ctx.bot.send_message(
            PROOF_CHANNEL, text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        log.info("proof posted for %s (%s)", mask_name(user_name), method)
    except TelegramError as e:
        log.warning("proof channel post failed: %s", e)


# ═══════════════════════════════════════════════════════════
#  🧰  HELPERS
# ═══════════════════════════════════════════════════════════

MENU_SELL     = f"{GEM} Sell Gmail"
MENU_ACCOUNT  = f"{CROWN} My Account"
MENU_WITHDRAW = f"{CARD} Withdraw"
MENU_HISTORY  = f"{CHART} History"
MENU_REFERRAL = f"{GIFT} Referral"
MENU_SUPPORT  = f"{BELL} Support"


def main_menu():
    return ReplyKeyboardMarkup(
        [
            [MENU_SELL,     MENU_ACCOUNT],
            [MENU_WITHDRAW, MENU_HISTORY],
            [MENU_REFERRAL, MENU_SUPPORT],
        ],
        resize_keyboard=True,
    )


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def _typing(ctx, chat_id):
    try:
        await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        pass


async def notify_admins(ctx, text, markup=None):
    for a in ADMIN_IDS:
        try:
            await ctx.bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception as e:
            log.warning("admin notify failed for %s: %s", a, e)


_channel_cache: dict[int, tuple[float, bool]] = {}
_CHANNEL_TTL = 60


async def _channel_ok(ctx, uid: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    now = time.time()
    cached = _channel_cache.get(uid)
    if cached and now - cached[0] < _CHANNEL_TTL:
        return cached[1]
    try:
        m = await ctx.bot.get_chat_member(REQUIRED_CHANNEL, uid)
        ok = m.status not in ("left", "kicked")
    except Exception as e:
        log.warning("channel check failed: %s", e)
        ok = True
    _channel_cache[uid] = (now, ok)
    return ok


async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    u = update.effective_user
    user = await A(ensure_user_sync, u, None)
    if user.get("banned"):
        await update.effective_message.reply_text(
            f"{LOCK} <b>You are banned from using {BOT_NAME}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return False
    if not await _channel_ok(ctx, u.id):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel",
                                  url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("✅ I Joined", callback_data="chk")],
        ])
        await update.effective_message.reply_text(
            f"{BELL} <b>Please join our channel to continue.</b>",
            parse_mode=ParseMode.HTML, reply_markup=kb,
        )
        return False
    return True


# ═══════════════════════════════════════════════════════════
#  👤  USER COMMANDS
# ═══════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ref = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else None
    await A(ensure_user_sync, update.effective_user, ref)
    if not await guard(update, ctx):
        return
    ctx.user_data.clear()
    name = esc(update.effective_user.first_name)
    text = (
        f"{STAR} <b>WELCOME TO {BOT_NAME.upper()}</b> {STAR}\n"
        f"{DIV}\n"
        f"{WAVE} Hey <b>{name}</b>!\n"
        f"{GEM} Earn <b>{money(cfg('rate'))}</b> per approved Gmail\n"
        f"{DIV}\n"
        f"{ARROW} <b>Step 1</b> — Tap {MENU_SELL}\n"
        f"{ARROW} <b>Step 2</b> — Create the account with our details\n"
        f"{ARROW} <b>Step 3</b> — Submit & get paid automatically\n"
        f"{DIV}\n"
        f"{FIRE} <i>Your first sale awaits — start now!</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def issue_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE, regenerate=False):
    uid = update.effective_user.id
    await _typing(ctx, update.effective_chat.id)
    async with _lock_for(uid):
        row = await A(issue_sync, uid, regenerate)

    body = (
        f"{USER} <b>First Name</b>\n   {mono(row['first'])}\n"
        f"{USER} <b>Last Name</b>\n   {mono(row['last'])}\n"
        f"{MAIL} <b>Email</b>\n   {mono(row['email'] + '@gmail.com')}\n"
        f"{KEY} <b>Password</b>\n   {mono(row['password'])}\n"
        f"{DIV}\n"
        f"{BAG} <b>Reward:</b> {money(row['rate'])}"
    )
    footer = (
        f"{WARN} Use these <b>exact</b> details.\n"
        f"{ARROW} Don't change the password\n"
        f"{ARROW} Don't add recovery info\n"
        f"{DIV}\n"
        f"{ARROW} Finished? Tap <b>Done</b> below 👇"
    )
    text = f"{STAR} <b>NEW GMAIL DETAILS</b> {STAR}\n{DIV}\n{body}\n{DIV}\n{footer}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ DONE — Submit for Review", callback_data=f"done:{row['id']}")],
        [
            InlineKeyboardButton("🔄 New Details", callback_data="new"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{row['id']}"),
        ],
    ])
    await ctx.bot.send_message(update.effective_chat.id, text,
                               parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_account(update, ctx):
    uid = update.effective_user.id
    user = await A(get_user, uid)
    c = await A(count_status, uid)
    body = (
        f"{USER} <b>ID:</b> {mono(uid)}\n"
        f"{BAG} <b>Balance:</b> {money(user.get('balance', 0))}\n"
        f"{CHART} <b>Total Earned:</b> {money(user.get('total_earned', 0))}\n"
        f"{SUBDIV}\n"
        f"{CHECK} <b>Approved:</b> {c.get('approved', 0)}\n"
        f"{CLOCK} <b>Pending:</b>  {c.get('pending', 0)}\n"
        f"{CROSS} <b>Rejected:</b> {c.get('rejected', 0)}"
    )
    text = f"{CROWN} <b>MY ACCOUNT</b> {CROWN}\n{DIV}\n{body}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_history(update, ctx):
    icons = {"approved": CHECK, "pending": CLOCK, "rejected": CROSS, "paid": CHECK}
    accs, wds = await A(history_sync, update.effective_user.id)

    acc_lines = "\n".join(
        f"{icons.get(a['status'], CLOCK)} {mono(a['email'] + '@gmail.com')} — {a['status']}"
        for a in accs
    ) or f"{DOT} <i>No submissions yet</i>"

    wd_lines = "\n".join(
        f"{icons.get(w['status'], CLOCK)} {money(w['amount'])} via {esc(w['method'])} — {w['status']}"
        for _, w in wds
    ) or f"{DOT} <i>No withdrawals yet</i>"

    text = (
        f"{SCROLL} <b>RECENT ACTIVITY</b> {SCROLL}\n"
        f"{DIV}\n"
        f"{MAIL} <b>Gmail Submissions</b>\n"
        f"{SUBDIV}\n{acc_lines}\n\n"
        f"{CARD} <b>Withdrawals</b>\n"
        f"{SUBDIV}\n{wd_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_referral(update, ctx):
    uid = update.effective_user.id
    user = await A(get_user, uid)
    link = f"https://t.me/{ctx.bot.username}?start={uid}"
    text = (
        f"{GIFT} <b>REFERRAL PROGRAM</b> {GIFT}\n"
        f"{DIV}\n"
        f"{TARGET} Invite friends — earn <b>{money(cfg('ref_bonus'))}</b>\n"
        f"    when their <b>first</b> Gmail is approved.\n"
        f"{SUBDIV}\n"
        f"{ARROW} <b>Your Link:</b>\n"
        f"<code>{esc(link)}</code>\n"
        f"{SUBDIV}\n"
        f"{USER} <b>Invited:</b> {user.get('ref_count', 0)} friends\n"
        f"{DIV}\n"
        f"{FIRE} <i>Share your link & grow together!</i>"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📤 Share Link",
                             url=f"https://t.me/share/url?url={link}&text=Join%20and%20earn%20with%20Gmail!")
    ]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def start_withdraw(update, ctx):
    user = await A(get_user, update.effective_user.id)
    bal = user.get("balance", 0)
    if bal < cfg("min_withdraw"):
        text = (
            f"{LOCK} <b>Minimum Withdraw is {money(cfg('min_withdraw'))}</b>\n"
            f"{DIV}\n"
            f"{BAG} <b>Your Balance:</b> {money(bal)}\n"
            f"{ARROW} Sell more Gmails to reach the minimum!"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💚 bKash",   callback_data="wd:bKash"),
        InlineKeyboardButton("🧡 Nagad",   callback_data="wd:Nagad"),
        InlineKeyboardButton("💛 Binance", callback_data="wd:Binance"),
    ]])
    text = (
        f"{CARD} <b>WITHDRAW FUNDS</b> {CARD}\n"
        f"{DIV}\n"
        f"{BAG} <b>Available:</b> {money(bal)}\n"
        f"{ARROW} Choose your payout method below 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  ⌨️  TEXT ROUTER
# ═══════════════════════════════════════════════════════════

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx):
        return

    text = update.message.text.strip()
    st   = ctx.user_data.get("state")
    uid  = update.effective_user.id

    menu = {
        MENU_SELL:     lambda: issue_account(update, ctx),
        MENU_ACCOUNT:  lambda: show_account(update, ctx),
        MENU_WITHDRAW: lambda: start_withdraw(update, ctx),
        MENU_HISTORY:  lambda: show_history(update, ctx),
        MENU_REFERRAL: lambda: show_referral(update, ctx),
        MENU_SUPPORT:  lambda: update.message.reply_text(
                            f"{BELL} <b>Support</b>\n{DIV}\n"
                            f"{ARROW} Contact: @{SUPPORT_USERNAME}",
                            parse_mode=ParseMode.HTML),
    }
    if text in menu:
        ctx.user_data.clear()
        await menu[text]()
        return

    if st == "wd_addr":
        ctx.user_data["addr"] = text
        ctx.user_data["state"] = "wd_amt"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="wd_cancel")]])
        await update.message.reply_text(
            f"{CARD} <b>Enter the withdrawal amount</b>\n"
            f"{DIV}\n"
            f"{ARROW} Minimum: {money(cfg('min_withdraw'))}",
            parse_mode=ParseMode.HTML, reply_markup=kb,
        )
        return

    if st == "wd_amt":
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text(f"{CROSS} Please send a valid number.")
            return
        user = await A(get_user, uid)
        bal  = user.get("balance", 0)
        if amt < cfg("min_withdraw") or amt > bal:
            await update.message.reply_text(
                f"{CROSS} Amount must be between "
                f"{money(cfg('min_withdraw'))} and {money(bal)}.",
                parse_mode=ParseMode.HTML,
            )
            return
        method, addr = ctx.user_data["method"], ctx.user_data["addr"]
        wid = await A(create_wd_sync, uid, method, addr, amt)
        ctx.user_data.clear()
        if wid is None:
            await update.message.reply_text(
                f"{CROSS} <b>Insufficient balance.</b>",
                parse_mode=ParseMode.HTML, reply_markup=main_menu(),
            )
            return
        await update.message.reply_text(
            f"{CHECK} <b>Withdrawal Submitted!</b>\n"
            f"{DIV}\n"
            f"{CARD} Method: <b>{esc(method)}</b>\n"
            f"{BAG} Amount: {money(amt)}\n"
            f"{CLOCK} Status: <b>Pending</b>\n"
            f"{DIV}\n"
            f"{ARROW} You'll be notified once it's reviewed.",
            parse_mode=ParseMode.HTML, reply_markup=main_menu(),
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Paid",   callback_data=f"wd_ok:{uid}:{wid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wd_no:{uid}:{wid}"),
        ]])
        await notify_admins(
            ctx,
            f"{CARD} <b>NEW WITHDRAWAL REQUEST</b>\n{DIV}\n"
            f"{USER} User: <b>{esc(update.effective_user.full_name)}</b> ({mono(uid)})\n"
            f"{CARD} Method: <b>{esc(method)}</b>\n"
            f"{MAIL} Address: {mono(addr)}\n"
            f"{BAG} Amount: {money(amt)}",
            kb,
        )
        return


# ═══════════════════════════════════════════════════════════
#  🔔  CALLBACKS
# ═══════════════════════════════════════════════════════════

async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    uid  = q.from_user.id
    await q.answer()

    if data == "chk":
        if await guard(update, ctx):
            await q.message.reply_text(
                f"{CHECK} Thanks! Send /start to begin.",
                reply_markup=main_menu(),
            )
        return

    if data == "wd_cancel":
        ctx.user_data.clear()
        await q.edit_message_text(f"{CROSS} Withdrawal cancelled.")
        return

    if data.startswith(("ok:", "no:", "wd_ok:", "wd_no:")):
        if not is_admin(uid):
            await q.answer("Not allowed.", show_alert=True)
            return
        action, tuid, rid = data.split(":")
        if action in ("ok", "no"):
            acc = await A(decide_acc_sync, tuid, rid, action == "ok")
            if not acc:
                await q.edit_message_text(f"{WARN} Already handled.")
                return
            if action == "ok":
                msg = (f"{CHECK} <b>Approved!</b>\n{DIV}\n"
                       f"{MAIL} {mono(acc['email'] + '@gmail.com')}\n"
                       f"{BAG} +{money(acc['rate'])} added to your balance {PARTY}")
            else:
                msg = (f"{CROSS} <b>Rejected</b>\n{DIV}\n"
                       f"{MAIL} {mono(acc['email'] + '@gmail.com')}")
            await q.edit_message_text(
                q.message.text + f"\n\n{DIV}\n➡️ <b>{'APPROVED' if action == 'ok' else 'REJECTED'}</b>",
                parse_mode=ParseMode.HTML,
            )
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            w = await A(decide_wd_sync, tuid, rid, action == "wd_ok")
            if not w:
                await q.edit_message_text(f"{WARN} Already handled.")
                return
            msg = (
                f"{CHECK} <b>Withdrawal Paid</b>\n{DIV}\n"
                f"{BAG} {money(w['amount'])} sent via <b>{esc(w['method'])}</b> {ROCKET}"
                if action == "wd_ok" else
                f"{CROSS} <b>Withdrawal Rejected</b>\n{DIV}\n"
                f"{BAG} {money(w['amount'])} refunded to your balance."
            )
            await q.edit_message_text(
                q.message.text + f"\n\n{DIV}\n➡️ <b>{'PAID' if action == 'wd_ok' else 'REJECTED'}</b>",
                parse_mode=ParseMode.HTML,
            )
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass

            if action == "wd_ok":
                u = await A(get_user, int(tuid))
                await post_payout_proof(
                    ctx,
                    user_name=(u or {}).get("name", ""),
                    method=w["method"],
                    addr=w["address"],
                    amount=w["amount"],
                )
        return

    if not await guard(update, ctx):
        return

    if data == "new":
        try:
            await q.message.delete()
        except Exception:
            pass
        await issue_account(update, ctx, regenerate=True)

    elif data.startswith("cancel:"):
        await A(cancel_sync, uid, data.split(":")[1])
        await q.edit_message_text(f"{CROSS} Cancelled.")

    elif data.startswith("done:"):
        acc = await A(submit_sync, uid, data.split(":")[1])
        if not acc:
            await q.edit_message_text(f"{WARN} This request is no longer valid.")
            return
        await q.edit_message_text(
            f"{CLOCK} <b>Submitted!</b>\n{DIV}\n"
            f"{MAIL} {mono(acc['email'] + '@gmail.com')}\n"
            f"{DIV}\n{ARROW} Waiting for admin approval…",
            parse_mode=ParseMode.HTML,
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"ok:{uid}:{acc['id']}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"no:{uid}:{acc['id']}"),
        ]])
        await notify_admins(
            ctx,
            f"{BELL} <b>NEW GMAIL SUBMISSION</b>\n{DIV}\n"
            f"{USER} User: <b>{esc(q.from_user.full_name)}</b> ({mono(uid)})\n"
            f"{MAIL} Email: {mono(acc['email'] + '@gmail.com')}\n"
            f"{KEY} Password: {mono(acc['password'])}\n"
            f"{BAG} Reward: {money(acc['rate'])}",
            kb,
        )

    elif data.startswith("wd:"):
        method = data.split(":")[1]
        ctx.user_data.update({"state": "wd_addr", "method": method})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="wd_cancel")]])
        await q.edit_message_text(
            f"{CARD} <b>{esc(method)} Payout</b>\n{DIV}\n"
            f"{ARROW} Send your <b>{esc(method)}</b> number / address:",
            parse_mode=ParseMode.HTML, reply_markup=kb,
        )


# ═══════════════════════════════════════════════════════════
#  🛠  ADMIN COMMANDS
# ═══════════════════════════════════════════════════════════

def admin_only(fn):
    async def wrapper(update, ctx):
        if is_admin(update.effective_user.id):
            await fn(update, ctx)
    return wrapper


@admin_only
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n, s = await A(stats_sync)
    text = (
        f"{CROWN} <b>{BOT_NAME} — ADMIN PANEL</b> {CROWN}\n"
        f"{DIV}\n"
        f"{USER} <b>Total Users:</b> {n}\n"
        f"{CLOCK} <b>Pending Gmail:</b> {s.get('pending_acc', 0)}\n"
        f"{CHECK} <b>Approved Gmail:</b> {s.get('approved_acc', 0)}\n"
        f"{CARD} <b>Pending Withdraws:</b> {s.get('pending_wd', 0)}\n"
        f"{SUBDIV}\n"
        f"{BELL} <b>Proof Channel:</b> "
        f"{'✅ ' + esc(PROOF_CHANNEL) if PROOF_CHANNEL else '❌ not configured'}\n"
        f"{SUBDIV}\n"
        f"{GEM} Rate: {money(cfg('rate'))}\n"
        f"{BAG} Min Withdraw: {money(cfg('min_withdraw'))}\n"
        f"{GIFT} Ref Bonus: {money(cfg('ref_bonus'))}\n"
        f"{SUBDIV}\n"
        f"{ARROW} <b>Commands</b>\n"
        f"{DOT} /setrate 6\n"
        f"{DOT} /setmin 100\n"
        f"{DOT} /setref 1\n"
        f"{DOT} /ban USER_ID\n"
        f"{DOT} /unban USER_ID\n"
        f"{DOT} /addbal USER_ID AMOUNT\n"
        f"{DOT} /broadcast message\n"
        f"{DOT} /proof — test proof channel"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@admin_only
async def set_cfg_cmd(update, ctx):
    cmd = update.message.text.split()[0].split("@")[0]
    key = {"/setrate": "rate", "/setmin": "min_withdraw", "/setref": "ref_bonus"}[cmd]
    try:
        val = float(ctx.args[0])
        if val <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(f"{CROSS} Usage: {cmd} <positive number>")
        return
    await A(set_cfg_sync, key, val)
    await update.message.reply_text(
        f"{CHECK} <b>{key.replace('_', ' ').title()}</b> → <code>{val}</code>",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def ban_cmd(update, ctx):
    ban = update.message.text.startswith("/ban")
    try:
        ok = await A(set_ban_sync, int(ctx.args[0]), ban)
        await update.message.reply_text(
            f"{CHECK} {'Banned' if ban else 'Unbanned'}." if ok else f"{CROSS} User not found."
        )
    except (IndexError, ValueError):
        await update.message.reply_text(f"{CROSS} Usage: /ban USER_ID")


@admin_only
async def addbal_cmd(update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(ctx.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text(f"{CROSS} Usage: /addbal USER_ID AMOUNT")
        return
    ok = await A(add_balance_sync, uid, amt)
    if ok:
        direction = "added to" if amt >= 0 else "deducted from"
        await update.message.reply_text(
            f"{CHECK} {money(abs(amt))} {direction} user {mono(uid)}.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"{CROSS} User not found.")


@admin_only
async def broadcast_cmd(update, ctx):
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text(f"{CROSS} Usage: /broadcast message")
        return
    ids = await A(all_user_ids_sync)
    sent = 0
    failed = 0
    for uid in ids:
        for attempt in range(2):
            try:
                await ctx.bot.send_message(int(uid), msg)
                sent += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                failed += 1
                break
        await asyncio.sleep(0.05)
    await update.message.reply_text(
        f"{ROCKET} <b>Broadcast Complete</b>\n{DIV}\n"
        f"{CHECK} Sent: <b>{sent}</b>\n"
        f"{CROSS} Failed: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def proof_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not PROOF_CHANNEL:
        await update.message.reply_text(
            f"{WARN} <b>Proof channel not configured.</b>\n{DIV}\n"
            f"{ARROW} Set env var: <code>PROOF_CHANNEL=@your_channel</code>\n"
            f"{ARROW} Then make the bot an admin in that channel.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await ctx.bot.send_message(
            PROOF_CHANNEL,
            f"{ROCKET} <b>WITHDRAWAL PAID</b> {ROCKET}\n"
            f"{DIV}\n"
            f"{USER} <b>User:</b> Test U.\n"
            f"{CARD} <b>Method:</b> bKash\n"
            f"{MAIL} <b>Account:</b> {mono('***1234')}\n"
            f"{BAG} <b>Amount:</b> {money(100.0)}\n"
            f"{CLOCK} <b>Time:</b> {time.strftime('%d %b %Y • %H:%M')}\n"
            f"{DIV}\n"
            f"{FIRE} <i>Instant payout — verified & paid.</i>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await update.message.reply_text(
            f"{CHECK} <b>Test proof sent to</b> {esc(PROOF_CHANNEL)}",
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as e:
        await update.message.reply_text(
            f"{CROSS} <b>Cannot post:</b> {esc(e)}\n{DIV}\n"
            f"{WARN} Make sure the bot is <b>admin</b> in {esc(PROOF_CHANNEL)}.",
            parse_mode=ParseMode.HTML,
        )


# ═══════════════════════════════════════════════════════════
#  🌐  HEALTH CHECK
# ═══════════════════════════════════════════════════════════

async def _health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")


# ═══════════════════════════════════════════════════════════
#  🚀  MAIN
# ═══════════════════════════════════════════════════════════

async def _error_handler(update, ctx):
    log.exception("Unhandled error", exc_info=ctx.error)


def _build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", _health))
    app.add_handler(CommandHandler("admin", admin_cmd))
    for c in ("setrate", "setmin", "setref"):
        app.add_handler(CommandHandler(c, set_cfg_cmd))
    app.add_handler(CommandHandler(["ban", "unban"], ban_cmd))
    app.add_handler(CommandHandler("addbal", addbal_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("proof", proof_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(_error_handler)
    return app


def main():
    app = _build_app()

    if RENDER_URL:
        # ── PRODUCTION: webhook mode (simple path, Render-safe) ──
        webhook_url = f"{RENDER_URL.rstrip('/')}/{WEBHOOK_PATH}"
        log.info("🌐 Starting %s in WEBHOOK mode", BOT_NAME)
        log.info("   Listen  : 0.0.0.0:%s", PORT)
        log.info("   Webhook : %s", webhook_url)

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        # ── LOCAL DEV: polling mode ──
        log.info("💻 Starting %s in POLLING mode (local dev)", BOT_NAME)
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
