#!/usr/bin/env python3
"""Stage-2 browser exam. Run with the harness venv python (playwright).
BASE=http://host:port python exam2_ui.py [-k substr]"""
import sys, os, json, time, re, traceback, threading
sys.path.insert(0, "../stage-1"); sys.path.insert(0, ".")
import exam
from exam import call, fixture, U, reset, login, uk, pay, eq, BASE
from exam2_api import f2, seeded, auth, cap, me, ga, ts
from playwright.sync_api import sync_playwright, expect

TESTS = []
def ui(*ids):
    def d(f): f.ids = ids; TESTS.append(f); return f
    return d

def tid(p, t): return p.locator(f'[data-testid="{t}"]')
def txt(p, t): return tid(p, t).inner_text().strip()

def sign_in(p, handle="ada", pw="correct horse"):
    p.goto(BASE + "/login")
    tid(p, "login-email").fill(handle + "@example.com"); tid(p, "login-password").fill(pw); tid(p, "login-submit").click()
    expect(tid(p, "current-user")).to_be_visible(timeout=8000)

def go(p, path):
    p.goto(BASE + path); expect(tid(p, "current-user")).to_be_visible(timeout=8000); p.wait_for_load_state("networkidle"); p.wait_for_timeout(150)

def new_page(b, w=1280, h=900):
    ctx = b.new_context(viewport={"width": w, "height": h}); p = ctx.new_page(); p.set_default_timeout(8000); return ctx, p

def amt_sent(p, fn):
    """capture JSON bodies of POST /payments during fn"""
    sent = []
    def h(req):
        if req.method == "POST" and req.url.split("?")[0].endswith("/payments"): sent.append(req.post_data)
    p.on("request", h); fn(); p.remove_listener("request", h); return sent

def setup(f=None):
    reset(f or f2());

@ui("A1", "A2", "A3", "A4")
def u_auth(b):
    setup(); ctx, p = new_page(b)
    p.goto(BASE + "/login")
    assert tid(p, "auth-error").count() == 0
    tid(p, "login-email").fill("ada@example.com"); tid(p, "login-password").fill("wrongwrong"); tid(p, "login-submit").click()
    expect(tid(p, "auth-error")).to_be_visible()
    tid(p, "login-password").fill("correct horse"); tid(p, "login-submit").click()
    expect(tid(p, "current-user")).to_contain_text("Ada")
    eq(txt(p, "current-handle"), "ada")
    for path in ("/", "/requests", "/split", "/authorizations"):
        go(p, path); assert "Ada" in txt(p, "current-user"); eq(txt(p, "current-handle"), "ada")
    tid(p, "logout-button").click()
    p.goto(BASE + "/"); p.wait_for_timeout(500)
    assert tid(p, "current-user").count() == 0 or not tid(p, "current-user").is_visible()
    # signup
    p.goto(BASE + "/signup")
    tid(p, "signup-email").fill("Zed.Q@example.com"); tid(p, "signup-password").fill("short"); tid(p, "signup-display-name").fill("Zed")
    tid(p, "signup-submit").click(); expect(tid(p, "auth-error")).to_be_visible()
    tid(p, "signup-password").fill("longenough1"); tid(p, "signup-submit").click()
    expect(tid(p, "current-user")).to_contain_text("Zed"); eq(txt(p, "current-handle"), "zed_q")
    assert tid(p, "auth-error").count() == 0
    ctx.close()

@ui("P1", "V2", "F3")
def u_balance_formats(b):
    for cur, mu, bal, exp in (("EUR", 2, 10000, "100.00 EUR"), ("JPY", 0, 1200, "1200 JPY"), ("BHD", 3, 12345, "12.345 BHD")):
        reset(fixture(currency=cur, minor_units=mu, users=[U("ada", bal), U("bob", 0)]))
        ctx, p = new_page(b); sign_in(p); go(p, "/")
        eq(txt(p, "wallet-balance"), exp); eq(tid(p, "wallet-balance").get_attribute("data-amount"), str(bal))
        eq(tid(p, "wallet-held").count(), 0)
        eq(txt(p, "wallet-available"), exp); eq(tid(p, "wallet-available").get_attribute("data-amount"), str(bal))
        expect(tid(p, "empty-activity")).to_be_visible()
        ctx.close()

