# Gmail Sell Bot (Firebase Realtime Database version)
# Users create Gmail accounts with details given by the bot and sell them to you.
#
# Install:  pip install "python-telegram-bot>=21" firebase-admin
# Env vars: BOT_TOKEN, ADMIN_IDS (comma separated), SUPPORT_USERNAME,
#           FIREBASE_DB_URL  (e.g. https://your-project-default-rtdb.firebaseio.com)
#           FIREBASE_CREDENTIALS  (full service-account JSON text)  OR a file serviceAccountKey.json
# Optional: REQUIRED_CHANNEL (e.g. @mychannel)

import asyncio
import html
import json
import logging
import os
import random
import secrets
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import firebase_admin
from firebase_admin import credentials, db as rtdb
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "your_support_username")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "")
# Channel where new Gmail submissions (with Approve/Reject buttons) are posted.
# Use the numeric id like -1001234567890 (or @username). Bot must be an admin of the channel.
_ch = os.getenv("ADMIN_CHANNEL", "").strip()
ADMIN_CHANNEL = int(_ch) if _ch.lstrip("-").isdigit() else _ch
CUR = "BDT"
WITHDRAW_METHODS = ["bKash", "Nagad", "Binance"]
WITHDRAW_COOLDOWN_HOURS = 24  # one withdraw request per user per this many hours
DEFAULTS = {"rate": 5.0, "min_withdraw": 50.0, "ref_bonus": 1.0}

logging.basicConfig(level=logging.INFO)

# ---------------- FIREBASE ----------------
_cred_json = os.getenv("FIREBASE_CREDENTIALS")
_cred = credentials.Certificate(json.loads(_cred_json) if _cred_json else "serviceAccountKey.json")
firebase_admin.initialize_app(_cred, {"databaseURL": os.getenv("FIREBASE_DB_URL", "")})
R = rtdb.reference
A = asyncio.to_thread  # run blocking Firebase calls without freezing the bot


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


def money(x):
    return f"{float(x):.2f} {CUR}"


def esc(s):
    return html.escape(str(s or ""))


def add_num(path, amt):
    R(path).transaction(lambda cur: (cur or 0) + amt)


def claim(path, old, new):
    """Atomically change a status from old -> new. Returns True only for the first caller."""
    got = {"v": False}

    def fn(cur):
        if cur == old:
            got["v"] = True
            return new
        got["v"] = False
        return cur

    R(path).transaction(fn)
    return got["v"]


# ---------------- IDENTITY GENERATOR ----------------
FIRST = ["Rafiq", "Tanvir", "Nusrat", "Sabbir", "Mim", "Arif", "Jannat", "Hasan", "Rumana", "Imran",
         "Sadia", "Fahim", "Tasnim", "Rakib", "Mitu", "Shuvo", "Farhana", "Nayeem", "Lamia", "Sohan"]
LAST = ["Ahmed", "Hossain", "Rahman", "Khan", "Islam", "Akter", "Chowdhury", "Uddin", "Sarker", "Mia",
        "Begum", "Mahmud", "Karim", "Sultana", "Biswas", "Talukdar", "Haque", "Sheikh", "Mondal", "Roy"]


def gen_password():
    chars = string.ascii_letters + string.digits
    pw = [secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase),
          secrets.choice(string.digits), secrets.choice("@#$%&*")]
    pw += [secrets.choice(chars) for _ in range(8)]
    random.shuffle(pw)
    return "".join(pw)


def gen_identity():
    while True:
        first, last = random.choice(FIRST), random.choice(LAST)
        email = f"{first}{last}{random.randint(1000, 99999)}".lower()
        if R(f"emails/{email}").get() is None:
            R(f"emails/{email}").set(True)  # reserve so it is never issued twice
            return first, last, email, gen_password()


# ---------------- DATABASE FUNCTIONS (blocking, called through A) ----------------
def get_user(uid):
    return R(f"users/{uid}").get()


def ensure_user_sync(u, ref=None):
    user = get_user(u.id)
    if user is None:
        ref_by = ref if ref and ref != u.id and get_user(ref) else 0
        R(f"users/{u.id}").set({"name": u.full_name, "username": u.username or "", "balance": 0,
                                "pending": 0, "total_earned": 0, "banned": False, "ref_by": ref_by,
                                "ref_count": 0, "joined": int(time.time())})
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
    rec = {"first": first, "last": last, "email": email, "password": pw,
           "status": "issued", "rate": cfg("rate"), "created": int(time.time())}
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
    add_num(f"users/{uid}/pending", acc["rate"])  # reward waits in Pending until admin decides
    return acc


