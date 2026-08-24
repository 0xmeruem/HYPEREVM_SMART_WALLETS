#!/usr/bin/env python3
# copybot.py — paper copytrade bot for Hyperliquid (box 167).  v2 (audited)
# Watches N target wallets' fills; mirrors their NET perp position per coin into a $1000 PAPER bank
# at % of bank, marks paper PnL at live HL mid, reports to Telegram. NO real orders.
# Position-tracking model via startPosition: handles opens, partial closes (hold), full closes,
# and reversals (Long>Short / Short>Long) uniformly.
import json, os, time, urllib.request, urllib.parse, urllib.error, threading, traceback, html
import datetime as dt

BASE = os.environ.get("COPYBOT_BASE", "/home/blessed/hypeevm/copybot")
os.makedirs(BASE, exist_ok=True)
STATE_P = os.path.join(BASE, "state.json")
BAK_P = os.path.join(BASE, "state.bak")
LOG_P = os.path.join(BASE, "copybot.log")
LOCK_P = os.path.join(BASE, "copybot.lock")
LOG_MAX = 5 * 1024 * 1024   # rotate log at 5MB
try:
    CFG = json.load(open(os.path.join(BASE, "config.json")))
except Exception:
    CFG = {"tg_token": "TEST", "wallets": [], "wallet_meta": {}, "mode": "growth"}
TG_TOKEN = CFG.get("tg_token", "TEST")
WALLETS = [w.lower() for w in CFG.get("wallets", [])]
WMETA = CFG.get("wallet_meta", {})
TEST_MODE = os.environ.get("COPYBOT_TEST") == "1"   # disables network side-effects

STRAT = {
    "mode": CFG.get("mode", "growth"),   # 'growth' (2% every trade) | 'safe' (consensus-2)
    "frac": CFG.get("frac", 0.02),
    "per_trade_cap": 0.25,
    "max_concurrent": CFG.get("max_concurrent", 15),
    "cost": 0.0007,
    "consensus_window": 3600,
    "consensus_k": 2,
    "min_notional_target": 50.0,
    "coins_blocklist": CFG.get("coins_blocklist", []),
    "max_loss_mult": 1.0,                # cap paper loss per trade at -max_loss_mult * notional (liquidation model)
    "history_cap": 500,
}
BANK0 = 1000.0
EPS = 1e-9
_CHAT_IDS = []   # in-memory mirror of st['chat_ids'] for tg_send