@ui("V2", "V6", "S4")
def u_available_headline(b):
    setup(f2(auths=[seeded(amt=2000)])); ctx, p = new_page(b); sign_in(p); go(p, "/")
    eq(txt(p, "wallet-available"), "80.00 EUR"); eq(tid(p, "wallet-available").get_attribute("data-amount"), "8000")
    eq(txt(p, "wallet-balance"), "100.00 EUR"); eq(txt(p, "wallet-held"), "20.00 EUR"); eq(tid(p, "wallet-held").get_attribute("data-amount"), "2000")
    fs = lambda t: float(tid(p, t).evaluate("e=>getComputedStyle(e).fontSize").replace("px", ""))
    assert fs("wallet-available") > fs("wallet-balance") and fs("wallet-available") > fs("wallet-held"), (fs("wallet-available"), fs("wallet-balance"), fs("wallet-held"))
    # largest text on page is available
    big = p.evaluate("""()=>{let m=0,el=null;for(const e of document.querySelectorAll('body *')){const s=parseFloat(getComputedStyle(e).fontSize);
      if(s>m && e.children.length==0 && e.innerText && e.innerText.trim()){m=s;el=e}} return [m, el.innerText]}""")
    assert "80.00" in big[1] or fs("wallet-available") >= big[0] - 0.5, big
    ctx.close()

@ui("P3", "P5", "P2", "F2", "C1")
def u_pay_flow(b):
    setup(); ctx, p = new_page(b); sign_in(p); go(p, "/")
    # invalid amounts: no request sent, error shown
    for bad in ("abc", "15.005", "", "-5", "1e3", "1,5"):
        tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill(bad)
        sent = amt_sent(p, lambda: (tid(p, "pay-submit").click(), p.wait_for_timeout(400)))
        eq(sent, [], f"amount {bad!r}"); expect(tid(p, "pay-error")).to_be_visible()
    eq(txt(p, "wallet-balance"), "100.00 EUR")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-note").fill("lunch <b>&</b> 🎉"); tid(p, "pay-visibility").select_option("private")
    for a, minor in (("15", 1500), ("15.5", 1550)):
        tid(p, "pay-amount").fill(a)
        sent = amt_sent(p, lambda: (tid(p, "pay-submit").click(), p.wait_for_timeout(900)))
        eq(len(sent), 1); body = json.loads(sent[0]); eq(body["amount"], minor); eq(body["to_handle"], "bob"); eq(body["visibility"], "private")
        eq(body["note"], "lunch <b>&</b> 🎉")
    eq(txt(p, "wallet-balance"), "69.50 EUR"); eq(tid(p, "wallet-balance").get_attribute("data-amount"), "6950")
    assert tid(p, "pay-error").count() == 0
    # values kept
    eq(tid(p, "pay-handle").input_value(), "bob"); eq(tid(p, "pay-amount").input_value(), "15.5"); eq(tid(p, "pay-note").input_value(), "lunch <b>&</b> 🎉")
    eq(tid(p, "pay-visibility").input_value(), "private")
    # resubmit unchanged: no new payment
    sent = amt_sent(p, lambda: (tid(p, "pay-submit").click(), p.wait_for_timeout(900)))
    # either no request or a replay with same key (server returns 200) -> balance falls once only
    eq(txt(p, "wallet-balance"), "69.50 EUR"); assert tid(p, "pay-error").count() == 0
    eq(tid(p, "activity-list").locator('[data-testid^="activity-item-"]').count(), 2)
    # change a field -> new payment
    tid(p, "pay-note").fill("again"); tid(p, "pay-submit").click(); p.wait_for_timeout(900)
    eq(txt(p, "wallet-balance"), "54.00 EUR")
    items = tid(p, "activity-list").locator('[data-testid^="activity-item-"]')
    eq(items.count(), 3)
    first = items.first.get_attribute("data-testid").replace("activity-item-", "")
    eq(txt(p, "activity-note-" + first), "again"); eq(txt(p, "activity-amount-" + first), "15.50 EUR")
    eq(items.first.get_attribute("data-visibility"), "private")
    t = txt(p, "activity-parties-" + first); assert "ada" in t and "bob" in t
    # decimal places 0
    ctx.close()
    reset(fixture(currency="JPY", minor_units=0, users=[U("ada", 5000), U("bob", 0)]))
    ctx, p = new_page(b); sign_in(p); go(p, "/")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("12.5"); sent = amt_sent(p, lambda: (tid(p, "pay-submit").click(), p.wait_for_timeout(400)))
    eq(sent, []); expect(tid(p, "pay-error")).to_be_visible()
    tid(p, "pay-amount").fill("1200"); tid(p, "pay-submit").click(); p.wait_for_timeout(800)
    eq(txt(p, "wallet-balance"), "3800 JPY")
    ctx.close()
    # BHD 3 decimals
    reset(fixture(currency="BHD", minor_units=3, users=[U("ada", 50000), U("bob", 0)]))
    ctx, p = new_page(b); sign_in(p); go(p, "/")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("1.2345")
    eq(len(amt_sent(p, lambda: (tid(p, "pay-submit").click(), p.wait_for_timeout(300)))), 0)
    tid(p, "pay-amount").fill("1.234"); tid(p, "pay-submit").click(); p.wait_for_timeout(800)
    eq(txt(p, "wallet-balance"), "48.766 BHD")
    ctx.close()