def decide_acc_sync(uid, aid, approve):
    if not claim(f"accounts/{uid}/{aid}/status", "pending", "approved" if approve else "rejected"):
        return None
    add_num("stats/pending_acc", -1)
    acc = R(f"accounts/{uid}/{aid}").get()
    # take the reward out of Pending (never below zero, e.g. for old submissions)
    R(f"users/{uid}/pending").transaction(lambda cur: max((cur or 0) - acc["rate"], 0))
    if approve:
        add_num("stats/approved_acc", 1)
        add_num(f"users/{uid}/balance", acc["rate"])
        add_num(f"users/{uid}/total_earned", acc["rate"])
        accs = R(f"accounts/{uid}").get() or {}
        approved = sum(1 for v in accs.values() if v.get("status") == "approved")
        ref = (get_user(uid) or {}).get("ref_by")
        if approved == 1 and ref:
            add_num(f"users/{ref}/balance", cfg("ref_bonus"))
            add_num(f"users/{ref}/total_earned", cfg("ref_bonus"))
    return acc


def count_status(uid):
    c = {}
    for v in (R(f"accounts/{uid}").get() or {}).values():
        c[v.get("status")] = c.get(v.get("status"), 0) + 1
    return c


def history_sync(uid):
    accs = [v for v in (R(f"accounts/{uid}").get() or {}).values() if v.get("status") != "issued"]
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
    """Returns (status, withdraw_id). status: ok / cooldown / nobalance."""
    now = int(time.time())
    user = get_user(uid) or {}
    if now - user.get("last_withdraw", 0) < WITHDRAW_COOLDOWN_HOURS * 3600:
        return "cooldown", None
    if not deduct_sync(uid, amt):
        return "nobalance", None
    R(f"users/{uid}/last_withdraw").set(now)
    key = R(f"withdrawals/{uid}").push({"method": method, "address": addr, "amount": amt,
                                         "status": "pending", "created": now}).key
    add_num("stats/pending_wd", 1)
    return "ok", key


def decide_wd_sync(uid, wid, paid):
    if not claim(f"withdrawals/{uid}/{wid}/status", "pending", "paid" if paid else "rejected"):
        return None
    add_num("stats/pending_wd", -1)
    w = R(f"withdrawals/{uid}/{wid}").get()
    if not paid:
        add_num(f"users/{uid}/balance", w["amount"])
        R(f"users/{uid}/last_withdraw").set(0)  # rejected: allow a new request right away
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


# ---------------- HELPERS ----------------
def main_menu():
    return ReplyKeyboardMarkup(
        [["💰 Sell Gmail", "👤 My Account"], ["💸 Withdraw", "📜 History"], ["🎁 Referral", "☎️ Support"]],
        resize_keyboard=True)


def is_admin(uid):
    return uid in ADMIN_IDS


async def notify_admins(ctx, text, markup=None):
    for a in ADMIN_IDS:
        try:
            await ctx.bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception as e:
            logging.warning("admin notify failed %s: %s", a, e)


async def notify_channel(ctx, text, markup=None):
    """Post Gmail submissions to the admin channel; fall back to admin DMs if not set or it fails."""
    if ADMIN_CHANNEL:
        try:
            await ctx.bot.send_message(ADMIN_CHANNEL, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except Exception as e:
            logging.warning("channel post failed, sending to admins instead: %s", e)
    await notify_admins(ctx, text, markup)


async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    u = update.effective_user
    user = await A(ensure_user_sync, u, None)
    if user.get("banned"):
        await update.effective_message.reply_text("🚫 You are banned from using this bot.")
        return False
    if REQUIRED_CHANNEL:
        try:
            m = await ctx.bot.get_chat_member(REQUIRED_CHANNEL, u.id)
            if m.status in ("left", "kicked"):
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
                    [InlineKeyboardButton("✅ I Joined", callback_data="chk")]])
                await update.effective_message.reply_text("📢 Please join our channel to use the bot.", reply_markup=kb)
                return False
        except Exception as e:
            logging.warning("channel check failed: %s", e)
    return True


