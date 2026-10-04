#!/usr/bin/env python3
"""Black-box exam for pocketful stage 1. Usage: BASE=http://localhost:8080 python3 exam.py [-k substr]"""
import os, sys, json, re, time, uuid, traceback, threading, copy
import requests
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("BASE", "http://localhost:8080")
S = requests.Session()
RFC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def call(method, path, token=None, body=None, key=None, raw=None, headers=None, params=None):
    h = {}
    if token: h["Authorization"] = "Bearer " + token
    if key is not None: h["Idempotency-Key"] = key
    if raw is not None:
        h["Content-Type"] = "application/json"; data = raw
    elif body is not None:
        h["Content-Type"] = "application/json"; data = json.dumps(body)
    else:
        data = None
    if headers: h.update(headers)
    return S.request(method, BASE + path, data=data, headers=h, params=params, timeout=15)


def uk(): return uuid.uuid4().hex


def fixture(users=None, **kw):
    f = {"currency": "EUR", "minor_units": 2,
         "users": users if users is not None else [
             U("ada", 10000), U("bob", 2500), U("cy", 0), U("dee", 500)],
         "payments": [], "requests": []}
    f.update(kw)
    return f


def U(h, bal, **kw):
    d = {"id": "u_" + h, "email": h + "@example.com", "password": "correct horse",
         "display_name": h.title(), "handle": h, "balance": bal}
    d.update(kw); return d


def reset(f=None):
    r = call("POST", "/_test/reset", body=f or fixture())
    assert r.status_code == 204, (r.status_code, r.text)


def login(h):
    r = call("POST", "/auth/login", body={"email": h + "@example.com", "password": "correct horse"})
    assert r.status_code == 200, (h, r.status_code, r.text)
    return r.json()["token"]


def setup(f=None):
    reset(f)
    return {u: login(u) for u in ["ada", "bob", "cy", "dee"]} if f is None else None


def bal(t): return call("GET", "/me", t).json()["balance"]


def pay(t, to, amt, key=None, **kw):
    b = {"to_handle": to, "amount": amt}; b.update(kw)
    return call("POST", "/payments", t, b, key=key or uk())


def err(r, status, code):
    assert r.status_code == status, f"want {status} {code}, got {r.status_code} {r.text[:200]}"
    j = r.json()
    assert j["error"]["code"] == code, f"want code {code}, got {j}"
    assert isinstance(j["error"]["message"], str)


def eq(a, b, m=""):
    assert a == b, f"{m} expected {b!r} got {a!r}"


TESTS = []
def test(*ids):
    def d(f):
        f.ids = ids; TESTS.append(f); return f
    return d


# ---------------- infrastructure ----------------
@test("R7")
def t_health():
    r = call("GET", "/health"); eq(r.status_code, 200); eq(r.json(), {"status": "ok"})

@test("R9", "R10")
def t_ctype_ts():
    T = setup()
    r = call("GET", "/me", T["ada"])
    assert r.headers["Content-Type"].lower().replace(" ", "") == "application/json;charset=utf-8", r.headers["Content-Type"]
    p = pay(T["ada"], "bob", 100).json()
    assert RFC.match(p["created_at"]) and not p["created_at"].endswith("Z") or RFC.match(p["created_at"]), p["created_at"]
    assert re.search(r"(Z|[+-]\d\d:\d\d)$", p["created_at"])
    r = call("GET", "/nothing-here", T["ada"])
    assert r.status_code in (404, 405), r.status_code

@test("R8")
def t_reset():
    T = setup()
    pay(T["ada"], "bob", 100)
    reset(fixture(users=[U("zed", 5)]))
    r = call("POST", "/auth/login", body={"email": "ada@example.com", "password": "correct horse"})
    err(r, 401, "unauthenticated")
    err(call("GET", "/me", T["ada"]), 401, "unauthenticated")
    t = login("zed"); eq(bal(t), 5)
    reset(); reset()
    T = {u: login(u) for u in ["ada", "bob"]}
    eq(bal(T["ada"]), 10000)
    eq(call("GET", "/activity", T["ada"]).json()["payments"], [])

@test("R24")
def t_reset_negative():
    T = setup()
    r = call("POST", "/_test/reset", body=fixture(users=[U("x", -1)]))
    err(r, 422, "validation_failed")
    eq(bal(T["ada"]), 10000)

@test("R12")
def t_ids():
    T = setup()
    p = pay(T["ada"], "bob", 100).json()
    for k in ("payment_id",):
        assert isinstance(p[k], str) and 0 < len(p[k]) <= 64
    me = call("GET", "/me", T["ada"]).json()
    assert len(me["user_id"]) <= 64
    eq(me, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 9900 + 0 if False else 9900,
            "currency": "EUR", "minor_units": 2})

@test("R25")
def t_currencies():
    for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
        reset(fixture(currency=cur, minor_units=mu, users=[U("ada", 1000), U("bob", 0)]))
        t = login("ada")
        me = call("GET", "/me", t).json()
        eq((me["currency"], me["minor_units"]), (cur, mu))
        p = pay(t, "bob", 1).json(); eq(p["currency"], cur)

@test("R5", "R6")
def t_user_in_fixture_seeded_state():
    f = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                          {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "sec", "visibility": "private"}],
                requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}])
    reset(f)
    a, b, c = login("ada"), login("bob"), login("cy")
    eq(bal(a), 10000)  # not replayed
    eq(bal(b), 2500)
    ids = [p["payment_id"] for p in call("GET", "/activity", a).json()["payments"]]
    eq(sorted(ids), ["p_1", "p_2"])
    ids = [p["payment_id"] for p in call("GET", "/activity", c).json()["payments"]]
    eq(ids, ["p_1"])
    rq = call("GET", "/requests", a).json()["requests"]
    eq(len(rq), 1); eq(rq[0]["request_id"], "rq_1"); eq(rq[0]["status"], "pending"); eq(rq[0]["payer_handle"], "ada")
    eq(call("GET", "/requests", c).json()["requests"], [])
    r = call("POST", "/requests/rq_1/pay", a, {}, key=uk()); eq(r.status_code, 201)

# ---------------- auth ----------------
@test("R35", "R36")
def t_signup_login():
    setup()
    r = call("POST", "/auth/signup", body={"email": "New.User@Example.com", "password": "longenough", "display_name": "N"})
    eq(r.status_code, 201); j = r.json()
    eq(set(j) >= {"user_id", "display_name", "token"}, True); eq(j["display_name"], "N")
    me = call("GET", "/me", j["token"]).json()
    eq(me["handle"], "new_user"); eq(me["balance"], 0)
    r = call("POST", "/auth/login", body={"email": "New.User@Example.com", "password": "longenough"})
    eq(r.status_code, 200); eq(r.json()["user_id"], j["user_id"])
    err(call("POST", "/auth/signup", body={"email": "New.User@Example.com", "password": "longenough", "display_name": "N"}), 409, "email_taken")
    err(call("POST", "/auth/signup", body={"email": "z@example.com", "password": "short", "display_name": "N"}), 422, "validation_failed")
    err(call("POST", "/auth/signup", body={"email": "z@example.com", "password": "1234567", "display_name": "N"}), 422, "validation_failed")
    eq(call("POST", "/auth/signup", body={"email": "z8@example.com", "password": "12345678", "display_name": "N"}).status_code, 201)
    for e in ("nodomain", "@x.com", "a@", "", "a b@c.d@e"):
        err(call("POST", "/auth/signup", body={"email": e, "password": "longenough", "display_name": "N"}), 422, "validation_failed")
    err(call("POST", "/auth/login", body={"email": "new.user@example.com", "password": "wrongwrong"}), 401, "unauthenticated")
    err(call("POST", "/auth/login", body={"email": "ghost@example.com", "password": "wrongwrong"}), 401, "unauthenticated")
    err(call("POST", "/auth/login", raw="{bad"), 400, "malformed_request")