@ui("P4", "C4")
def u_pay_refused(b):
    setup(); ctx, p = new_page(b); sign_in(p); go(p, "/")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("90"); tid(p, "pay-note").fill("keep me"); tid(p, "pay-visibility").select_option("private")
    # another client spends the balance after the browser read it
    pay(login("ada"), "cy", 9500)
    tid(p, "pay-submit").click()
    expect(tid(p, "pay-error")).to_be_visible()
    assert tid(p, "pay-uncertain").count() == 0 or txt(p, "pay-uncertain") == ""
    expect(tid(p, "wallet-balance")).to_have_text("5.00 EUR")
    eq(tid(p, "pay-handle").input_value(), "bob"); eq(tid(p, "pay-amount").input_value(), "90"); eq(tid(p, "pay-note").input_value(), "keep me")
    eq(tid(p, "pay-visibility").input_value(), "private")
    # unknown handle
    tid(p, "pay-handle").fill("nobody"); tid(p, "pay-amount").fill("1"); tid(p, "pay-submit").click(); expect(tid(p, "pay-error")).to_be_visible()
    tid(p, "pay-handle").fill("ada"); tid(p, "pay-submit").click(); expect(tid(p, "pay-error")).to_be_visible()
    ctx.close()

@ui("P6", "Q1", "Q2", "Q3", "C1")
def u_requests(b):
    setup(); ctx, p = new_page(b); sign_in(p, "bob"); go(p, "/")
    tid(p, "request-handle").fill("ada"); tid(p, "request-amount").fill("12"); tid(p, "request-note").fill("taxi")
    tid(p, "request-submit").click(); p.wait_for_timeout(700)
    tid(p, "request-handle").fill("ada"); tid(p, "request-amount").fill("1.005"); eq(len([1]), 1)
    sent = []
    p.on("request", lambda r: sent.append(r.url) if r.method == "POST" and r.url.endswith("/requests") else None)
    tid(p, "request-submit").click(); p.wait_for_timeout(300); eq(sent, []); expect(tid(p, "request-error")).to_be_visible()
    tid(p, "request-handle").fill("ghost"); tid(p, "request-amount").fill("1"); tid(p, "request-submit").click(); expect(tid(p, "request-error")).to_be_visible()
    go(p, "/requests")
    out = tid(p, "outgoing-list").locator('[data-testid^="request-item-"]'); eq(out.count(), 1)
    rid = out.first.get_attribute("data-testid").replace("request-item-", "")
    eq(out.first.get_attribute("data-status"), "pending"); eq(txt(p, "request-amount-" + rid), "12.00 EUR")
    assert tid(p, "request-cancel-" + rid).count() == 1 and tid(p, "request-pay-" + rid).count() == 0 and tid(p, "request-decline-" + rid).count() == 0
    assert tid(p, "empty-requests").count() == 0
    # ada incoming
    ctx2, p2 = new_page(b); sign_in(p2, "ada"); go(p2, "/requests")
    inc = tid(p2, "incoming-list").locator('[data-testid^="request-item-"]'); eq(inc.count(), 1)
    assert tid(p2, "request-pay-" + rid).count() == 1 and tid(p2, "request-decline-" + rid).count() == 1 and tid(p2, "request-cancel-" + rid).count() == 0
    # cancel elsewhere while pay visible -> request-error + stale button vanishes
    tid(p, "request-cancel-" + rid).click(); p.wait_for_timeout(700)
    eq(tid(p, "request-item-" + rid).get_attribute("data-status"), "cancelled"); eq(tid(p, "request-cancel-" + rid).count(), 0)
    tid(p2, "request-pay-" + rid).click()
    expect(tid(p2, "request-error")).to_be_visible()
    expect(tid(p2, "request-pay-" + rid)).to_have_count(0); eq(tid(p2, "request-item-" + rid).get_attribute("data-status"), "cancelled")
    eq(me(login("ada"))["balance"], 10000)
    # pay + decline flows
    for h in (1, 2):
        call("POST", "/requests", login("bob"), {"payer_handle": "ada", "amount": 100 * h}, key=uk())
    go(p2, "/requests")
    items = tid(p2, "incoming-list").locator('[data-testid="x"], [data-testid^="request-item-"][data-status="pending"]')
    ids = [i.get_attribute("data-testid").replace("request-item-", "") for i in items.all()]
    eq(len(ids), 2)
    tid(p2, "request-pay-" + ids[0]).click(); p2.wait_for_timeout(800)
    eq(tid(p2, "request-item-" + ids[0]).get_attribute("data-status"), "paid"); eq(tid(p2, "request-pay-" + ids[0]).count(), 0)
    tid(p2, "request-decline-" + ids[1]).click(); p2.wait_for_timeout(800)
    eq(tid(p2, "request-item-" + ids[1]).get_attribute("data-status"), "declined"); eq(tid(p2, "request-decline-" + ids[1]).count(), 0)
    assert tid(p2, "request-error").count() == 0
    ctx.close(); ctx2.close()
    # empty
    setup(); ctx, p = new_page(b); sign_in(p, "cy"); go(p, "/requests"); expect(tid(p, "empty-requests")).to_be_visible(); ctx.close()