# ---------------- USER COMMANDS ----------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ref = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else None
    await A(ensure_user_sync, update.effective_user, ref)
    if not await guard(update, ctx):
        return
    ctx.user_data.clear()
    await update.message.reply_text(
        f"👋 <b>Welcome, {esc(update.effective_user.first_name)}!</b>\n\n"
        f"💎 Sell Gmail accounts and earn <b>{money(cfg('rate'))}</b> per approved account.\n\n"
        "1️⃣ Tap <b>Sell Gmail</b>\n2️⃣ Create the account with the details we give\n"
        "3️⃣ Submit it and get paid after approval ✅",
        parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def issue_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE, regenerate=False):
    uid = update.effective_user.id
    row = await A(issue_sync, uid, regenerate)
    text = (
        "📧 <b>Create this Gmail account</b>\n\n"
        f"👤 First name: <code>{row['first']}</code>\n"
        f"👤 Last name: <code>{row['last']}</code>\n"
        f"📨 Email: <code>{row['email']}@gmail.com</code>\n"
        f"🔑 Password: <code>{row['password']}</code>\n\n"
        f"💵 Reward: <b>{money(row['rate'])}</b>\n\n"
        "⚠️ Use <b>exactly</b> these details. Do not add recovery info or change the password.\n"
        "Tap any value to copy. When finished press <b>Done</b>.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Done - Submit", callback_data=f"done:{row['id']}")],
        [InlineKeyboardButton("🔄 New Details", callback_data="new"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{row['id']}")]])
    await ctx.bot.send_message(update.effective_chat.id, text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_account(update, ctx):
    uid = update.effective_user.id
    user = await A(get_user, uid)
    c = await A(count_status, uid)
    await update.message.reply_text(
        "👤 <b>My Account</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💰 Balance: <b>{money(user.get('balance', 0))}</b>\n"
        f"📈 Total earned: {money(user.get('total_earned', 0))}\n"
        f"⏳ Pending: {money(user.get('pending', 0))}\n"
        f"\n✅ Approved Gmail: {c.get('approved', 0)}\n🕒 Waiting for review: {c.get('pending', 0)}\n❌ Rejected Gmail: {c.get('rejected', 0)}",
        parse_mode=ParseMode.HTML)


async def show_history(update, ctx):
    icon = {"approved": "✅", "pending": "⏳", "rejected": "❌", "paid": "✅"}
    accs, wds = await A(history_sync, update.effective_user.id)
    t = "📜 <b>Recent Gmail submissions</b>\n"
    t += "\n".join(f"{icon.get(a['status'], '⏳')} {a['email']}@gmail.com - {a['status']}" for a in accs) or "None yet"
    t += "\n\n💸 <b>Recent withdrawals</b>\n"
    t += "\n".join(f"{icon.get(w['status'], '⏳')} {money(w['amount'])} via {w['method']} - {w['status']}"
                   for _, w in wds) or "None yet"
    await update.message.reply_text(t, parse_mode=ParseMode.HTML)


async def show_referral(update, ctx):
    uid = update.effective_user.id
    user = await A(get_user, uid)
    await update.message.reply_text(
        f"🎁 <b>Referral</b>\n\nInvite friends and earn <b>{money(cfg('ref_bonus'))}</b> when their first Gmail is approved.\n\n"
        f"🔗 Your link:\nhttps://t.me/{ctx.bot.username}?start={uid}\n\n👥 Invited: {user.get('ref_count', 0)}",
        parse_mode=ParseMode.HTML)


async def start_withdraw(update, ctx):
    user = await A(get_user, update.effective_user.id)
    bal = user.get("balance", 0)
    left = user.get("last_withdraw", 0) + WITHDRAW_COOLDOWN_HOURS * 3600 - int(time.time())
    if left > 0:
        await update.message.reply_text(
            f"⏳ You already made a withdraw request. Try again in {left // 3600}h {(left % 3600) // 60}m.")
        return
    if bal < cfg("min_withdraw"):
        await update.message.reply_text(
            f"❌ Minimum withdraw is {money(cfg('min_withdraw'))}.\nYour balance: {money(bal)}")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(m, callback_data=f"wd:{m}") for m in WITHDRAW_METHODS]])
    await update.message.reply_text(f"💸 Balance: <b>{money(bal)}</b>\nChoose a method:",
                                    parse_mode=ParseMode.HTML, reply_markup=kb)


