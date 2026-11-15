"""
💎 MAILPAYY BOT (100K+ SCALABLE | EN & BN)
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
#  ⚙️  CONFIG & TRANSLATIONS
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
WEBHOOK_PATH      = "tg-hook"

CUR              = "BDT"
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


_validate_env()

# ═══════════════════════════════════════════════════════════
#  ✨  TELEGRAM ANIMATED EMOJIS CONFIG
# ═══════════════════════════════════════════════════════════

ANIMATED: dict[str, str] = {
    "✨": "5321275567060081617",
    "🔥": "5316521303159150257",
    "💎": "5323787699962845141",
    "👑": "5321487312630782711",
    "⚡": "5321023426538248035",
    "🎯": "5321453641127368889",
    "🎉": "5321226451634427971",
    "🚀": "5321319194712937700",
    "🛡": "5321398766708005471",
    "📊": "5321048500796397331",
    "📜": "5321166039407994885",
    "🎁": "5321242343894227319",
    "💰": "5323338909876335012",
    "💳": "5321210104552692543",
    "🔔": "5321056607605890211",
    "👋": "5321114585075816582",
    "✅": "5321312842670217992",
    "❌": "5321174383149554365",
    "⏳": "5321188246704200133",
    "⚠️": "5321102186342142663",
    "🔒": "5321354251410413621",
    "📧": "5321288907731835199",
    "👤": "5321378196045421001",
    "🔑": "5321428910323925122",
    "🏆": "5321401925184231044",
    "💫": "5321238900154217003",
}


def _emoji(char: str) -> str:
    eid = ANIMATED.get(char, "")
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
    return char


DIV    = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SUBDIV = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DOT    = "•"

STAR   = _emoji("✨")
FIRE   = _emoji("🔥")
GEM    = _emoji("💎")
CROWN  = _emoji("👑")
BOLT   = _emoji("⚡")
ARROW  = _emoji("⚡")
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
WARN   = _emoji("⚠️")
LOCK   = _emoji("🔒")
MAIL   = _emoji("📧")
USER   = _emoji("👤")
KEY    = _emoji("🔑")
TROPHY = _emoji("🏆")
SPARK  = _emoji("💫")

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
            f"{ARROW} <b>Step 3</b> — Submit & get paid automatically!\n"
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
            f"{WAVE} হ্যালো প্রিয় <b>{{name}}</b>!\n"
            f"{GEM} প্রতিটি ভ্যালিড জিমেইল তৈরিতে আয় করুন <b>{{rate}}</b>\n"
            f"{DIV}\n"
            f"{ARROW} <b>ধাপ ১</b> — নিচ থেকে <b>জিমেইল সেল করুন</b> চাপুন\n"
            f"{ARROW} <b>ধাপ ২</b> — আমাদের দেওয়া তথ্য দিয়ে জিমেইল তৈরি করুন\n"
            f"{ARROW} <b>ধাপ ৩</b> — সাবমিট করে ইনস্ট্যান্ট ক্যাশ নিন!\n"
            f"{DIV}\n"
            f"{FIRE} <i>আপনার অনলাইন ইনকাম আজই শুরু করুন!</i>"
        ),
        "banned": f"{LOCK} <b>আপনি এই বট থেকে ব্যান হয়েছেন।</b>",
        "join_channel": f"{BELL} <b>বটটি ব্যবহার করতে আমাদের অফিসিয়াল চ্যানেলে জয়েন করুন! জয়েন করার পর নিচের বাটনে ক্লিক করুন।</b>",
        "joined_btn": "✅ জয়েন করেছি",
        "join_btn_text": "📢 আমাদের চ্যানেলে জয়েন করুন",
    }
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
#  🧬  EXPANDED IDENTITY GENERATOR (FOR 100K+ USERS)
# ═══════════════════════════════════════════════════════════

FIRST = [
    "Rafiq", "Tanvir", "Nusrat", "Sabbir", "Mim", "Arif", "Jannat", "Hasan",
    "Rumana", "Imran", "Sadia", "Fahim", "Tasnim", "Rakib", "Mitu", "Shuvo",
    "Farhana", "Nayeem", "Lamia", "Sohan", "Al Amin", "Mehedi", "Nodi", "Pial",
    "Afsana", "Rony", "Puja", "Joy", "Tania", "Rakibul", "Sumaiya", "Shohag",
    "Bristy", "Monir", "Nipa", "Shihab", "Maliha", "Foysal", "Sabrina", "Zubair",
    "Nazmul", "Akash", "Tuhin", "Ripa", "Badhon", "Mou", "Sajib", "Bristi", "Rifat"
]
LAST = [
    "Ahmed", "Hossain", "Rahman", "Khan", "Islam", "Akter", "Chowdhury",
    "Uddin", "Sarker", "Mia", "Begum", "Mahmud", "Karim", "Sultana",
    "Biswas", "Talukdar", "Haque", "Sheikh", "Mondal", "Roy", "Siddique",
    "Miah", "Dewan", "Bhuiyan", "Khandakar", "Prodhan", "Mollah", "Kabir",
    "Das", "Sen", "Barua", "Paul", "Vhoumik", "Mazumder", "Bhowmik", "Ali"
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
    random.shuffle(pw)
    return "".join(pw)


def gen_identity():
    while True:
        first, last = random.choice(FIRST), random.choice(LAST)
        clean_first = first.replace(" ", "").lower()
        clean_last = last.replace(" ", "").lower()
        email = f"{clean_first}{clean_last}{random.randint(10000, 999999)}"
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
    if user and "lang" in user:
        return user["lang"]
    return "en"


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

async def post_payout_proof(ctx, user_name: str, method: str, addr: str, amount: float):
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
        f"{FIRE} <i>100% Instant & Secure Payment Verified!</i>"
    )
    try:
        await ctx.bot.send_message(
            PROOF_CHANNEL, text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as e:
        log.warning("proof channel post failed: %s", e)


# ═══════════════════════════════════════════════════════════
#  🧰  MENUS & HELPERS
# ═══════════════════════════════════════════════════════════

def get_menu(lang: str):
    t = LANGS.get(lang, LANGS["en"])
    return ReplyKeyboardMarkup(
        [
            [t["sell"],     t["account"]],
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


async def notify_admins(ctx, text, markup=None):
    for a in ADMIN_IDS:
        try:
            await ctx.bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
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
    lang = user.get("lang", "en")
    t = LANGS.get(lang, LANGS["en"])

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

    name = esc(u.first_name)
    text = t["welcome"].format(bot_name=BOT_NAME.upper(), name=name, rate=money(cfg('rate')))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=get_menu(lang))


async def toggle_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    current_lang = await A(get_user_lang, uid)
    new_lang = "bn" if current_lang == "en" else "en"
    await A(set_user_lang_sync, uid, new_lang)
    
    msg = f"{SPARK} ভাষা সফলভাবে বাংলায় পরিবর্তন করা হয়েছে!" if new_lang == "bn" else f"{SPARK} Language successfully switched to English!"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=get_menu(new_lang))


async def issue_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE, regenerate=False):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    await _typing(ctx, update.effective_chat.id)
    async with _lock_for(uid):
        row = await A(issue_sync, uid, regenerate)

    is_bn = (lang == "bn")
    body = (
        f"{USER} <b>First Name:</b> {mono(row['first'])}\n"
        f"{USER} <b>Last Name:</b>  {mono(row['last'])}\n"
        f"{MAIL} <b>Email ID:</b>   {mono(row['email'] + '@gmail.com')}\n"
        f"{KEY}  <b>Password:</b>   {mono(row['password'])}\n"
        f"{DIV}\n"
        f"{BAG}  <b>{'রিওয়ার্ড' if is_bn else 'Reward'}:</b> {money(row['rate'])}"
    )
    footer = (
        f"{WARN} <b>{'সতর্কতা' if is_bn else 'Warning'}:</b> {'ঠিক এই তথ্যগুলোই ব্যবহার করুন।' if is_bn else 'Use these exact details.'}\n"
        f"• {'পাসওয়ার্ড পরিবর্তন করবেন না' if is_bn else 'Do not change the password'}\n"
        f"• {'কোনো রিকভারি ইনফো অ্যাড করবেন না' if is_bn else 'Do not add recovery info'}\n"
        f"{DIV}\n"
        f"{ARROW} {'কাজ শেষ হলে নিচের বাটন চাপুন' if is_bn else 'Finished? Tap button below'} 👇"
    )
    text = f"{STAR} <b>{'নতুন জিমেইল ডিটেইলস' if is_bn else 'NEW GMAIL DETAILS'}</b> {STAR}\n{DIV}\n{body}\n{DIV}\n{footer}"

    btn_done = "✅ কাজ শেষ (Submit)" if is_bn else "✅ DONE (Submit)"
    btn_new = "🔄 নতুন ডিটেইলস" if is_bn else "🔄 New Details"
    btn_cancel = "❌ বাতিল" if is_bn else "❌ Cancel"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_done, callback_data=f"done:{row['id']}")],
        [
            InlineKeyboardButton(btn_new, callback_data="new"),
            InlineKeyboardButton(btn_cancel, callback_data=f"cancel:{row['id']}"),
        ],
    ])
    await ctx.bot.send_message(update.effective_chat.id, text,
                               parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_account(update, ctx):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    user = await A(get_user, uid)
    c = await A(count_status, uid)
    is_bn = (lang == "bn")

    body = (
        f"{USER} <b>{'ইউজার আইডি' if is_bn else 'User ID'}:</b> {mono(uid)}\n"
        f"{BAG}  <b>{'মূল ব্যালেন্স' if is_bn else 'Balance'}:</b> {money(user.get('balance', 0))}\n"
        f"{CHART} <b>{'মোট আয়' if is_bn else 'Total Earned'}:</b> {money(user.get('total_earned', 0))}\n"
        f"{SUBDIV}\n"
        f"{CHECK} <b>{'অনুমোদিত' if is_bn else 'Approved'}:</b>   {c.get('approved', 0)}\n"
        f"{CLOCK} <b>{'পেন্ডিং' if is_bn else 'Pending'}:</b>     {c.get('pending', 0)}\n"
        f"{CROSS} <b>{'রিজেক্টেড' if is_bn else 'Rejected'}:</b>  {c.get('rejected', 0)}"
    )
    text = f"{CROWN} <b>{'অ্যাকাউন্ট ড্যাশবোর্ড' if is_bn else 'ACCOUNT DASHBOARD'}</b> {CROWN}\n{DIV}\n{body}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_history(update, ctx):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    is_bn = (lang == "bn")
    icons = {"approved": CHECK, "pending": CLOCK, "rejected": CROSS, "paid": CHECK}
    accs, wds = await A(history_sync, uid)

    acc_lines = "\n".join(
        f"{icons.get(a['status'], CLOCK)} {mono(a['email'] + '@gmail.com')} — <b>{a['status']}</b>"
        for a in accs
    ) or f"{DOT} <i>{'কোনো সাবমিশন নেই' if is_bn else 'No submissions yet'}</i>"

    wd_lines = "\n".join(
        f"{icons.get(w['status'], CLOCK)} {money(w['amount'])} via <b>{esc(w['method'])}</b> — <b>{w['status']}</b>"
        for _, w in wds
    ) or f"{DOT} <i>{'কোনো উইথড্র হিস্ট্রি নেই' if is_bn else 'No withdrawals yet'}</i>"

    text = (
        f"{SCROLL} <b>{'আপনার সাম্প্রতিক হিস্ট্রি' if is_bn else 'RECENT ACTIVITY'}</b> {SCROLL}\n"
        f"{DIV}\n"
        f"{MAIL} <b>{'জিমেইল সাবমিশনস' if is_bn else 'Gmail Submissions'}</b>\n"
        f"{SUBDIV}\n{acc_lines}\n\n"
        f"{CARD} <b>{'উইথড্রয়ালস' if is_bn else 'Withdrawals'}</b>\n"
        f"{SUBDIV}\n{wd_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def show_referral(update, ctx):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    user = await A(get_user, uid)
    is_bn = (lang == "bn")
    link = f"https://t.me/{ctx.bot.username}?start={uid}"
    
    text = (
        f"{GIFT} <b>{'রেফারেল প্রোগ্রাম ও বোনাস' if is_bn else 'REFERRAL PROGRAM'}</b> {GIFT}\n"
        f"{DIV}\n"
        f"{TARGET} {'বন্ধু আনুন এবং প্রথম জিমেইল অ্যাপ্রুভে পান' if is_bn else 'Invite friends and earn'} <b>{money(cfg('ref_bonus'))}</b> {'বোনাস!' if is_bn else 'bonus!'}\n"
        f"{SUBDIV}\n"
        f"{ARROW} <b>{'আপনার রেফারেল লিংক' if is_bn else 'Your Link'}:</b>\n"
        f"<code>{esc(link)}</code>\n"
        f"{SUBDIV}\n"
        f"{USER} <b>{'মোট রেফার করেছেন' if is_bn else 'Invited'}:</b> {user.get('ref_count', 0)} {'জন' if is_bn else 'friends'}\n"
        f"{DIV}\n"
        f"{FIRE} <i>{'লিংক শেয়ার করুন এবং আয় বাড়ান!' if is_bn else 'Share your link & grow!'}</i>"
    )
    btn_share = "📤 বন্ধুদের সাথে শেয়ার করুন" if is_bn else "📤 Share Link"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_share, url=f"https://t.me/share/url?url={link}&text=Join%20MailPayy%20and%20earn%20money!")
    ]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def start_withdraw(update, ctx):
    uid = update.effective_user.id
    lang = await A(get_user_lang, uid)
    user = await A(get_user, uid)
    bal = user.get("balance", 0)
    is_bn = (lang == "bn")

    if bal < cfg("min_withdraw"):
        text = (
            f"{LOCK} <b>{'অপর্যাপ্ত ব্যালেন্স!' if is_bn else 'Insufficient Balance!'}</b>\n"
            f"{DIV}\n"
            f"{ARROW} {'সর্বনিম্ন উইথড্র' if is_bn else 'Minimum Withdraw'}: <b>{money(cfg('min_withdraw'))}</b>\n"
            f"{BAG} {'আপনার ব্যালেন্স' if is_bn else 'Your Balance'}: <b>{money(bal)}</b>\n"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💚 bKash",   callback_data="wd:bKash"),
        InlineKeyboardButton("🧡 Nagad",   callback_data="wd:Nagad"),
        InlineKeyboardButton("💛 Binance", callback_data="wd:Binance"),
    ]])
    text = (
        f"{CARD} <b>{'টাকা উইথড্র করুন' if is_bn else 'WITHDRAW FUNDS'}</b> {CARD}\n"
        f"{DIV}\n"
        f"{BAG} <b>{'উপলব্ধ ব্যালেন্স' if is_bn else 'Available'}:</b> {money(bal)}\n"
        f"{ARROW} {'পেমেন্ট মেথড সিলেক্ট করুন নিচে থেকে' if is_bn else 'Choose payout method below'} 👇"
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
    lang = await A(get_user_lang, uid)
    is_bn = (lang == "bn")

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
                            f"{BELL} <b>{'সাপোর্ট' if is_bn else 'Support'}</b>\n{DIV}\n"
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
        btn_cancel = "❌ বাতিল" if is_bn else "❌ Cancel"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_cancel, callback_data="wd_cancel")]])
        await update.message.reply_text(
            f"{CARD} <b>{'উইথড্র অ্যামাউন্ট লিখুন' if is_bn else 'Enter withdrawal amount'}</b>\n"
            f"{DIV}\n"
            f"{ARROW} {'সর্বনিম্ন' if is_bn else 'Minimum'}: {money(cfg('min_withdraw'))}",
            parse_mode=ParseMode.HTML, reply_markup=kb,
        )
        return

    if st == "wd_amt":
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text(f"{CROSS} {'সঠিক সংখ্যা দিন।' if is_bn else 'Provide valid number.'}", parse_mode=ParseMode.HTML)
            return
        user = await A(get_user, uid)
        bal  = user.get("balance", 0)
        if amt < cfg("min_withdraw") or amt > bal:
            await update.message.reply_text(
                f"{CROSS} {'সীমা অতিক্রম করেছে।' if is_bn else 'Invalid amount range.'}",
                parse_mode=ParseMode.HTML,
            )
            return
        method, addr = ctx.user_data["method"], ctx.user_data["addr"]
        wid = await A(create_wd_sync, uid, method, addr, amt)
        ctx.user_data.clear()
        if wid is None:
            await update.message.reply_text(
                f"{CROSS} <b>{'অপর্যাপ্ত ব্যালেন্স।' if is_bn else 'Insufficient balance.'}</b>",
                parse_mode=ParseMode.HTML, reply_markup=get_menu(lang),
            )
            return
        await update.message.reply_text(
            f"{CHECK} <b>{'উইথড্র সফল হয়েছে!' if is_bn else 'Withdrawal Submitted!'}</b>\n"
            f"{DIV}\n"
            f"{CARD} Method: <b>{esc(method)}</b>\n"
            f"{BAG} Amount: {money(amt)}\n"
            f"{CLOCK} Status: <b>Pending</b>",
            parse_mode=ParseMode.HTML, reply_markup=get_menu(lang),
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
    lang = await A(get_user_lang, uid)
    is_bn = (lang == "bn")
    await q.answer()

    if data == "chk":
        if uid in _channel_cache:
            del _channel_cache[uid]
            
        if await guard(update, ctx):
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.message.reply_text(
                f"{CHECK} {'ধন্যবাদ! বট সচল রয়েছে।' if is_bn else 'Thanks! Bot is ready.'}",
                parse_mode=ParseMode.HTML,
                reply_markup=get_menu(lang),
            )
        else:
            await q.answer("❌ আপনি এখনো চ্যানেলে জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)
        return

    if data == "wd_cancel":
        ctx.user_data.clear()
        await q.edit_message_text(f"{CROSS} {'বাতিল করা হয়েছে।' if is_bn else 'Cancelled.'}", parse_mode=ParseMode.HTML)
        return

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
            if action == "ok":
                msg = f"{CHECK} <b>Approved!</b>\n{DIV}\n{MAIL} {mono(acc['email'] + '@gmail.com')}\n{BAG} +{money(acc['rate'])} {PARTY}"
            else:
                msg = f"{CROSS} <b>Rejected</b>\n{DIV}\n{MAIL} {mono(acc['email'] + '@gmail.com')}"
            await q.edit_message_text(q.message.text + f"\n\n{DIV}\n➡️ <b>{'APPROVED' if action == 'ok' else 'REJECTED'}</b>", parse_mode=ParseMode.HTML)
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
            await q.edit_message_text(q.message.text + f"\n\n{DIV}\n➡️ <b>{'PAID' if action == 'wd_ok' else 'REJECTED'}</b>", parse_mode=ParseMode.HTML)
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass

            if action == "wd_ok":
                u = await A(get_user, int(tuid))
                await post_payout_proof(ctx, (u or {}).get("name", ""), w["method"], w["address"], w["amount"])
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
        await q.edit_message_text(f"{CROSS} Cancelled.", parse_mode=ParseMode.HTML)

    elif data.startswith("done:"):
        aid = data.split(":")[1]
        acc_submitted = await A(submit_sync, uid, aid)
        if not acc_submitted:
            await q.edit_message_text(f"{WARN} This request is no longer valid.", parse_mode=ParseMode.HTML)
            return

        full_email = f"{acc_submitted['email']}@gmail.com"

        await q.edit_message_text(
            f"{CHECK} <b>সফলভাবে সাবমিট হয়েছে!</b>\n"
            f"{DIV}\n"
            f"{MAIL} {mono(full_email)}\n"
            f"{DIV}\n{ARROW} এডমিন চেক করার পর ব্যালেন্স যোগ হবে...",
            parse_mode=ParseMode.HTML,
        )
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"ok:{uid}:{acc_submitted['id']}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"no:{uid}:{acc_submitted['id']}"),
        ]])
        await notify_admins(
            ctx,
            f"{BELL} <b>NEW GMAIL SUBMISSION</b>\n{DIV}\n"
            f"{USER} User: <b>{esc(q.from_user.full_name)}</b> ({mono(uid)})\n"
            f"{MAIL} Email: {mono(full_email)}\n"
            f"{KEY} Password: {mono(acc_submitted['password'])}\n"
            f"{BAG} Reward: {money(acc_submitted['rate'])}",
            kb,
        )

    elif data.startswith("wd:"):
        method = data.split(":")[1]
        ctx.user_data.update({"state": "wd_addr", "method": method})
        btn_cancel = "❌ বাতিল" if is_bn else "❌ Cancel"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_cancel, callback_data="wd_cancel")]])
        await q.edit_message_text(
            f"{CARD} <b>{esc(method)} Payout</b>\n{DIV}\n"
            f"{ARROW} Enter your <b>{esc(method)}</b> account / number:",
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
        await update.message.reply_text(f"{CROSS} Usage: {cmd} <number>", parse_mode=ParseMode.HTML)
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
    if ok:
        await update.message.reply_text(f"{CHECK} Balance updated for {mono(uid)}.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"{CROSS} User not found.", parse_mode=ParseMode.HTML)


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
            parse_mode=ParseMode.HTML
        )
        await update.message.reply_text(f"{CHECK} Test proof sent.", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"{CROSS} Error: {e}", parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#  🌐  RUNNER
# ═══════════════════════════════════════════════════════════

async def _health(update, ctx):
    await update.message.reply_text("OK")


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
    return app


def main():
    app = _build_app()
    if RENDER_URL:
        webhook_url = f"{RENDER_URL.rstrip('/')}/{WEBHOOK_PATH}"
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