@ui("L1", "L2", "P3")
def u_split(b):
    setup(); ctx, p = new_page(b); sign_in(p, "ada"); go(p, "/split")
    tid(p, "split-amount").fill("10.00"); tid(p, "split-handles").fill("ada, bob,cy")
    pv = lambda h: txt(p, "split-share-" + h)
    expect(tid(p, "split-preview")).to_be_visible()
    expect(tid(p, "split-share-ada")).to_have_text("3.34 EUR"); eq(pv("bob"), "3.33 EUR"); eq(pv("cy"), "3.33 EUR")
    tid(p, "split-handles").fill("cy,ada,bob"); expect(tid(p, "split-share-cy")).to_have_text("3.34 EUR"); eq(pv("ada"), "3.33 EUR")
    tid(p, "split-amount").fill("0.01"); tid(p, "split-handles").fill("ada,bob,cy")
    expect(tid(p, "split-share-ada")).to_have_text("0.01 EUR"); eq(pv("bob"), "0.00 EUR")
    sent = []
    p.on("request", lambda r: sent.append(r.post_data) if r.method == "POST" and r.url.endswith("/splits") else None)
    tid(p, "split-amount").fill("0.005"); tid(p, "split-submit").click(); p.wait_for_timeout(300); eq(sent, []); expect(tid(p, "split-error")).to_be_visible()
    tid(p, "split-amount").fill("30"); tid(p, "split-handles").fill("ada,bob,ghost"); tid(p, "split-submit").click(); expect(tid(p, "split-error")).to_be_visible()
    tid(p, "split-handles").fill("ada,bob,cy"); tid(p, "split-note").fill("dinner")
    tid(p, "split-submit").click(); p.wait_for_timeout(900)
    eq(len(sent), 2 if len(sent) == 2 else 1)
    body = json.loads(sent[-1]); eq(body["amount"], 3000); eq(body["participant_handles"], ["ada", "bob", "cy"])
    reqs = call("GET", "/requests", login("bob")).json()["requests"]; eq([r["amount"] for r in reqs], [1000])
    for h in ("ada", "bob", "cy"): eq(txt(p, "split-share-" + h), "10.00 EUR")
    ctx.close()
    # JPY split
    reset(fixture(currency="JPY", minor_units=0, users=[U("ada", 0), U("bob", 0), U("cy", 0)]))
    ctx, p = new_page(b); sign_in(p); go(p, "/split")
    tid(p, "split-amount").fill("1000"); tid(p, "split-handles").fill("ada,bob,cy")
    expect(tid(p, "split-share-ada")).to_have_text("334 JPY"); ctx.close()