def log(m):
    if TEST_MODE:
        return
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat()} {m}"
    print(line, flush=True)
    try:
        if os.path.exists(LOG_P) and os.path.getsize(LOG_P) > LOG_MAX:
            try:
                os.replace(LOG_P, LOG_P + ".1")   # keep one rotation
            except Exception:
                open(LOG_P, "w").close()
        with open(LOG_P, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

def esc(x):
    return html.escape(str(x), quote=False)

# ---------------- HL API ----------------
def hl_info(body, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:   # rate limited — honor Retry-After, back off hard, don't hammer
                ra = e.headers.get("Retry-After")
                wait = int(ra) if (ra and str(ra).isdigit()) else min(5 * (2 ** i), 30)
                log(f"HL 429 rate-limited, backoff {wait}s")
                time.sleep(wait)
                if i == tries - 1:
                    raise
                continue
            if i == tries - 1:
                raise
            time.sleep(1 + i)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1 + i)

def get_mids():
    try:
        return hl_info({"type": "allMids"})
    except Exception as e:
        log(f"allMids fail {e}"); return {}

def get_fills_since(w, start_ms):
    try:
        r = hl_info({"type": "userFillsByTime", "user": w, "startTime": int(start_ms)})
        return r if isinstance(r, list) else []
    except Exception as e:
        log(f"userFills fail {w[:10]} {e}"); return []

# ---------------- Telegram ----------------
def tg(method, params):
    if TEST_MODE:
        return {}
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log(f"tg {method} fail {e}"); return {}

def tg_send(text):
    for cid in list(_CHAT_IDS):
        tg("sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})

# ---------------- state ----------------
def _default_state():
    return {"bank": BANK0, "realized": 0.0, "open": {}, "last_ms": {}, "last_tid": {}, "closed": 0, "wins": 0,
            "chat_ids": [], "tg_offset": 0, "started": time.time(), "gross_win": 0.0, "gross_loss": 0.0,
            "peak": BANK0, "maxdd": 0.0, "history": [], "recent_opens": []}

def load_state():
    for path in (STATE_P, BAK_P):
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    st = json.load(fh)
                st.setdefault("last_tid", {})
                st.setdefault("recent_opens", [])
                return st
            except Exception as e:
                # corrupt — preserve for inspection, try backup next (never silently wipe then overwrite)
                try:
                    os.replace(path, path + ".bad")
                except Exception:
                    pass
                log(f"state load fail {path}: {e} (moved to .bad)")
    log("no valid state found -> fresh bank")
    return _default_state()

def save_state(st):
    tmp = STATE_P + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=0)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
    if os.path.exists(STATE_P):
        try:
            os.replace(STATE_P, BAK_P)   # roll previous good state to backup
        except Exception:
            pass
    os.replace(tmp, STATE_P)

# ---------------- consensus tracker ----------------
recent_opens = []  # (ts, coin, side, wallet)
def consensus_count(coin, side, now_ms):
    cutoff = now_ms - STRAT["consensus_window"] * 1000
    return len({w for (ts, c, s, w) in recent_opens if c == coin and s == side and ts >= cutoff})

def mid_of(mids, coin):
    v = mids.get(coin)
    try:
        return float(v) if v is not None else None
    except Exception:
        return None

# ---------------- signed size delta from HL dir ----------------
def signed_delta(direction, sz):
    if direction in ("Open Long", "Close Short", "Short > Long"):
        return +sz          # buying: increases (signed) position
    if direction in ("Open Short", "Close Long", "Long > Short"):
        return -sz          # selling: decreases (signed) position
    return 0.0              # spot Buy/Sell, Funding, etc. -> ignored for perp mirror

# ---------------- paper open/close ----------------
def open_paper(st, mids, w, coin, side, tgt_notional, now_ms, fill_px):
    if tgt_notional < STRAT["min_notional_target"]:
        return
    if coin in STRAT["coins_blocklist"]:
        return
    if len(st["open"]) >= STRAT["max_concurrent"]:
        return
    # consensus counts DISTINCT TARGET wallets that opened this coin/side recently (recorded in
    # process_fill on the target's real open — independent of whether WE can mirror it).
    if STRAT["mode"] == "safe" and consensus_count(coin, side, now_ms) < STRAT["consensus_k"]:
        return
    mid = mid_of(mids, coin)
    if mid is None or mid <= 0:
        return   # require a live mark to price MY entry (do not fabricate at target's price)
    notional = min(STRAT["frac"] * st["bank"], STRAT["per_trade_cap"] * st["bank"])
    if notional < 1 or st["bank"] <= 5:
        return
    key = f"{w}:{coin}"
    st["open"][key] = {"coin": coin, "side": side, "entry": mid, "notional": round(notional, 2),
                       "wallet": w, "open_ts": now_ms}
    wl = WMETA.get(w, {})
    tg_send(f"🟢 <b>OPEN {side} {esc(coin)}</b>\n${notional:,.0f} @ {mid:g}\ncopy of <code>{esc(w[:10])}…</code> (pnl ${wl.get('pnl',0):,})\nbank ${st['bank']:,.0f} · open {len(st['open'])}/{STRAT['max_concurrent']}")
    log(f"OPEN {side} {coin} ${notional:.0f} @ {mid} copy {w[:10]}")

def close_paper(st, mids, key, now_ms, fill_px=None):
    pos = st["open"].get(key)
    if not pos:
        return
    entry = pos["entry"]; notional = pos["notional"]
    mid = mid_of(mids, pos["coin"])
    if mid is None or mid <= 0:
        mid = fill_px if (fill_px and fill_px > 0) else entry   # exit proxy if mark missing
    if pos["side"] == "LONG":
        gross = notional * (mid / entry - 1)
    else:
        gross = notional * (1 - mid / entry)
    gross = max(gross, -STRAT["max_loss_mult"] * notional)   # liquidation floor
    pnl = gross - notional * STRAT["cost"]
    st["bank"] += pnl
    st["realized"] += pnl
    st["closed"] += 1
    st["wins"] += 1 if pnl > 0 else 0
    if pnl > 0: st["gross_win"] += pnl
    else: st["gross_loss"] += -pnl
    st["peak"] = max(st.get("peak", BANK0), st["bank"])
    if st["peak"] > 0:
        st["maxdd"] = max(st.get("maxdd", 0), (st["peak"] - st["bank"]) / st["peak"])
    hold_m = (now_ms - pos["open_ts"]) / 60000
    hist = st.setdefault("history", [])
    hist.append({"coin": pos["coin"], "side": pos["side"], "pnl": round(pnl, 3), "ts": now_ms, "hold_min": round(hold_m, 1)})
    if len(hist) > STRAT["history_cap"]:
        del hist[:len(hist) - STRAT["history_cap"]]
    del st["open"][key]
    st.get("orphan_strikes", {}).pop(key, None)   # clear any reconcile strike on this key (normal close)
    emoji = "✅" if pnl > 0 else "🔻"
    wr = st["wins"] / st["closed"] if st["closed"] else 0
    tg_send(f"{emoji} <b>CLOSE {pos['side']} {esc(pos['coin'])}</b>  {pnl:+,.2f}$\n{notional:,.0f}$ {entry:g}→{mid:g} · held {hold_m:.0f}m\n<b>bank ${st['bank']:,.2f}</b> ({(st['bank']/BANK0-1)*100:+.1f}%) · realized ${st['realized']:+,.0f} · WR {wr*100:.0f}% ({st['closed']})")
    log(f"CLOSE {pos['side']} {pos['coin']} pnl {pnl:+.2f} bank {st['bank']:.2f}")

# ---------------- core: process one fill (position-tracking) ----------------
def process_fill(st, mids, w, f, paused=False):
    coin = f.get("coin"); direction = f.get("dir", "")
    try:
        fill_px = float(f.get("px"))
    except Exception:
        return
    try:
        sz = abs(float(f.get("sz", 0)))
    except Exception:
        return
    delta = signed_delta(direction, sz)
    if delta == 0:
        return   # spot / funding / non-position fill
    now_ms = _i(f.get("time", 0)) or int(time.time() * 1000)
    key = f"{w}:{coin}"
    sp = f.get("startPosition")
    try:
        start_pos = float(sp) if sp is not None else None
    except Exception:
        start_pos = None

    if start_pos is not None:
        new_pos = start_pos + delta
        target_side = "LONG" if new_pos > EPS else ("SHORT" if new_pos < -EPS else "FLAT")
    else:
        # fallback (startPosition missing): infer coarsely from dir
        if direction in ("Open Long",): target_side = "LONG"
        elif direction in ("Open Short",): target_side = "SHORT"
        elif direction in ("Close Long", "Close Short"): target_side = "FLAT"
        elif direction == "Long > Short": target_side = "SHORT"
        elif direction == "Short > Long": target_side = "LONG"
        else: target_side = None

    have = st["open"].get(key)
    # CLOSE my position if target went flat or reversed
    if have and (target_side == "FLAT" or
                 (target_side == "LONG" and have["side"] == "SHORT") or
                 (target_side == "SHORT" and have["side"] == "LONG")):
        close_paper(st, mids, key, now_ms, fill_px)
        have = None
    # OPEN only on an actual OPENING/REVERSAL action — never on a partial Close that merely
    # leaves the target still in-position (that = target winding down a position we didn't open,
    # e.g. bot started mid-position). Prevents false entries as the target EXITS.
    is_open_action = direction in ("Open Long", "Open Short", "Long > Short", "Short > Long")
    if is_open_action and target_side in ("LONG", "SHORT"):
        tgt_notional = sz * fill_px
        # record the TARGET's real open for consensus (distinct-wallet set), gated on non-dust
        if tgt_notional >= STRAT["min_notional_target"]:
            recent_opens.append((now_ms, coin, target_side, w))
            if len(recent_opens) > 5000:
                del recent_opens[:2000]
        if key not in st["open"] and not paused:
            open_paper(st, mids, w, coin, target_side, tgt_notional, now_ms, fill_px)

# ---------------- reconcile orphaned paper positions ----------------
def get_positions(w):
    """current coins the wallet actually holds a non-zero perp position in (via clearinghouseState)."""
    try:
        r = hl_info({"type": "clearinghouseState", "user": w})
        held = {}
        for ap in (r or {}).get("assetPositions", []):
            pos = ap.get("position", {})
            coin = pos.get("coin")
            try:
                szi = float(pos.get("szi", 0))
            except Exception:
                szi = 0
            if coin and abs(szi) > 0:
                held[coin] = szi
        return held, True
    except Exception as e:
        log(f"clearinghouseState fail {w[:10]} {e}")
        return {}, False

def reconcile(st, mids, now_ms):
    """close paper positions the target no longer actually holds (missed-close / gap safety net)."""
    by_wallet = {}
    for key, pos in list(st["open"].items()):
        by_wallet.setdefault(pos["wallet"], []).append((key, pos))
    strikes = st.setdefault("orphan_strikes", {})
    for w, poslist in by_wallet.items():
        held, ok = get_positions(w)
        if not ok:
            continue   # API failed — don't act on incomplete info (fail-safe: keep positions)
        for key, pos in poslist:
            szi = held.get(pos["coin"])
            target_side = None
            if szi is not None:
                target_side = "LONG" if szi > 0 else "SHORT"
            if target_side is None or target_side != pos["side"]:
                # 2-strike: require two consecutive orphan observations before closing
                # (guards against a transient API blip or any coin-name divergence)
                strikes[key] = strikes.get(key, 0) + 1
                if strikes[key] >= 2:
                    log(f"reconcile: closing orphan {key} (target now {target_side or 'FLAT'})")
                    close_paper(st, mids, key, now_ms)
                    strikes.pop(key, None)
            else:
                strikes.pop(key, None)   # target still holds matching side -> reset
        time.sleep(0.2)
    # drop strikes for positions no longer open
    for k in list(strikes):
        if k not in st["open"]:
            strikes.pop(k, None)

# ---------------- per-wallet fill batch (sort + tid-dedup) — testable ----------------
def _i(x):
    try:
        return int(x)
    except Exception:
        return 0

def process_wallet_fills(st, mids, w, fills, paused=False):
    if not fills:
        return
    fills = sorted(fills, key=lambda f: (_i(f.get("time", 0)), _i(f.get("tid", 0))))   # safe: malformed can't stall
    last_tid = st.setdefault("last_tid", {}).get(w, 0)
    for f in fills:
        tid = _i(f.get("tid", 0))
        if tid and tid <= last_tid:
            continue
        try:
            process_fill(st, mids, w, f, paused=paused)
        except Exception as e:
            log(f"process_fill err {w[:10]} {e}")
        if tid:
            st["last_tid"][w] = max(st["last_tid"].get(w, 0), tid)
        st["last_ms"][w] = max(st["last_ms"].get(w, 0), _i(f.get("time", 0)))

# ---------------- Telegram command handler ----------------
HELP = ("🤖 <b>HyperCopy paper bot</b>\n"
        "/status – bank, PnL, drawdown\n/positions – open paper trades\n/pnl – realized breakdown\n"
        "/wallets – targets tracked\n/strategy – current config\n/mode growth|safe – switch mode\n"
        "/stop – pause new opens\n/resume – resume\n/help – this")

def handle_commands(st):
    upd = tg("getUpdates", {"offset": st.get("tg_offset", 0), "timeout": 0})
    if not isinstance(upd, dict) or not upd.get("ok"):
        return
    for u in upd.get("result", []):
        st["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message") or {}
        cid = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not cid:
            continue
        if cid not in st.setdefault("chat_ids", []):
            st["chat_ids"].append(cid)
            if len(st["chat_ids"]) > 20:
                st["chat_ids"] = st["chat_ids"][-20:]   # bound growth
        cmd = text.lower().split()[0] if text else ""
        if cmd in ("/start", "/help"):
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text": HELP + f"\n\nTracking {len(WALLETS)} wallets · bank ${st['bank']:,.2f} · mode {STRAT['mode']}"})
        elif cmd == "/status":
            wr = st["wins"] / st["closed"] if st["closed"] else 0
            up = (time.time() - st.get("started", time.time())) / 3600
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text":
                f"💰 <b>bank ${st['bank']:,.2f}</b> ({(st['bank']/BANK0-1)*100:+.1f}%)\nrealized ${st['realized']:+,.2f}\n"
                f"open {len(st['open'])}/{STRAT['max_concurrent']} · closed {st['closed']} · WR {wr*100:.0f}%\n"
                f"maxDD {st.get('maxdd',0)*100:.1f}% · mode {STRAT['mode']} · up {up:.1f}h\ntracking {len(WALLETS)} wallets"})
        elif cmd == "/positions":
            if not st["open"]:
                tg("sendMessage", {"chat_id": cid, "text": "no open paper positions"})
            else:
                lines = [f"{p['side']} {esc(p['coin'])} ${p['notional']:,.0f} @ {p['entry']:g} ({esc(p['wallet'][:8])}…)" for p in list(st["open"].values())[:30]]
                tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text": "<b>Open ("+str(len(st['open']))+"):</b>\n"+"\n".join(lines)})
        elif cmd == "/pnl":
            gw = st.get("gross_win", 0); gl = st.get("gross_loss", 0)
            pf = gw / gl if gl > 0 else 0
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text":
                f"realized <b>${st['realized']:+,.2f}</b>\ngross win ${gw:,.0f} / gross loss ${gl:,.0f}\nprofit factor {pf:.2f} · trades {st['closed']}"})
        elif cmd == "/wallets":
            tg("sendMessage", {"chat_id": cid, "text": f"tracking {len(WALLETS)} vetted HL perp wallets (top-100 strict copytrade filter)"})
        elif cmd == "/strategy":
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text":
                f"mode <b>{STRAT['mode']}</b>\nsize {STRAT['frac']*100:.0f}% of bank/trade (cap {STRAT['per_trade_cap']*100:.0f}%)\nmax concurrent {STRAT['max_concurrent']}\nround-trip cost {STRAT['cost']*100:.2f}%\nsafe consensus k={STRAT['consensus_k']}"})
        elif cmd == "/mode":
            parts = text.lower().split()
            if len(parts) > 1 and parts[1] in ("growth", "safe"):
                STRAT["mode"] = parts[1]; tg("sendMessage", {"chat_id": cid, "text": f"mode set to {parts[1]}"})
            else:
                tg("sendMessage", {"chat_id": cid, "text": "usage: /mode growth|safe"})
        elif cmd == "/stop":
            st["paused"] = True; tg("sendMessage", {"chat_id": cid, "text": "⏸ paused — no new opens (existing positions still close)"})
        elif cmd == "/resume":
            st["paused"] = False; tg("sendMessage", {"chat_id": cid, "text": "▶️ resumed"})