# ---------------- TEXT ROUTER ----------------
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx):
        return
    text = update.message.text.strip()
    st = ctx.user_data.get("state")
    uid = update.effective_user.id

    if st == "wd_addr":
        ctx.user_data["addr"] = text
        ctx.user_data["state"] = "wd_amt"
        await update.message.reply_text("Enter the amount to withdraw:")
        return
    if st == "wd_amt":
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text("❌ Send a valid number.")
            return
        user = await A(get_user, uid)
        bal = user.get("balance", 0)
        if amt < cfg("min_withdraw") or amt > bal:
            await update.message.reply_text(f"❌ Amount must be between {money(cfg('min_withdraw'))} and {money(bal)}.")
            return
        method, addr = ctx.user_data["method"], ctx.user_data["addr"]
        status, wid = await A(create_wd_sync, uid, method, addr, amt)
        ctx.user_data.clear()
        if status == "cooldown":
            await update.message.reply_text(
                f"⏳ You can make only one withdraw request every {WITHDRAW_COOLDOWN_HOURS} hours.",
                reply_markup=main_menu())
            return
        if status == "nobalance":
            await update.message.reply_text("❌ Insufficient balance.", reply_markup=main_menu())
            return
        await update.message.reply_text("✅ Withdraw request submitted. Please wait for approval.",
                                        reply_markup=main_menu())
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Paid", callback_data=f"wd_ok:{uid}:{wid}"),
                                    InlineKeyboardButton("❌ Reject", callback_data=f"wd_no:{uid}:{wid}")]])
        await notify_admins(ctx, f"💸 <b>Withdraw request</b>\nUser: {esc(update.effective_user.full_name)} (<code>{uid}</code>)\n"
                                 f"Method: {method}\nAddress: <code>{esc(addr)}</code>\nAmount: {money(amt)}", kb)
        return

    menu = {
        "💰 Sell Gmail": lambda: issue_account(update, ctx),
        "👤 My Account": lambda: show_account(update, ctx),
        "💸 Withdraw": lambda: start_withdraw(update, ctx),
        "📜 History": lambda: show_history(update, ctx),
        "🎁 Referral": lambda: show_referral(update, ctx),
        "☎️ Support": lambda: update.message.reply_text(f"☎️ Support: @{SUPPORT_USERNAME}"),
    }
    if text in menu:
        await menu[text]()


# ---------------- CALLBACKS ----------------
async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    await q.answer()

    if data == "chk":
        if await guard(update, ctx):
            await q.message.reply_text("✅ Thanks! Send /start", reply_markup=main_menu())
        return

    # ----- admin actions -----
    if data.startswith(("ok:", "no:", "wd_ok:", "wd_no:")):
        if not is_admin(uid):
            return
        action, tuid, rid = data.split(":")
        if action in ("ok", "no"):
            acc = await A(decide_acc_sync, tuid, rid, action == "ok")
            if not acc:
                await q.edit_message_text("Already handled.")
                return
            if action == "ok":
                msg = f"✅ Your Gmail <code>{acc['email']}@gmail.com</code> was approved! +{money(acc['rate'])}"
            else:
                msg = f"❌ Your Gmail <code>{acc['email']}@gmail.com</code> was rejected."
            await q.edit_message_text(q.message.text + f"\n\n➡️ {'APPROVED' if action == 'ok' else 'REJECTED'}")
            try:
                await ctx.bot.send_message(int(tuid), msg, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            w = await A(decide_wd_sync, tuid, rid, action == "wd_ok")
            if not w:
                await q.edit_message_text("Already handled.")
                return
            msg = (f"✅ Your withdraw of {money(w['amount'])} was paid." if action == "wd_ok"
                   else f"❌ Withdraw rejected. {money(w['amount'])} refunded to your balance.")
            await q.edit_message_text(q.message.text + f"\n\n➡️ {'PAID' if action == 'wd_ok' else 'REJECTED'}")
            try:
                await ctx.bot.send_message(int(tuid), msg)
            except Exception:
                pass
        return

    if not await guard(update, ctx):
        return

    if data == "new":
        await q.message.delete()
        await issue_account(update, ctx, regenerate=True)

    elif data.startswith("cancel:"):
        await A(cancel_sync, uid, data.split(":")[1])
        await q.edit_message_text("❌ Cancelled.")

    elif data.startswith("done:"):
        acc = await A(submit_sync, uid, data.split(":")[1])
        if not acc:
            await q.edit_message_text("⚠️ This request is no longer valid.")
            return
        await q.edit_message_text(f"⏳ Submitted <code>{acc['email']}@gmail.com</code>. Waiting for admin approval.",
                                  parse_mode=ParseMode.HTML)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"ok:{uid}:{acc['id']}"),
                                    InlineKeyboardButton("❌ Reject", callback_data=f"no:{uid}:{acc['id']}")]])
        await notify_channel(ctx, f"🆕 <b>New Gmail submission</b>\nUser: {esc(q.from_user.full_name)} (<code>{uid}</code>)\n"
                                 f"Email: <code>{acc['email']}@gmail.com</code>\nPassword: <code>{acc['password']}</code>\n"
                                 f"Reward: {money(acc['rate'])}", kb)

    elif data.startswith("wd:"):
        method = data.split(":")[1]
        ctx.user_data.update({"state": "wd_addr", "method": method})
        await q.edit_message_text(f"Send your <b>{method}</b> number / address:", parse_mode=ParseMode.HTML)