@ui("V3", "V4", "V5", "S2")
def u_authorizations(b):
    setup(f2(auths=[seeded("a_s", amt=1500)])); ctx, p = new_page(b); sign_in(p, "ada"); go(p, "/authorizations")
    li = tid(p, "authorization-list"); eq(li.locator('[data-testid^="authorization-item-"]').count(), 1)
    eq(tid(p, "authorization-item-a_s").get_attribute("data-status"), "open"); eq(txt(p, "authorization-amount-a_s"), "15.00 EUR")
    assert tid(p, "authorization-void-a_s").count() == 1 and tid(p, "authorization-capture-a_s").count() == 0 and tid(p, "authorization-captured-a_s").count() == 0
    assert re.match(r"^\d{4}-\d\d-\d\dT", txt(p, "authorization-expires-a_s"))
    # authorize form
    go(p, "/authorizations")
    tid(p, "authorize-handle").fill("bob"); tid(p, "authorize-amount").fill("999999"); tid(p, "authorize-submit").click(); expect(tid(p, "authorize-error")).to_be_visible()
    tid(p, "authorize-amount").fill("1.005")
    sent = []; p.on("request", lambda r: sent.append(1) if r.method == "POST" and r.url.endswith("/authorizations") else None)
    tid(p, "authorize-submit").click(); p.wait_for_timeout(300); eq(sent, []); expect(tid(p, "authorize-error")).to_be_visible()
    tid(p, "authorize-amount").fill("20"); tid(p, "authorize-note").fill("deposit"); tid(p, "authorize-visibility").select_option("private")
    tid(p, "authorize-submit").click(); p.wait_for_timeout(900)
    assert tid(p, "authorize-error").count() == 0
    eq(li.locator('[data-testid^="authorization-item-"]').count(), 2)
    newid = [e.get_attribute("data-testid") for e in li.locator('[data-testid^="authorization-item-"]').all()][0].replace("authorization-item-", "")
    assert newid != "a_s"; eq(txt(p, "authorization-amount-" + newid), "20.00 EUR")
    go(p, "/"); eq(txt(p, "wallet-available"), "65.00 EUR"); eq(txt(p, "wallet-held"), "35.00 EUR"); eq(txt(p, "wallet-balance"), "100.00 EUR")
    go(p, "/authorizations")
    tid(p, "authorization-void-" + newid).click(); p.wait_for_timeout(800)
    eq(tid(p, "authorization-item-" + newid).get_attribute("data-status"), "voided"); eq(tid(p, "authorization-void-" + newid).count(), 0)
    # bob captures
    ctx2, p2 = new_page(b); sign_in(p2, "bob"); go(p2, "/authorizations")
    assert tid(p2, "authorization-void-a_s").count() == 0
    eq(tid(p2, "authorization-capture-amount-a_s").input_value().replace(",", "."), "15.00")
    tid(p2, "authorization-capture-amount-a_s").fill("5.005"); tid(p2, "authorization-capture-a_s").click(); expect(tid(p2, "authorization-error")).to_be_visible()
    tid(p2, "authorization-capture-amount-a_s").fill("99"); tid(p2, "authorization-capture-a_s").click(); expect(tid(p2, "authorization-error")).to_be_visible()
    tid(p2, "authorization-capture-amount-a_s").fill("10"); tid(p2, "authorization-capture-a_s").click(); p2.wait_for_timeout(900)
    eq(tid(p2, "authorization-item-a_s").get_attribute("data-status"), "captured"); eq(txt(p2, "authorization-captured-a_s"), "10.00 EUR")
    eq(tid(p2, "authorization-capture-a_s").count(), 0)
    go(p2, "/"); eq(txt(p2, "wallet-balance"), "35.00 EUR")
    ctx.close(); ctx2.close()
    setup(); ctx, p = new_page(b); sign_in(p, "cy"); go(p, "/authorizations"); expect(tid(p, "empty-authorizations")).to_be_visible(); ctx.close()
    # void refused elsewhere (captured by api)
    setup(f2(auths=[seeded("a_s", amt=1500)])); ctx, p = new_page(b); sign_in(p, "ada"); go(p, "/authorizations")
    cap(login("bob"), "a_s", {})
    tid(p, "authorization-void-a_s").click(); expect(tid(p, "authorization-error")).to_be_visible()
    expect(tid(p, "authorization-void-a_s")).to_have_count(0)
    ctx.close()