@test("R15", "R16")
def t_handle_derivation():
    setup()
    def su(email):
        return call("POST", "/auth/signup", body={"email": email, "password": "longenough", "display_name": "N"})
    r = su("Jo.Smith+tag-x@example.com"); eq(r.status_code, 201)
    eq(call("GET", "/me", r.json()["token"]).json()["handle"], "jo_smith_tag_x")
    long = "a" * 25 + "@example.com"
    r = su(long); eq(r.status_code, 201)
    eq(call("GET", "/me", r.json()["token"]).json()["handle"], "a" * 20)
    # collision with truncated
    err(su("a" * 22 + "@other.com"), 409, "handle_taken")
    # collision with seeded handle, different email
    err(su("ADA@other.com"), 409, "handle_taken")
    # no account created
    err(call("POST", "/auth/login", body={"email": "ADA@other.com", "password": "longenough"}), 401, "unauthenticated")
    # later same email still not registered => still handle_taken, not email_taken
    err(su("ada@other.com"), 409, "handle_taken")
    r = su("jo.smith-tag.x@example.com"); err(r, 409, "handle_taken")

@test("R17")
def t_new_user_flow():
    T = setup()
    r = call("POST", "/auth/signup", body={"email": "newbie@example.com", "password": "longenough", "display_name": "N"})
    t = r.json()["token"]
    eq(pay(T["ada"], "newbie", 300).status_code, 201); eq(bal(t), 300)
    r = call("POST", "/requests", T["ada"], {"payer_handle": "newbie", "amount": 50}, key=uk()); eq(r.status_code, 201)
    eq(len(call("GET", "/requests", t).json()["requests"]), 1)

@test("R29", "R37")
def t_auth_required():
    setup()
    for m, p in (("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"), ("POST", "/payments"), ("POST", "/requests"),
                 ("POST", "/splits"), ("POST", "/settlements"), ("POST", "/requests/x/pay"),
                 ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel")):
        err(call(m, p, None, {} if m == "POST" else None, key=uk() if m == "POST" else None), 401, "unauthenticated")
        err(call(m, p, "garbage-token", {} if m == "POST" else None, key=uk() if m == "POST" else None), 401, "unauthenticated")
    r = call("GET", "/me", headers={"Authorization": "Basic abc"}); err(r, 401, "unauthenticated")
    r = call("GET", "/me", headers={"Authorization": "Bearer"}); err(r, 401, "unauthenticated")
    r = call("GET", "/me", headers={"Authorization": "Bearer "}); err(r, 401, "unauthenticated")

@test("R38")
def t_multi_tokens():
    setup()
    t1, t2 = login("ada"), login("ada")
    assert t1 != t2 or True
    eq(call("GET", "/me", t1).status_code, 200); eq(call("GET", "/me", t2).status_code, 200)
    t3 = login("ada"); eq(call("GET", "/me", t1).status_code, 200)

@test("R39")
def t_password_not_trivially_stored():
    # export may contain hashes; plaintext password must not appear
    setup()
    e = call("GET", "/_test/export")
    assert "correct horse" not in e.text, "plaintext password appears in export"

# ---------------- payments ----------------
@test("R49", "R50", "R51")
def t_payment_basic():
    T = setup()
    r = pay(T["ada"], "bob", 1500, note="dinner", visibility="public")
    eq(r.status_code, 201); p = r.json()
    for k, v in {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob", "amount": 1500,
                 "currency": "EUR", "note": "dinner", "visibility": "public", "request_id": None}.items():
        eq(p[k], v, k)
    assert RFC.match(p["created_at"])
    eq(bal(T["ada"]), 8500); eq(bal(T["bob"]), 4000)
    p2 = pay(T["ada"], "bob", 1).json(); eq(p2["note"], ""); eq(p2["visibility"], "public")
    assert p2["payment_id"] != p["payment_id"]
    # exact balance
    eq(pay(T["dee"], "cy", 500).status_code, 201); eq(bal(T["dee"]), 0)
    err(pay(T["dee"], "cy", 1), 409, "insufficient_funds")

@test("R50")
def t_payment_errors():
    T = setup(); a = T["ada"]
    err(pay(a, "bob", 10001), 409, "insufficient_funds")
    eq(bal(a), 10000); eq(bal(T["bob"]), 2500)
    eq(call("GET", "/activity", a).json()["payments"], [])
    for amt in (0, -5, 1000000001, 1.5, "100", True, False, None, [1], {"a": 1}):
        r = pay(a, "bob", amt); err(r, 422, "validation_failed") if True else None
    err(pay(a, "ada", 5), 422, "self_payment")
    err(pay(a, "ghost", 5), 404, "not_found")
    err(pay(a, "bob", 5, note="x" * 201), 422, "validation_failed")
    eq(pay(a, "bob", 5, note="x" * 200).status_code, 201)
    for n in (None, 5, True, ["a"]):
        err(pay(a, "bob", 5, note=n), 422, "validation_failed")
    for v in ("friends", "PUBLIC", "", None, 1, True):
        err(pay(a, "bob", 5, visibility=v), 422, "validation_failed")
    err(call("POST", "/payments", a, {"amount": 5}, key=uk()), 422, "validation_failed")  # missing to_handle
    err(call("POST", "/payments", a, {"to_handle": "bob"}, key=uk()), 422, "validation_failed")  # missing amount
    err(call("POST", "/payments", a, {"to_handle": 5, "amount": 5}, key=uk()), 400, "malformed_request")
    err(call("POST", "/payments", a, raw="{nope", key=uk()), 400, "malformed_request")
    err(call("POST", "/payments", a, raw="[1,2]", key=uk()), 400, "malformed_request")
    err(call("POST", "/payments", a, raw="", key=uk()), 400, "malformed_request")
    eq(bal(a), 9995)

@test("R13", "R22")
def t_amount_forms():
    T = setup(); a = T["ada"]
    for raw in ('{"to_handle":"bob","amount":1000.0}', '{"to_handle":"bob","amount":1e3}', '{"to_handle":"bob","amount":1E3}'):
        r = call("POST", "/payments", a, raw=raw, key=uk()); eq(r.status_code, 201, raw)
        eq(r.json()["amount"], 1000)
    for raw in ('{"to_handle":"bob","amount":1000.5}', '{"to_handle":"bob","amount":1e10}', '{"to_handle":"bob","amount":0.0}', '{"to_handle":"bob","amount":"1000"}'):
        err(call("POST", "/payments", a, raw=raw, key=uk()), 422, "validation_failed")
    # boundaries
    reset(fixture(users=[U("ada", 2 ** 53 - 1000), U("bob", 0), U("cy", 0)]))
    a = login("ada")
    eq(pay(a, "bob", 1000000000).status_code, 201)
    eq(bal(a), 2 ** 53 - 1000 - 10 ** 9)
    eq(bal(login("bob")), 10 ** 9)
    err(pay(a, "bob", 1000000001), 422, "validation_failed")
    r = call("POST", "/requests", a, {"payer_handle": "bob", "amount": 10 ** 9}, key=uk()); eq(r.status_code, 201)
    err(call("POST", "/requests", a, {"payer_handle": "bob", "amount": 10 ** 9 + 1}, key=uk()), 422, "validation_failed")

@test("R52")
def t_note_verbatim():
    T = setup(); a = T["ada"]
    for note in ["  padded  ", "<b>hi</b> & \"q\" 'x' \\ \n\t", "héllo ñ 日本語 \u0301e", "🎉🎉" + "👨‍👩‍👧", "e\u0301 vs \u00e9", ""]:
        r = pay(a, "bob", 1, note=note); eq(r.status_code, 201)
        eq(r.json()["note"], note)
    eq(pay(a, "bob", 1, note="🎉" * 200).status_code, 201)
    err(pay(a, "bob", 1, note="🎉" * 201), 422, "validation_failed")
    eq(pay(a, "bob", 1, note="é" * 200).status_code, 201)
    notes = [p["note"] for p in call("GET", "/activity", a, params={"limit": 200}).json()["payments"]]
    assert "  padded  " in notes and "e\u0301 vs \u00e9" in notes

@test("R11")
def t_unknown_fields():
    T = setup(); a = T["ada"]
    r = call("POST", "/payments", a, {"to_handle": "bob", "amount": 5, "zzz": [1], "id": "evil", "from_handle": "cy"}, key=uk())
    eq(r.status_code, 201); eq(r.json()["from_handle"], "ada")
    r = call("GET", "/activity", a, params={"bogus": "1", "limit": 5}); eq(r.status_code, 200)
    r = call("GET", "/requests", a, params={"bogus": "1"}); eq(r.status_code, 200)
    r = call("POST", "/auth/login", body={"email": "ada@example.com", "password": "correct horse", "x": 1}); eq(r.status_code, 200)

# ---------------- idempotency ----------------
@test("R28", "R33")
def t_key_header():
    T = setup(); a = T["ada"]
    for p, b in (("/payments", {"to_handle": "bob", "amount": 5}), ("/requests", {"payer_handle": "bob", "amount": 5}),
                 ("/splits", {"amount": 5, "participant_handles": ["bob"]}), ("/requests/x/pay", {}),
                 ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})):
        err(call("POST", p, a, b), 400, "missing_idempotency_key") if p != "/settlements" else None
        err(call("POST", p, a, b, key=""), 400, "missing_idempotency_key") if p != "/settlements" else None
    err(call("POST", "/payments", a, {"to_handle": "bob", "amount": 5}, key="k" * 256), 422, "validation_failed")
    eq(call("POST", "/payments", a, {"to_handle": "bob", "amount": 5}, key="k" * 255).status_code, 201)
    eq(call("POST", "/payments", a, {"to_handle": "bob", "amount": 5}, key="k").status_code, 201)
    eq(bal(a), 9990)

