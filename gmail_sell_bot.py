"""
💎 MAILPAYY BOT (NO OTP | PAYOUT MINI APP | 100K+ SCALABLE | EN & BN)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Users create Gmail accounts from bot-provided details and
sell them for cash. Firebase Realtime Database backend.
Withdrawals are made from a premium web page (Telegram Mini App)
served by this same process. Public proof channel posts ONLY
when a withdrawal is paid.

Install : pip install python-telegram-bot==21.6 firebase-admin aiohttp
Env     : BOT_TOKEN, ADMIN_IDS, SUPPORT_USERNAME,
          FIREBASE_DB_URL, FIREBASE_CREDENTIALS
Optional: REQUIRED_CHANNEL, PROOF_CHANNEL, WEBAPP_URL
          (Render auto-sets RENDER_EXTERNAL_URL and PORT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import hashlib
import hmac
import html
import json
import logging
import math
import os
import random
import re
import secrets
import string
import time
from urllib.parse import parse_qsl

import firebase_admin
from aiohttp import web
from firebase_admin import credentials, db as rtdb
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update,
    WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
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
WEBAPP_URL        = (os.getenv("WEBAPP_URL", "").strip() or RENDER_URL).rstrip("/")
PORT              = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH      = "tg-hook"
WEBHOOK_SECRET    = hashlib.sha256(("wh" + BOT_TOKEN).encode()).hexdigest()[:48]

CUR              = "BDT"
DEFAULTS         = {"rate": 5.0, "min_withdraw": 50.0, "ref_bonus": 1.0}
METHODS          = ("bKash", "Nagad", "Binance")

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
    if not WEBAPP_URL:
        log.warning("⚠️ WEBAPP_URL / RENDER_EXTERNAL_URL not set — payout page will not open.")


_validate_env()

# ═══════════════════════════════════════════════════════════
#  ✨  ANIMATED EMOJIS
# ═══════════════════════════════════════════════════════════

ANIMATED: dict[str, str] = {
    "✨": "5321275567060081617", "🔥": "5316521303159150257",
    "💎": "5323787699962845141", "👑": "5321487312630782711",
    "⚡": "5321023426538248035", "🎯": "5321453641127368889",
    "🎉": "5321226451634427971", "🚀": "5321319194712937700",
    "🛡": "5321398766708005471", "📊": "5321048500796397331",
    "📜": "5321166039407994885", "🎁": "5321242343894227319",
    "💰": "5323338909876335012", "💳": "5321210104552692543",
    "🔔": "5321056607605890211", "👋": "5321114585075816582",
    "✅": "5321312842670217992", "❌": "5321174383149554365",
    "⏳": "5321188246704200133", "⚠️": "5321102186342142663",
    "🔒": "5321354251410413621", "📧": "5321288907731835199",
    "👤": "5321378196045421001", "🔑": "5321428910323925122",
    "🏆": "5321401925184231044", "💫": "5321238900154217003",
}


def _emoji(char: str) -> str:
    eid = ANIMATED.get(char, "")
    return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>' if eid else char


DIV    = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SUBDIV = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DOT    = "•"

STAR, FIRE, GEM, CROWN = _emoji("✨"), _emoji("🔥"), _emoji("💎"), _emoji("👑")
ARROW, TARGET, PARTY = _emoji("⚡"), _emoji("🎯"), _emoji("🎉")
ROCKET, CHART, SCROLL = _emoji("🚀"), _emoji("📊"), _emoji("📜")
GIFT, BAG, CARD, BELL = _emoji("🎁"), _emoji("💰"), _emoji("💳"), _emoji("🔔")
WAVE, CHECK, CROSS = _emoji("👋"), _emoji("✅"), _emoji("❌")
CLOCK, WARN, LOCK = _emoji("⏳"), _emoji("⚠️"), _emoji("🔒")
MAIL, USER, KEY, SPARK = _emoji("📧"), _emoji("👤"), _emoji("🔑"), _emoji("💫")

# ═══════════════════════════════════════════════════════════
#  🌐  TEXT LOCALIZATION (EN & BN)
# ═══════════════════════════════════════════════════════════

LANGS = {
    "en": {
        "sell": "💎 Sell Gmail",
        "account": "👑 My Account",
        "withdraw": "💳 Withdraw",
        "history": "📊 History",
        "referral": "🎁 Referral",
        "support": "🔔 Support",
        "lang_btn": "🇧🇩 ভাষা পরিবর্তন করুন (Bangla)",
        "welcome": (
            f"{STAR} <b>WELCOME TO {{bot_name}}</b> {STAR}\n"
            f"{DIV}\n"
            f"{WAVE} Hello <b>{{name}}</b>!\n"
            f"{GEM} Earn <b>{{rate}}</b> per approved Gmail account.\n"
            f"{DIV}\n"
            f"{ARROW} <b>Step 1</b> — Tap <b>Sell Gmail</b>\n"
            f"{ARROW} <b>Step 2</b> — Create the account using provided details\n"
            f"{ARROW} <b>Step 3</b> — Submit & get paid!\n"
            f"{DIV}\n"
            f"{FIRE} <i>Start your earning journey right now!</i>"
        ),
        "banned": f"{LOCK} <b>You are banned from using this bot.</b>",
        "join_channel": f"{BELL} <b>Please join our official channel to continue. After joining, tap the button below.</b>",
        "joined_btn": "✅ I Have Joined",
        "join_btn_text": "📢 Join Channel",
    },
    "bn": {
        "sell": "💎 জিমেইল সেল করুন",
        "account": "👑 আমার অ্যাকাউন্ট",
        "withdraw": "💳 উইথড্র",
        "history": "📊 হিস্ট্রি",
        "referral": "🎁 রেফারেল",
        "support": "🔔 সাপোর্ট",
        "lang_btn": "🇬🇧 Change Language (English)",
        "welcome": (
            f"{STAR} <b>{{bot_name}} প্ল্যাটফর্মে স্বাগতম!</b> {STAR}\n"
            f"{DIV}\n"
            f"{WAVE} হ্যালো প্রিয় <b>{{name}}</b>!\n"
            f"{GEM} প্রতিটি ভ্যালিড জিমেইল তৈরিতে আয় করুন <b>{{rate}}</b>\n"
            f"{DIV}\n"
            f"{ARROW} <b>ধাপ ১</b> — নিচ থেকে <b>জিমেইল সেল করুন</b> চাপুন\n"
            f"{ARROW} <b>ধাপ ২</b> — আমাদের দেওয়া তথ্য দিয়ে জিমেইল তৈরি করুন\n"
            f"{ARROW} <b>ধাপ ৩</b> — সাবমিট করে ক্যাশ নিন!\n"
            f"{DIV}\n"
            f"{FIRE} <i>আপনার অনলাইন ইনকাম আজই শুরু করুন!</i>"
        ),
        "banned": f"{LOCK} <b>আপনি এই বট থেকে ব্যান হয়েছেন।</b>",
        "join_channel": f"{BELL} <b>বটটি ব্যবহার করতে আমাদের অফিসিয়াল চ্যানেলে জয়েন করুন! জয়েন করার পর নিচের বাটনে ক্লিক করুন।</b>",
        "joined_btn": "✅ জয়েন করেছি",
        "join_btn_text": "📢 আমাদের চ্যানেলে জয়েন করুন",
    },
}


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
    a = str(addr or "").strip()
    return "***" if len(a) <= 4 else "***" + a[-4:]


# ═══════════════════════════════════════════════════════════
#  🔌  FIREBASE
# ═══════════════════════════════════════════════════════════

_cred = credentials.Certificate(
    json.loads(FIREBASE_CRED_STR) if FIREBASE_CRED_STR else "serviceAccountKey.json"
)
firebase_admin.initialize_app(_cred, {"databaseURL": FIREBASE_DB_URL})
R = rtdb.reference
A = asyncio.to_thread
TG: Application | None = None  # set in run()


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
        lock = _issue_locks[uid] = asyncio.Lock()
    return lock


# ═══════════════════════════════════════════════════════════
#  🧬  IDENTITY GENERATOR
# ═══════════════════════════════════════════════════════════

FIRST = [
    "Rafiq", "Tanvir", "Nusrat", "Sabbir", "Mim", "Arif", "Jannat", "Hasan",
    "Rumana", "Imran", "Sadia", "Fahim", "Tasnim", "Rakib", "Mitu", "Shuvo",
    "Farhana", "Nayeem", "Lamia", "Sohan", "Al Amin", "Mehedi", "Nodi", "Pial",
    "Afsana", "Rony", "Puja", "Joy", "Tania", "Rakibul", "Sumaiya", "Shohag",
    "Bristy", "Monir", "Nipa", "Shihab", "Maliha", "Foysal", "Sabrina", "Zubair",
    "Nazmul", "Akash", "Tuhin", "Ripa", "Badhon", "Mou", "Sajib", "Bristi", "Rifat",
]
LAST = [
    "Ahmed", "Hossain", "Rahman", "Khan", "Islam", "Akter", "Chowdhury",
    "Uddin", "Sarker", "Mia", "Begum", "Mahmud", "Karim", "Sultana",
    "Biswas", "Talukdar", "Haque", "Sheikh", "Mondal", "Roy", "Siddique",
    "Miah", "Dewan", "Bhuiyan", "Khandakar", "Prodhan", "Mollah", "Kabir",
    "Das", "Sen", "Barua", "Paul", "Vhoumik", "Mazumder", "Bhowmik", "Ali",
]


def gen_password():
    chars = string.ascii_letters + string.digits
    pw = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("@#$%*"),
    ]
    pw += [secrets.choice(chars) for _ in range(8)]
    random.SystemRandom().shuffle(pw)
    return "".join(pw)


def gen_identity():
    while True:
        first, last = random.choice(FIRST), random.choice(LAST)
        email = f"{first.replace(' ', '').lower()}{last.replace(' ', '').lower()}{random.randint(10000, 999999)}"
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
            "lang": "en",
        })
        if ref_by:
            add_num(f"users/{ref_by}/ref_count", 1)
        user = get_user(u.id)
    return user


def get_user_lang(uid):
    user = get_user(uid)
    return user["lang"] if user and "lang" in user else "en"


def set_user_lang_sync(uid, lang):
    R(f"users/{uid}/lang").set(lang)


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

async def post_payout_proof(bot, user_name: str, method: str, addr: str, amount: float):
    if not PROOF_CHANNEL:
        return
    text = (
        f"{ROCKET} <b>SUCCESSFUL WITHDRAWAL PROOF</b> {ROCKET}\n"
        f"{DIV}\n"
        f"{USER} <b>User:</b> {esc(mask_name(user_name))}\n"
        f"{CARD} <b>Gateway:</b> {esc(method)}\n"
        f"{MAIL} <b>Account:</b> {mono(mask_addr(addr))}\n"
        f"{BAG} <b>Amount Paid:</b> {money(amount)}\n"
        f"{CLOCK} <b>Timestamp:</b> {time.strftime('%d %b %Y • %H:%M')}\n"
        f"{DIV}\n"
        f"{FIRE} <i>100% Secure Payment Verified!</i>"
    )
    try:
        await bot.send_message(PROOF_CHANNEL, text, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
    except TelegramError as e:
        log.warning("proof channel post failed: %s", e)


# ═══════════════════════════════════════════════════════════
#  🧰  MENUS & HELPERS
# ═══════════════════════════════════════════════════════════

def get_menu(lang: str):
    t = LANGS.get(lang, LANGS["en"])
    return ReplyKeyboardMarkup(
        [
            [t["sell"], t["account"]],
            [t["withdraw"], t["history"]],
            [t["referral"], t["support"]],
            [t["lang_btn"]],
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


async def notify_admins(bot, text, markup=None):
    for a in ADMIN_IDS:
        try:
            await bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception as e:
            log.warning("admin notify failed for %s: %s", a, e)


_channel_cache: dict[int, tuple[float, bool]] = {}
_CHANNEL_TTL = 2


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
    except Exception:
        ok = True
    _channel_cache[uid] = (now, ok)
    return ok


async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    u = update.effective_user
    user = await A(ensure_user_sync, u, None)
    t = LANGS.get(user.get("lang", "en"), LANGS["en"])

    if user.get("banned"):
        await update.effective_message.reply_text(t["banned"], parse_mode=ParseMode.HTML)
        return False
    if not await _channel_ok(ctx, u.id):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(t["join_btn_text"], url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton(t["joined_btn"], callback_data="chk")],
        ])
        await update.effective_message.reply_text(t["join_channel"], parse_mode=ParseMode.HTML, reply_markup=kb)
        return False
    return True


# ═══════════════════════════════════════════════════════════
#  👤  USER COMMANDS
# ═══════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ref = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else None
    u = update.effective_user
    await A(ensure_user_sync, u, ref)
    if not await guard(update, ctx):
        return
    ctx.user_data.clear()
    lang = await A(get_user_lang, u.id)
    t = LANGS.get(lang, LANGS["en"])
    text = t["welcome"].format(bot_name=BOT_NAME.upper(), name=esc(u.first_name), rate=money(cfg("rate")))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=get_menu(lang))


async def toggle_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    new_lang = "bn" if await A(get_user_lang, uid) == "en" else "en"
    await A(set_user_lang_sync, uid, new_lang)
    msg = (f"{SPARK} ভাষা সফলভাবে বাংলায় পরিবর্তন করা হয়েছে!" if new_lang == "bn"
           else f"{SPARK} Language successfully switched to English!")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=get_menu(new_lang))


async def issue_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE, regenerate=False):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    await _typing(ctx, update.effective_chat.id)
    async with _lock_for(uid):
        row = await A(issue_sync, uid, regenerate)

    bn = lang == "bn"
    body = (
        f"{USER} <b>First Name:</b> {mono(row['first'])}\n"
        f"{USER} <b>Last Name:</b>  {mono(row['last'])}\n"
        f"{MAIL} <b>Email ID:</b>   {mono(row['email'] + '@gmail.com')}\n"
        f"{KEY}  <b>Password:</b>   {mono(row['password'])}\n"
        f"{DIV}\n"
        f"{BAG}  <b>{'রিওয়ার্ড' if bn else 'Reward'}:</b> {money(row['rate'])}"
    )
    footer = (
        f"{WARN} <b>{'সতর্কতা' if bn else 'Warning'}:</b> {'ঠিক এই তথ্যগুলোই ব্যবহার করুন।' if bn else 'Use these exact details.'}\n"
        f"• {'পাসওয়ার্ড পরিবর্তন করবেন না' if bn else 'Do not change the password'}\n"
        f"• {'কোনো রিকভারি ইনফো অ্যাড করবেন না' if bn else 'Do not add recovery info'}\n"
        f"{DIV}\n"
        f"{ARROW} {'কাজ শেষ হলে নিচের বাটন চাপুন' if bn else 'Finished? Tap button below'} 👇"
    )
    text = f"{STAR} <b>{'নতুন জিমেইল ডিটেইলস' if bn else 'NEW GMAIL DETAILS'}</b> {STAR}\n{DIV}\n{body}\n{DIV}\n{footer}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ কাজ শেষ (Submit)" if bn else "✅ DONE (Submit)", callback_data=f"done:{row['id']}")],
        [
            InlineKeyboardButton("🔄 নতুন ডিটেইলস" if bn else "🔄 New Details", callback_data="new"),
            InlineKeyboardButton("❌ বাতিল" if bn else "❌ Cancel", callback_data=f"cancel:{row['id']}"),
        ],
    ])
    await ctx.bot.send_message(update.effective_chat.id, text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_account(update, ctx):
    uid = update.effective_user.id
    bn = await A(get_user_lang, uid) == "bn"
    user = await A(get_user, uid)
    c = await A(count_status, uid)

    body = (
        f"{USER} <b>{'ইউজার আইডি' if bn else 'User ID'}:</b> {mono(uid)}\n"
        f"{BAG}  <b>{'মূল ব্যালেন্স' if bn else 'Balance'}:</b> {money(user.get('balance', 0))}\n"
        f"{CHART} <b>{'মোট আয়' if bn else 'Total Earned'}:</b> {money(user.get('total_earned', 0))}\n"
        f"{SUBDIV}\n"
        f"{CHECK} <b>{'অনুমোদিত' if bn else 'Approved'}:</b>   {c.get('approved', 0)}\n"
        f"{CLOCK} <b>{'পেন্ডিং' if bn else 'Pending'}:</b>     {c.get('pending', 0)}\n"
        f"{CROSS} <b>{'রিজেক্টেড' if bn else 'Rejected'}:</b>  {c.get('rejected', 0)}"
    )
    text = f"{CROWN} <b>{'অ্যাকাউন্ট ড্যাশবোর্ড' if bn else 'ACCOUNT DASHBOARD'}</b> {CROWN}\n{DIV}\n{body}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_history(update, ctx):
    uid = update.effective_user.id
    bn = await A(get_user_lang, uid) == "bn"
    icons = {"approved": CHECK, "pending": CLOCK, "rejected": CROSS, "paid": CHECK}
    accs, wds = await A(history_sync, uid)

    acc_lines = "\n".join(
        f"{icons.get(a['status'], CLOCK)} {mono(a['email'] + '@gmail.com')} — <b>{a['status']}</b>"
        for a in accs
    ) or f"{DOT} <i>{'কোনো সাবমিশন নেই' if bn else 'No submissions yet'}</i>"

    wd_lines = "\n".join(
        f"{icons.get(w['status'], CLOCK)} {money(w['amount'])} via <b>{esc(w['method'])}</b> — <b>{w['status']}</b>"
        for _, w in wds
    ) or f"{DOT} <i>{'কোনো উইথড্র হিস্ট্রি নেই' if bn else 'No withdrawals yet'}</i>"

    text = (
        f"{SCROLL} <b>{'আপনার সাম্প্রতিক হিস্ট্রি' if bn else 'RECENT ACTIVITY'}</b> {SCROLL}\n"
        f"{DIV}\n"
        f"{MAIL} <b>{'জিমেইল সাবমিশনস' if bn else 'Gmail Submissions'}</b>\n"
        f"{SUBDIV}\n{acc_lines}\n\n"
        f"{CARD} <b>{'উইথড্রয়ালস' if bn else 'Withdrawals'}</b>\n"
        f"{SUBDIV}\n{wd_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_referral(update, ctx):
    uid = update.effective_user.id
    bn = await A(get_user_lang, uid) == "bn"
    user = await A(get_user, uid)
    link = f"https://t.me/{ctx.bot.username}?start={uid}"

    text = (
        f"{GIFT} <b>{'রেফারেল প্রোগ্রাম ও বোনাস' if bn else 'REFERRAL PROGRAM'}</b> {GIFT}\n"
        f"{DIV}\n"
        f"{TARGET} {'বন্ধু আনুন এবং প্রথম জিমেইল অ্যাপ্রুভে পান' if bn else 'Invite friends and earn'} <b>{money(cfg('ref_bonus'))}</b> {'বোনাস!' if bn else 'bonus!'}\n"
        f"{SUBDIV}\n"
        f"{ARROW} <b>{'আপনার রেফারেল লিংক' if bn else 'Your Link'}:</b>\n"
        f"<code>{esc(link)}</code>\n"
        f"{SUBDIV}\n"
        f"{USER} <b>{'মোট রেফার করেছেন' if bn else 'Invited'}:</b> {user.get('ref_count', 0)} {'জন' if bn else 'friends'}\n"
        f"{DIV}\n"
        f"{FIRE} <i>{'লিংক শেয়ার করুন এবং আয় বাড়ান!' if bn else 'Share your link & grow!'}</i>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "📤 বন্ধুদের সাথে শেয়ার করুন" if bn else "📤 Share Link",
        url=f"https://t.me/share/url?url={link}&text=Join%20MailPayy%20and%20earn%20money!")]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def start_withdraw(update, ctx):
    uid = update.effective_user.id
    bn = await A(get_user_lang, uid) == "bn"
    user = await A(get_user, uid)
    bal = user.get("balance", 0)

    if not WEBAPP_URL:
        await update.message.reply_text(f"{WARN} Payout page is not configured. Contact support.",
                                        parse_mode=ParseMode.HTML)
        return

    text = (
        f"{CARD} <b>{'টাকা উইথড্র করুন' if bn else 'WITHDRAW FUNDS'}</b> {CARD}\n"
        f"{DIV}\n"
        f"{BAG} <b>{'উপলব্ধ ব্যালেন্স' if bn else 'Available'}:</b> {money(bal)}\n"
        f"{ARROW} {'সর্বনিম্ন উইথড্র' if bn else 'Minimum Withdraw'}: {money(cfg('min_withdraw'))}\n"
        f"{DIV}\n"
        f"{ARROW} {'পেআউট পেজ খুলতে নিচের বাটন চাপুন' if bn else 'Tap the button below to open the payout page'} 👇"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "💳 পেআউট পেজ খুলুন" if bn else "💳 Open Payout Page",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}/payout"))]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  ⌨️  TEXT ROUTER
# ═══════════════════════════════════════════════════════════

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx):
        return

    text = update.message.text.strip()
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    bn = lang == "bn"
    t = LANGS.get(lang, LANGS["en"])

    if text == t["lang_btn"]:
        await toggle_lang(update, ctx)
        return

    menu = {
        t["sell"]:     lambda: issue_account(update, ctx),
        t["account"]:  lambda: show_account(update, ctx),
        t["withdraw"]: lambda: start_withdraw(update, ctx),
        t["history"]:  lambda: show_history(update, ctx),
        t["referral"]: lambda: show_referral(update, ctx),
        t["support"]:  lambda: update.message.reply_text(
            f"{BELL} <b>{'সাপোর্ট' if bn else 'Support'}</b>\n{DIV}\n{ARROW} Contact: @{SUPPORT_USERNAME}",
            parse_mode=ParseMode.HTML),
    }
    if text in menu:
        ctx.user_data.clear()
        await menu[text]()


# ═══════════════════════════════════════════════════════════
#  🔔  CALLBACKS
# ═══════════════════════════════════════════════════════════

async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    bn = await A(get_user_lang, uid) == "bn"
    lang = "bn" if bn else "en"
    await q.answer()

    if data == "chk":
        _channel_cache.pop(uid, None)
        if await guard(update, ctx):
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.message.reply_text(
                f"{CHECK} {'ধন্যবাদ! বট সচল রয়েছে।' if bn else 'Thanks! Bot is ready.'}",
                parse_mode=ParseMode.HTML, reply_markup=get_menu(lang))
        else:
            await q.answer("❌ আপনি এখনো চ্যানেলে জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)
        return

    # ── admin decisions ──
    if data.startswith(("ok:", "no:", "wd_ok:", "wd_no:")):
        if not is_admin(uid):
            await q.answer("Not allowed.", show_alert=True)
            return
        action, tuid, rid = data.split(":")
        if action in ("ok", "no"):
            acc = await A(decide_acc_sync, tuid, rid, action == "ok")
            if not acc:
                await q.edit_message_text(f"{WARN} Already handled.", parse_mode=ParseMode.HTML)
                return
            mail = mono(acc["email"] + "@gmail.com")
            if action == "ok":
                msg = f"{CHECK} <b>Approved!</b>\n{DIV}\n{MAIL} {mail}\n{BAG} +{money(acc['rate'])} {PARTY}"
            else:
                msg = f"{CROSS} <b>Rejected</b>\n{DIV}\n{MAIL} {mail}"
            await q.edit_message_text(
                q.message.text_html + f"\n\n{DIV}\n➡️ <b>{'APPROVED' if action == 'ok' else 'REJECTED'}</b>",
                parse_mode=ParseMode.HTML)
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            w = await A(decide_wd_sync, tuid, rid, action == "wd_ok")
            if not w:
                await q.edit_message_text(f"{WARN} Already handled.", parse_mode=ParseMode.HTML)
                return
            msg = (
                f"{CHECK} <b>Withdrawal Paid</b> {ROCKET}\n{DIV}\n{BAG} {money(w['amount'])} sent via {esc(w['method'])}"
                if action == "wd_ok" else
                f"{CROSS} <b>Withdrawal Rejected</b>\n{DIV}\nRefunded."
            )
            await q.edit_message_text(
                q.message.text_html + f"\n\n{DIV}\n➡️ <b>{'PAID' if action == 'wd_ok' else 'REJECTED'}</b>",
                parse_mode=ParseMode.HTML)
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            if action == "wd_ok":
                u = await A(get_user, int(tuid))
                await post_payout_proof(ctx.bot, (u or {}).get("name", ""), w["method"], w["address"], w["amount"])
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
        await q.edit_message_text(f"{CROSS} {'বাতিল করা হয়েছে।' if bn else 'Cancelled.'}", parse_mode=ParseMode.HTML)

    elif data.startswith("done:"):
        aid = data.split(":")[1]
        acc = await A(submit_sync, uid, aid)
        if not acc:
            await q.edit_message_text(f"{WARN} {'এই রিকোয়েস্ট আর বৈধ নয়।' if bn else 'This request is no longer valid.'}",
                                      parse_mode=ParseMode.HTML)
            return

        full_email = f"{acc['email']}@gmail.com"
        await q.edit_message_text(
            f"{CHECK} <b>{'সাবমিট সফল হয়েছে!' if bn else 'Submitted Successfully!'}</b>\n"
            f"{DIV}\n{MAIL} {mono(full_email)}\n{DIV}\n"
            f"{ARROW} {'এডমিন চেক করার পর ব্যালেন্স যোগ হবে...' if bn else 'Waiting for admin review...'}",
            parse_mode=ParseMode.HTML)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"ok:{uid}:{aid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"no:{uid}:{aid}"),
        ]])
        await notify_admins(
            ctx.bot,
            f"{BELL} <b>NEW GMAIL SUBMISSION</b>\n{DIV}\n"
            f"{USER} User: <b>{esc(q.from_user.full_name)}</b> ({mono(uid)})\n"
            f"{MAIL} Email: {mono(full_email)}\n"
            f"{KEY} Password: {mono(acc['password'])}\n"
            f"{BAG} Reward: {money(acc['rate'])}",
            kb)


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
        f"{USER} Users: <b>{n}</b>\n"
        f"{CLOCK} Pending Gmail: <b>{s.get('pending_acc', 0)}</b>\n"
        f"{CHECK} Approved Gmail: <b>{s.get('approved_acc', 0)}</b>\n"
        f"{CARD} Pending Withdraws: <b>{s.get('pending_wd', 0)}</b>\n"
        f"{SUBDIV}\n"
        f"{GEM} Rate: {money(cfg('rate'))}\n"
        f"{BAG} Min Withdraw: {money(cfg('min_withdraw'))}\n"
        f"{GIFT} Ref Bonus: {money(cfg('ref_bonus'))}\n"
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
        await update.message.reply_text(f"{CROSS} Usage: {cmd} &lt;number&gt;", parse_mode=ParseMode.HTML)
        return
    await A(set_cfg_sync, key, val)
    await update.message.reply_text(f"{CHECK} Updated → <code>{val}</code>", parse_mode=ParseMode.HTML)


@admin_only
async def ban_cmd(update, ctx):
    ban = update.message.text.startswith("/ban")
    try:
        ok = await A(set_ban_sync, int(ctx.args[0]), ban)
        await update.message.reply_text(f"{CHECK} Success." if ok else f"{CROSS} User not found.", parse_mode=ParseMode.HTML)
    except (IndexError, ValueError):
        await update.message.reply_text(f"{CROSS} Usage: /ban USER_ID", parse_mode=ParseMode.HTML)


@admin_only
async def addbal_cmd(update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(ctx.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text(f"{CROSS} Usage: /addbal USER_ID AMOUNT", parse_mode=ParseMode.HTML)
        return
    ok = await A(add_balance_sync, uid, amt)
    await update.message.reply_text(
        f"{CHECK} Balance updated for {mono(uid)}." if ok else f"{CROSS} User not found.",
        parse_mode=ParseMode.HTML)


@admin_only
async def broadcast_cmd(update, ctx):
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text(f"{CROSS} Usage: /broadcast message", parse_mode=ParseMode.HTML)
        return
    ids = await A(all_user_ids_sync)
    sent, failed = 0, 0
    for uid in ids:
        try:
            await ctx.bot.send_message(int(uid), msg)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"{ROCKET} Broadcast: Sent {sent}, Failed {failed}", parse_mode=ParseMode.HTML)


@admin_only
async def proof_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not PROOF_CHANNEL:
        await update.message.reply_text(f"{WARN} PROOF_CHANNEL not set.", parse_mode=ParseMode.HTML)
        return
    try:
        await ctx.bot.send_message(
            PROOF_CHANNEL,
            f"{ROCKET} <b>WITHDRAWAL PAID</b> {ROCKET}\n{DIV}\n{BAG} {money(100)} Test Proof",
            parse_mode=ParseMode.HTML)
        await update.message.reply_text(f"{CHECK} Test proof sent.", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"{CROSS} Error: {esc(e)}", parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#  💳  PAYOUT WEB APP (Telegram Mini App)
# ═══════════════════════════════════════════════════════════

PAYOUT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">
<title>Payout</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#07080f; --bg2:#0d0f1c; --card:#12152a; --line:rgba(255,255,255,.08);
  --txt:#f2f4ff; --mut:#8b90ad; --acc:#7c5cff; --acc2:#22d3ee; --ok:#34d399; --bad:#fb7185;
  --r:18px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans Bengali","Hind Siliguri",sans-serif}
body{min-height:100vh;padding:14px 16px calc(110px + env(safe-area-inset-bottom));
  background:radial-gradient(900px 420px at 85% -10%,rgba(124,92,255,.22),transparent 60%),
             radial-gradient(700px 380px at -10% 10%,rgba(34,211,238,.14),transparent 60%),var(--bg)}
.top{display:flex;align-items:center;justify-content:space-between;margin:4px 0 16px}
.top h1{font-size:20px;margin:0;font-weight:700;letter-spacing:.2px}
.lang{background:var(--card);border:1px solid var(--line);color:var(--txt);border-radius:999px;
  padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer}
.bal{position:relative;overflow:hidden;border-radius:24px;padding:22px 20px;
  background:linear-gradient(135deg,#6a4dff 0%,#3b82f6 55%,#22d3ee 120%);
  box-shadow:0 18px 40px -14px rgba(90,70,255,.7)}
.bal:before{content:"";position:absolute;right:-50px;top:-50px;width:190px;height:190px;border-radius:50%;
  background:rgba(255,255,255,.14)}
.bal:after{content:"";position:absolute;left:-30px;bottom:-70px;width:170px;height:170px;border-radius:50%;
  background:rgba(255,255,255,.08)}
.bal small{display:block;opacity:.85;font-size:12px;letter-spacing:.6px;text-transform:uppercase;position:relative;z-index:1}
.bal .v{font-size:36px;font-weight:800;margin:6px 0 2px;position:relative;z-index:1;font-variant-numeric:tabular-nums}
.bal .v span{font-size:15px;font-weight:600;opacity:.85;margin-left:6px}
.bal .m{font-size:12px;opacity:.85;position:relative;z-index:1}
h3{margin:22px 4px 10px;font-size:13px;color:var(--mut);font-weight:600;letter-spacing:.7px;text-transform:uppercase}
.methods{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.mt{background:var(--card);border:1.5px solid var(--line);border-radius:var(--r);padding:14px 6px 12px;
  text-align:center;cursor:pointer;transition:.18s;color:var(--txt)}
.mt .ic{width:42px;height:42px;border-radius:14px;margin:0 auto 8px;display:grid;place-items:center;
  font-weight:800;font-size:18px;color:#fff}
.mt b{font-size:13px}
.mt.on{border-color:var(--acc);background:rgba(124,92,255,.12);transform:translateY(-2px);
  box-shadow:0 10px 24px -12px var(--acc)}
.field{background:var(--card);border:1.5px solid var(--line);border-radius:var(--r);padding:12px 14px;
  margin-bottom:12px;transition:.18s}
.field:focus-within{border-color:var(--acc)}
.field.err{border-color:var(--bad)}
.field label{display:block;font-size:11px;color:var(--mut);margin-bottom:4px;letter-spacing:.5px;text-transform:uppercase}
.field input{width:100%;background:transparent;border:0;outline:0;color:var(--txt);font-size:18px;font-weight:600;
  font-family:inherit}
.field input::placeholder{color:#4d5272;font-weight:500}
.chips{display:flex;gap:8px;margin:-2px 0 12px}
.chip{flex:1;background:var(--bg2);border:1px solid var(--line);color:var(--txt);border-radius:12px;
  padding:9px 0;font-size:12px;font-weight:600;cursor:pointer}
.chip:active{transform:scale(.97)}
.sum{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:6px 14px}
.sum div{display:flex;justify-content:space-between;padding:10px 0;font-size:14px;color:var(--mut)}
.sum div+div{border-top:1px dashed var(--line)}
.sum b{color:var(--txt)} .sum .t b{color:var(--ok);font-size:16px}
.hist .it{display:flex;align-items:center;justify-content:space-between;background:var(--card);
  border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:8px;font-size:13px}
.hist .it small{display:block;color:var(--mut);margin-top:2px}
.pill{padding:4px 10px;border-radius:999px;font-size:11px;font-weight:700}
.pill.pending{background:rgba(251,191,36,.14);color:#fbbf24}
.pill.paid{background:rgba(52,211,153,.14);color:var(--ok)}
.pill.rejected{background:rgba(251,113,133,.14);color:var(--bad)}
.empty{color:var(--mut);text-align:center;font-size:13px;padding:14px}
.bar{position:fixed;left:0;right:0;bottom:0;padding:12px 16px calc(12px + env(safe-area-inset-bottom));
  background:linear-gradient(to top,var(--bg) 70%,transparent)}
.go{width:100%;border:0;border-radius:16px;padding:16px;font-size:16px;font-weight:700;color:#fff;cursor:pointer;
  background:linear-gradient(90deg,var(--acc),#3b82f6);box-shadow:0 12px 28px -10px rgba(124,92,255,.8);transition:.18s}
.go:disabled{opacity:.4;box-shadow:none;cursor:not-allowed}
.go:not(:disabled):active{transform:scale(.985)}
.toast{position:fixed;left:16px;right:16px;top:14px;background:#2a1520;border:1px solid var(--bad);color:#ffd5dc;
  padding:12px 14px;border-radius:14px;font-size:13px;transform:translateY(-140%);transition:.3s;z-index:20}
.toast.show{transform:none}
.ov{position:fixed;inset:0;background:rgba(7,8,15,.92);backdrop-filter:blur(8px);display:none;
  flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:30px;z-index:30}
.ov.show{display:flex}
.ring{width:96px;height:96px;border-radius:50%;background:rgba(52,211,153,.14);display:grid;place-items:center;
  animation:pop .5s cubic-bezier(.2,1.4,.4,1)}
.ring svg{width:50px;height:50px;stroke:var(--ok);stroke-width:3.2;fill:none;stroke-linecap:round;stroke-linejoin:round;
  stroke-dasharray:60;stroke-dashoffset:60;animation:dr .6s .25s forwards}
@keyframes pop{from{transform:scale(.3);opacity:0}}
@keyframes dr{to{stroke-dashoffset:0}}
.ov h2{margin:20px 0 6px;font-size:22px} .ov p{color:var(--mut);margin:0 0 24px;font-size:14px;line-height:1.5}
.ov button{border:0;border-radius:14px;padding:13px 34px;background:var(--card);color:var(--txt);font-weight:700;
  font-size:15px;border:1px solid var(--line);cursor:pointer}
.skel{opacity:.5}
</style>
</head>
<body>
<div class="toast" id="toast"></div>

<div class="top">
  <h1 id="t_title">Withdraw</h1>
  <button class="lang" id="langBtn">বাংলা</button>
</div>

<div class="bal">
  <small id="t_avail">Available balance</small>
  <div class="v skel" id="bal">0.00<span>BDT</span></div>
  <div class="m"><span id="t_min">Minimum</span>: <b id="min">--</b> BDT</div>
</div>

<h3 id="t_method">Payment method</h3>
<div class="methods" id="methods"></div>

<h3 id="t_details">Details</h3>
<div class="field" id="fAddr">
  <label id="lAddr">Account</label>
  <input id="addr" autocomplete="off" inputmode="numeric" maxlength="64">
</div>
<div class="field" id="fAmt">
  <label id="lAmt">Amount (BDT)</label>
  <input id="amt" inputmode="decimal" placeholder="0.00" autocomplete="off">
</div>
<div class="chips">
  <button class="chip" data-p="min" id="cMin">Min</button>
  <button class="chip" data-p="half">50%</button>
  <button class="chip" data-p="max" id="cMax">Max</button>
</div>

<div class="sum">
  <div><span id="t_fee">Fee</span><b>0.00 BDT</b></div>
  <div class="t"><span id="t_get">You receive</span><b id="get">0.00 BDT</b></div>
</div>

<h3 id="t_hist">Recent withdrawals</h3>
<div class="hist" id="hist"></div>

<div class="bar"><button class="go" id="go" disabled>Withdraw</button></div>

<div class="ov" id="ov">
  <div class="ring"><svg viewBox="0 0 52 52"><path d="M14 27 L23 36 L39 17"/></svg></div>
  <h2 id="t_ok">Request submitted</h2>
  <p id="t_okp"></p>
  <button id="close">OK</button>
</div>

<script>
"use strict";
const tg = window.Telegram && Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); try{ tg.setHeaderColor("#07080f"); tg.setBackgroundColor("#07080f"); }catch(e){} }
const INIT = tg ? tg.initData : "";

const T = {
  en:{title:"Withdraw",avail:"Available balance",min:"Minimum",method:"Payment method",details:"Details",
      amt:"Amount (BDT)",fee:"Fee",get:"You receive",hist:"Recent withdrawals",go:"Withdraw",
      ok:"Request submitted",okp:"Your withdrawal is pending admin review. You will be notified in Telegram.",
      none:"No withdrawals yet",bkash:"bKash number",nagad:"Nagad number",binance:"Binance Pay ID / UID / Email",
      eNum:"Enter a valid 11-digit number (01XXXXXXXXX)",eBin:"Enter a valid Binance Pay ID / UID / Email",
      eMin:"Amount is below the minimum",eBal:"Amount is higher than your balance",eAmt:"Enter a valid amount",
      eOpen:"Please open this page from the Telegram bot",eNet:"Network error, try again",
      st:{pending:"Pending",paid:"Paid",rejected:"Rejected"},close:"OK"},
  bn:{title:"উইথড্র",avail:"উপলব্ধ ব্যালেন্স",min:"সর্বনিম্ন",method:"পেমেন্ট মেথড",details:"তথ্য",
      amt:"পরিমাণ (BDT)",fee:"ফি",get:"আপনি পাবেন",hist:"সাম্প্রতিক উইথড্র",go:"উইথড্র করুন",
      ok:"রিকোয়েস্ট জমা হয়েছে",okp:"আপনার উইথড্র এডমিনের রিভিউয়ের অপেক্ষায় আছে। টেলিগ্রামে জানানো হবে।",
      none:"কোনো উইথড্র নেই",bkash:"বিকাশ নম্বর",nagad:"নগদ নম্বর",binance:"Binance Pay ID / UID / ইমেইল",
      eNum:"সঠিক ১১ ডিজিটের নম্বর দিন (01XXXXXXXXX)",eBin:"সঠিক Binance Pay ID / UID / ইমেইল দিন",
      eMin:"পরিমাণ সর্বনিম্নের চেয়ে কম",eBal:"পরিমাণ ব্যালেন্সের চেয়ে বেশি",eAmt:"সঠিক পরিমাণ দিন",
      eOpen:"দয়া করে টেলিগ্রাম বট থেকে এই পেজ খুলুন",eNet:"নেটওয়ার্ক সমস্যা, আবার চেষ্টা করুন",
      st:{pending:"পেন্ডিং",paid:"পরিশোধিত",rejected:"বাতিল"},close:"ঠিক আছে"}
};
const M = [
  {id:"bKash",  c:"#e2136e", i:"b", key:"bkash"},
  {id:"Nagad",  c:"#f6921e", i:"N", key:"nagad"},
  {id:"Binance",c:"#f0b90b", i:"B", key:"binance"}
];
const $ = id => document.getElementById(id);
let S = {lang:"en", bal:0, min:50, method:"bKash", hist:[], busy:false};

function t(k){ return T[S.lang][k]; }
function fmt(n){ return Number(n).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}); }
function toast(msg){ const e=$("toast"); e.textContent=msg; e.classList.add("show"); clearTimeout(toast.t);
  toast.t=setTimeout(()=>e.classList.remove("show"),3200); }
function hap(k){ try{ tg.HapticFeedback.notificationOccurred(k); }catch(e){} }

function renderMethods(){
  const box=$("methods"); box.textContent="";
  M.forEach(m=>{
    const d=document.createElement("div"); d.className="mt"+(S.method===m.id?" on":"");
    const ic=document.createElement("div"); ic.className="ic"; ic.style.background=m.c; ic.textContent=m.i;
    const b=document.createElement("b"); b.textContent=m.id;
    d.append(ic,b); d.onclick=()=>{S.method=m.id; $("addr").value=""; renderMethods(); renderText(); check();};
    box.append(d);
  });
}
function renderHist(){
  const h=$("hist"); h.textContent="";
  if(!S.hist.length){ const e=document.createElement("div"); e.className="empty"; e.textContent=t("none"); h.append(e); return; }
  S.hist.forEach(x=>{
    const r=document.createElement("div"); r.className="it";
    const l=document.createElement("div"); const a=document.createElement("b");
    a.textContent=fmt(x.amount)+" BDT"; const s=document.createElement("small");
    s.textContent=x.method+" • "+new Date(x.created*1000).toLocaleDateString();
    l.append(a,s);
    const p=document.createElement("span"); p.className="pill "+x.status; p.textContent=t("st")[x.status]||x.status;
    r.append(l,p); h.append(r);
  });
}
function renderText(){
  $("t_title").textContent=t("title"); $("t_avail").textContent=t("avail"); $("t_min").textContent=t("min");
  $("t_method").textContent=t("method"); $("t_details").textContent=t("details"); $("lAmt").textContent=t("amt");
  $("t_fee").textContent=t("fee"); $("t_get").textContent=t("get"); $("t_hist").textContent=t("hist");
  $("go").textContent=t("go"); $("t_ok").textContent=t("ok"); $("t_okp").textContent=t("okp"); $("close").textContent=t("close");
  $("langBtn").textContent=S.lang==="en"?"বাংলা":"English";
  const m=M.find(x=>x.id===S.method); $("lAddr").textContent=t(m.key);
  $("addr").inputMode = S.method==="Binance" ? "text" : "numeric";
  $("addr").placeholder = S.method==="Binance" ? "ID / UID / Email" : "01XXXXXXXXX";
  $("bal").classList.remove("skel"); $("bal").innerHTML=fmt(S.bal)+"<span>BDT</span>"; $("min").textContent=fmt(S.min);
  renderHist();
}
function addrOk(){
  const v=$("addr").value.trim();
  return S.method==="Binance" ? /^[A-Za-z0-9@._+\-]{4,64}$/.test(v) : /^01[3-9][0-9]{8}$/.test(v);
}
function amtVal(){ const v=parseFloat($("amt").value); return isFinite(v)?Math.round(v*100)/100:NaN; }
function check(){
  const a=amtVal();
  $("get").textContent=fmt(isNaN(a)?0:a)+" BDT";
  $("go").disabled = !(addrOk() && !isNaN(a) && a>=S.min && a<=S.bal) || S.busy;
}
function validate(){
  const a=amtVal(); let e="";
  if(!addrOk()){ e=S.method==="Binance"?t("eBin"):t("eNum"); $("fAddr").classList.add("err"); }
  else if(isNaN(a)||a<=0){ e=t("eAmt"); $("fAmt").classList.add("err"); }
  else if(a<S.min){ e=t("eMin"); $("fAmt").classList.add("err"); }
  else if(a>S.bal){ e=t("eBal"); $("fAmt").classList.add("err"); }
  return e;
}
async function api(path, body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Init-Data":INIT},
    body:JSON.stringify(body||{})});
  const j=await r.json().catch(()=>({})); if(!r.ok) throw new Error(j.error||"err"); return j;
}
async function load(){
  if(!INIT){ toast(t("eOpen")); return; }
  try{
    const d=await api("/api/info");
    S.bal=d.balance; S.min=d.min; S.hist=d.history; S.lang=d.lang==="bn"?"bn":"en";
  }catch(e){ toast(t("eNet")); }
  renderMethods(); renderText(); check();
}
$("langBtn").onclick=()=>{ S.lang=S.lang==="en"?"bn":"en"; renderText(); };
$("addr").oninput=()=>{ $("fAddr").classList.remove("err"); check(); };
$("amt").oninput=()=>{ $("fAmt").classList.remove("err"); check(); };
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{
  const p=c.dataset.p; let v = p==="min"?S.min : p==="half"?S.bal/2 : S.bal;
  v=Math.max(0,Math.floor(v*100)/100); $("amt").value=v?String(v):""; $("fAmt").classList.remove("err"); check();
  try{ tg.HapticFeedback.selectionChanged(); }catch(e){}
});
$("go").onclick=async()=>{
  const e=validate(); if(e){ toast(e); hap("error"); return; }
  S.busy=true; $("go").disabled=true; $("go").textContent="...";
  try{
    const d=await api("/api/withdraw",{method:S.method,address:$("addr").value.trim(),amount:amtVal()});
    S.bal=d.balance; S.hist=d.history; $("amt").value=""; $("addr").value="";
    hap("success"); $("ov").classList.add("show");
  }catch(err){ hap("error"); toast(err.message&&err.message!=="err"?err.message:t("eNet")); }
  S.busy=false; renderText(); check();
};
$("close").onclick=()=>{ $("ov").classList.remove("show"); if(tg) tg.close(); };
renderMethods(); renderText(); load();
</script>
</body>
</html>
"""