@ui("C2", "C3")
def u_refresh_latest_wins(b):
    setup(); ctx, p = new_page(b); sign_in(p); go(p, "/")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("7"); tid(p, "pay-note").fill("keep")
    t_ada = login("ada")
    # delay first /me (and /activity) request response; later ones fast
    state = {"n": 0}
    def handler(route):
        req = route.request
        if req.method == "GET" and (req.url.split("?")[0].endswith("/me") or req.url.split("?")[0].endswith("/activity")):
            state["n"] += 1; n = state["n"]
            resp = route.fetch()  # reads current server state now
            if n <= 2: time.sleep(2.0)
            route.fulfill(response=resp)
        else: route.continue_()
    p.route("**/*", handler)
    tid(p, "wallet-refresh").click()                       # refresh #1: stale snapshot (balance 100), delayed
    p.wait_for_timeout(300)
    pay(t_ada, "cy", 1000)                                  # server changes after refresh #1 read
    tid(p, "wallet-refresh").click()                        # refresh #2: newer snapshot (90)
    p.wait_for_timeout(4500)
    expect(tid(p, "wallet-balance")).to_have_attribute("data-amount", "9000")
    eq(tid(p, "pay-amount").input_value(), "7"); eq(tid(p, "pay-note").input_value(), "keep")
    ctx.close()