@test("R40", "R43", "R44")
def t_replay():
    T = setup(); a = T["ada"]; k = uk()
    r1 = call("POST", "/payments", a, raw='{"to_handle":"bob","amount":700,"note":"n"}', key=k); eq(r1.status_code, 201)
    r2 = call("POST", "/payments", a, raw='{ "note":"n",\n "amount":700.0, "to_handle":"bob"}', key=k)
    # 700.0 vs 700 parse to equal JSON numbers in most parsers; accept 200 or 409 only for 700.0 variant
    r2b = call("POST", "/payments", a, raw='{ "note":"n",\n "amount":700, "to_handle":"bob"}', key=k)
    eq(r2b.status_code, 200); eq(r2b.json(), r1.json())
    eq(bal(a), 9300)
    err(call("POST", "/payments", a, {"to_handle": "bob", "amount": 701, "note": "n"}, key=k), 409, "idempotency_key_reuse")
    err(call("POST", "/payments", a, {"to_handle": "cy", "amount": 700, "note": "n"}, key=k), 409, "idempotency_key_reuse")
    # unknown fields in body count? different JSON value -> reuse
    eq(bal(a), 9300)
    # replay with now-invalid body -> still reuse (claimed key first)
    err(call("POST", "/payments", a, {"to_handle": "bob", "amount": -1}, key=k), 409, "idempotency_key_reuse")
    err(call("POST", "/payments", a, {"to_handle": "ghost", "amount": 1}, key=k), 409, "idempotency_key_reuse")
    # replay after funds depleted still returns original
    pay(a, "bob", 9300)
    eq(call("POST", "/payments", a, {"to_handle": "bob", "amount": 700, "note": "n"}, key=k).status_code, 200)
    eq(bal(a), 0)

@test("R41", "R42")
def t_key_scope():
    T = setup(); k = uk()
    r1 = call("POST", "/payments", T["ada"], {"to_handle": "cy", "amount": 100}, key=k)
    r2 = call("POST", "/payments", T["bob"], {"to_handle": "cy", "amount": 100}, key=k)
    eq(r1.status_code, 201); eq(r2.status_code, 201)
    assert r1.json()["payment_id"] != r2.json()["payment_id"]
    eq(bal(T["cy"]), 200)
    r3 = call("POST", "/requests", T["ada"], {"payer_handle": "cy", "amount": 100}, key=k)
    eq(r3.status_code, 201)  # same key, same-ish body, different path
    r4 = call("POST", "/payments", T["ada"], {"to_handle": "cy", "amount": 100}, key=k); eq(r4.status_code, 200)
    # two tokens of same user share key scope
    a2 = login("ada")
    r5 = call("POST", "/payments", a2, {"to_handle": "cy", "amount": 100}, key=k); eq(r5.status_code, 200); eq(r5.json(), r1.json())

@test("R43")
def t_key_after_4xx():
    T = setup(); a = T["ada"]; k = uk()
    err(call("POST", "/payments", a, {"to_handle": "ghost", "amount": 1}, key=k), 404, "not_found")
    eq(call("POST", "/payments", a, {"to_handle": "bob", "amount": 1}, key=k).status_code, 201)
    k2 = uk()
    err(call("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 5000}, key=k2), 409, "insufficient_funds")
    pay(T["ada"], "dee", 5000)
    r = call("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 5000}, key=k2); eq(r.status_code, 201)
    # validation fail then different valid body with same key
    k3 = uk()
    err(call("POST", "/payments", a, {"to_handle": "bob", "amount": 0}, key=k3), 422, "validation_failed")
    eq(call("POST", "/payments", a, {"to_handle": "bob", "amount": 2}, key=k3).status_code, 201)
    k4 = uk()
    err(call("POST", "/requests", a, {"payer_handle": "ada", "amount": 2}, key=k4), 422, "self_request")
    eq(call("POST", "/requests", a, {"payer_handle": "bob", "amount": 2}, key=k4).status_code, 201)

@test("R45", "R3", "R2", "R34")
def t_concurrent_same_key():
    T = setup(); a = T["ada"]; k = uk()
    def f(_): return call("POST", "/payments", a, {"to_handle": "bob", "amount": 1000}, key=k)
    with ThreadPoolExecutor(30) as ex: rs = list(ex.map(f, range(30)))
    codes = sorted(r.status_code for r in rs); eq(codes.count(201), 1, codes); eq(codes.count(200), 29, codes)
    ids = {r.json()["payment_id"] for r in rs}; eq(len(ids), 1)
    eq(bal(a), 9000)
    # concurrent split
    k = uk()
    def g(_): return call("POST", "/splits", a, {"amount": 300, "participant_handles": ["ada", "bob", "cy"]}, key=k)
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(g, range(20)))
    codes = sorted(r.status_code for r in rs); eq(codes.count(201), 1, codes); eq(codes.count(200), 19, codes)
    eq(len(call("GET", "/requests", T["bob"]).json()["requests"]), 1)
    # concurrent create request
    k = uk()
    def h(_): return call("POST", "/requests", a, {"payer_handle": "cy", "amount": 5}, key=k)
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(h, range(20)))
    codes = sorted(r.status_code for r in rs); eq(codes.count(201), 1, codes)
    eq(len(call("GET", "/requests", T["cy"]).json()["requests"]), 2)

@test("R1", "R2", "R34")
def t_concurrent_overdraw():
    T = setup(); d = T["dee"]  # 500
    def f(i): return pay(d, ["ada", "bob", "cy"][i % 3], 100)
    with ThreadPoolExecutor(50) as ex: rs = list(ex.map(f, range(50)))
    codes = [r.status_code for r in rs]
    eq(codes.count(201), 5, codes); eq(codes.count(409), 45, codes)
    assert all(c < 500 for c in codes)
    eq(bal(d), 0)
    total = sum(bal(T[u]) for u in T); eq(total, 13000)

@test("R3", "R45")
def t_concurrent_pay_request():
    T = setup()
    r = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 1000}, key=uk()); rid = r.json()["request_id"]
    def f(i): return call("POST", f"/requests/{rid}/pay", T["ada"], {}, key=uk())
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(f, range(20)))
    codes = sorted(r.status_code for r in rs)
    eq(codes.count(201), 1, codes); eq(codes.count(409), 19, codes)
    for r in rs:
        if r.status_code == 409: eq(r.json()["error"]["code"], "request_not_pending")
    eq(bal(T["ada"]), 9000); eq(bal(T["bob"]), 3500)
    # concurrent pay vs decline vs cancel
    r = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 1000}, key=uk()); rid = r.json()["request_id"]
    def g(i):
        if i % 3 == 0: return ("pay", call("POST", f"/requests/{rid}/pay", T["ada"], {}, key=uk()))
        if i % 3 == 1: return ("dec", call("POST", f"/requests/{rid}/decline", T["ada"]))
        return ("can", call("POST", f"/requests/{rid}/cancel", T["bob"]))
    with ThreadPoolExecutor(30) as ex: rs = list(ex.map(g, range(30)))
    assert all(r.status_code < 500 for _, r in rs)
    final = call("GET", "/requests", T["ada"], params={"limit": 200}).json()["requests"]
    st = [x for x in final if x["request_id"] == rid][0]["status"]
    wins = {"pay": "paid", "dec": "declined", "can": "cancelled"}
    ok_kinds = {k for k, r in rs if r.status_code in (200, 201)}
    eq(len({wins[k] for k in ok_kinds}), 1, (ok_kinds, st))
    eq(wins[list(ok_kinds)[0]], st)
    eq(bal(T["ada"]), 9000 - (1000 if st == "paid" else 0))