# ---------------- ADMIN COMMANDS ----------------
def admin_only(fn):
    async def wrapper(update, ctx):
        if is_admin(update.effective_user.id):
            await fn(update, ctx)
    return wrapper


@admin_only
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n, s = await A(stats_sync)
    await update.message.reply_text(
        "🛠 <b>Admin Panel</b>\n\n"
        f"👥 Users: {n}\n"
        f"⏳ Pending Gmail: {s.get('pending_acc', 0)}\n"
        f"✅ Approved Gmail: {s.get('approved_acc', 0)}\n"
        f"💸 Pending withdraws: {s.get('pending_wd', 0)}\n\n"
        f"Rate: {money(cfg('rate'))} | Min withdraw: {money(cfg('min_withdraw'))} | Ref bonus: {money(cfg('ref_bonus'))}\n\n"
        "<b>Commands</b>\n/setrate 6\n/setmin 100\n/setref 1\n/ban USER_ID\n/unban USER_ID\n"
        "/addbal USER_ID AMOUNT\n/broadcast message",
        parse_mode=ParseMode.HTML)


@admin_only
async def set_cfg_cmd(update, ctx):
    key = {"/setrate": "rate", "/setmin": "min_withdraw", "/setref": "ref_bonus"}[update.message.text.split()[0].split("@")[0]]
    try:
        val = float(ctx.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setrate 6")
        return
    await A(set_cfg_sync, key, val)
    await update.message.reply_text(f"✅ {key} = {val}")


@admin_only
async def ban_cmd(update, ctx):
    ban = update.message.text.startswith("/ban")
    try:
        ok = await A(set_ban_sync, int(ctx.args[0]), ban)
        await update.message.reply_text("✅ Done" if ok else "User not found")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ban USER_ID")


@admin_only
async def addbal_cmd(update, ctx):
    try:
        ok = await A(add_balance_sync, int(ctx.args[0]), float(ctx.args[1]))
        await update.message.reply_text("✅ Balance updated" if ok else "User not found")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addbal USER_ID AMOUNT")


@admin_only
async def broadcast_cmd(update, ctx):
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text("Usage: /broadcast message")
        return
    sent = 0
    for uid in await A(all_user_ids_sync):
        try:
            await ctx.bot.send_message(int(uid), msg)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"📢 Sent to {sent} users")


# ---------------- KEEP-ALIVE WEB SERVER (for Render + UptimeRobot) ----------------
class PingHandler(BaseHTTPRequestHandler):
    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def do_GET(self):
        self._ok()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self._ok()

    def log_message(self, *args):
        pass  # keep logs clean


def start_keep_alive():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Keep-alive server listening on port %s", port)


# ---------------- MAIN ----------------
def main():
    start_keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    for c in ("setrate", "setmin", "setref"):
        app.add_handler(CommandHandler(c, set_cfg_cmd))
    app.add_handler(CommandHandler(["ban", "unban"], ban_cmd))
    app.add_handler(CommandHandler("addbal", addbal_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