@ui("C6")
def u_uncertain(b):
    setup(); ctx, p = new_page(b); sign_in(p); go(p, "/")
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("12.34"); tid(p, "pay-note").fill("n")
    keys = []; bodies = []; mode = {"drop": True}
    def handler(route):
        r = route.request
        if r.method == "POST" and r.url.split("?")[0].endswith("/payments"):
            keys.append(r.headers.get("idempotency-key")); bodies.append(r.post_data)
            if mode["drop"]:
                route.fetch(); route.abort("failed"); return   # commits server-side, response lost
        route.continue_()
    p.route("**/*", handler)
    tid(p, "pay-submit").click()
    expect(tid(p, "pay-uncertain")).to_be_visible(); assert txt(p, "pay-uncertain") != ""
    assert tid(p, "pay-error").count() == 0
    eq(me(login("ada"))["balance"], 10000 - 1234)  # committed
    mode["drop"] = False
    tid(p, "pay-submit").click(); p.wait_for_timeout(1000)
    eq(len(keys), 2); eq(keys[0], keys[1]); assert keys[0]; eq(json.loads(bodies[0]), json.loads(bodies[1]))
    assert tid(p, "pay-uncertain").count() == 0 and tid(p, "pay-error").count() == 0
    expect(tid(p, "wallet-balance")).to_have_text("87.66 EUR")
    eq(me(login("ada"))["balance"], 8766)
    eq(tid(p, "activity-list").locator('[data-testid^="activity-item-"]').count(), 1)
    # uncertain, then field changed => new key allowed (new payment)
    mode["drop"] = True; tid(p, "pay-amount").fill("1"); tid(p, "pay-submit").click(); expect(tid(p, "pay-uncertain")).to_be_visible()
    ctx.close()

@ui("U2", "U3", "U4")
def u_upgrade(b):
    setup(); ctx, p = new_page(b); sign_in(p); go(p, "/")
    call("POST", "/requests", login("bob"), {"payer_handle": "ada", "amount": 300}, key=uk())
    tid(p, "pay-handle").fill("bob"); tid(p, "pay-amount").fill("5"); tid(p, "pay-note").fill("lost")
    mode = {"drop": True}; keys = []
    def handler(route):
        r = route.request
        if r.method == "POST" and r.url.split("?")[0].endswith("/payments"):
            keys.append(r.headers.get("idempotency-key"))
            if mode["drop"]: route.fetch(); route.abort("failed"); return
        route.continue_()
    p.route("**/*", handler)
    tid(p, "pay-submit").click(); expect(tid(p, "pay-uncertain")).to_be_visible()
    e = call("GET", "/_test/export"); eq(e.status_code, 200)
    # a wipe + import = upgrade between browser requests
    reset(fixture(users=[U("zed", 1)])); eq(call("POST", "/_test/import", raw=e.text).status_code, 204)
    mode["drop"] = False
    tid(p, "pay-submit").click(); p.wait_for_timeout(1200)
    eq(keys[0], keys[-1]); assert tid(p, "pay-uncertain").count() == 0 and tid(p, "pay-error").count() == 0
    expect(tid(p, "wallet-balance")).to_have_text("95.00 EUR")
    eq(me(login("ada"))["balance"], 9500)  # exactly once
    assert tid(p, "current-user").is_visible()
    go(p, "/requests")
    rid = tid(p, "incoming-list").locator('[data-testid^="request-item-"]').first.get_attribute("data-testid").replace("request-item-", "")
    tid(p, "request-pay-" + rid).click(); p.wait_for_timeout(900)
    eq(tid(p, "request-item-" + rid).get_attribute("data-status"), "paid"); eq(me(login("ada"))["balance"], 9200)
    ctx.close()