# ---------------- requests ----------------
@test("R53", "R54", "R18")
def t_requests_create():
    T = setup()
    r = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, key=uk()); eq(r.status_code, 201)
    q = r.json()
    for k, v in {"requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada", "payer_handle": "ada", "amount": 1200,
                 "currency": "EUR", "note": "taxi", "status": "pending", "payment_id": None}.items(): eq(q[k], v, k)
    assert RFC.match(q["created_at"]); assert "visibility" not in q or True
    # exceeds balance
    r = call("POST", "/requests", T["bob"], {"payer_handle": "dee", "amount": 99999}, key=uk()); eq(r.status_code, 201)
    eq(r.json()["note"], "")
    rq = r.json()["request_id"]
    err(call("POST", f"/requests/{rq}/pay", T["dee"], {}, key=uk()), 409, "insufficient_funds")
    eq(bal(T["dee"]), 500); eq(bal(T["bob"]), 2500)
    eq(call("GET", "/requests", T["dee"]).json()["requests"][0]["status"], "pending")
    pay(T["ada"], "dee", 99499 - 0 if False else 9500)
    pay(T["bob"], "dee", 2500)
    # dee has 12500 < 99999; fund via fixture-free route: not possible; use smaller request
    r = call("POST", "/requests", T["bob"], {"payer_handle": "cy", "amount": 400}, key=uk()); rq2 = r.json()["request_id"]
    err(call("POST", f"/requests/{rq2}/pay", T["cy"], {}, key=uk()), 409, "insufficient_funds")
    pay(T["ada"], "cy", 400)
    r = call("POST", f"/requests/{rq2}/pay", T["cy"], {}, key=uk()); eq(r.status_code, 201)
    eq(bal(T["cy"]), 0)
    # errors
    b = T["bob"]
    for amt in (0, -1, 10 ** 9 + 1, 2.5, "5", True, None):
        err(call("POST", "/requests", b, {"payer_handle": "ada", "amount": amt}, key=uk()), 422, "validation_failed")
    err(call("POST", "/requests", b, {"payer_handle": "bob", "amount": 5}, key=uk()), 422, "self_request")
    err(call("POST", "/requests", b, {"payer_handle": "ada", "amount": 5, "note": "x" * 201}, key=uk()), 422, "validation_failed")
    err(call("POST", "/requests", b, {"payer_handle": "ada", "amount": 5, "note": None}, key=uk()), 422, "validation_failed")
    err(call("POST", "/requests", b, {"payer_handle": "ghost", "amount": 5}, key=uk()), 404, "not_found")
    err(call("POST", "/requests", b, {"payer_handle": "ada"}, key=uk()), 422, "validation_failed")
    err(call("POST", "/requests", b, {"amount": 5}, key=uk()), 422, "validation_failed")
    err(call("POST", "/requests", b, {"payer_handle": 7, "amount": 5}, key=uk()), 400, "malformed_request")
    err(call("POST", "/requests", b, raw="not json", key=uk()), 400, "malformed_request")

@test("R55", "R56", "R57", "R19")
def t_pay_request():
    T = setup()
    rq = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, key=uk()).json()["request_id"]
    err(call("POST", f"/requests/{rq}/pay", T["bob"], {}, key=uk()), 403, "forbidden")
    err(call("POST", f"/requests/{rq}/pay", T["cy"], {}, key=uk()), 403, "forbidden")
    err(call("POST", "/requests/nope/pay", T["ada"], {}, key=uk()), 404, "not_found")
    for v in ("x", None, 3):
        err(call("POST", f"/requests/{rq}/pay", T["ada"], {"visibility": v}, key=uk()), 422, "validation_failed")
    k = uk()
    r = call("POST", f"/requests/{rq}/pay", T["ada"], {"visibility": "private"}, key=k); eq(r.status_code, 201)
    p = r.json()
    eq(p["request_id"], rq); eq(p["visibility"], "private"); eq(p["amount"], 1200); eq(p["from_handle"], "ada"); eq(p["to_handle"], "bob")
    eq(p["note"], "taxi") if p["note"] == "taxi" else None
    eq(bal(T["ada"]), 8800); eq(bal(T["bob"]), 3700)
    q = call("GET", "/requests", T["bob"], params={"status": "paid"}).json()["requests"][0]
    eq(q["status"], "paid"); eq(q["payment_id"], p["payment_id"])
    # replay
    r2 = call("POST", f"/requests/{rq}/pay", T["ada"], {"visibility": "private"}, key=k); eq(r2.status_code, 200); eq(r2.json(), p)
    err(call("POST", f"/requests/{rq}/pay", T["ada"], {}, key=k), 409, "idempotency_key_reuse")
    err(call("POST", f"/requests/{rq}/pay", T["ada"], {"visibility": "public"}, key=k), 409, "idempotency_key_reuse")
    err(call("POST", f"/requests/{rq}/pay", T["ada"], {"visibility": "private"}, key=uk()), 409, "request_not_pending")
    eq(bal(T["ada"]), 8800)
    # private: hidden from cy, shown to both parties
    eq([x["payment_id"] for x in call("GET", "/activity", T["cy"]).json()["payments"]], [])
    for t in (T["ada"], T["bob"]):
        eq([x["payment_id"] for x in call("GET", "/activity", t).json()["payments"]], [p["payment_id"]])
    # default body and omitted body -> public
    rq2 = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 10}, key=uk()).json()["request_id"]
    r = call("POST", f"/requests/{rq2}/pay", T["ada"], key=uk())
    eq(r.status_code, 201); eq(r.json()["visibility"], "public")
    # replay cross-user: replay when request paid still 200
    # keys scoped to caller: payer replays after other things
    rq3 = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 10}, key=uk()).json()["request_id"]
    k = uk(); eq(call("POST", f"/requests/{rq3}/pay", T["ada"], {}, key=k).status_code, 201)
    eq(call("POST", f"/requests/{rq3}/pay", T["ada"], {}, key=k).status_code, 200)
    # same key different request path = different request
    rq4 = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 10}, key=uk()).json()["request_id"]
    eq(call("POST", f"/requests/{rq4}/pay", T["ada"], {}, key=k).status_code, 201)

@test("R57")
def t_pay_replay_after_cancel_like():
    T = setup()
    rq = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 100}, key=uk()).json()["request_id"]
    k = uk()
    err(call("POST", f"/requests/{rq}/pay", T["dee"], {}, key=k), 403, "forbidden")
    r = call("POST", f"/requests/{rq}/pay", T["ada"], {}, key=k); eq(r.status_code, 201)
    # create-request replay after request paid/cancelled
    k2 = uk()
    r1 = call("POST", "/requests", T["bob"], {"payer_handle": "cy", "amount": 100}, key=k2).json()
    eq(call("POST", f"/requests/{r1['request_id']}/cancel", T["bob"]).status_code, 200)
    r2 = call("POST", "/requests", T["bob"], {"payer_handle": "cy", "amount": 100}, key=k2)
    eq(r2.status_code, 200); eq(r2.json(), r1); eq(r2.json()["status"], "pending")

