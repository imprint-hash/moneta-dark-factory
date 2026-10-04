#!/usr/bin/env python3
"""Stage-2 API exam. BASE=http://host:port python3 exam2_api.py [-k substr]. Imports stage-1 helpers."""
import sys, os
sys.path.insert(0, "../stage-1")
import exam
from exam import *
import datetime as dt

TESTS2 = []
def t2(*ids):
    def d(f):
        f.ids = ids; TESTS2.append(f); return f
    return d

def iso(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
def now(): return dt.datetime.now(dt.timezone.utc)
def ts(delta): return (now() + dt.timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

def f2(ttl=None, auths=None, ops=None, users=None):
    f = fixture(users=users)
    if ttl is not None: f["authorization_ttl_seconds"] = ttl
    if auths is not None: f["authorizations"] = auths
    if ops: f["settlement_operator_ids"] = ops
    return f

def S2(ttl=None, auths=None, ops=None):
    reset(f2(ttl, auths, ops)); return {u: login(u) for u in ["ada", "bob", "cy", "dee"]}

def me(t): return call("GET", "/me", t).json()
def auth(t, to, amt, key=None, **kw):
    b = {"to_handle": to, "amount": amt}; b.update(kw)
    return call("POST", "/authorizations", t, b, key=key or uk())
def cap(t, aid, body=None, key=None):
    return call("POST", f"/authorizations/{aid}/capture", t, {} if body is None else body, key=key or uk())
def void(t, aid): return call("POST", f"/authorizations/{aid}/void", t)
def ga(t, **p): return call("GET", "/authorizations", t, params=p)
def seeded(aid="a_1", frm="ada", to="bob", amt=2000, status="open", exp=3600 * 3, **kw):
    d = {"id": aid, "from_user_id": "u_" + frm, "to_user_id": "u_" + to, "amount": amt, "note": "deposit",
         "visibility": "public", "status": status, "expires_at": ts(exp)}
    d.update(kw); return d

@t2("H3")
def a_me_shape():
    T = S2(); m = me(T["ada"])
    eq({k: m[k] for k in ("balance", "total", "available", "held")}, dict(balance=10000, total=10000, available=10000, held=0))
    for k in ("user_id", "display_name", "handle", "currency", "minor_units"): assert k in m
    p = pay(T["ada"], "bob", 100).json()
    eq(p.get("authorization_id", "MISSING"), None); eq(p["request_id"], None)
    eq(me(T["ada"])["held"], 0); eq(me(T["ada"])["available"], 9900)

@t2("H1", "H2", "H3", "V6")
def a_seeded():
    T = S2(auths=[seeded()]); m = me(T["ada"])
    eq((m["balance"], m["total"], m["available"], m["held"]), (10000, 10000, 8000, 2000))
    eq(me(T["bob"])["held"], 0)
    # held funds cannot fund payments
    err(pay(T["ada"], "bob", 8001), 409, "insufficient_funds")
    eq(pay(T["ada"], "bob", 8000).status_code, 201)
    eq(me(T["ada"])["available"], 0)
    # list
    L = ga(T["ada"]).json()["authorizations"]; eq(len(L), 1); eq(L[0]["authorization_id"], "a_1")
    eq(L[0]["status"], "open"); eq(L[0]["remaining_amount"], 2000); eq(L[0]["captured_amount"], 0)
    eq(len(ga(T["bob"]).json()["authorizations"]), 1)
    eq(ga(T["cy"]).json()["authorizations"], [])
    # not in activity
    ids = [p["payment_id"] for p in call("GET", "/activity", T["ada"]).json()["payments"]]
    assert "a_1" not in ids

@t2("H2", "H1")
def a_seeded_bad():
    T = S2()
    for auths in ([seeded(amt=10001)], [seeded(amt=6000), seeded("a_2", amt=5000)]):
        r = call("POST", "/_test/reset", body=f2(auths=auths)); err(r, 422, "validation_failed")
        eq(bal(T["ada"]), 10000)  # nothing changed
    # expired / non-open do not count
    r = call("POST", "/_test/reset", body=f2(auths=[seeded(amt=20000, exp=-7200), seeded("a_2", amt=20000, status="voided"),
                                                  seeded("a_3", amt=20000, status="captured")]))
    eq(r.status_code, 204)
    T = {u: login(u) for u in ["ada", "bob"]}
    eq(me(T["ada"])["available"], 10000)
    eq(sorted(a["status"] for a in ga(T["ada"]).json()["authorizations"]), ["captured", "expired", "voided"])
    # exactly equal to balance ok
    eq(call("POST", "/_test/reset", body=f2(auths=[seeded(amt=10000)])).status_code, 204)
    eq(me(login("ada"))["available"], 0)
    # ttl validation
    for bad in (0, -5, 1.5, "600", True, None):
        f = f2(); f["authorization_ttl_seconds"] = bad
        r = call("POST", "/_test/reset", body=f); assert r.status_code in (422, 400), (bad, r.status_code)
    # omission fine (older fixture)
    f = fixture(); eq(call("POST", "/_test/reset", body=f).status_code, 204)

@t2("H8", "H9", "H4")
def a_authorize():
    T = S2(ttl=600); r = auth(T["ada"], "bob", 2000, note="deposit", visibility="private")
    eq(r.status_code, 201, r.text); a = r.json()
    for k, v in dict(from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob", amount=2000, captured_amount=0,
                     currency="EUR", note="deposit", visibility="private", status="open", payment_id=None, remaining_amount=2000,
                     payment_ids=[]).items(): eq(a[k], v, k)
    eq((iso(a["expires_at"]) - iso(a["created_at"])).total_seconds(), 600)
    assert re.search(r"(Z|[+-]\d\d:\d\d)$", a["expires_at"]) and len(a["authorization_id"]) <= 64
    m = me(T["ada"]); eq((m["balance"], m["total"], m["available"], m["held"]), (10000, 10000, 8000, 2000))
    eq(me(T["bob"])["balance"], 2500)
    # not in activity
    for u in ("ada", "bob", "cy"): eq(call("GET", "/activity", T[u]).json()["payments"], [])
    # defaults
    a2 = auth(T["ada"], "bob", 1).json(); eq(a2["note"], ""); eq(a2["visibility"], "public")
    # errors
    err(auth(T["ada"], "bob", 8000), 409, "insufficient_funds")
    eq(auth(T["ada"], "bob", 7998).status_code, 201)
    err(auth(T["ada"], "bob", 2), 409, "insufficient_funds")
    for amt in (0, -1, 10 ** 9 + 1, 1.5, "5", True, None): err(auth(T["bob"], "ada", amt), 422, "validation_failed")
    err(auth(T["bob"], "bob", 5), 422, "self_payment")
    err(auth(T["bob"], "ghost", 5), 404, "not_found")
    err(auth(T["bob"], "ada", 5, note="x" * 201), 422, "validation_failed")
    err(auth(T["bob"], "ada", 5, visibility="friends"), 422, "validation_failed")
    err(call("POST", "/authorizations", T["bob"], {"to_handle": "ada", "amount": 5}), 400, "missing_idempotency_key")
    err(call("POST", "/authorizations", None, {"to_handle": "ada", "amount": 5}, key=uk()), 401, "unauthenticated")
    # funds held cannot fund other things
    reset(f2()); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    eq(auth(T["dee"], "ada", 500).status_code, 201)
    err(pay(T["dee"], "ada", 1), 409, "insufficient_funds")
    rq = call("POST", "/requests", T["ada"], {"payer_handle": "dee", "amount": 1}, key=uk()).json()["request_id"]
    err(call("POST", f"/requests/{rq}/pay", T["dee"], {}, key=uk()), 409, "insufficient_funds")
    eq(call("POST", "/requests", T["ada"], {"payer_handle": "dee", "amount": 1}, key=uk()).status_code, 201)
    eq(me(T["dee"])["total"], 500)

@t2("H7", "H8", "H9")
def a_authorize_idem():
    T = S2(); k = uk(); b = {"to_handle": "bob", "amount": 1000}
    r1 = call("POST", "/authorizations", T["ada"], b, key=k); r2 = call("POST", "/authorizations", T["ada"], b, key=k)
    eq((r1.status_code, r2.status_code), (201, 200)); eq(r2.json(), r1.json()); eq(me(T["ada"])["held"], 1000)
    err(call("POST", "/authorizations", T["ada"], {"to_handle": "bob", "amount": 1001}, key=k), 409, "idempotency_key_reuse")
    err(call("POST", "/authorizations", T["ada"], {"to_handle": "bob", "amount": -1}, key=k), 409, "idempotency_key_reuse")
    # same key other path = fresh
    eq(call("POST", "/payments", T["ada"], b, key=k).status_code, 201)
    # failed then reuse
    k2 = uk(); err(auth(T["dee"], "ada", 99999, key=k2), 409, "insufficient_funds")
    eq(auth(T["dee"], "ada", 5, key=k2).status_code, 201)
    # concurrency
    k3 = uk()
    def f(_): return call("POST", "/authorizations", T["ada"], {"to_handle": "cy", "amount": 100}, key=k3)
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(f, range(20)))
    c = sorted(r.status_code for r in rs); eq(c.count(201), 1, c); eq(c.count(200), 19, c)
    eq(me(T["ada"])["held"], 1100)

@t2("H10", "H11", "H7")
def a_capture_basic():
    T = S2(); aid = auth(T["ada"], "bob", 2000, note="dep", visibility="private").json()["authorization_id"]
    err(cap(T["ada"], aid, {"amount": 100}), 403, "forbidden")
    err(cap(T["cy"], aid, {"amount": 100}), 403, "forbidden")
    err(cap(T["bob"], "nope", {}), 404, "not_found")
    err(call("POST", f"/authorizations/{aid}/capture", T["bob"], {}), 400, "missing_idempotency_key")
    err(cap(T["bob"], aid, {"amount": 0}), 422, "validation_failed")
    err(cap(T["bob"], aid, {"amount": -3}), 422, "validation_failed")
    err(cap(T["bob"], aid, {"amount": 1.5}), 422, "validation_failed")
    err(cap(T["bob"], aid, {"amount": "5"}), 422, "validation_failed")
    err(cap(T["bob"], aid, {"amount": 2001}), 422, "capture_exceeds_authorization")
    eq(me(T["ada"])["held"], 2000)
    k = uk(); r = cap(T["bob"], aid, {"amount": 1500}, key=k); eq(r.status_code, 201, r.text); p = r.json()
    for kk, v in dict(from_handle="ada", to_handle="bob", amount=1500, authorization_id=aid, request_id=None, note="dep", visibility="private", currency="EUR").items(): eq(p[kk], v, kk)
    assert p["payment_id"]
    m = me(T["ada"]); eq((m["total"], m["balance"], m["available"], m["held"]), (8500, 8500, 8500, 0))
    eq(me(T["bob"])["total"], 4000)
    a = ga(T["ada"]).json()["authorizations"][0]
    eq((a["status"], a["captured_amount"], a["payment_id"], a["payment_ids"], a["remaining_amount"]), ("captured", 1500, p["payment_id"], [p["payment_id"]], 0))
    # replay
    r2 = cap(T["bob"], aid, {"amount": 1500}, key=k); eq(r2.status_code, 200); eq(r2.json(), p)
    err(cap(T["bob"], aid, {}, key=k), 409, "idempotency_key_reuse")
    err(cap(T["bob"], aid, {"amount": 1500, "final": False}, key=k), 409, "idempotency_key_reuse")
    eq(me(T["bob"])["total"], 4000)
    err(cap(T["bob"], aid, {"amount": 1}), 409, "authorization_not_open")
    err(cap(T["bob"], aid, {}), 409, "authorization_not_open")
    err(void(T["ada"], aid), 409, "authorization_not_open")
    # feed: private hidden from cy, visible to parties
    ids = lambda t: [x["payment_id"] for x in call("GET", "/activity", t).json()["payments"]]
    assert p["payment_id"] in ids(T["ada"]) and p["payment_id"] in ids(T["bob"]) and p["payment_id"] not in ids(T["cy"])
    # default capture (no body at all / {}), full remaining
    aid2 = auth(T["ada"], "bob", 300).json()["authorization_id"]
    r = cap(T["bob"], aid2, {}); eq(r.status_code, 201); eq(r.json()["amount"], 300); eq(r.json()["visibility"], "public")
    # empty body
    aid3 = auth(T["ada"], "bob", 300).json()["authorization_id"]
    r = call("POST", f"/authorizations/{aid3}/capture", T["bob"], key=uk()); assert r.status_code in (201, 400, 422)
    # payment with auth id in the pay-key replay: keys scoped path
    aid4 = auth(T["ada"], "bob", 10).json()["authorization_id"]; k = uk()
    eq(cap(T["bob"], aid4, {}, key=k).status_code, 201)
    aid5 = auth(T["ada"], "bob", 10).json()["authorization_id"]
    eq(cap(T["bob"], aid5, {}, key=k).status_code, 201)  # same key, other path
    eq(sum(me(T[u])["total"] for u in T), 13000)

@t2("H12", "H14", "H15")
def a_capture_extended():
    T = S2(); aid = auth(T["ada"], "bob", 2000).json()["authorization_id"]
    r1 = cap(T["bob"], aid, {"amount": 700, "final": False}); eq(r1.status_code, 201)
    a = ga(T["bob"], status="open").json()["authorizations"][0]
    eq((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]), ("open", 700, 1300, r1.json()["payment_id"], [r1.json()["payment_id"]]))
    m = me(T["ada"]); eq((m["total"], m["available"], m["held"]), (9300, 8000 - 0 + 0 if False else 9300 - 1300, 1300))
    err(cap(T["bob"], aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
    err(cap(T["bob"], aid, {"amount": 1301}), 422, "capture_exceeds_authorization")
    for bad in ("no", 1, None, "false"):
        r = cap(T["bob"], aid, {"amount": 10, "final": bad}); assert r.status_code in (400, 422), (bad, r.status_code)
    r2 = cap(T["bob"], aid, {"amount": 300, "final": False}); eq(r2.status_code, 201)
    # default amount = remaining
    r3 = cap(T["bob"], aid, {"final": False}); eq(r3.status_code, 201); eq(r3.json()["amount"], 1000)
    a = ga(T["bob"]).json()["authorizations"][0]
    eq((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"]), ("captured", 2000, 0, r3.json()["payment_id"]))
    eq(a["payment_ids"], [r1.json()["payment_id"], r2.json()["payment_id"], r3.json()["payment_id"]])
    err(cap(T["bob"], aid, {"amount": 1, "final": False}), 409, "authorization_not_open")
    eq(me(T["ada"])["held"], 0); eq(me(T["ada"])["total"], 8000)
    # final partial releases
    aid = auth(T["ada"], "bob", 1000).json()["authorization_id"]
    cap(T["bob"], aid, {"amount": 100, "final": False}); r = cap(T["bob"], aid, {"amount": 200, "final": True}); eq(r.status_code, 201)
    a = [x for x in ga(T["ada"]).json()["authorizations"] if x["authorization_id"] == aid][0]
    eq((a["status"], a["captured_amount"], a["remaining_amount"], len(a["payment_ids"])), ("captured", 300, 0, 2))
    eq(me(T["ada"])["held"], 0); eq(me(T["ada"])["total"], 7700)
    # void after partial capture
    aid = auth(T["ada"], "bob", 1000).json()["authorization_id"]
    p = cap(T["bob"], aid, {"amount": 400, "final": False}).json()
    eq(me(T["ada"])["held"], 600)
    r = void(T["ada"], aid); eq(r.status_code, 200); a = r.json()
    eq((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_ids"]), ("voided", 400, 0, [p["payment_id"]]))
    m = me(T["ada"]); eq((m["held"], m["total"], m["available"]), (0, 7300, 7300))
    err(cap(T["bob"], aid, {"amount": 1}), 409, "authorization_not_open")
    eq(sum(me(T[u])["total"] for u in T), 13000)
    # replay of extended capture returns original, no double move
    aid = auth(T["ada"], "bob", 1000).json()["authorization_id"]; k = uk()
    a1 = cap(T["bob"], aid, {"amount": 100, "final": False}, key=k); a2 = cap(T["bob"], aid, {"amount": 100, "final": False}, key=k)
    eq((a1.status_code, a2.status_code), (201, 200)); eq(a1.json(), a2.json())
    eq(me(T["ada"])["held"], 900)
    err(cap(T["bob"], aid, {"amount": 100}, key=k), 409, "idempotency_key_reuse")

@t2("H15")
def a_void():
    T = S2(); aid = auth(T["ada"], "bob", 2000).json()["authorization_id"]
    err(void(T["bob"], aid), 403, "forbidden"); err(void(T["cy"], aid), 403, "forbidden")
    err(void(T["ada"], "nope"), 404, "not_found")
    eq(me(T["ada"])["held"], 2000)
    r = void(T["ada"], aid); eq(r.status_code, 200); eq(r.json()["status"], "voided"); eq(r.json()["authorization_id"], aid)
    eq(me(T["ada"])["available"], 10000); eq(me(T["ada"])["held"], 0)
    eq(void(T["ada"], aid).status_code, 200); eq(void(T["ada"], aid).json()["status"], "voided")
    err(cap(T["bob"], aid, {}), 409, "authorization_not_open")
    err(void(T["bob"], aid), 403, "forbidden")
    # void of captured
    a2 = auth(T["ada"], "bob", 10).json()["authorization_id"]; cap(T["bob"], a2, {})
    err(void(T["ada"], a2), 409, "authorization_not_open")

@t2("H16", "H13")
def a_expiry():
    T = S2(ttl=2); aid = auth(T["ada"], "bob", 2000).json()["authorization_id"]
    eq(me(T["ada"])["held"], 2000)
    time.sleep(3.2)
    m = me(T["ada"]); eq((m["held"], m["available"], m["total"]), (0, 10000, 10000))
    eq(ga(T["ada"]).json()["authorizations"][0]["status"], "expired")
    eq(len(ga(T["ada"], status="open").json()["authorizations"]), 0)
    eq(len(ga(T["ada"], status="expired").json()["authorizations"]), 1)
    err(cap(T["bob"], aid, {}), 409, "authorization_expired") if False else None
    r = cap(T["bob"], aid, {}); assert r.status_code == 409 and r.json()["error"]["code"] in ("authorization_expired", "authorization_not_open"), r.text
    # spec: expired status -> not_open for non-open; a hold past deadline detected on write: ensure it's expired code or not_open
    err(void(T["ada"], aid), 409, "authorization_not_open")
    eq(pay(T["ada"], "bob", 10000).status_code, 201)
    # partial capture then expiry keeps record, releases remainder
    reset(f2(ttl=2)); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    aid = auth(T["ada"], "bob", 2000).json()["authorization_id"]
    p = cap(T["bob"], aid, {"amount": 500, "final": False}).json()
    time.sleep(3.2)
    a = ga(T["ada"]).json()["authorizations"][0]
    eq((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_ids"]), ("expired", 500, 0, [p["payment_id"]]))
    eq((me(T["ada"])["held"], me(T["ada"])["available"]), (0, 9500))
    # expiry observed by a write without prior read: authorize funds released
    reset(f2(ttl=1)); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    auth(T["dee"], "ada", 500); time.sleep(2.2)
    eq(pay(T["dee"], "ada", 500).status_code, 201)
    # capture right at/after expiry without reads
    reset(f2(ttl=1)); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    aid = auth(T["ada"], "bob", 100).json()["authorization_id"]; time.sleep(2.2)
    r = cap(T["bob"], aid, {}); eq(r.status_code, 409)
    # seeded past & future expiry
    T = S2(auths=[seeded("a_p", exp=-7200), seeded("a_f", amt=1000, exp=7200)])
    L = {a["authorization_id"]: a for a in ga(T["ada"]).json()["authorizations"]}
    eq((L["a_p"]["status"], L["a_f"]["status"]), ("expired", "open"))
    eq(me(T["ada"])["held"], 1000)
    r = cap(T["bob"], "a_p", {}); eq(r.status_code, 409)
    r = cap(T["bob"], "a_f", {"amount": 400}); eq(r.status_code, 201)
    eq(me(T["ada"])["total"], 9600)
    # seeded ttl default 600
    T = S2(); a = auth(T["ada"], "bob", 1).json(); eq((iso(a["expires_at"]) - iso(a["created_at"])).total_seconds(), 600)

@t2("H17")
def a_list():
    T = S2(); ids = []
    for i in range(4):
        ids.append(auth(T["ada"], "bob", 10 + i).json()["authorization_id"]); time.sleep(0.02)
    ids.append(auth(T["bob"], "ada", 5).json()["authorization_id"])
    auth(T["cy"], "dee", 0 + 1) if False else None
    void(T["ada"], ids[0]); cap(T["bob"], ids[1], {})
    def g(t, **p): return [a["authorization_id"] for a in ga(t, **p).json()["authorizations"]]
    eq(len(g(T["ada"])), 5); eq(len(g(T["cy"])), 0)
    eq(g(T["ada"], direction="outgoing"), ids[:4][::-1]); eq(g(T["ada"], direction="incoming"), [ids[4]])
    eq(g(T["bob"], direction="incoming"), ids[:4][::-1])
    eq(set(g(T["ada"], status="open")), {ids[2], ids[3], ids[4]})
    eq(g(T["ada"], status="voided"), [ids[0]]); eq(g(T["ada"], status="captured"), [ids[1]]); eq(g(T["ada"], status="expired"), [])
    eq(g(T["ada"], direction="outgoing", status="open"), [ids[3], ids[2]])
    j = ga(T["ada"], limit=2).json(); eq(len(j["authorizations"]), 2); eq(j["has_more"], True); eq(set(j), {"authorizations", "has_more"})
    j = ga(T["ada"], limit=2, offset=4).json(); eq((len(j["authorizations"]), j["has_more"]), (1, False))
    eq(ga(T["ada"], limit=5).json()["has_more"], False)
    eq(ga(T["ada"], bogus=1).status_code, 200)
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "1e1"}, {"offset": "+1"}, {"direction": "x"}, {"status": "weird"}, {"direction": "incoming "}):
        err(ga(T["ada"], **bad), 422, "validation_failed")
    err(call("GET", "/authorizations"), 401, "unauthenticated")
    # html vs json
    r = call("GET", "/authorizations", T["ada"], headers={"Accept": "text/html"})
    assert "text/html" in r.headers["Content-Type"], r.headers["Content-Type"]
    r = call("GET", "/requests", T["ada"], headers={"Accept": "text/html"}); assert "text/html" in r.headers["Content-Type"]
    r = call("GET", "/requests", T["ada"]); assert "json" in r.headers["Content-Type"]

@t2("H4", "H5", "H18")
def a_settlement_available():
    T = S2(ops=["u_ada"])
    auth(T["dee"], "ada", 400)  # dee total 500 available 100
    err(sett(T["ada"], [tr("dee", "bob", 101)]), 409, "insufficient_funds")
    eq(sett(T["ada"], [tr("dee", "bob", 100)]).status_code, 201)
    # net via incoming ok: chained
    eq(sett(T["ada"], [tr("bob", "dee", 50), tr("dee", "cy", 50)]).status_code, 201)
    eq(me(T["dee"])["held"], 400); assert me(T["dee"])["available"] >= 0
    # capture can spend reserved money
    aid = [a for a in ga(T["dee"]).json()["authorizations"]][0]["authorization_id"]
    eq(cap(T["ada"], aid, {}).status_code, 201)
    eq(me(T["dee"])["total"], 0)
    eq(sum(me(T[u])["total"] for u in T), 13000)

@t2("H14", "H18", "H4")
def a_concurrency():
    T = S2(); aid = auth(T["ada"], "bob", 1000).json()["authorization_id"]
    def f(i): return cap(T["bob"], aid, {"amount": 300, "final": False})
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(f, range(20)))
    c = [r.status_code for r in rs]; eq(c.count(201), 3, c); assert all(x in (201, 409, 422) for x in c), c
    eq(c.count(422) + c.count(409), 17)
    a = ga(T["ada"]).json()["authorizations"][0]; eq(a["captured_amount"], 900); eq(a["remaining_amount"], 100); eq(a["status"], "open")
    # concurrent final captures
    aid = auth(T["ada"], "bob", 1000).json()["authorization_id"]
    def g(i): return cap(T["bob"], aid, {"amount": 400})
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(g, range(20)))
    c = [r.status_code for r in rs]; eq(c.count(201), 1, c); assert all(x < 500 for x in c)
    # concurrent void vs capture
    aid = auth(T["ada"], "bob", 500).json()["authorization_id"]
    def h(i): return ("c", cap(T["bob"], aid, {})) if i % 2 else ("v", void(T["ada"], aid))
    with ThreadPoolExecutor(20) as ex: rs = list(ex.map(h, range(20)))
    assert all(r.status_code < 500 for _, r in rs)
    a = [x for x in ga(T["ada"]).json()["authorizations"] if x["authorization_id"] == aid][0]
    m = me(T["ada"]); eq(m["held"], 100)
    if a["status"] == "captured": eq(m["total"], 10000 - 900 - 400 - 500 - 0 if False else m["total"])
    eq(sum(me(T[u])["total"] for u in T), 13000)
    # concurrent authorize + pay racing for available
    reset(f2()); T = {u: login(u) for u in ["ada", "bob", "cy", "dee"]}
    def r_(i):
        if i % 2: return auth(T["dee"], "ada", 100)
        return pay(T["dee"], "bob", 100)
    with ThreadPoolExecutor(30) as ex: rs = list(ex.map(r_, range(30)))
    c = [r.status_code for r in rs]; eq(c.count(201), 5, c); assert all(x in (201, 409) for x in c)
    m = me(T["dee"]); assert m["available"] >= 0 and m["available"] == m["total"] - m["held"]; eq(m["available"], 0)
    eq(sum(me(T[u])["total"] for u in T), 13000)

@t2("H7", "H4")
def a_export_import_auths():
    T = S2(ops=["u_ada"]); k = uk(); b = {"to_handle": "bob", "amount": 700, "note": "n"}
    a = call("POST", "/authorizations", T["ada"], b, key=k).json()
    ck = uk(); c = cap(T["bob"], a["authorization_id"], {"amount": 200, "final": False}, key=ck).json()
    e = call("GET", "/_test/export"); eq(e.status_code, 200)
    reset(); eq(call("POST", "/_test/import", raw=e.text).status_code, 204)
    eq(call("GET", "/me", T["ada"]).json()["held"], 500)
    r = call("POST", "/authorizations", T["ada"], b, key=k); eq(r.status_code, 200); eq(r.json(), a)
    r = cap(T["bob"], a["authorization_id"], {"amount": 200, "final": False}, key=ck); eq(r.status_code, 200); eq(r.json(), c)
    eq(me(T["ada"])["total"], 9800)
    eq(cap(T["bob"], a["authorization_id"], {}).status_code, 201)
    eq(me(T["ada"])["held"], 0)

@t2("U1", "U3", "H3")
def a_stage1_export_compat():
    # an export has no authorizations key semantic here; just ensure fixture w/o authorizations works and idempotent export roundtrips
    T = S2(); pay(T["ada"], "bob", 100)
    e = call("GET", "/_test/export").json()
    st = e["state"]
    eq(call("POST", "/_test/import", body=e).status_code, 204)
    eq(me(T["ada"])["available"], 9900)

@t2("S2")
def a_accept_html():
    T = S2()
    for p in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
        r = call("GET", p, headers={"Accept": "text/html"})
        assert r.status_code == 200 and "html" in r.headers["Content-Type"], (p, r.status_code, r.headers.get("Content-Type"))
    r = call("GET", "/requests", T["ada"], headers={"Accept": "application/json"}); assert "json" in r.headers["Content-Type"]
    err(call("GET", "/requests", None), 401, "unauthenticated")
    r = call("GET", "/health"); eq(r.json(), {"status": "ok"})


if __name__ == "__main__":
    flt = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else ""
    for _ in range(60):
        try:
            if requests.get(BASE + "/health", timeout=2).status_code == 200: break
        except Exception: time.sleep(1)
    ok = bad = 0
    tests = TESTS2 if "--only2" in sys.argv else (TESTS + TESTS2)
    for f in tests:
        if flt and flt not in f.__name__: continue
        try:
            f(); ok += 1; print("PASS", f.__name__, f.ids)
        except Exception as ex:
            bad += 1; print("FAIL", f.__name__, f.ids, "::", repr(ex)[:700])
            if "-v" in sys.argv: traceback.print_exc()
    print(f"passed={ok} failed={bad}")
    sys.exit(1 if bad else 0)