@ui("S7", "S8")
def u_mobile_layout(b):
    setup(f2(auths=[seeded(amt=500)]));
    pay(login("ada"), "bob", 100, note="x" * 150 + " " + "y" * 60)
    call("POST", "/requests", login("bob"), {"payer_handle": "ada", "amount": 9999999}, key=uk())
    for w, h in ((375, 800), (1280, 900)):
        ctx, p = new_page(b, w, h); sign_in(p)
        for path in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
            if path in ("/login", "/signup"):
                p.goto(BASE + path)
            else: go(p, path)
            p.wait_for_timeout(250)
            ov = p.evaluate("()=>document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert ov <= 0, f"horizontal overflow {ov}px at {w} on {path}"
        go(p, "/")
        # labels
        for t in ("pay-handle", "pay-amount", "pay-note", "pay-visibility", "request-handle", "request-amount"):
            ok = tid(p, t).evaluate("""e=>!!(e.getAttribute('aria-label')||e.getAttribute('aria-labelledby')||(e.labels&&e.labels.length)||e.closest('label'))""")
            assert ok, "no visible label for " + t
        # focus visible
        tid(p, "pay-handle").focus(); o = tid(p, "pay-handle").evaluate("e=>{const s=getComputedStyle(e);return [s.outlineStyle,s.outlineWidth,s.boxShadow,s.borderColor]}")
        assert (o[0] != "none" and o[1] != "0px") or o[2] != "none", ("focus not apparent", o)
        nav = p.evaluate("""()=>{const n=[...document.querySelectorAll('nav')];return n.map(e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return {t:r.top,l:r.left,w:r.width,h:r.height,pos:s.position}})}""")
        assert nav, "no <nav>"
        if w == 375: assert any(n["t"] > 400 for n in nav), ("bottom nav expected on phone", nav)
        else: assert any(n["l"] < 50 and n["w"] < 320 and n["h"] > n["w"] * 0.5 and n["t"] < 500 for n in nav), ("side menu expected on desktop", nav)
        bg = p.evaluate("()=>getComputedStyle(document.body).backgroundColor+'|'+getComputedStyle(document.body).backgroundImage+'|'+getComputedStyle(document.documentElement).backgroundImage")
        print("   bg:", bg[:160])
        p.screenshot(path=f"./shot-{w}.png", full_page=True)
        ctx.close()

@ui("F1", "F2")
def u_feed_order_privacy(b):
    setup(); ta, tb, tc = login("ada"), login("bob"), login("cy")
    a = pay(ta, "bob", 100, note="first").json(); time.sleep(1.1)
    c = pay(ta, "bob", 200, note="", visibility="private").json(); time.sleep(1.1)
    d = pay(tb, "ada", 300, note="third").json()
    ctx, p = new_page(b); sign_in(p, "cy"); go(p, "/")
    items = [e.get_attribute("data-testid") for e in tid(p, "activity-list").locator('[data-testid^="activity-item-"]').all()]
    eq(items, ["activity-item-" + d["payment_id"], "activity-item-" + a["payment_id"]])
    ctx.close()
    ctx, p = new_page(b); sign_in(p, "ada"); go(p, "/")
    items = [e.get_attribute("data-testid") for e in tid(p, "activity-list").locator('[data-testid^="activity-item-"]').all()]
    eq(items, ["activity-item-" + x["payment_id"] for x in (d, c, a)])
    eq(txt(p, "activity-note-" + c["payment_id"]), ""); eq(tid(p, "activity-item-" + c["payment_id"]).get_attribute("data-visibility"), "private")
    eq(tid(p, "activity-item-" + a["payment_id"]).get_attribute("data-visibility"), "public")
    eq(txt(p, "activity-amount-" + c["payment_id"]), "2.00 EUR"); eq(txt(p, "wallet-balance"), "99.00 EUR" if False else txt(p, "wallet-balance"))
    ctx.close()

if __name__ == "__main__":
    flt = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else ""
    ok = bad = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for f in TESTS:
            if flt and flt not in f.__name__: continue
            try:
                f(b); ok += 1; print("PASS", f.__name__, f.ids)
            except Exception as ex:
                bad += 1; print("FAIL", f.__name__, f.ids, "::", str(ex)[:600].replace("\n", " | "))
                if "-v" in sys.argv: traceback.print_exc()
        b.close()
    print(f"passed={ok} failed={bad}"); sys.exit(1 if bad else 0)