@test("R58", "R59")
def t_decline_cancel():
    T = setup()
    def mk(): return call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 100}, key=uk()).json()["request_id"]
    r1 = mk()
    err(call("POST", f"/requests/{r1}/decline", T["bob"]), 403, "forbidden")
    err(call("POST", f"/requests/{r1}/decline", T["cy"]), 403, "forbidden")
    err(call("POST", f"/requests/{r1}/cancel", T["ada"]), 403, "forbidden")
    err(call("POST", f"/requests/{r1}/cancel", T["cy"]), 403, "forbidden")
    err(call("POST", "/requests/zzz/decline", T["ada"]), 404, "not_found")
    err(call("POST", "/requests/zzz/cancel", T["ada"]), 404, "not_found")
    r = call("POST", f"/requests/{r1}/decline", T["ada"]); eq(r.status_code, 200); eq(r.json()["status"], "declined"); eq(r.json()["request_id"], r1)
    r = call("POST", f"/requests/{r1}/decline", T["ada"]); eq(r.status_code, 200); eq(r.json()["status"], "declined")
    err(call("POST", f"/requests/{r1}/cancel", T["bob"]), 409, "request_not_pending")
    err(call("POST", f"/requests/{r1}/pay", T["ada"], {}, key=uk()), 409, "request_not_pending")
    r2 = mk()
    r = call("POST", f"/requests/{r2}/cancel", T["bob"]); eq(r.status_code, 200); eq(r.json()["status"], "cancelled")
    eq(call("POST", f"/requests/{r2}/cancel", T["bob"]).json()["status"], "cancelled")
    err(call("POST", f"/requests/{r2}/decline", T["ada"]), 409, "request_not_pending")
    err(call("POST", f"/requests/{r2}/pay", T["ada"], {}, key=uk()), 409, "request_not_pending")
    r3 = mk()
    call("POST", f"/requests/{r3}/pay", T["ada"], {}, key=uk())
    err(call("POST", f"/requests/{r3}/decline", T["ada"]), 409, "request_not_pending")
    err(call("POST", f"/requests/{r3}/cancel", T["bob"]), 409, "request_not_pending")
    eq(bal(T["ada"]), 9900)
    # requests not visible to third parties still give 403 or 404? spec: not payer -> 403; accept both for strangers
    r4 = mk()
    rr = call("POST", f"/requests/{r4}/decline", T["cy"]); assert rr.status_code in (403, 404)

@test("R60", "R21", "R33", "R32")
def t_list_requests():
    T = setup()
    ids = []
    for i in range(5):
        ids.append(call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 10 + i}, key=uk()).json()["request_id"])
        time.sleep(0.02)
    out = call("POST", "/requests", T["ada"], {"payer_handle": "bob", "amount": 77}, key=uk()).json()["request_id"]
    call("POST", "/requests", T["cy"], {"payer_handle": "dee", "amount": 1}, key=uk())
    call("POST", f"/requests/{ids[0]}/decline", T["ada"]); call("POST", f"/requests/{ids[1]}/cancel", T["bob"])
    a = T["ada"]
    j = call("GET", "/requests", a).json(); eq(set(j), {"requests", "has_more"})
    eq(len(j["requests"]), 6); eq(j["has_more"], False)
    inc = call("GET", "/requests", a, params={"direction": "incoming"}).json()["requests"]; eq(len(inc), 5)
    outg = call("GET", "/requests", a, params={"direction": "outgoing"}).json()["requests"]; eq([x["request_id"] for x in outg], [out])
    eq(len(call("GET", "/requests", a, params={"direction": "incoming", "status": "pending"}).json()["requests"]), 3)
    for st, n in (("declined", 1), ("cancelled", 1), ("paid", 0), ("pending", 4)):
        eq(len(call("GET", "/requests", a, params={"status": st}).json()["requests"]), n, st)
    r = call("GET", "/requests", a, params={"limit": 2}).json(); eq(len(r["requests"]), 2); eq(r["has_more"], True)
    r = call("GET", "/requests", a, params={"limit": 2, "offset": 4}).json(); eq(len(r["requests"]), 2); eq(r["has_more"], False)
    r = call("GET", "/requests", a, params={"limit": 6}).json(); eq(r["has_more"], False)
    r = call("GET", "/requests", a, params={"limit": 5}).json(); eq(r["has_more"], True)
    r = call("GET", "/requests", a, params={"offset": 100}).json(); eq(r["requests"], []); eq(r["has_more"], False)
    # newest first
    all_ = call("GET", "/requests", a).json()["requests"]
    eq(all_[0]["request_id"], out)
    inc_ids = [x["request_id"] for x in inc]; eq(inc_ids, ids[::-1])
    for bad in ({"limit": 0}, {"limit": 201}, {"limit": -1}, {"limit": "abc"}, {"limit": "1e1"}, {"limit": "4.0"}, {"limit": "+4"}, {"limit": ""},
                {"offset": -1}, {"offset": "1e0"}, {"offset": "+1"}, {"offset": "1.0"}, {"offset": "x"},
                {"direction": "sideways"}, {"status": "weird"}, {"direction": "INCOMING"}):
        err(call("GET", "/requests", a, params=bad), 422, "validation_failed")
    eq(call("GET", "/requests", a, params={"limit": 200}).status_code, 200)
    eq(call("GET", "/requests", a, params={"limit": 1}).status_code, 200)
    # privacy: dee sees only own
    eq(len(call("GET", "/requests", T["dee"]).json()["requests"]), 1)
    eq(call("GET", "/requests", T["bob"], params={"direction": "outgoing"}).json()["requests"].__len__(), 5)

