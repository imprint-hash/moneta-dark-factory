"""Pocketful stage 1: payments, idempotency, auth, export/import.

All state lives in one in-memory dict guarded by a single lock, so every write
(balances, payments, idempotency records) is one atomic step and readers never
see an intermediate state.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_AMOUNT = 1_000_000_000
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
DIGITS_RE = re.compile(r"^[0-9]+$")
STATUSES = ("pending", "paid", "declined", "cancelled")
VISIBILITIES = ("public", "private")
AUTH_STATUSES = ("open", "captured", "voided", "expired")

LOCK = threading.RLock()
STATE: dict = {}
IDX: dict = {}


class ApiError(Exception):
    def __init__(self, status, code, message=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    value = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                           n=4096, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt.hex()}${value.hex()}"


def verify_password(password, encoded) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        algo, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        value = hashlib.scrypt(password.encode("utf-8", "surrogatepass"),
                               salt=bytes.fromhex(salt), n=4096, r=8, p=1,
                               maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- helpers

def now_iso(dt=None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_integral(v):
    """Integral numeric value -> int, else None."""
    if not is_number(v):
        return None
    if isinstance(v, int):
        return v
    if math.isfinite(v) and v == int(v):
        return int(v)
    return None


def canonical(v):
    """Canonical JSON text; integral floats equal their int (1e3 == 1000)."""
    def norm(x):
        if isinstance(x, bool) or x is None or isinstance(x, (str, int)):
            return x
        if isinstance(x, float):
            return int(x) if math.isfinite(x) and x == int(x) else x
        if isinstance(x, list):
            return [norm(i) for i in x]
        if isinstance(x, dict):
            return {k: norm(i) for k, i in x.items()}
        return x
    return json.dumps(norm(v), sort_keys=True, separators=(",", ":"))


def parse_amount(v) -> int:
    n = as_integral(v)
    if n is None or n < 1 or n > MAX_AMOUNT:
        raise ApiError(422, "validation_failed", "amount must be an integer from 1 to 1000000000")
    return n


def parse_note(body) -> str:
    if "note" not in body:
        return ""
    n = body["note"]
    if not isinstance(n, str) or len(n) > 200:
        raise ApiError(422, "validation_failed", "note must be a string of at most 200 characters")
    return n


def parse_visibility(body) -> str:
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if v not in VISIBILITIES or not isinstance(v, str):
        raise ApiError(422, "validation_failed", "visibility must be public or private")
    return v


def require_str(body, field):
    """Missing -> 422, wrong JSON type -> 400."""
    if field not in body:
        raise ApiError(422, "validation_failed", f"{field} is required")
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(400, "malformed_request", f"{field} must be a string")
    return v


def parse_paging(query):
    def get(name, default, lo, hi):
        vals = query.get(name)
        if not vals:
            return default
        raw = vals[-1]
        if not DIGITS_RE.match(raw) or len(raw) > 18:
            raise ApiError(422, "validation_failed", f"{name} must be plain decimal digits")
        n = int(raw)
        if n < lo or (hi is not None and n > hi):
            raise ApiError(422, "validation_failed", f"{name} out of range")
        return n
    return get("limit", 50, 1, 200), get("offset", 0, 0, None)


# ---------------------------------------------------------------- state

def empty_state(currency="EUR", minor_units=2):
    return {
        "currency": currency, "minor_units": minor_units,
        "users": {}, "tokens": {}, "payments": [], "requests": {}, "splits": {},
        "settlements": {}, "idem": {}, "operators": [],
        "ttl": 600, "authorizations": {},
        "counters": {"payment": 0, "request": 0, "split": 0, "settlement": 0,
                     "user": 0, "seq": 0, "authorization": 0},
    }


def build_index(state):
    by_email, by_handle = {}, {}
    for u in state["users"].values():
        by_email[u["email"].lower()] = u["id"]
        by_handle[u["handle"]] = u["id"]
    payments = {p["id"]: p for p in state["payments"]}
    return {"by_email": by_email, "by_handle": by_handle, "payments": payments}


def install(state):
    global STATE, IDX
    idx = build_index(state)
    with LOCK:
        STATE, IDX = state, idx


def bad(msg):
    raise ApiError(422, "validation_failed", msg)


def balance_of(v, what):
    n = as_integral(v)
    if n is None or n < 0 or n > 2 ** 53:
        bad(f"{what} must be a non-negative integer")
    return n


def need_str(d, k, what):
    v = d.get(k)
    if not isinstance(v, str):
        bad(f"{what}.{k} must be a string")
    return v


def parse_ts(v, what):
    if v is None:
        return None
    if not isinstance(v, str):
        bad(f"{what} must be a timestamp string")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        bad(f"{what} is not a valid timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return now_iso(dt)


def state_from_fixture(fx) -> dict:
    if not isinstance(fx, dict):
        raise ApiError(400, "malformed_request", "fixture must be an object")
    currency = fx.get("currency", "EUR")
    mu = fx.get("minor_units", 2)
    if not isinstance(currency, str) or not currency:
        bad("currency must be a string")
    mu = as_integral(mu)
    if mu not in (0, 2, 3):
        bad("minor_units must be 0, 2 or 3")
    st = empty_state(currency, mu)
    if "authorization_ttl_seconds" in fx:
        ttl = as_integral(fx["authorization_ttl_seconds"])
        if ttl is None or ttl < 1:
            bad("authorization_ttl_seconds must be a positive integer")
        st["ttl"] = ttl
    for key in ("users", "payments", "requests", "settlement_operator_ids", "authorizations"):
        if key in fx and fx[key] is not None and not isinstance(fx[key], list):
            bad(f"{key} must be a list")
    seen_email, seen_handle = set(), set()
    for raw in fx.get("users") or []:
        if not isinstance(raw, dict):
            bad("user must be an object")
        uid = need_str(raw, "id", "user")
        if not uid or len(uid) > 64 or uid in st["users"]:
            bad("user id invalid or duplicated")
        email = need_str(raw, "email", "user")
        password = need_str(raw, "password", "user")
        handle = need_str(raw, "handle", "user")
        display = raw.get("display_name", handle)
        if not isinstance(display, str):
            bad("user.display_name must be a string")
        if not HANDLE_RE.match(handle) or handle in seen_handle:
            bad("user handle invalid or duplicated")
        if email.lower() in seen_email:
            bad("duplicate email")
        seen_handle.add(handle)
        seen_email.add(email.lower())
        st["users"][uid] = {
            "id": uid, "email": email, "display_name": display, "handle": handle,
            "balance": balance_of(raw.get("balance", 0), "balance"),
            "pw": hash_password(password),
        }
    base = datetime.now(timezone.utc) - timedelta(
        seconds=len(fx.get("payments") or []) + len(fx.get("requests") or []) + 1)
    tick = 0
    for raw in fx.get("payments") or []:
        if not isinstance(raw, dict):
            bad("payment must be an object")
        pid = need_str(raw, "id", "payment")
        if not pid or len(pid) > 64 or pid in {p["id"] for p in st["payments"]}:
            bad("payment id invalid or duplicated")
        frm, to = need_str(raw, "from_user_id", "payment"), need_str(raw, "to_user_id", "payment")
        if frm not in st["users"] or to not in st["users"]:
            bad("payment references unknown user")
        amount = as_integral(raw.get("amount"))
        if amount is None or amount < 0:
            bad("payment amount invalid")
        note = raw.get("note", "")
        vis = raw.get("visibility", "public")
        if not isinstance(note, str) or vis not in VISIBILITIES:
            bad("payment note/visibility invalid")
        created = parse_ts(raw.get("created_at"), "created_at") or now_iso(base + timedelta(seconds=tick))
        tick += 1
        st["counters"]["seq"] += 1
        st["payments"].append({
            "id": pid, "from_user_id": frm, "to_user_id": to, "amount": amount,
            "note": note, "visibility": vis, "request_id": raw.get("request_id"),
            "settlement_id": None, "created_at": created, "seq": st["counters"]["seq"],
        })
    for raw in fx.get("requests") or []:
        if not isinstance(raw, dict):
            bad("request must be an object")
        rid = need_str(raw, "id", "request")
        if not rid or len(rid) > 64 or rid in st["requests"]:
            bad("request id invalid or duplicated")
        rq, py = need_str(raw, "requester_id", "request"), need_str(raw, "payer_id", "request")
        if rq not in st["users"] or py not in st["users"]:
            bad("request references unknown user")
        amount = as_integral(raw.get("amount"))
        if amount is None or amount < 0:
            bad("request amount invalid")
        note = raw.get("note", "")
        status = raw.get("status", "pending")
        if not isinstance(note, str) or status not in STATUSES:
            bad("request note/status invalid")
        pay_id = raw.get("payment_id")
        if pay_id is not None and not isinstance(pay_id, str):
            bad("request payment_id invalid")
        created = parse_ts(raw.get("created_at"), "created_at") or now_iso(base + timedelta(seconds=tick))
        tick += 1
        st["counters"]["seq"] += 1
        st["requests"][rid] = {
            "id": rid, "requester_id": rq, "payer_id": py, "amount": amount,
            "note": note, "status": status, "payment_id": pay_id,
            "split_id": None, "created_at": created, "seq": st["counters"]["seq"],
        }
    now_dt = datetime.now(timezone.utc)
    for raw in fx.get("authorizations") or []:
        if not isinstance(raw, dict):
            bad("authorization must be an object")
        aid = need_str(raw, "id", "authorization")
        if not aid or len(aid) > 64 or aid in st["authorizations"]:
            bad("authorization id invalid or duplicated")
        frm, to = need_str(raw, "from_user_id", "authorization"), need_str(raw, "to_user_id", "authorization")
        if frm not in st["users"] or to not in st["users"] or frm == to:
            bad("authorization references unknown user")
        amount = as_integral(raw.get("amount"))
        if amount is None or amount < 1:
            bad("authorization amount invalid")
        note = raw.get("note", "")
        vis = raw.get("visibility", "public")
        status = raw.get("status", "open")
        if not isinstance(note, str) or vis not in VISIBILITIES or status not in AUTH_STATUSES:
            bad("authorization note/visibility/status invalid")
        expires = parse_ts(raw.get("expires_at"), "expires_at")
        if expires is None:
            bad("authorization expires_at is required")
        cap = as_integral(raw.get("captured_amount", amount if status == "captured" else 0))
        if cap is None or cap < 0 or cap > amount:
            bad("authorization captured_amount invalid")
        pids = raw.get("payment_ids") or []
        if not isinstance(pids, list) or not all(isinstance(x, str) for x in pids):
            bad("authorization payment_ids invalid")
        created = parse_ts(raw.get("created_at"), "created_at") or now_iso(base + timedelta(seconds=tick))
        tick += 1
        if status == "open" and datetime.fromisoformat(expires) <= now_dt:
            status = "expired"
        st["counters"]["seq"] += 1
        st["authorizations"][aid] = {
            "id": aid, "from_user_id": frm, "to_user_id": to, "amount": amount,
            "captured_amount": cap, "note": note, "visibility": vis, "status": status,
            "expires_at": expires, "payment_ids": pids, "created_at": created,
            "seq": st["counters"]["seq"],
        }
    holds = {}
    for a in st["authorizations"].values():
        if a["status"] == "open":
            holds[a["from_user_id"]] = holds.get(a["from_user_id"], 0) + a["amount"] - a["captured_amount"]
    for uid, h in holds.items():
        if h > st["users"][uid]["balance"]:
            bad("seeded holds exceed balance")
    ops = fx.get("settlement_operator_ids") or []
    if not all(isinstance(o, str) for o in ops):
        bad("settlement_operator_ids must be strings")
    st["operators"] = list(dict.fromkeys(ops))
    return st


def state_from_export(state) -> dict:
    """Validate an exported state object strictly; return a fresh deep copy."""
    if not isinstance(state, dict):
        bad("state must be an object")
    s = copy.deepcopy(state)
    if isinstance(s, dict) and isinstance(s.get("counters"), dict):
        s["counters"].setdefault("authorization", 0)
    if isinstance(s, dict):
        s.setdefault("ttl", 600)
        s.setdefault("authorizations", {})
    try:
        cur = s["currency"]
        if not isinstance(cur, str) or as_integral(s["minor_units"]) not in (0, 2, 3):
            bad("currency invalid")
        users, tokens = s["users"], s["tokens"]
        payments, requests = s["payments"], s["requests"]
        if not (isinstance(users, dict) and isinstance(tokens, dict) and isinstance(payments, list)
                and isinstance(requests, dict) and isinstance(s["splits"], dict)
                and isinstance(s["settlements"], dict) and isinstance(s["idem"], dict)
                and isinstance(s["operators"], list) and isinstance(s["counters"], dict)):
            bad("state has wrong shapes")
        for k in ("payment", "request", "split", "settlement", "user", "seq"):
            if not isinstance(s["counters"].get(k), int) or isinstance(s["counters"][k], bool):
                bad("counters invalid")
        handles, emails = set(), set()
        for uid, u in users.items():
            if not isinstance(u, dict) or u.get("id") != uid:
                bad("user invalid")
            for k in ("email", "display_name", "handle", "pw"):
                need_str(u, k, "user")
            if not HANDLE_RE.match(u["handle"]) or u["handle"] in handles or u["email"].lower() in emails:
                bad("user handle/email invalid")
            handles.add(u["handle"])
            emails.add(u["email"].lower())
            balance_of(u.get("balance"), "balance")
        for tok, uid in tokens.items():
            if uid not in users:
                bad("token references unknown user")
        ids = set()
        for p in payments:
            if not isinstance(p, dict):
                bad("payment invalid")
            for k in ("id", "from_user_id", "to_user_id", "note", "created_at"):
                need_str(p, k, "payment")
            if p["id"] in ids or p["from_user_id"] not in users or p["to_user_id"] not in users:
                bad("payment invalid")
            ids.add(p["id"])
            if as_integral(p.get("amount")) is None or p.get("visibility") not in VISIBILITIES:
                bad("payment invalid")
            if not isinstance(p.get("seq"), int):
                bad("payment invalid")
        for rid, r in requests.items():
            if not isinstance(r, dict) or r.get("id") != rid:
                bad("request invalid")
            if r.get("requester_id") not in users or r.get("payer_id") not in users \
                    or r.get("status") not in STATUSES or as_integral(r.get("amount")) is None:
                bad("request invalid")
        for k, rec in s["idem"].items():
            if not isinstance(rec, dict) or not isinstance(rec.get("hash"), str) \
                    or not isinstance(rec.get("status"), int) or "response" not in rec:
                bad("idempotency record invalid")
        if not all(isinstance(o, str) for o in s["operators"]):
            bad("operators invalid")
        ttl = as_integral(s["ttl"])
        if ttl is None or ttl < 1 or not isinstance(s["authorizations"], dict):
            bad("authorization settings invalid")
        holds = {}
        for aid, a in s["authorizations"].items():
            if not isinstance(a, dict) or a.get("id") != aid:
                bad("authorization invalid")
            for k in ("from_user_id", "to_user_id", "expires_at", "created_at", "note"):
                need_str(a, k, "authorization")
            if a["from_user_id"] not in users or a["to_user_id"] not in users \
                    or a.get("status") not in AUTH_STATUSES or a.get("visibility") not in VISIBILITIES \
                    or as_integral(a.get("amount")) is None or as_integral(a.get("captured_amount")) is None \
                    or not isinstance(a.get("payment_ids"), list) or not isinstance(a.get("seq"), int):
                bad("authorization invalid")
            if a["status"] == "open":
                holds[a["from_user_id"]] = holds.get(a["from_user_id"], 0) + a["amount"] - a["captured_amount"]
        for uid, h in holds.items():
            if h > users[uid]["balance"]:
                bad("holds exceed balance")
    except KeyError:
        bad("state is missing fields")
    return s


# ---------------------------------------------------------------- domain

def next_id(prefix, counter, exists):
    c = STATE["counters"]
    while True:
        c[counter] += 1
        cand = f"{prefix}_{c[counter]}"
        if not exists(cand):
            return cand


def payment_view(p):
    users = STATE["users"]
    return {
        "payment_id": p["id"],
        "from_user_id": p["from_user_id"],
        "from_handle": users[p["from_user_id"]]["handle"],
        "to_user_id": p["to_user_id"],
        "to_handle": users[p["to_user_id"]]["handle"],
        "amount": p["amount"],
        "currency": STATE["currency"],
        "note": p["note"],
        "visibility": p["visibility"],
        "request_id": p.get("request_id"),
        "authorization_id": p.get("authorization_id"),
        "settlement_id": p.get("settlement_id"),
        "created_at": p["created_at"],
    }


def make_payment(frm, to, amount, note, visibility, request_id=None,
                 settlement_id=None, created_at=None, authorization_id=None):
    """Move money and record the payment. Caller holds LOCK and has checked funds."""
    st = STATE
    st["users"][frm["id"]]["balance"] -= amount
    st["users"][to["id"]]["balance"] += amount
    st["counters"]["seq"] += 1
    p = {
        "id": next_id("p", "payment", lambda i: i in IDX["payments"]),
        "from_user_id": frm["id"], "to_user_id": to["id"], "amount": amount,
        "note": note, "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "authorization_id": authorization_id,
        "created_at": created_at or now_iso(), "seq": st["counters"]["seq"],
    }
    st["payments"].append(p)
    IDX["payments"][p["id"]] = p
    return p


def user_by_handle(handle):
    uid = IDX["by_handle"].get(handle)
    return STATE["users"][uid] if uid else None


def idempotent(user, method, path, key, body, op):
    """Generic idempotency layer. Caller holds LOCK. op() -> response dict (201)
    or raises ApiError (nothing is recorded for failures)."""
    rk = json.dumps([user["id"], method, path, key])
    h = canonical(body)
    rec = STATE["idem"].get(rk)
    if rec is not None:
        if rec["hash"] != h:
            raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
        return 200, copy.deepcopy(rec["response"])
    resp = op()
    STATE["idem"][rk] = {"hash": h, "status": 201, "response": copy.deepcopy(resp)}
    return 201, resp


# ---------------------------------------------------------------- endpoints

def do_signup(body):
    email = require_str(body, "email")
    password = require_str(body, "password")
    display = require_str(body, "display_name")
    if not EMAIL_RE.match(email) or len(password) < 8:
        bad("invalid email or password too short")
    handle = re.sub(r"[^a-z0-9_]", "_", email.split("@")[0].lower())[:20]
    pw = hash_password(password)
    with LOCK:
        if email.lower() in IDX["by_email"]:
            raise ApiError(409, "email_taken")
        if handle in IDX["by_handle"]:
            raise ApiError(409, "handle_taken")
        uid = next_id("u", "user", lambda i: i in STATE["users"])
        STATE["users"][uid] = {"id": uid, "email": email, "display_name": display,
                               "handle": handle, "balance": 0, "pw": pw}
        IDX["by_email"][email.lower()] = uid
        IDX["by_handle"][handle] = uid
        token = secrets.token_hex(24)
        STATE["tokens"][token] = uid
    return 201, {"user_id": uid, "display_name": display, "token": token}


def do_login(body):
    email = require_str(body, "email")
    password = require_str(body, "password")
    with LOCK:
        uid = IDX["by_email"].get(email.lower())
        u = dict(STATE["users"][uid]) if uid else None
    if not u or not verify_password(password, u["pw"]):
        raise ApiError(401, "unauthenticated", "invalid credentials")
    with LOCK:
        if uid not in STATE["users"]:
            raise ApiError(401, "unauthenticated", "invalid credentials")
        token = secrets.token_hex(24)
        STATE["tokens"][token] = uid
    return 200, {"user_id": uid, "display_name": u["display_name"], "token": token}


def do_me(user):
    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                 "handle": user["handle"], "balance": user["balance"],
                 "total": user["balance"], "available": available(user),
                 "held": held_of(user["id"]),
                 "currency": STATE["currency"], "minor_units": STATE["minor_units"]}


def do_payment(user, body):
    to_handle = require_str(body, "to_handle")
    if "amount" not in body:
        bad("amount is required")
    amount = parse_amount(body["amount"])
    note = parse_note(body)
    vis = parse_visibility(body)
    if to_handle == user["handle"]:
        raise ApiError(422, "self_payment", "cannot pay yourself")
    to = user_by_handle(to_handle)
    if to is None:
        raise ApiError(404, "not_found", "no such handle")
    if available(user) < amount:
        raise ApiError(409, "insufficient_funds")
    return payment_view(make_payment(user, to, amount, note, vis))


def do_activity(user, query):
    limit, offset = parse_paging(query)
    out, skipped = [], 0
    uid = user["id"]
    for p in reversed(STATE["payments"]):
        if p["visibility"] != "public" and uid not in (p["from_user_id"], p["to_user_id"]):
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append(payment_view(p))
        if len(out) > limit:
            break
    return 200, {"payments": out[:limit], "has_more": len(out) > limit}


def request_view(r):
    users = STATE["users"]
    return {
        "request_id": r["id"],
        "requester_id": r["requester_id"],
        "requester_handle": users[r["requester_id"]]["handle"],
        "payer_id": r["payer_id"],
        "payer_handle": users[r["payer_id"]]["handle"],
        "amount": r["amount"],
        "currency": STATE["currency"],
        "note": r["note"],
        "status": r["status"],
        "payment_id": r["payment_id"],
        "created_at": r["created_at"],
    }


def new_request(requester, payer, amount, note, split_id=None, created_at=None):
    st = STATE
    st["counters"]["seq"] += 1
    r = {
        "id": next_id("rq", "request", lambda i: i in st["requests"]),
        "requester_id": requester["id"], "payer_id": payer["id"], "amount": amount,
        "note": note, "status": "pending", "payment_id": None, "split_id": split_id,
        "created_at": created_at or now_iso(), "seq": st["counters"]["seq"],
    }
    st["requests"][r["id"]] = r
    return r


def do_request(user, body):
    payer_handle = require_str(body, "payer_handle")
    if "amount" not in body:
        bad("amount is required")
    amount = parse_amount(body["amount"])
    note = parse_note(body)
    if payer_handle == user["handle"]:
        raise ApiError(422, "self_request", "cannot request from yourself")
    payer = user_by_handle(payer_handle)
    if payer is None:
        raise ApiError(404, "not_found", "no such handle")
    return request_view(new_request(user, payer, amount, note))


def get_request_for(rid):
    r = STATE["requests"].get(rid)
    if r is None:
        raise ApiError(404, "not_found", "no such request")
    return r


def do_pay(user, body, rid):
    r = get_request_for(rid)
    if r["payer_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may pay")
    vis = parse_visibility(body)
    if r["status"] != "pending":
        raise ApiError(409, "request_not_pending")
    if available(user) < r["amount"]:
        raise ApiError(409, "insufficient_funds")
    requester = STATE["users"][r["requester_id"]]
    p = make_payment(user, requester, r["amount"], r["note"], vis, request_id=r["id"])
    r["status"] = "paid"
    r["payment_id"] = p["id"]
    return payment_view(p)


def do_decline_cancel(user, rid, action):
    r = get_request_for(rid)
    party, target = (("payer_id", "declined") if action == "decline"
                     else ("requester_id", "cancelled"))
    if r[party] != user["id"]:
        raise ApiError(403, "forbidden", f"only the {party[:-3]} may {action}")
    if r["status"] == target:
        return 200, request_view(r)
    if r["status"] != "pending":
        raise ApiError(409, "request_not_pending")
    r["status"] = target
    return 200, request_view(r)


def do_requests(user, query):
    limit, offset = parse_paging(query)
    direction = (query.get("direction") or [None])[-1]
    status = (query.get("status") or [None])[-1]
    if direction is not None and direction not in ("incoming", "outgoing"):
        bad("unknown direction")
    if status is not None and status not in STATUSES:
        bad("unknown status")
    uid = user["id"]
    out, skipped = [], 0
    for r in sorted(STATE["requests"].values(), key=lambda x: x["seq"], reverse=True):
        mine_in, mine_out = r["payer_id"] == uid, r["requester_id"] == uid
        if direction == "incoming" and not mine_in:
            continue
        if direction == "outgoing" and not mine_out:
            continue
        if not (mine_in or mine_out) or (status and r["status"] != status):
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append(request_view(r))
        if len(out) > limit:
            break
    return 200, {"requests": out[:limit], "has_more": len(out) > limit}


def equal_shares(amount, n):
    base, extra = divmod(amount, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def do_split(user, body):
    if "amount" not in body:
        bad("amount is required")
    amount = parse_amount(body["amount"])
    if "participant_handles" not in body:
        bad("participant_handles is required")
    handles = body["participant_handles"]
    if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
        raise ApiError(400, "malformed_request", "participant_handles must be a list of strings")
    if not handles or len(set(handles)) != len(handles):
        bad("participant_handles must be non-empty and unique")
    note = parse_note(body)
    people = []
    for h in handles:
        u = user_by_handle(h)
        if u is None:
            raise ApiError(404, "not_found", f"no such handle {h}")
        people.append(u)
    st = STATE
    now = now_iso()
    amounts = equal_shares(amount, len(people))
    split_id = next_id("sp", "split", lambda i: i in st["splits"])
    reqs = [request_view(new_request(user, u, a, note, split_id, now))
            for u, a in zip(people, amounts) if u["id"] != user["id"]]
    resp = {
        "split_id": split_id, "amount": amount, "currency": st["currency"], "note": note,
        "shares": [{"handle": u["handle"], "amount": a} for u, a in zip(people, amounts)],
        "requests": reqs, "created_at": now,
    }
    st["splits"][split_id] = {"id": split_id, "user_id": user["id"],
                              "request_ids": [r["request_id"] for r in reqs],
                              "created_at": now}
    return resp


def do_settlement(user, body):
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32:
        bad("transfers must be a list of 1 to 32 objects")
    if not all(isinstance(t, dict) for t in transfers):
        bad("each transfer must be an object")
    entries = []
    for t in transfers:
        fh, th = t.get("from_handle"), t.get("to_handle")
        if not isinstance(fh, str) or not isinstance(th, str) or "amount" not in t:
            bad("transfer needs from_handle, to_handle and amount")
        amount = parse_amount(t["amount"])
        note = parse_note(t)
        vis = parse_visibility(t)
        if fh == th:
            raise ApiError(422, "self_payment", "cannot transfer to the same wallet")
        frm, to = user_by_handle(fh), user_by_handle(th)
        if frm is None or to is None:
            raise ApiError(404, "not_found", "no such handle")
        entries.append((frm, to, amount, note, vis))
    net = {}
    for frm, to, amount, _, _ in entries:
        net[frm["id"]] = net.get(frm["id"], 0) - amount
        net[to["id"]] = net.get(to["id"], 0) + amount
    for uid, delta in net.items():
        if available(STATE["users"][uid]) + delta < 0:
            raise ApiError(409, "insufficient_funds", "settlement is not affordable")
    st = STATE
    committed = now_iso()
    sid = next_id("st", "settlement", lambda i: i in st["settlements"])
    payments = [make_payment(f, t, a, n, v, settlement_id=sid, created_at=committed)
                for f, t, a, n, v in entries]
    st["settlements"][sid] = {"id": sid, "user_id": user["id"], "committed_at": committed,
                              "payment_ids": [p["id"] for p in payments]}
    return {"settlement_id": sid, "committed_at": committed,
            "payments": [payment_view(p) for p in payments]}


def sweep():
    """Expire open authorizations whose deadline has passed (lazy, on every request)."""
    now = datetime.now(timezone.utc)
    for a in STATE["authorizations"].values():
        if a["status"] == "open" and datetime.fromisoformat(a["expires_at"]) <= now:
            a["status"] = "expired"


def remaining_of(a):
    return a["amount"] - a["captured_amount"] if a["status"] == "open" else 0


def held_of(uid):
    return sum(remaining_of(a) for a in STATE["authorizations"].values()
               if a["from_user_id"] == uid)


def available(user):
    return user["balance"] - held_of(user["id"])


def authorization_view(a):
    users = STATE["users"]
    pids = a["payment_ids"]
    return {
        "authorization_id": a["id"],
        "from_user_id": a["from_user_id"],
        "from_handle": users[a["from_user_id"]]["handle"],
        "to_user_id": a["to_user_id"],
        "to_handle": users[a["to_user_id"]]["handle"],
        "amount": a["amount"],
        "captured_amount": a["captured_amount"],
        "remaining_amount": remaining_of(a),
        "currency": STATE["currency"],
        "note": a["note"],
        "visibility": a["visibility"],
        "status": a["status"],
        "expires_at": a["expires_at"],
        "payment_id": pids[-1] if pids else None,
        "payment_ids": list(pids),
        "created_at": a["created_at"],
    }


def do_authorize(user, body):
    to_handle = require_str(body, "to_handle")
    if "amount" not in body:
        bad("amount is required")
    amount = parse_amount(body["amount"])
    note = parse_note(body)
    vis = parse_visibility(body)
    if to_handle == user["handle"]:
        raise ApiError(422, "self_payment", "cannot authorize yourself")
    to = user_by_handle(to_handle)
    if to is None:
        raise ApiError(404, "not_found", "no such handle")
    if available(user) < amount:
        raise ApiError(409, "insufficient_funds")
    st = STATE
    st["counters"]["seq"] += 1
    created = datetime.now(timezone.utc).replace(microsecond=0)
    a = {
        "id": next_id("a", "authorization", lambda i: i in st["authorizations"]),
        "from_user_id": user["id"], "to_user_id": to["id"], "amount": amount,
        "captured_amount": 0, "note": note, "visibility": vis, "status": "open",
        "expires_at": now_iso(created + timedelta(seconds=st["ttl"])),
        "payment_ids": [], "created_at": now_iso(created), "seq": st["counters"]["seq"],
    }
    st["authorizations"][a["id"]] = a
    return authorization_view(a)


def get_auth_for(aid):
    a = STATE["authorizations"].get(aid)
    if a is None:
        raise ApiError(404, "not_found", "no such authorization")
    return a


def do_capture(user, body, aid):
    a = get_auth_for(aid)
    if a["to_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the receiver may capture")
    amount = None
    if "amount" in body:
        amount = as_integral(body["amount"])
        if amount is None or amount < 1:
            bad("amount must be a positive integer")
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise ApiError(400, "malformed_request", "final must be a boolean")
    if a["status"] == "expired":
        raise ApiError(409, "authorization_expired")
    if a["status"] != "open":
        raise ApiError(409, "authorization_not_open")
    remaining = remaining_of(a)
    if amount is None:
        amount = remaining
    if amount > remaining:
        raise ApiError(422, "capture_exceeds_authorization", "amount exceeds the remaining hold")
    frm, to = STATE["users"][a["from_user_id"]], STATE["users"][a["to_user_id"]]
    p = make_payment(frm, to, amount, a["note"], a["visibility"], authorization_id=a["id"])
    a["captured_amount"] += amount
    a["payment_ids"].append(p["id"])
    if final or a["captured_amount"] >= a["amount"]:
        a["status"] = "captured"
    return payment_view(p)


def do_void(user, aid):
    a = get_auth_for(aid)
    if a["from_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may void")
    if a["status"] == "voided":
        return 200, authorization_view(a)
    if a["status"] != "open":
        raise ApiError(409, "authorization_not_open")
    a["status"] = "voided"
    return 200, authorization_view(a)


def do_authorizations(user, query):
    limit, offset = parse_paging(query)
    direction = (query.get("direction") or [None])[-1]
    status = (query.get("status") or [None])[-1]
    if direction is not None and direction not in ("incoming", "outgoing"):
        bad("unknown direction")
    if status is not None and status not in AUTH_STATUSES:
        bad("unknown status")
    uid = user["id"]
    out, skipped = [], 0
    for a in sorted(STATE["authorizations"].values(), key=lambda x: x["seq"], reverse=True):
        mine_out, mine_in = a["from_user_id"] == uid, a["to_user_id"] == uid
        if direction == "outgoing" and not mine_out:
            continue
        if direction == "incoming" and not mine_in:
            continue
        if not (mine_in or mine_out) or (status and a["status"] != status):
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append(authorization_view(a))
        if len(out) > limit:
            break
    return 200, {"authorizations": out[:limit], "has_more": len(out) > limit}


# ---------------------------------------------------------------- http

# (method, path) -> (needs idempotency, handler(user, body))
IDEMPOTENT_ROUTES = {
    ("POST", "/payments"): do_payment,
    ("POST", "/requests"): do_request,
    ("POST", "/splits"): do_split,
    ("POST", "/settlements"): do_settlement,
    ("POST", "/authorizations"): do_authorize,
}
REQ_ACTION_RE = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")
AUTH_ACTION_RE = re.compile(r"^/authorizations/([^/]+)/(capture|void)$")
UI_PATHS = ("/", "/requests", "/split", "/signup", "/login", "/authorizations")


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {"app.html": "text/html; charset=utf-8", "app.css": "text/css; charset=utf-8",
                "app.js": "application/javascript; charset=utf-8"}
ASSETS = {}


def asset(name):
    if name not in ASSETS:
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            ASSETS[name] = f.read()
    return ASSETS[name]


def render_page(path):
    return asset("app.html").decode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"

    def log_message(self, *a):
        pass

    # -- plumbing
    def send_json(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error_body(self, e):
        self.send_json(e.status, {"error": {"code": e.code, "message": e.message}})

    def read_raw(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            data = b""
            while True:
                line = self.rfile.readline().strip()
                size = int(line.split(b";")[0] or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    return data
                data += self.rfile.read(size)
                self.rfile.readline()
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    @staticmethod
    def parse_json(raw, allow_empty=False):
        if not raw.strip():
            if allow_empty:
                return {}
            raise ApiError(400, "malformed_request", "body required")

        def refuse(c):
            raise ValueError(c)
        try:
            return json.loads(raw.decode("utf-8"), parse_constant=refuse)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ApiError(400, "malformed_request", "body is not valid JSON")

    def authenticate(self):
        h = self.headers.get("Authorization") or ""
        parts = h.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise ApiError(401, "unauthenticated", "missing or malformed bearer token")
        sweep()
        uid = STATE["tokens"].get(parts[1])
        if uid is None or uid not in STATE["users"]:
            raise ApiError(401, "unauthenticated", "unknown token")
        return STATE["users"][uid]

    # -- dispatch
    def serve(self):
        try:
            self.dispatch()
        except ApiError as e:
            self.send_error_body(e)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            try:
                self.send_json(500, {"error": {"code": "internal_error", "message": "internal error"}})
            except Exception:
                pass

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = serve

    def dispatch(self):
        method = self.command
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query, keep_blank_values=True)
        raw = self.read_raw() if method in ("POST", "PUT", "PATCH", "DELETE") else b""

        if method == "GET" and path == "/health":
            return self.send_json(200, {"status": "ok"})
        if method == "POST" and path == "/_test/reset":
            fx = self.parse_json(raw)
            install(state_from_fixture(fx))
            return self.send_json(204)
        if method == "GET" and path == "/_test/export":
            with LOCK:
                snap = json.loads(json.dumps(STATE))
            return self.send_json(200, {"track": "pocketful", "format_version": 1, "state": snap})
        if method == "POST" and path == "/_test/import":
            doc = self.parse_json(raw)
            if not isinstance(doc, dict) or doc.get("track") != "pocketful" \
                    or doc.get("format_version") != 1 or isinstance(doc.get("format_version"), bool) \
                    or "state" not in doc:
                bad("not a pocketful export")
            install(state_from_export(doc["state"]))
            return self.send_json(204)
        if method == "POST" and path == "/auth/signup":
            return self.send_json(*do_signup(self.obj(raw)))
        if method == "POST" and path == "/auth/login":
            return self.send_json(*do_login(self.obj(raw)))

        if method == "GET" and path.startswith("/static/") and path[8:] in STATIC_TYPES:
            body = asset(path[8:])
            self.send_response(200)
            self.send_header("Content-Type", STATIC_TYPES[path[8:]])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return self.wfile.write(body)
        if method == "GET" and path in UI_PATHS and (
                path == "/" or "text/html" in (self.headers.get("Accept") or "").lower()):
            return self.send_html(render_page(path))
        route = (method, path)
        handler = IDEMPOTENT_ROUTES.get(route)
        am = AUTH_ACTION_RE.match(path) if method == "POST" else None
        if am:
            aid, action = am.group(1), am.group(2)
            if action == "capture":
                handler = lambda user, body, _aid=aid: do_capture(user, body, _aid)
            else:
                with LOCK:
                    user = self.authenticate()
                    result = do_void(user, aid)
                return self.send_json(*result)
        m = REQ_ACTION_RE.match(path) if method == "POST" else None
        if m:
            rid, action = m.group(1), m.group(2)
            if action == "pay":
                handler = lambda user, body, _rid=rid: do_pay(user, body, _rid)
            else:
                with LOCK:
                    user = self.authenticate()
                    result = do_decline_cancel(user, rid, action)
                return self.send_json(*result)
        known = handler is not None or route in (
            ("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
            ("GET", "/authorizations"))
        if not known:
            raise ApiError(404, "not_found", "no such route")

        if handler is not None:
            with LOCK:
                user = self.authenticate()
                if route == ("POST", "/settlements") and user["id"] not in STATE["operators"]:
                    raise ApiError(403, "forbidden", "settlement operator required")
                key = self.headers.get("Idempotency-Key")
                if key is None or key == "":
                    raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
                body = self.parse_json(raw, allow_empty=path.endswith(("/pay", "/capture")))
                if not isinstance(body, dict):
                    raise ApiError(400, "malformed_request", "body must be a JSON object")
                if len(key) > 255:
                    raise ApiError(422, "validation_failed", "Idempotency-Key too long")
                status, resp = idempotent(user, method, path, key, body,
                                          lambda: handler(user, body))
            return self.send_json(status, resp)

        with LOCK:
            user = self.authenticate()
            if route == ("GET", "/me"):
                result = do_me(user)
            elif route == ("GET", "/requests"):
                result = do_requests(user, query)
            elif route == ("GET", "/authorizations"):
                result = do_authorizations(user, query)
            else:
                result = do_activity(user, query)
        return self.send_json(*result)

    def obj(self, raw):
        """Parse a JSON object body or raise 400."""
        v = self.parse_json(raw)
        if not isinstance(v, dict):
            raise ApiError(400, "malformed_request", "body must be a JSON object")
        return v


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def main():
    install(empty_state())
    port = int(os.environ.get("PORT") or 8080)
    srv = Server(("0.0.0.0", port), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