def verify_init_data(init_data: str, max_age: int = 86400):
    """Validate Telegram WebApp initData. Returns user dict or None."""
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got_hash = pairs.pop("hash", "")
        if not got_hash:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(pairs.get("user", "{}"))
        return user if isinstance(user, dict) and "id" in user else None
    except Exception:
        return None


def _wd_history(uid):
    wds = list((R(f"withdrawals/{uid}").get() or {}).values())
    wds.sort(key=lambda x: x.get("created", 0), reverse=True)
    return [{"method": w.get("method"), "amount": w.get("amount"),
             "status": w.get("status"), "created": w.get("created", 0)} for w in wds[:5]]


def _web_user(request):
    return verify_init_data(request.headers.get("X-Init-Data", ""))


async def web_payout(request):
    return web.Response(text=PAYOUT_HTML, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


async def web_info(request):
    tu = _web_user(request)
    if not tu:
        return web.json_response({"error": "unauthorized"}, status=401)
    uid = tu["id"]
    user = await A(get_user, uid)
    if not user or user.get("banned"):
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({
        "balance": float(user.get("balance", 0)), "min": cfg("min_withdraw"),
        "lang": user.get("lang", "en"), "history": await A(_wd_history, uid),
    })


_ADDR_RE = {"bKash": re.compile(r"^01[3-9]\d{8}$"), "Nagad": re.compile(r"^01[3-9]\d{8}$"),
            "Binance": re.compile(r"^[A-Za-z0-9@._+\-]{4,64}$")}


async def web_withdraw(request):
    tu = _web_user(request)
    if not tu:
        return web.json_response({"error": "unauthorized"}, status=401)
    uid = tu["id"]
    try:
        body = await request.json()
        method = str(body.get("method", ""))
        addr = str(body.get("address", "")).strip()
        amt = round(float(body.get("amount")), 2)
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)

    if method not in METHODS or not _ADDR_RE[method].match(addr):
        return web.json_response({"error": "Invalid account"}, status=400)
    if not math.isfinite(amt) or amt <= 0 or amt < cfg("min_withdraw"):
        return web.json_response({"error": "Amount is below the minimum"}, status=400)

    user = await A(get_user, uid)
    if not user or user.get("banned"):
        return web.json_response({"error": "forbidden"}, status=403)

    wid = await A(create_wd_sync, uid, method, addr, amt)
    if wid is None:
        return web.json_response({"error": "Insufficient balance"}, status=400)

    bn = user.get("lang") == "bn"
    try:
        await TG.bot.send_message(
            uid,
            f"{CHECK} <b>{'উইথড্র রিকোয়েস্ট জমা হয়েছে!' if bn else 'Withdrawal Submitted!'}</b>\n{DIV}\n"
            f"{CARD} Method: <b>{esc(method)}</b>\n{BAG} Amount: {money(amt)}\n{CLOCK} Status: <b>Pending</b>",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Paid", callback_data=f"wd_ok:{uid}:{wid}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"wd_no:{uid}:{wid}"),
    ]])
    await notify_admins(
        TG.bot,
        f"{CARD} <b>NEW WITHDRAWAL REQUEST</b>\n{DIV}\n"
        f"{USER} User: <b>{esc(user.get('name'))}</b> ({mono(uid)})\n"
        f"{CARD} Method: <b>{esc(method)}</b>\n{MAIL} Address: {mono(addr)}\n{BAG} Amount: {money(amt)}",
        kb)

    fresh = await A(get_user, uid)
    return web.json_response({"ok": True, "balance": float(fresh.get("balance", 0)),
                              "history": await A(_wd_history, uid)})