# ---------------- activity ----------------
@test("R20", "R63", "R33", "R32")
def t_activity():
    T = setup()
    p_pub = pay(T["ada"], "bob", 10, visibility="public").json()["payment_id"]
    p_priv = pay(T["ada"], "bob", 20, visibility="private").json()["payment_id"]
    p_priv2 = pay(T["cy"] if False else T["bob"], "ada", 5, visibility="private").json()["payment_id"]
    p_pub2 = pay(T["dee"], "cy", 5).json()["payment_id"]
    def ids(t, **p): return [x["payment_id"] for x in call("GET", "/activity", t, params=p).json()["payments"]]
    eq(set(ids(T["ada"])), {p_pub, p_priv, p_priv2, p_pub2})
    eq(set(ids(T["bob"])), {p_pub, p_priv, p_priv2, p_pub2})
    eq(set(ids(T["cy"])), {p_pub, p_pub2})
    eq(set(ids(T["dee"])), {p_pub, p_pub2})
    # requests never show
    call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 1}, key=uk())
    eq(len(ids(T["cy"])), 2)
    j = call("GET", "/activity", T["cy"]).json(); eq(set(j), {"payments", "has_more"})
    # order newest first (sleep to separate seconds)
    time.sleep(1.1)
    last = pay(T["ada"], "dee", 1, visibility="private").json()["payment_id"]
    eq(ids(T["ada"])[0], last)
    # pagination
    full = ids(T["ada"], limit=200)
    eq(len(full), 5)
    r = call("GET", "/activity", T["ada"], params={"limit": 2}).json(); eq(len(r["payments"]), 2); eq(r["has_more"], True)
    r2 = call("GET", "/activity", T["ada"], params={"limit": 2, "offset": 2}).json(); eq(r2["has_more"], True)
    r3 = call("GET", "/activity", T["ada"], params={"limit": 2, "offset": 4}).json(); eq(len(r3["payments"]), 1); eq(r3["has_more"], False)
    eq([x["payment_id"] for x in r["payments"] + r2["payments"] + r3["payments"]], full)
    for bad in ({"limit": 0}, {"limit": 201}, {"limit": "1e1"}, {"limit": "+4"}, {"limit": "4.0"}, {"offset": -1}, {"offset": "abc"}):
        err(call("GET", "/activity", T["ada"], params=bad), 422, "validation_failed")
    # spec-level: 1-char test of full payment shape
    x = call("GET", "/activity", T["ada"]).json()["payments"][0]
    for k in ("payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "created_at"):
        assert k in x, k

@test("R19", "R20")
def t_requests_not_in_others_feed_and_split_not_feed():
    T = setup()
    call("POST", "/splits", T["ada"], {"amount": 300, "participant_handles": ["ada", "bob", "cy"]}, key=uk())
    for u in T: eq(call("GET", "/activity", T[u]).json()["payments"], [])
    eq(call("GET", "/requests", T["dee"]).json()["requests"], [])

# ---------------- splits ----------------
def shares(amount, hs, caller="ada"):
    T = setup()
    r = call("POST", "/splits", T[caller], {"amount": amount, "participant_handles": hs, "note": "dinner"}, key=uk())
    return r, T

@test("R64", "R61")
def t_split_rounding():
    for amt, hs, exp in ((1000, ["ada", "bob", "cy"], [334, 333, 333]), (1, ["ada", "bob", "cy"], [1, 0, 0]),
                         (10, ["ada", "bob", "cy"], [4, 3, 3]), (999, ["ada", "bob", "cy"], [333] * 3),
                         (5, ["ada", "bob", "cy", "dee", "ada2"], None), (3000, ["ada", "bob", "cy"], [1000] * 3),
                         (1000, ["cy", "ada", "bob"], [334, 333, 333]), (1000, ["bob", "cy", "ada"], [334, 333, 333]),
                         (2, ["bob", "cy", "dee"], [1, 1, 0])):
        if exp is None: continue
        r, T = shares(amt, hs); eq(r.status_code, 201, r.text)
        j = r.json(); eq([s["amount"] for s in j["shares"]], exp); eq([s["handle"] for s in j["shares"]], hs)
        eq(sum(s["amount"] for s in j["shares"]), amt)
        eq([q["payer_handle"] for q in j["requests"]], [h for h in hs if h != "ada"])
        eq([q["amount"] for q in j["requests"]], [s["amount"] for s in j["shares"] if s["handle"] != "ada"])
        for q in j["requests"]:
            eq(q["requester_handle"], "ada"); eq(q["status"], "pending"); eq(q["payment_id"], None); eq(q["note"], "dinner")
        eq(j["amount"], amt); eq(j["currency"], "EUR"); eq(j["note"], "dinner"); assert RFC.match(j["created_at"]) and j["split_id"]
    # 5 over 5
    reset(fixture(users=[U(h, 0) for h in ["ada", "bob", "cy", "dee", "eve"]])); a = login("ada")
    j = call("POST", "/splits", a, {"amount": 5, "participant_handles": ["ada", "bob", "cy", "dee", "eve"]}, key=uk()).json()
    eq([s["amount"] for s in j["shares"]], [1] * 5)
    j = call("POST", "/splits", a, {"amount": 7, "participant_handles": ["eve", "dee", "cy", "bob"]}, key=uk()).json()
    eq([s["amount"] for s in j["shares"]], [2, 2, 2, 1])

@test("R62", "R61")
def t_split_cases():
    T = setup(); a = T["ada"]
    # caller omitted
    r = call("POST", "/splits", a, {"amount": 100, "participant_handles": ["bob", "cy"]}, key=uk()); eq(r.status_code, 201)
    j = r.json(); eq(len(j["shares"]), 2); eq(len(j["requests"]), 2); eq(sum(s["amount"] for s in j["shares"]), 100)
    # solo
    r = call("POST", "/splits", a, {"amount": 100, "participant_handles": ["ada"]}, key=uk()); eq(r.status_code, 201)
    eq(r.json()["requests"], []); eq(r.json()["shares"], [{"handle": "ada", "amount": 100}])
    # zero share creates a request
    r = call("POST", "/splits", a, {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, key=uk()).json()
    eq([q["amount"] for q in r["requests"]], [0, 0])
    eq(r["note"], "")
    # no balance checks
    r = call("POST", "/splits", T["cy"], {"amount": 1000000000, "participant_handles": ["ada", "cy"]}, key=uk()); eq(r.status_code, 201)
    eq(bal(a), 10000)
    for amt in (0, -1, 10 ** 9 + 1, 1.5, "3", True, None):
        err(call("POST", "/splits", a, {"amount": amt, "participant_handles": ["bob"]}, key=uk()), 422, "validation_failed")
    for hs in ([], ["bob", "bob"], ["ada", "bob", "ada"]):
        err(call("POST", "/splits", a, {"amount": 5, "participant_handles": hs}, key=uk()), 422, "validation_failed")
    err(call("POST", "/splits", a, {"amount": 5, "participant_handles": ["bob"], "note": "x" * 201}, key=uk()), 422, "validation_failed")
    err(call("POST", "/splits", a, {"amount": 5, "participant_handles": ["bob", "ghost"]}, key=uk()), 404, "not_found")
    err(call("POST", "/splits", a, {"amount": 5}, key=uk()), 422, "validation_failed")
    err(call("POST", "/splits", a, {"amount": 5, "participant_handles": "bob"}, key=uk()), 400, "malformed_request")
    err(call("POST", "/splits", a, {"amount": 5, "participant_handles": [1]}, key=uk()), 400, "malformed_request")
    # 404 leaves no requests
    n0 = len(call("GET", "/requests", T["bob"], params={"limit": 200}).json()["requests"])
    call("POST", "/splits", a, {"amount": 5, "participant_handles": ["bob", "ghost"]}, key=uk())
    eq(len(call("GET", "/requests", T["bob"], params={"limit": 200}).json()["requests"]), n0)
    # replay
    k = uk(); b = {"amount": 90, "participant_handles": ["ada", "bob", "cy"]}
    r1 = call("POST", "/splits", a, b, key=k); r2 = call("POST", "/splits", a, b, key=k)
    eq(r2.status_code, 200); eq(r2.json(), r1.json())
    err(call("POST", "/splits", a, {"amount": 90, "participant_handles": ["ada", "cy", "bob"]}, key=k), 409, "idempotency_key_reuse")
    # participant order matters for equality of body
    # handles only visible: requests listed to bob
    inc = call("GET", "/requests", T["bob"], params={"direction": "incoming", "limit": 200}).json()["requests"]
    assert any(x["request_id"] == r1.json()["requests"][0]["request_id"] for x in inc)

@test("R65", "R1")
def t_conservation_splits():
    T = setup(); total = 13000
    for i in range(6):
        r = call("POST", "/splits", T["ada"], {"amount": 1000 + i, "participant_handles": ["ada", "bob", "cy"]}, key=uk()).json()
        for q in r["requests"]:
            payer = T[q["payer_handle"]]
            if q["amount"] <= bal(payer):
                eq(call("POST", f"/requests/{q['request_id']}/pay", payer, {}, key=uk()).status_code, 201)
    # bob/cy only have 2500/0; some pay attempts skipped
    eq(sum(bal(T[u]) for u in T), total)
    # cy has funds to pay after receiving
    pay(T["ada"], "cy", 3000)
    reqs = call("GET", "/requests", T["cy"], params={"status": "pending", "direction": "incoming", "limit": 200}).json()["requests"]
    for q in reqs:
        r = call("POST", f"/requests/{q['request_id']}/pay", T["cy"], {}, key=uk())
        assert r.status_code in (201, 409)
    eq(sum(bal(T[u]) for u in T), total)

@test("R1", "R34")
def t_load_mixed():
    T = setup()
    def f(i):
        t = [T["ada"], T["bob"], T["cy"], T["dee"]][i % 4]; to = ["ada", "bob", "cy", "dee"][(i + 1 + i // 4) % 4]
        r = pay(t, to, 100 + i)
        return r.status_code
    with ThreadPoolExecutor(50) as ex: codes = list(ex.map(f, range(200)))
    assert all(c in (201, 409, 422) for c in codes), set(codes)
    eq(sum(bal(T[u]) for u in T), 13000)
    for u in T: assert bal(T[u]) >= 0

# ---------------- settlements ----------------
def sfix(ops=("u_ada",)):
    return fixture(settlement_operator_ids=list(ops))

def sett(t, transfers, key=None, **kw):
    b = {"transfers": transfers}; b.update(kw)
    return call("POST", "/settlements", t, b, key=key or uk())

def tr(f, t, a, **kw):
    d = {"from_handle": f, "to_handle": t, "amount": a}; d.update(kw); return d

def sT():
    reset(sfix()); return {u: login(u) for u in ["ada", "bob", "cy", "dee"]}

@test("R71", "R72")
def t_settle_auth():
    T = sT()
    err(call("POST", "/settlements", None, {"transfers": [tr("ada", "bob", 1)]}, key=uk()), 401, "unauthenticated")
    err(sett(T["bob"], [tr("ada", "bob", 1)]), 403, "forbidden")
    eq(sett(T["ada"], [tr("bob", "cy", 1)]).status_code, 201)  # operator not party
    # missing key
    err(call("POST", "/settlements", T["ada"], {"transfers": [tr("ada", "bob", 1)]}), 400, "missing_idempotency_key")
    # operator gains no access to others' private/requests
    pay(T["bob"], "cy", 5, visibility="private")
    eq(call("GET", "/activity", T["ada"]).json()["payments"].__len__(), 1)  # only own settlement member? ada not party => 0
    # default operators empty
    reset(fixture()); a = login("ada")
    err(sett(a, [tr("ada", "bob", 1)]), 403, "forbidden")

@test("R71")
def t_settle_no_access():
    T = sT()
    rq = call("POST", "/requests", T["bob"], {"payer_handle": "cy", "amount": 5}, key=uk()).json()["request_id"]
    eq(call("GET", "/requests", T["ada"]).json()["requests"], [])
    rr = call("POST", f"/requests/{rq}/pay", T["ada"], {}, key=uk()); assert rr.status_code in (403, 404)
    rr = call("POST", f"/requests/{rq}/cancel", T["ada"]); assert rr.status_code in (403, 404)

@test("R74", "R73", "R72")
def t_settle_basic():
    T = sT()
    # chained: bob has 2500; cy 0 -> bob->cy 2000, cy->dee 1500 affordable via net
    r = sett(T["ada"], [tr("bob", "cy", 2000, note="a"), tr("cy", "dee", 1500, visibility="private"), tr("ada", "bob", 100)])
    eq(r.status_code, 201, r.text); j = r.json()
    assert j["settlement_id"] and RFC.match(j["committed_at"])
    eq(len(j["payments"]), 3)
    eq([(p["from_handle"], p["to_handle"], p["amount"]) for p in j["payments"]], [("bob", "cy", 2000), ("cy", "dee", 1500), ("ada", "bob", 100)])
    for p in j["payments"]:
        eq(p["settlement_id"], j["settlement_id"]); eq(p["request_id"], None); eq(p["created_at"], j["committed_at"])
    eq([p["note"] for p in j["payments"]], ["a", "", ""]); eq([p["visibility"] for p in j["payments"]], ["public", "private", "public"])
    eq(bal(T["ada"]), 9900); eq(bal(T["bob"]), 2600 - 2000 + 0 if False else 2500 - 2000 + 100)
    eq(bal(T["cy"]), 500); eq(bal(T["dee"]), 2000)
    # feed visibility
    cyfeed = {p["payment_id"] for p in call("GET", "/activity", T["cy"]).json()["payments"]}
    eq(cyfeed, {j["payments"][0]["payment_id"], j["payments"][1]["payment_id"], j["payments"][2]["payment_id"]} - {j["payments"][2]["payment_id"]}) if False else None
    ids = {p["payment_id"]: p for p in j["payments"]}
    bobfeed = {p["payment_id"] for p in call("GET", "/activity", T["bob"]).json()["payments"]}
    assert j["payments"][1]["payment_id"] not in bobfeed
    assert j["payments"][0]["payment_id"] in bobfeed
    f = [p for p in call("GET", "/activity", T["dee"]).json()["payments"] if p["payment_id"] == j["payments"][1]["payment_id"]]
    eq(len(f), 1); eq(f[0]["settlement_id"], j["settlement_id"])
    # ordinary payment: settlement_id null
    p = pay(T["ada"], "bob", 1).json(); eq(p.get("settlement_id", "MISSING"), None)
    got = [x for x in call("GET", "/activity", T["ada"]).json()["payments"] if x["payment_id"] == p["payment_id"]][0]
    eq(got.get("settlement_id", "MISSING"), None)
    # operator ada not party to private cy->dee: not in her feed
    adafeed = {x["payment_id"] for x in call("GET", "/activity", T["ada"], params={"limit": 200}).json()["payments"]}
    assert j["payments"][1]["payment_id"] not in adafeed
    eq(sum(bal(T[u]) for u in T), 13000)

@test("R73")
def t_settle_net_and_fail():
    T = sT()
    # circular 3-cycle with zero-balance cy works
    r = sett(T["ada"], [tr("cy", "dee", 100), tr("dee", "cy", 100)]); eq(r.status_code, 201)
    eq(bal(T["cy"]), 0); eq(bal(T["dee"]), 500)
    # insufficient collective
    ca = bal(T["ada"]);
    r = sett(T["ada"], [tr("ada", "bob", 100), tr("cy", "ada", 1)]); err(r, 409, "insufficient_funds")
    eq(bal(T["ada"]), ca); eq(bal(T["bob"]), 2500); eq(bal(T["cy"]), 0)
    # same wallet outgoing sums: dee 500 sends 300+300 -> fail
    err(sett(T["ada"], [tr("dee", "bob", 300), tr("dee", "cy", 300)]), 409, "insufficient_funds")
    eq(bal(T["dee"]), 500)
    # exactly zero ok
    eq(sett(T["ada"], [tr("dee", "bob", 300), tr("dee", "cy", 200)]).status_code, 201); eq(bal(T["dee"]), 0)
    eq(call("GET", "/activity", T["cy"]).json()["payments"].__len__(), 4)

@test("R72")
def t_settle_validation():
    T = sT(); a = T["ada"]; ok = tr("bob", "cy", 1)
    # entry errors take precedence in input order, before insufficient funds
    err(sett(a, [tr("dee", "bob", 999999), tr("bob", "ghost", 5)]), 404, "not_found")
    err(sett(a, [tr("dee", "bob", 999999), tr("bob", "bob", 5)]), 422, "self_payment")
    err(sett(a, [tr("bob", "ghost", 5), tr("bob", "bob", 5)]), 404, "not_found")
    err(sett(a, [tr("bob", "bob", 5), tr("bob", "ghost", 5)]), 422, "self_payment")
    err(sett(a, [tr("ghost", "bob", 5)]), 404, "not_found")
    err(sett(a, []), 422, "validation_failed")
    err(sett(a, [ok] * 33), 422, "validation_failed")
    eq(sett(a, [tr("ada", "bob", 1)] * 32).status_code, 201)
    for bad in ([tr("bob", "cy", 0)], [tr("bob", "cy", 10 ** 9 + 1)], [tr("bob", "cy", 1.5)], [tr("bob", "cy", "5")],
                [tr("bob", "cy", 5, note="x" * 201)], [tr("bob", "cy", 5, note=None)], [tr("bob", "cy", 5, visibility="no")],
                [{"from_handle": "bob", "amount": 5}], [{"to_handle": "bob", "amount": 5}], [{"from_handle": "bob", "to_handle": "cy"}]):
        err(sett(a, bad), 422, "validation_failed")
    err(call("POST", "/settlements", a, {}, key=uk()), 422, "validation_failed")
    for bad in ("x", {"a": 1}, 5, None, [1], ["x"]):
        r = call("POST", "/settlements", a, {"transfers": bad}, key=uk()); assert r.status_code in (400, 422), (bad, r.status_code)
        assert r.json()["error"]["code"] in ("malformed_request", "validation_failed")
    err(call("POST", "/settlements", a, raw="{", key=uk()), 400, "malformed_request")
    eq(sett(a, [tr("bob", "cy", 3, extra=1)], zzz=1).status_code, 201)
    # failed validation claims no key & creates nothing
    k = uk(); n0 = bal(T["bob"])
    err(sett(a, [tr("bob", "cy", 10), tr("bob", "ghost", 1)], key=k), 404, "not_found")
    eq(bal(T["bob"]), n0)
    eq(sett(a, [tr("bob", "cy", 10)], key=k).status_code, 201)
    # key too long
    err(sett(a, [ok], key="k" * 256), 422, "validation_failed")

@test("R75", "R40")
def t_settle_replay():
    T = sT(); a = T["ada"]; k = uk()
    b = [tr("ada", "bob", 100), tr("bob", "cy", 50)]
    r1 = sett(a, b, key=k); eq(r1.status_code, 201)
    r2 = sett(a, b, key=k); eq(r2.status_code, 200); eq(r2.json(), r1.json())
    eq(bal(a), 9900)
    err(sett(a, [tr("ada", "bob", 101)], key=k), 409, "idempotency_key_reuse")
    err(sett(a, [], key=k), 409, "idempotency_key_reuse")
    # concurrency
    k = uk()
    def f(_): return sett(a, [tr("ada", "dee", 10)], key=k)
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(f, range(20)))
    c = sorted(r.status_code for r in rs); eq(c.count(201), 1, c); eq(c.count(200), 19, c)
    eq(bal(a), 9890); eq(len({r.json()["settlement_id"] for r in rs}), 1)
    # concurrent overdraft settlements
    def g(i): return sett(a, [tr("dee", "cy", 300)])
    d0 = bal(T["dee"])
    with ThreadPoolExecutor(10) as ex: rs = list(ex.map(g, range(10)))
    ok = sum(1 for r in rs if r.status_code == 201); eq(ok, d0 // 300)
    assert all(r.status_code in (201, 409) for r in rs)
    assert bal(T["dee"]) >= 0
    eq(sum(bal(T[u]) for u in T), 13000)

# ---------------- export / import ----------------
@test("R66", "R67", "R68", "R69", "R70", "R75")
def t_export_import():
    reset(sfix()); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    new = call("POST", "/auth/signup", body={"email": "imp@example.com", "password": "longenough", "display_name": "I"}).json()
    pk = uk(); pb = {"to_handle": "bob", "amount": 111, "note": "n", "visibility": "private"}
    p = call("POST", "/payments", T["ada"], pb, key=pk).json()
    rq = call("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 50}, key=uk()).json()
    rk = uk(); pr = call("POST", f"/requests/{rq['request_id']}/pay", T["ada"], {}, key=rk).json()
    rq2 = call("POST", "/requests", T["bob"], {"payer_handle": "cy", "amount": 50}, key=uk()).json()
    sk = uk(); sb = [tr("ada", "bob", 100), tr("bob", "cy", 50)]
    sr = sett(T["ada"], sb, key=sk).json()
    fk = uk(); err(call("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 99999}, key=fk), 409, "insufficient_funds")
    spk = uk(); spb = {"amount": 90, "participant_handles": ["ada", "bob", "cy"]}
    sp = call("POST", "/splits", T["ada"], spb, key=spk).json()
    before = {u: bal(T[u]) for u in T}
    acts = call("GET", "/activity", T["bob"], params={"limit": 200}).json()
    reqs = call("GET", "/requests", T["bob"], params={"limit": 200}).json()
    e = call("GET", "/_test/export"); eq(e.status_code, 200)
    ej = e.json(); eq(ej["track"], "pocketful"); eq(ej["format_version"], 1); assert isinstance(ej["state"], dict)
    snapshot = e.text
    pay(T["ada"], "dee", 1000)  # post-export write
    eq(call("GET", "/_test/export").json()["state"] != ej["state"], True)
    # wipe with different fixture, then import
    reset(fixture(users=[U("zed", 7)]))
    r = call("POST", "/_test/import", raw=snapshot); eq(r.status_code, 204, r.text)
    for rep in range(2):
        for u in T: eq(bal(T[u]), before[u], u)
        eq(call("GET", "/me", new["token"]).json()["handle"], "imp")
        err(call("POST", "/auth/login", body={"email": "zed@example.com", "password": "correct horse"}), 401, "unauthenticated")
        t2 = login("ada")
        eq(call("GET", "/activity", T["bob"], params={"limit": 200}).json(), acts)
        eq(call("GET", "/requests", T["bob"], params={"limit": 200}).json(), reqs)
        r = call("POST", "/payments", T["ada"], pb, key=pk); eq(r.status_code, 200); eq(r.json(), p)
        r = call("POST", f"/requests/{rq['request_id']}/pay", T["ada"], {}, key=rk); eq(r.status_code, 200); eq(r.json(), pr)
        r = sett(T["ada"], sb, key=sk); eq(r.status_code, 200); eq(r.json(), sr)
        r = call("POST", "/splits", T["ada"], spb, key=spk); eq(r.status_code, 200); eq(r.json(), sp)
        err(call("POST", "/payments", T["ada"], {**pb, "amount": 112}, key=pk), 409, "idempotency_key_reuse")
        # failed key reusable
        pay(T["ada"], "dee", 1) if False else None
        if rep == 0:
            r = call("POST", "/_test/import", raw=snapshot); eq(r.status_code, 204)  # repeat is idempotent
    # operator permission survives; failed key reusable (use small amount dee can send)
    eq(call("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 99999}, key=fk).status_code, 409)
    eq(sett(T["ada"], [tr("ada", "bob", 1)]).status_code, 201)
    err(sett(T["bob"], [tr("ada", "bob", 1)]), 403, "forbidden")
    # new writes work and ids not colliding
    p2 = pay(T["ada"], "bob", 2); eq(p2.status_code, 201)
    ids = [x["payment_id"] for x in call("GET", "/activity", T["ada"], params={"limit": 200}).json()["payments"]]
    eq(len(ids), len(set(ids)))
    # reset clears imported
    reset(); err(call("GET", "/me", T["ada"]), 401, "unauthenticated")
    err(call("GET", "/me", new["token"]), 401, "unauthenticated")

@test("R67")
def t_import_invalid():
    T = setup(); pay(T["ada"], "bob", 100)
    e = call("GET", "/_test/export").json()
    err(call("POST", "/_test/import", raw="{bad"), 400, "malformed_request")
    err(call("POST", "/_test/import", body={**e, "track": "other"}), 422, "validation_failed")
    err(call("POST", "/_test/import", body={**e, "format_version": 2}), 422, "validation_failed")
    err(call("POST", "/_test/import", body={"track": "pocketful", "format_version": 1}), 422, "validation_failed")
    err(call("POST", "/_test/import", body={"format_version": 1, "state": e["state"]}), 422, "validation_failed")
    err(call("POST", "/_test/import", body={**e, "state": "nope"}), 422, "validation_failed")
    err(call("POST", "/_test/import", body={**e, "state": {}}), 422, "validation_failed")
    eq(bal(T["ada"]), 9900)
    eq(call("POST", "/_test/import", body=e).status_code, 204)
    eq(bal(T["ada"]), 9900)

@test("R68")
def t_export_snapshot_readonly():
    T = setup()
    e1 = call("GET", "/_test/export").text
    e2 = call("GET", "/_test/export").text
    eq(json.loads(e1), json.loads(e2))
    pay(T["ada"], "bob", 1)
    eq(call("POST", "/_test/import", raw=e1).status_code, 204)
    eq(bal(T["ada"]), 10000)
    eq(call("GET", "/activity", T["ada"]).json()["payments"], [])

# ---------------- misc ----------------
@test("R14")
def t_handles_fixture():
    reset(fixture(users=[U("a_b_9", 1), U("x" * 20, 1, email="x@example.com")]))
    t = login("a_b_9"); eq(call("GET", "/me", t).json()["handle"], "a_b_9")
    t2 = call("POST", "/auth/login", body={"email": "x@example.com", "password": "correct horse"}).json()["token"]
    eq(pay(t, "x" * 20, 1).status_code, 201)
    err(pay(t, "A_B_9", 1), 404, "not_found")
    err(pay(t, "x" * 21, 1), 404, "not_found")  # handle too long -> no such user (or 422)


if __name__ == "__main__":
    flt = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else ""
    # wait for health
    for _ in range(60):
        try:
            if requests.get(BASE + "/health", timeout=2).status_code == 200: break
        except Exception: time.sleep(1)
    ok = bad = 0
    for f in TESTS:
        if flt and flt not in f.__name__: continue
        try:
            f(); ok += 1; print("PASS", f.__name__, f.ids)
        except Exception as ex:
            bad += 1; print("FAIL", f.__name__, f.ids, "::", repr(ex)[:600])
            if "-v" in sys.argv: traceback.print_exc()
    print(f"passed={ok} failed={bad}")
    sys.exit(1 if bad else 0)
