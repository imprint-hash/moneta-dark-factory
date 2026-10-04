/* Pocketful web app: vanilla JS, no external assets. One bundle, rendered per route. */
(function () {
  'use strict';

  // ------------------------------------------------------------------ helpers
  const $app = document.getElementById('app');
  const TOKEN_KEY = 'pocketful.token';
  const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
  let ME = null;
  let route = location.pathname.replace(/\/+$/, '') || '/';

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'tid') el.setAttribute('data-testid', v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const svg = (path) => {
    const w = document.createElement('span');
    w.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + path + '</svg>';
    return w.firstChild;
  };
  const ICON = {
    home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    req: '<path d="M4 4h16v13H8l-4 4z"/>',
    split: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M12 12h9"/>',
    hold: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/>',
    in: '<path d="M12 4v14M6 12l6 6 6-6"/>',
    out: '<path d="M12 20V6M6 12l6-6 6 6"/>',
    pub: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
  };

  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  }

  function initials(s) {
    const t = String(s || '?').replace(/[^A-Za-z0-9]+/g, ' ').trim();
    const parts = t.split(' ').filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  }
  const PALETTES = [['#6a82e6', '#34406f'], ['#8f7be0', '#3f3472'], ['#4aa3b8', '#1f4a5a'], ['#c471b0', '#5a2f55'], ['#d48b5e', '#5d3a28'], ['#5fb383', '#25513a']];
  function avatar(name, cls) {
    let n = 0;
    for (const c of String(name)) n = (n * 31 + c.charCodeAt(0)) >>> 0;
    const p = PALETTES[n % PALETTES.length];
    const a = h('div', { class: 'avatar ' + (cls || ''), 'aria-hidden': 'true', text: initials(name) });
    a.style.setProperty('--a1', p[0]);
    a.style.setProperty('--a2', p[1]);
    return a;
  }

  function money(minor) {
    const mu = ME ? ME.minor_units : 2;
    const cur = ME ? ME.currency : '';
    const neg = minor < 0;
    let s = String(Math.abs(minor));
    if (mu === 0) return (neg ? '-' : '') + s + ' ' + cur;
    s = s.padStart(mu + 1, '0');
    return (neg ? '-' : '') + s.slice(0, -mu) + '.' + s.slice(-mu) + ' ' + cur;
  }
  function decimalText(minor) {
    const mu = ME.minor_units;
    let s = String(minor);
    if (mu === 0) return s;
    s = s.padStart(mu + 1, '0');
    return s.slice(0, -mu) + '.' + s.slice(-mu);
  }
  // typed decimal -> integer minor units, or {error}
  function parseAmount(text) {
    const mu = ME.minor_units;
    const t = String(text == null ? '' : text).trim();
    if (!t) return { error: 'Enter an amount.' };
    if (!/^(\d+(\.\d+)?|\.\d+)$/.test(t)) return { error: 'Amount must be a plain number such as 15 or 15.50.' };
    const [ip, fp = ''] = t.split('.');
    if (fp.length > mu) {
      return { error: mu === 0 ? 'This currency has no decimal places.' : 'At most ' + mu + ' decimal places are allowed for ' + ME.currency + '.' };
    }
    const digits = (ip.replace(/^0+(?=\d)/, '') || '0') + fp.padEnd(mu, '0');
    if (digits.length > 15) return { error: 'That amount is too large.' };
    const n = Number(digits);
    if (!(n >= 1)) return { error: 'Amount must be greater than zero.' };
    return { minor: n };
  }
  function friendlyExpiry(a) {
    const d = new Date(a.expires_at);
    if (isNaN(d)) return '';
    const on = d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (a.status !== 'open') return (a.status === 'expired' ? 'Expired ' : 'Was due ') + on;
    const mins = Math.round((d - Date.now()) / 60000);
    if (mins < 1) return 'Expires in under a minute \u00b7 ' + on;
    if (mins < 90) return 'Expires in ' + mins + ' min \u00b7 ' + on;
    if (mins < 2880) return 'Expires in ' + Math.round(mins / 60) + ' h \u00b7 ' + on;
    return 'Expires on ' + on;
  }
  function when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const now = new Date();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return 'Today, ' + time;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ', ' + time;
  }

  // ------------------------------------------------------------------ api
  class Unknown extends Error {}
  async function call(method, path, opts) {
    opts = opts || {};
    const headers = { Accept: 'application/json' };
    const tok = localStorage.getItem(TOKEN_KEY);
    if (tok && !opts.anon) headers.Authorization = 'Bearer ' + tok;
    if (opts.key) headers['Idempotency-Key'] = opts.key;
    let body;
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    let res;
    try {
      res = await fetch(path, { method, headers, body, cache: 'no-store' });
    } catch (e) {
      throw new Unknown('network');
    }
    let data = null;
    const text = await res.text().catch(() => '');
    if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
    if (res.status >= 500) throw new Unknown('server ' + res.status);
    if (res.status === 401 && !opts.anon) {
      localStorage.removeItem(TOKEN_KEY);
      if (route !== '/login' && route !== '/signup') { location.href = '/login'; }
    }
    return { ok: res.ok, status: res.status, data };
  }
  function errText(r) {
    const code = r.data && r.data.error && r.data.error.code;
    const msg = r.data && r.data.error && r.data.error.message;
    const map = {
      insufficient_funds: 'Not enough available funds for that. Money on hold can’t be spent.',
      not_found: 'We couldn’t find that person or item.',
      self_payment: 'You can’t send money to yourself.',
      self_request: 'You can’t request money from yourself.',
      request_not_pending: 'That request is no longer pending.',
      forbidden: 'You’re not allowed to do that.',
      authorization_not_open: 'That reservation is already closed.',
      authorization_expired: 'That reservation has expired.',
      capture_exceeds_authorization: 'That is more than what is still reserved.',
      email_taken: 'That email is already registered.',
      handle_taken: 'That email maps to a handle that is already taken.',
      unauthenticated: 'Those details don’t match an account.',
      idempotency_key_reuse: 'That request was already used with different details.',
    };
    return map[code] || msg || 'Something went wrong (' + r.status + ').';
  }

  // Keyed list reconciliation: rows whose data is unchanged are kept as-is (so typing,
  // focus and selections inside them are never disturbed by a background refresh).
  function reconcile(listEl, items, keyOf, build) {
    const cache = listEl._rows || (listEl._rows = new Map());
    const active = document.activeElement;
    const focusId = active && listEl.contains(active) ? active.id : null;
    const sel = focusId && active.selectionStart != null ? [active.selectionStart, active.selectionEnd] : null;
    const seen = new Set();
    const nodes = items.map((it) => {
      const k = keyOf(it), sig = JSON.stringify(it);
      seen.add(k);
      const hit = cache.get(k);
      if (hit && hit.sig === sig) return hit.node;
      const node = build(it);
      cache.set(k, { sig, node });
      return node;
    });
    for (const k of [...cache.keys()]) if (!seen.has(k)) cache.delete(k);
    nodes.forEach((n, i) => { if (listEl.children[i] !== n) listEl.insertBefore(n, listEl.children[i] || null); });
    while (listEl.children.length > nodes.length) listEl.lastElementChild.remove();
    if (focusId && document.activeElement && document.activeElement.id !== focusId) {
      const again = document.getElementById(focusId);
      if (again) { again.focus({ preventScroll: true }); if (sel) try { again.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } }
    }
  }

  // ------------------------------------------------------------------ state boxes
  function stateBox(kind, text, tid, extra) {
    const ic = { refused: '✕', sent: '✓', uncertain: '?', loading: '' }[kind];
    return h('div', { class: 'state ' + kind, tid, role: kind === 'refused' ? 'alert' : 'status' },
      h('span', { class: 'ic', 'aria-hidden': 'true', text: ic }), h('span', { text }), extra);
  }
  // A slot shows at most one state element; set() replaces, clear() removes
  function slot() {
    const el = h('div', { 'aria-live': 'polite' });
    return {
      el,
      set(kind, text, tid) { el.replaceChildren(stateBox(kind, text, tid)); },
      clear() { el.replaceChildren(); },
    };
  }

  // idempotency key per distinct content
  function keyring() {
    const m = new Map();
    return (name, sig) => {
      const cur = m.get(name);
      if (cur && cur.sig === sig) return cur.key;
      const key = uid();
      m.set(name, { sig, key });
      return key;
    };
  }
  const keyFor = keyring();

  function field(id, label, input, hint) {
    return h('div', { class: 'field' }, h('label', { for: id, text: label }), input, hint ? h('span', { class: 'tiny', text: hint }) : null);
  }
  function btn(label, attrs) {
    return h('button', Object.assign({ type: 'submit', class: 'btn' }, attrs), h('span', { text: label }));
  }
  function setBusy(b, busy, label) {
    b.disabled = !!busy;
    const t = b.querySelector('span:last-child');
    if (busy) {
      b.dataset.label = t.textContent;
      t.textContent = label || 'Working…';
      b.prepend(h('span', { class: 'spin', 'aria-hidden': 'true' }));
    } else {
      b.querySelectorAll('.spin').forEach((n) => n.remove());
      if (b.dataset.label) t.textContent = b.dataset.label;
    }
  }
  function cleanHandle(v) {
    return String(v || '').trim().replace(/^@/, '');
  }

  // ------------------------------------------------------------------ shell
  const NAV = [
    ['/', 'Home', 'home'], ['/requests', 'Requests', 'req'], ['/split', 'Split', 'split'], ['/authorizations', 'Reserve', 'hold'],
  ];
  function shell(content) {
    $app.replaceChildren();
    if (!ME) {
      const wrap = h('div', { class: 'authwrap' }, content);
      $app.append(h('main', {}, wrap));
      return;
    }
    const side = h('div', { class: 'side' },
      h('div', { class: 'top' },
        h('div', { class: 'brand' }, h('span', { class: 'mark' }, svg('<path d="M5 12h14M12 5v14"/>')), h('span', { class: 'bt', text: 'Pocketful' })),
        h('div', { class: 'who' }, avatar(ME.display_name),
          h('div', { class: 'names' }, h('b', { tid: 'current-user', text: ME.display_name }),
            h('span', {}, '@', h('span', { tid: 'current-handle', text: ME.handle })))),
        h('button', { class: 'ghost', tid: 'logout-button', type: 'button', onclick: logout }, 'Log out')),
      h('nav', { class: 'menu', 'aria-label': 'Main' }, NAV.map(([href, label, ic]) =>
        h('a', { href, 'aria-current': route === href ? 'page' : false }, svg(ICON[ic]), h('span', { text: label })))));
    $app.append(h('div', { class: 'shell' }, side, h('main', {}, h('div', { class: 'page' }, content))));
  }
  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    location.href = '/login';
  }
  async function loadMe() {
    if (!localStorage.getItem(TOKEN_KEY)) return null;
    try {
      const r = await call('GET', '/me');
      if (r.ok) return r.data;
    } catch (e) { /* keep going signed-out view */ }
    return null;
  }

  // ------------------------------------------------------------------ wallet card
  function walletCard(me) {
    const card = h('section', { class: 'card balance', 'aria-label': 'Wallet' },
      h('div', { class: 'label', text: 'Available to spend' }),
      h('div', { class: 'avail', tid: 'wallet-available', 'data-amount': String(me.available), text: money(me.available) }),
      h('div', { class: 'secondary' },
        h('div', {}, h('small', { text: 'Total' }), h('span', { class: 'v', tid: 'wallet-balance', 'data-amount': String(me.total), text: money(me.total) })),
        me.held > 0 ? h('div', {}, h('small', { text: 'On hold' }), h('span', { class: 'v heldv', tid: 'wallet-held', 'data-amount': String(me.held), text: money(me.held) })) : null));
    return card;
  }
  let refreshSeq = 0;
  // Latest refresh wins: only the most recently started refresh may render.
  async function refreshHome(parts) {
    const mine = ++refreshSeq;
    try {
      const [me, act] = await Promise.all([call('GET', '/me'), call('GET', '/activity?limit=50')]);
      if (mine !== refreshSeq) return;
      if (!me.ok || !act.ok) return;
      ME = me.data;
      parts.wallet.replaceChildren(walletCard(ME));
      renderFeed(parts.feed, act.data.payments);
      renderContacts(parts.contacts, act.data.payments);
    } catch (e) { /* a failed read leaves the last good view in place */ }
  }

  function renderContacts(box, payments) {
    const seen = [];
    for (const p of payments) {
      const other = p.from_user_id === ME.user_id ? p.to_handle : p.to_user_id === ME.user_id ? p.from_handle : null;
      if (other && !seen.includes(other)) seen.push(other);
      if (seen.length >= 8) break;
    }
    box.replaceChildren(
      ...seen.map((hd) => h('button', { type: 'button', class: 'contact', title: 'Pay @' + hd, onclick: () => pickContact(hd) },
        avatar(hd), h('span', { class: 'h', text: '@' + hd }))),
      h('button', { type: 'button', class: 'contact add', onclick: () => pickContact('') },
        h('div', { class: 'avatar', 'aria-hidden': 'true', text: '+' }), h('span', { class: 'h', text: 'Add' })));
  }
  function pickContact(hd) {
    const inp = document.getElementById('pay-handle');
    if (!inp) return;
    if (hd) { inp.value = hd; inp.dispatchEvent(new Event('input', { bubbles: true })); }
    inp.scrollIntoView({ block: 'center', behavior: 'smooth' });
    inp.focus({ preventScroll: true });
  }

  function renderFeed(box, payments) {
    if (!payments.length) {
      box.replaceChildren(h('div', { class: 'empty', tid: 'empty-activity' }, h('b', { text: 'No activity yet' }), 'Payments you send, receive or that are public will show up here.'));
      return;
    }
    const list = h('ul', { class: 'list', tid: 'activity-list' }, payments.map((p) => {
      const dir = p.from_user_id === ME.user_id ? 'out' : p.to_user_id === ME.user_id ? 'in' : 'other';
      const verb = dir === 'out' ? 'You paid' : dir === 'in' ? 'You received' : 'Public payment';
      const id = p.payment_id;
      return h('li', { class: 'item', tid: 'activity-item-' + id, 'data-visibility': p.visibility },
        h('div', { class: 'ico ' + dir }, svg(dir === 'out' ? ICON.out : dir === 'in' ? ICON.in : ICON.pub)),
        h('div', { class: 'main' },
          h('div', { class: 'title', tid: 'activity-parties-' + id, text: '@' + p.from_handle + ' → @' + p.to_handle }),
          h('div', { class: 'note', tid: 'activity-note-' + id, text: p.note }),
          h('div', { class: 'meta' }, h('span', { text: verb }), h('span', { text: when(p.created_at) }),
            h('span', { class: 'chip ' + p.visibility }, svg(p.visibility === 'private' ? ICON.lock : ICON.pub).cloneNode(true), p.visibility === 'private' ? 'Private' : 'Public'))),
        h('div', { class: 'amt ' + dir }, dir === 'out' ? h('span', { 'aria-hidden': 'true', text: '− ' }) : dir === 'in' ? h('span', { 'aria-hidden': 'true', text: '+ ' }) : null,
          h('span', { tid: 'activity-amount-' + id, text: money(p.amount) })));
    }));
    box.replaceChildren(list);
  }

  // ------------------------------------------------------------------ generic money form
  // spec: { prefix, title, sub, fields: 'pay'|'request'|'authorize', path, ... }
  function moneyForm(cfg, onDone) {
    const P = cfg.prefix;
    const handle = h('input', { id: P + '-handle', tid: P + '-handle', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: 'e.g. bob' });
    const amount = h('input', { id: P + '-amount', tid: P + '-amount', inputmode: 'decimal', autocomplete: 'off', placeholder: ME.minor_units ? '0.' + '0'.repeat(ME.minor_units) : '0' });
    const note = h('input', { id: P + '-note', tid: P + '-note', maxlength: '200', autocomplete: 'off', placeholder: 'What is it for? (optional)' });
    const vis = cfg.visibility === false ? null : h('select', { id: P + '-visibility', tid: P + '-visibility' },
      h('option', { value: 'public', text: 'Public' }), h('option', { value: 'private', text: 'Private' }));
    const submit = btn(cfg.button, { tid: P + '-submit' });
    const status = slot();
    const form = h('form', { novalidate: true, 'aria-label': cfg.title },
      field(P + '-handle', cfg.handleLabel, handle),
      h('div', { class: vis ? 'row2' : '' }, field(P + '-amount', 'Amount (' + ME.currency + ')', amount), vis ? field(P + '-visibility', 'Visibility', vis) : null),
      field(P + '-note', 'Note', note),
      submit, status.el);
    let uncertain = false;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const to = cleanHandle(handle.value);
      const amt = parseAmount(amount.value);
      if (!to) return status.set('refused', 'Enter who this is for.', P + '-error');
      if (amt.error) return status.set('refused', amt.error, P + '-error');
      const body = cfg.body(to, amt.minor, note.value, vis ? vis.value : undefined);
      const sig = JSON.stringify(body);
      const key = keyFor(P, sig);
      status.set('loading', cfg.busy);
      setBusy(submit, true, 'Sending…');
      try {
        const r = await call('POST', cfg.path, { body, key });
        if (r.ok) {
          uncertain = false;
          status.set('sent', cfg.success(r.data, to, amt.minor), P + '-success');
          setBusy(submit, false);
          await onDone(r.data);
        } else {
          uncertain = false;
          status.set('refused', errText(r), P + '-error');
          setBusy(submit, false);
          await onDone(null);
        }
      } catch (e) {
        uncertain = true;
        status.set('uncertain', cfg.uncertain, P + '-uncertain');
        setBusy(submit, false);
      }
    });
    return { form, handle, amount, note, vis };
  }

  // ------------------------------------------------------------------ pages
  async function pageHome() {
    const parts = { wallet: h('div', {}, h('div', { class: 'skeleton' })), contacts: h('div', { class: 'contacts' }), feed: h('div', {}, stateBox('loading', 'Loading your activity…')) };
    const done = () => refreshHome(parts);
    const pay = moneyForm({
      prefix: 'pay', title: 'Send money', button: 'Send money', handleLabel: 'Pay to (handle)',
      path: '/payments', busy: 'Sending your payment…',
      body: (to, minor, note, vis) => ({ to_handle: to, amount: minor, note, visibility: vis }),
      success: (d, to, minor) => 'Sent ' + money(minor) + ' to @' + to + '.',
      uncertain: 'We lost the connection, so we can’t tell whether this payment went through. Nothing is wrong with your details — press the button to retry safely; it can only be sent once.',
    }, done);
    const req = moneyForm({
      prefix: 'request', title: 'Request money', button: 'Request money', handleLabel: 'Ask (handle)', visibility: false,
      path: '/requests', busy: 'Sending your request…',
      body: (to, minor, note) => ({ payer_handle: to, amount: minor, note }),
      success: (d, to, minor) => 'Asked @' + to + ' for ' + money(minor) + '.',
      uncertain: 'We couldn’t confirm that request was created. Press the button to retry safely.',
    }, done);
    const auth = moneyForm(authorizeCfg(), done);

    const refresh = h('button', { type: 'button', class: 'ghost', tid: 'wallet-refresh', onclick: () => refreshHome(parts) }, 'Refresh');
    shell(h('div', { class: 'stack' },
      h('div', { class: 'sect' }, h('h1', { class: 'page-title', style: 'margin:0', text: 'Hi, ' + ME.display_name }), refresh),
      parts.wallet,
      h('section', { 'aria-label': 'Quick pay' }, h('div', { class: 'sect' }, h('h2', { text: 'Quick pay' })), parts.contacts),
      h('div', { class: 'grid two' },
        h('section', { class: 'card' }, h('h2', { text: 'Send money' }), h('p', { class: 'sub', text: 'Moves money right away.' }), pay.form),
        h('section', { class: 'card' }, h('h2', { text: 'Request money' }), h('p', { class: 'sub', text: 'Ask someone to pay you.' }), req.form)),
      h('section', { class: 'card' }, h('h2', { text: 'Reserve money' }), h('p', { class: 'sub', text: 'Hold funds for someone to collect later.' }), auth.form),
      h('section', { 'aria-label': 'Activity' }, h('div', { class: 'sect' }, h('h2', { text: 'Activity' })), parts.feed)));
    pay.handle.id = 'pay-handle';
    await refreshHome(parts);
  }

  function authorizeCfg() {
    return {
      prefix: 'authorize', title: 'Reserve money', button: 'Reserve money', handleLabel: 'Reserve for (handle)',
      path: '/authorizations', busy: 'Reserving the funds…',
      body: (to, minor, note, vis) => ({ to_handle: to, amount: minor, note, visibility: vis }),
      success: (d, to, minor) => 'Reserved ' + money(minor) + ' for @' + to + '. Nothing moves until they collect.',
      uncertain: 'We couldn’t confirm the reservation. Press the button to retry safely.',
    };
  }

  async function pageRequests() {
    const err = slot();
    const incoming = h('ul', { class: 'list', tid: 'incoming-list' });
    const outgoing = h('ul', { class: 'list', tid: 'outgoing-list' });
    const inSec = h('section', { 'aria-label': 'Incoming requests' }, h('div', { class: 'sect' }, h('h2', { text: 'Asking you to pay' })), incoming);
    const outSec = h('section', { 'aria-label': 'Outgoing requests' }, h('div', { class: 'sect' }, h('h2', { text: 'You asked for' })), outgoing);
    const emptyBox = h('div', {});
    const loading = stateBox('loading', 'Loading requests…');
    shell(h('div', { class: 'stack' }, h('h1', { class: 'page-title', text: 'Requests' }), err.el, loading, emptyBox, inSec, outSec));
    inSec.hidden = outSec.hidden = true;
    let seq = 0;
    const rowState = {};

    function row(r, dir) {
      const id = r.request_id;
      const other = dir === 'in' ? r.requester_handle : r.payer_handle;
      const kids = [];
      const ctl = [];
      if (r.status === 'pending' && dir === 'in') {
        const vis = h('select', { id: 'rv-' + id, 'aria-label': 'Visibility' }, h('option', { value: 'public', text: 'Public' }), h('option', { value: 'private', text: 'Private' }));
        vis.value = rowState['rv-' + id] || 'public';
        vis.addEventListener('change', () => { rowState['rv-' + id] = vis.value; });
        ctl.push(h('div', { class: 'field' }, h('label', { for: 'rv-' + id, text: 'Visibility when paid' }), vis));
        ctl.push(h('button', { class: 'btn small', type: 'button', tid: 'request-pay-' + id, onclick: (e) => act(e.currentTarget, 'pay', r, vis.value) }, 'Pay ' + money(r.amount)));
        ctl.push(h('button', { class: 'btn small secondary', type: 'button', tid: 'request-decline-' + id, onclick: (e) => act(e.currentTarget, 'decline', r) }, 'Decline'));
      }
      if (r.status === 'pending' && dir === 'out') {
        ctl.push(h('button', { class: 'btn small danger', type: 'button', tid: 'request-cancel-' + id, onclick: (e) => act(e.currentTarget, 'cancel', r) }, 'Cancel request'));
      }
      return h('li', { class: 'item', tid: 'request-item-' + id, 'data-status': r.status },
        h('div', { class: 'ico ' + (dir === 'in' ? 'out' : 'in') }, svg(dir === 'in' ? ICON.out : ICON.in)),
        h('div', { class: 'main' },
          h('div', { class: 'title', text: dir === 'in' ? '@' + other + ' asks you for' : 'You asked @' + other }),
          h('div', { class: 'note', text: r.note }),
          h('div', { class: 'meta' }, h('span', { class: 'chip ' + r.status, text: r.status[0].toUpperCase() + r.status.slice(1) }), h('span', { text: when(r.created_at) }))),
        h('div', { class: 'amt ' + (dir === 'in' ? 'out' : 'in') }, h('span', { tid: 'request-amount-' + id, text: money(r.amount) })),
        ctl.length ? h('div', { class: 'actions' }, ctl) : null);
    }
    async function load() {
      const mine = ++seq;
      try {
        const [a, b] = await Promise.all([call('GET', '/requests?direction=incoming&limit=200'), call('GET', '/requests?direction=outgoing&limit=200')]);
        if (mine !== seq || !a.ok || !b.ok) return;
        loading.remove();
        reconcile(incoming, a.data.requests, (r) => r.request_id, (r) => row(r, 'in'));
        reconcile(outgoing, b.data.requests, (r) => r.request_id, (r) => row(r, 'out'));
        const none = !a.data.requests.length && !b.data.requests.length;
        inSec.hidden = outSec.hidden = none;
        emptyBox.replaceChildren(none ? h('div', { class: 'empty', tid: 'empty-requests' }, h('b', { text: 'No requests' }), 'When someone asks you for money, or you ask them, it shows up here.') : '');
        [incoming, outgoing].forEach((l) => { const n = l.nextElementSibling; if (n && n.classList.contains('none-note')) n.remove(); });
        if (!a.data.requests.length && !none) incoming.after(h('p', { class: 'muted none-note', text: 'Nothing waiting for you.' }));
        if (!b.data.requests.length && !none) outgoing.after(h('p', { class: 'muted none-note', text: 'You haven\u2019t asked anyone.' }));
      } catch (e) { /* keep last view */ }
    }
    async function act(button, action, r, vis) {
      err.clear();
      button.disabled = true;
      try {
        let res;
        if (action === 'pay') res = await call('POST', '/requests/' + r.request_id + '/pay', { body: { visibility: vis }, key: keyFor('rq-' + r.request_id, vis) });
        else res = await call('POST', '/requests/' + r.request_id + '/' + action, {});
        if (!res.ok) err.set('refused', errText(res), 'request-error');
        else err.set('sent', action === 'pay' ? 'Paid ' + money(r.amount) + ' to @' + r.requester_handle + '.' : action === 'decline' ? 'Request declined.' : 'Request cancelled.', 'request-success');
      } catch (e) {
        err.set('uncertain', 'We couldn’t confirm what happened. Refresh to check, then try again.', 'request-uncertain');
      }
      button.disabled = false;
      await load();
    }
    await load();
  }

  function sharesOf(minor, n) {
    const base = Math.floor(minor / n), extra = minor % n;
    return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
  }
  async function pageSplit() {
    const amount = h('input', { id: 'split-amount', tid: 'split-amount', inputmode: 'decimal', autocomplete: 'off', placeholder: ME.minor_units ? '0.' + '0'.repeat(ME.minor_units) : '0' });
    const handles = h('input', { id: 'split-handles', tid: 'split-handles', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: 'ada, bob, cy' });
    const note = h('input', { id: 'split-note', tid: 'split-note', maxlength: '200', placeholder: 'e.g. dinner (optional)' });
    const preview = h('div', { 'aria-live': 'polite' });
    const submit = btn('Split and request', { tid: 'split-submit' });
    const status = slot();
    function compute() {
      const names = handles.value.split(',').map(cleanHandle).filter(Boolean);
      const amt = parseAmount(amount.value);
      return { names, amt };
    }
    function paint() {
      const { names, amt } = compute();
      let problem = null;
      if (!names.length || amount.value.trim() === '') problem = 'Enter an amount and the handles to split between — shares appear here as you type.';
      else if (amt.error) problem = amt.error;
      else if (names.some((n) => !HANDLE_RE.test(n))) problem = 'Handles use lowercase letters, numbers and underscores.';
      else if (new Set(names).size !== names.length) problem = 'Each handle can appear only once.';
      if (problem) {
        preview.replaceChildren(h('p', { class: 'muted', text: problem }));
        return null;
      }
      const sh = sharesOf(amt.minor, names.length);
      preview.replaceChildren(h('div', { tid: 'split-preview' },
        h('ul', { class: 'shares' }, names.map((n, i) =>
          h('li', { class: 'share' }, avatar(n), h('div', { class: 'nm' }, '@' + n, h('small', { text: n === ME.handle ? 'You (already paid)' : 'Will be asked' })),
            h('span', { class: 'v', tid: 'split-share-' + n, text: money(sh[i]) })))),
        h('div', { class: 'preview-total' }, h('span', { text: 'Total' }), h('span', { text: money(amt.minor) }))));
      return { names, minor: amt.minor };
    }
    [amount, handles, note].forEach((i) => i.addEventListener('input', paint));
    const form = h('form', { novalidate: true, 'aria-label': 'Split a bill' },
      field('split-amount', 'Amount you paid (' + ME.currency + ')', amount),
      field('split-handles', 'Split between (handles, comma separated)', handles, 'The extra cent goes to the first people listed.'),
      field('split-note', 'Note', note), preview, submit, status.el);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const { names, amt } = compute();
      if (amt.error) return status.set('refused', amt.error, 'split-error');
      if (!names.length) return status.set('refused', 'Enter at least one handle.', 'split-error');
      const body = { amount: amt.minor, participant_handles: names, note: note.value };
      const key = keyFor('split', JSON.stringify(body));
      status.set('loading', 'Creating the split…');
      setBusy(submit, true, 'Sending…');
      try {
        const r = await call('POST', '/splits', { body, key });
        if (r.ok) status.set('sent', 'Split created. ' + r.data.requests.length + ' request' + (r.data.requests.length === 1 ? '' : 's') + ' sent.', 'split-success');
        else status.set('refused', errText(r), 'split-error');
      } catch (e) {
        status.set('uncertain', 'We couldn’t confirm the split was created. Press the button to retry safely.', 'split-uncertain');
      }
      setBusy(submit, false);
    });
    shell(h('div', { class: 'stack' }, h('h1', { class: 'page-title', text: 'Split a bill' }),
      h('section', { class: 'card split-card' }, h('h2', { text: 'Who owes what' }), h('p', { class: 'sub', text: 'You paid. Everyone else is asked for their equal share.' }), form)));
    paint();
  }

  async function pageAuthorizations() {
    const parts = { wallet: h('div', {}) };
    const err = slot();
    const listBox = h('div', {}, stateBox('loading', 'Loading reservations…'));
    let seq = 0;
    async function load() {
      const mine = ++seq;
      try {
        const [me, a] = await Promise.all([call('GET', '/me'), call('GET', '/authorizations?limit=200')]);
        if (mine !== seq || !me.ok || !a.ok) return;
        ME = me.data;
        parts.wallet.replaceChildren(walletCard(ME));
        paintList(a.data.authorizations);
      } catch (e) { /* keep */ }
    }
    const listUl = h('ul', { class: 'list', tid: 'authorization-list' });
    const capState = {};
    function paintList(items) {
      if (!items.length) {
        listBox.replaceChildren(h('div', { class: 'empty', tid: 'empty-authorizations' }, h('b', { text: 'No reservations' }), 'Reserve money for someone to collect later, or collect what others reserved for you.'));
        return;
      }
      if (!listUl.isConnected) listBox.replaceChildren(listUl);
      reconcile(listUl, items, (a) => a.authorization_id, (a) => {
        const id = a.authorization_id;
        const incoming = a.to_user_id === ME.user_id;
        const other = incoming ? a.from_handle : a.to_handle;
        const ctl = [];
        if (a.status === 'open' && incoming) {
          const cs = capState[id] || (capState[id] = { dirty: false, value: '', keep: false });
          const ci = h('input', { id: 'cap-' + id, tid: 'authorization-capture-amount-' + id, inputmode: 'decimal', value: cs.dirty ? cs.value : decimalText(a.remaining_amount), autocomplete: 'off' });
          ci.addEventListener('input', () => { cs.dirty = true; cs.value = ci.value; });
          const keep = h('input', { id: 'keep-' + id, type: 'checkbox', style: 'width:20px;min-height:20px;flex:none' });
          keep.checked = cs.keep;
          keep.addEventListener('change', () => { cs.keep = keep.checked; });
          ctl.push(field('cap-' + id, 'Amount to collect', ci));
          ctl.push(h('div', { class: 'field', style: 'flex:1 1 100%;display:flex;flex-direction:row;align-items:center;gap:8px' }, keep, h('label', { for: 'keep-' + id, text: 'Keep the rest on hold' })));
          ctl.push(h('button', { class: 'btn small', type: 'button', tid: 'authorization-capture-' + id, onclick: (e) => capture(e.currentTarget, a, ci, keep) }, 'Collect'));
        }
        if (a.status === 'open' && !incoming) {
          ctl.push(h('button', { class: 'btn small danger', type: 'button', tid: 'authorization-void-' + id, onclick: (e) => voidIt(e.currentTarget, a) }, 'Release hold'));
        }
        return h('li', { class: 'item', tid: 'authorization-item-' + id, 'data-status': a.status },
          h('div', { class: 'ico ' + (incoming ? 'in' : 'out') }, svg(ICON.hold)),
          h('div', { class: 'main' },
            h('div', { class: 'title', text: incoming ? '@' + other + ' reserved for you' : 'You reserved for @' + other }),
            h('div', { class: 'note', text: a.note }),
            h('div', { class: 'meta' },
              h('span', { class: 'chip ' + a.status, text: a.status[0].toUpperCase() + a.status.slice(1) }),
              h('span', { class: 'chip ' + a.visibility, text: a.visibility === 'private' ? 'Private' : 'Public' }),
              a.status === 'captured' ? h('span', {}, 'Collected ', h('b', { tid: 'authorization-captured-' + id, text: money(a.captured_amount) })) : null,
              a.status === 'open' && a.captured_amount > 0 ? h('span', { text: 'Collected so far ' + money(a.captured_amount) }) : null),
            h('div', { class: 'meta' }, h('span', { class: 'friendly', text: friendlyExpiry(a) }), h('span', { class: 'tiny' }, h('time', { tid: 'authorization-expires-' + id, datetime: a.expires_at, text: a.expires_at })))),
          h('div', { class: 'amt ' + (incoming ? 'in' : 'out') }, h('span', { tid: 'authorization-amount-' + id, text: money(a.amount) })),
          ctl.length ? h('div', { class: 'actions' }, ctl) : null);
      });
    }
    async function capture(button, a, input, keep) {
      err.clear();
      const amt = parseAmount(input.value);
      if (amt.error) return err.set('refused', amt.error, 'authorization-error');
      const body = { amount: amt.minor };
      if (keep && keep.checked) body.final = false;
      button.disabled = true;
      try {
        const r = await call('POST', '/authorizations/' + a.authorization_id + '/capture', { body, key: keyFor('cap-' + a.authorization_id, JSON.stringify(body)) });
        if (r.ok) delete capState[a.authorization_id];
        if (r.ok) err.set('sent', 'Collected ' + money(amt.minor) + ' from @' + a.from_handle + '.', 'authorization-success');
        else err.set('refused', errText(r), 'authorization-error');
      } catch (e) {
        err.set('uncertain', 'We couldn’t confirm the collection. Press Collect again to retry safely.', 'authorization-uncertain');
      }
      button.disabled = false;
      await load();
    }
    async function voidIt(button, a) {
      err.clear();
      button.disabled = true;
      try {
        const r = await call('POST', '/authorizations/' + a.authorization_id + '/void', {});
        if (r.ok) err.set('sent', 'Hold released. The money is available again.', 'authorization-success');
        else err.set('refused', errText(r), 'authorization-error');
      } catch (e) {
        err.set('uncertain', 'We couldn’t confirm the release. Refresh to check.', 'authorization-uncertain');
      }
      button.disabled = false;
      await load();
    }
    const form = moneyForm(authorizeCfg(), load);
    shell(h('div', { class: 'stack' }, h('h1', { class: 'page-title', text: 'Reserve money' }), parts.wallet,
      h('section', { class: 'card' }, h('h2', { text: 'New reservation' }), h('p', { class: 'sub', text: 'Held money stays yours until the recipient collects it, or the hold expires.' }), form.form),
      err.el,
      h('section', { 'aria-label': 'Reservations' }, h('div', { class: 'sect' }, h('h2', { text: 'Reservations' })), listBox)));
    await load();
  }

  function authPage(kind) {
    const isSignup = kind === 'signup';
    const err = slot();
    const email = h('input', { id: kind + '-email', tid: kind + '-email', type: 'email', autocomplete: 'email', inputmode: 'email' });
    const pass = h('input', { id: kind + '-password', tid: kind + '-password', type: 'password', autocomplete: isSignup ? 'new-password' : 'current-password' });
    const name = isSignup ? h('input', { id: 'signup-display-name', tid: 'signup-display-name', autocomplete: 'name' }) : null;
    const submit = btn(isSignup ? 'Create account' : 'Log in', { tid: kind + '-submit' });
    const form = h('form', { novalidate: true, 'aria-label': isSignup ? 'Sign up' : 'Log in' },
      isSignup ? field('signup-display-name', 'Your name', name) : null,
      field(kind + '-email', 'Email', email),
      field(kind + '-password', 'Password', pass, isSignup ? 'At least 8 characters.' : null),
      submit, h('div', { 'aria-live': 'polite' }, err.el));
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      // auth-error is present only while there is an error
      err.clear();
      setBusy(submit, true, isSignup ? 'Creating…' : 'Logging in…');
      try {
        const body = isSignup ? { email: email.value.trim(), password: pass.value, display_name: name.value.trim() } : { email: email.value.trim(), password: pass.value };
        const r = await call('POST', '/auth/' + kind, { body, anon: true });
        if (r.ok) { localStorage.setItem(TOKEN_KEY, r.data.token); location.href = '/'; return; }
        err.set('refused', errText(r), 'auth-error');
      } catch (e) {
        err.set('uncertain', 'We couldn’t reach the service. Try again.', 'auth-error');
      }
      setBusy(submit, false);
    });
    shell(h('div', { class: 'card authcard' },
      h('div', { class: 'brand' }, h('span', { class: 'mark' }, svg('<path d="M5 12h14M12 5v14"/>')), 'Pocketful'),
      h('h1', { class: 'page-title', style: 'text-align:center;font-size:22px', text: isSignup ? 'Create your wallet' : 'Welcome back' }),
      form,
      h('p', { class: 'alt' }, isSignup ? 'Already have an account? ' : 'New here? ', h('a', { href: isSignup ? '/login' : '/signup', text: isSignup ? 'Log in' : 'Create an account' }))));
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    ME = await loadMe();
    const authed = ['/', '/requests', '/split', '/authorizations'];
    if (authed.includes(route) && !ME) { location.replace('/login'); return; }
    if (route === '/login' || route === '/signup') return authPage(route.slice(1));
    if (route === '/requests') return pageRequests();
    if (route === '/split') return pageSplit();
    if (route === '/authorizations') return pageAuthorizations();
    return pageHome();
  }
  boot();
})();