# ---------------- main loop ----------------
MAX_BACKFILL_MS = 30 * 60 * 1000   # on restart, never replay >30min of history (avoid stale-trade flood)

def acquire_lock():
    """single-instance guard: exit if another copybot holds the lock (prevents watchdog double-start)."""
    if TEST_MODE:
        return None
    try:
        import fcntl
        fh = open(LOCK_P, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid())); fh.flush()
        return fh   # keep handle alive to hold the lock
    except Exception as e:
        log(f"another instance holds the lock ({e}); exiting")
        raise SystemExit(0)

def main():
    global _CHAT_IDS, recent_opens
    _lockfh = acquire_lock()
    st = load_state()
    now_ms = int(time.time() * 1000)
    floor_ms = now_ms - MAX_BACKFILL_MS
    for w in WALLETS:
        st["last_ms"][w] = max(st["last_ms"].get(w, now_ms), floor_ms)   # resume, cap replay to 30min
    _CHAT_IDS = list(st.get("chat_ids", []))
    recent_opens[:] = [tuple(x) for x in st.get("recent_opens", [])]     # restore consensus history
    save_state(st)
    log(f"copybot start: {len(WALLETS)} wallets, mode {STRAT['mode']}, bank ${st['bank']:.2f}")
    tg_send(f"🚀 <b>HyperCopy paper bot online</b>\n{len(WALLETS)} wallets · $1000 paper · mode {STRAT['mode']}\n/start then /status")
    cycle = 0
    SLICE = CFG.get("slice", 25)
    off = 0
    while True:
        try:
            try:
                handle_commands(st)
                _CHAT_IDS = list(st.get("chat_ids", []))
            except Exception as e:
                log(f"handle_commands err {e}")
            try:
                mids = get_mids()
            except Exception as e:
                log(f"get_mids err {e}"); mids = {}
            paused = st.get("paused", False)
            batch = WALLETS[off:off + SLICE]
            off = (off + SLICE) % max(len(WALLETS), 1)
            for w in batch:
                try:
                    last_ms = st["last_ms"].get(w, now_ms)
                    fills = get_fills_since(w, last_ms)   # inclusive; tid dedup handles same-ms overlap
                    process_wallet_fills(st, mids, w, fills, paused=paused)
                except Exception as e:
                    log(f"wallet loop err {w[:10]} {e}")
                time.sleep(0.2)
            if cycle % 40 == 0 and st["open"]:
                try:
                    reconcile(st, mids, int(time.time() * 1000))
                except Exception as e:
                    log(f"reconcile err {e}")
            st["recent_opens"] = recent_opens[-5000:]   # persist consensus history (match in-mem cap)
            try:
                save_state(st)
            except Exception as e:
                log(f"SAVE FAIL {e}")
                tg_send(f"⚠️ state save failed: {esc(e)}")
            cycle += 1
            if cycle % 20 == 0:
                log(f"cycle {cycle}: bank ${st['bank']:.2f} open {len(st['open'])} closed {st['closed']} off {off}")
        except Exception as e:
            log(f"loop error: {e}\n{traceback.format_exc()[:500]}")
            time.sleep(5)
        time.sleep(CFG.get("cycle_sleep", 30))

if __name__ == "__main__":
    main()