async def web_telegram_hook(request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return web.Response(status=403)
    try:
        upd = Update.de_json(await request.json(), TG.bot)
        await TG.update_queue.put(upd)
    except Exception:
        log.exception("bad webhook update")
    return web.Response(text="ok")


async def web_ok(request):
    return web.Response(text="OK")


# ═══════════════════════════════════════════════════════════
#  🌐  RUNNER
# ═══════════════════════════════════════════════════════════

async def _health(update, ctx):
    await update.message.reply_text("OK")


def _build_app() -> Application:
    builder = Application.builder().token(BOT_TOKEN)
    if RENDER_URL:
        builder = builder.updater(None)  # updates arrive through our aiohttp webhook route
    app = builder.build()
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
    return app


async def run():
    global TG
    TG = _build_app()

    site_app = web.Application()
    site_app.router.add_get("/", web_ok)
    site_app.router.add_get("/health", web_ok)
    site_app.router.add_get("/payout", web_payout)
    site_app.router.add_post("/api/info", web_info)
    site_app.router.add_post("/api/withdraw", web_withdraw)
    site_app.router.add_post(f"/{WEBHOOK_PATH}", web_telegram_hook)

    await TG.initialize()
    await TG.start()
    if RENDER_URL:
        await TG.bot.set_webhook(
            f"{RENDER_URL.rstrip('/')}/{WEBHOOK_PATH}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            secret_token=WEBHOOK_SECRET,
        )
    else:
        await TG.bot.delete_webhook(drop_pending_updates=True)
        await TG.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    runner = web.AppRunner(site_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("🚀 %s is running on port %s", BOT_NAME, PORT)

    try:
        await asyncio.Event().wait()
    finally:
        if not RENDER_URL:
            await TG.updater.stop()
        await TG.stop()
        await TG.shutdown()
        await runner.cleanup()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
