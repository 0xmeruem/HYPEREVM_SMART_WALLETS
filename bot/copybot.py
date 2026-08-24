#!/usr/bin/env python3
# copybot.py — paper copytrade bot for Hyperliquid (box 167).
# Watches N target wallets' fills; mirrors Open/Close into a $1000 PAPER bank at % of bank,
# marks paper PnL at live HL mid, reports to Telegram. NO real orders (add HL agent key to go live).
import json, os, time, urllib.request, urllib.parse, threading, traceback
import datetime as dt

BASE = "/home/blessed/hypeevm/copybot"
os.makedirs(BASE, exist_ok=True)
STATE_P = os.path.join(BASE, "state.json")
LOG_P = os.path.join(BASE, "copybot.log")
CFG = json.load(open(os.path.join(BASE, "config.json")))
TG_TOKEN = CFG["tg_token"]
WALLETS = [w.lower() for w in CFG["wallets"]]
WMETA = CFG.get("wallet_meta", {})

# ---------------- strategy config ----------------
STRAT = {
    "mode": CFG.get("mode", "growth"),   # 'growth' (2% every trade) | 'safe' (consensus-2)
    "frac": 0.02,                         # fraction of bank per copied trade
    "per_trade_cap": 0.25,                # never risk >25% bank on one paper trade
    "max_concurrent": 15,
    "cost": 0.0007,                       # round-trip taker+slippage on notional
    "consensus_window": 3600,             # sec, for safe mode
    "consensus_k": 2,
    "min_notional_target": 50.0,          # ignore target dust opens
    "coins_blocklist": [],                # optionally skip illiquid coins
}
BANK0 = 1000.0

def log(m):
    line = f"{dt.datetime.utcnow().isoformat()}Z {m}"
    print(line, flush=True)
    try:
        open(LOG_P, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass

# ---------------- HL API ----------------
def hl_info(body, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
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
        return hl_info({"type": "userFillsByTime", "user": w, "startTime": int(start_ms)})
    except Exception as e:
        log(f"userFills fail {w[:10]} {e}"); return []

# ---------------- Telegram ----------------
def tg(method, params):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log(f"tg {method} fail {e}"); return {}

def tg_send(text):
    st = load_state()
    for cid in st.get("chat_ids", []):
        tg("sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})

# ---------------- state ----------------
_lock = threading.Lock()
def load_state():
    if os.path.exists(STATE_P):
        return json.load(open(STATE_P))
    return {"bank": BANK0, "realized": 0.0, "open": {}, "last_ms": {}, "closed": 0, "wins": 0,
            "chat_ids": [], "tg_offset": 0, "started": time.time(), "gross_win": 0.0, "gross_loss": 0.0,
            "peak": BANK0, "maxdd": 0.0, "history": []}
def save_state(st):
    tmp = STATE_P + ".tmp"
    json.dump(st, open(tmp, "w"), indent=0)
    os.replace(tmp, STATE_P)

# ---------------- consensus tracker ----------------
recent_opens = []  # (ts, coin, dir, wallet)
def consensus_count(coin, direction, now_ms):
    cutoff = now_ms - STRAT["consensus_window"] * 1000
    return len({w for (ts, c, d, w) in recent_opens if c == coin and d == direction and ts >= cutoff})

def mid_of(mids, coin):
    v = mids.get(coin)
    try:
        return float(v) if v is not None else None
    except Exception:
        return None

# ---------------- core: process a wallet's new fills ----------------
def process_fill(st, mids, w, f):
    coin = f.get("coin"); direction = f.get("dir", ""); pxf = f.get("px")
    try:
        fill_px = float(pxf)
    except Exception:
        return
    try:
        sz = abs(float(f.get("sz", 0)))
    except Exception:
        sz = 0
    tgt_notional = sz * fill_px
    now_ms = int(f.get("time", time.time() * 1000))
    key = f"{w}:{coin}"
    mid = mid_of(mids, coin) or fill_px  # fall back to fill px if mid missing

    if direction in ("Open Long", "Open Short"):
        recent_opens.append((now_ms, coin, direction, w))
        if len(recent_opens) > 5000:
            del recent_opens[:2000]
        if key in st["open"]:
            return  # already mirroring this wallet+coin position
        if tgt_notional < STRAT["min_notional_target"]:
            return
        if coin in STRAT["coins_blocklist"]:
            return
        if len(st["open"]) >= STRAT["max_concurrent"]:
            return
        if STRAT["mode"] == "safe":
            if consensus_count(coin, direction, now_ms) < STRAT["consensus_k"]:
                return
        notional = min(STRAT["frac"] * st["bank"], STRAT["per_trade_cap"] * st["bank"])
        if notional < 1:
            return
        side = "LONG" if direction == "Open Long" else "SHORT"
        st["open"][key] = {"coin": coin, "side": side, "entry": mid, "notional": round(notional, 2),
                           "wallet": w, "open_ts": now_ms}
        wl = WMETA.get(w, {})
        tg_send(f"🟢 <b>OPEN {side} {coin}</b>\n${notional:,.0f} @ {mid:g}\ncopy of <code>{w[:10]}…</code> (pnl ${wl.get('pnl',0):,})\nbank ${st['bank']:,.0f} · open {len(st['open'])}/{STRAT['max_concurrent']}")
        log(f"OPEN {side} {coin} ${notional:.0f} @ {mid} copy {w[:10]}")

    elif direction in ("Close Long", "Close Short"):
        pos = st["open"].get(key)
        if not pos:
            return
        entry = pos["entry"]; notional = pos["notional"]
        if pos["side"] == "LONG":
            gross = notional * (mid / entry - 1)
        else:
            gross = notional * (1 - mid / entry)
        fee = notional * STRAT["cost"]
        pnl = gross - fee
        st["bank"] += pnl
        st["realized"] += pnl
        st["closed"] += 1
        st["wins"] += 1 if pnl > 0 else 0
        if pnl > 0: st["gross_win"] += pnl
        else: st["gross_loss"] += -pnl
        st["peak"] = max(st.get("peak", BANK0), st["bank"])
        dd = (st["peak"] - st["bank"]) / st["peak"] if st["peak"] > 0 else 0
        st["maxdd"] = max(st.get("maxdd", 0), dd)
        hold_m = (now_ms - pos["open_ts"]) / 60000
        st.setdefault("history", []).append({"coin": coin, "side": pos["side"], "pnl": round(pnl, 3),
                                             "ts": now_ms, "hold_min": round(hold_m, 1)})
        del st["open"][key]
        emoji = "✅" if pnl > 0 else "🔻"
        wr = st["wins"] / st["closed"] if st["closed"] else 0
        tg_send(f"{emoji} <b>CLOSE {pos['side']} {coin}</b>  {pnl:+,.2f}$\n{notional:,.0f}$ {entry:g}→{mid:g} · held {hold_m:.0f}m\n<b>bank ${st['bank']:,.2f}</b> ({(st['bank']/BANK0-1)*100:+.1f}%) · realized ${st['realized']:+,.0f} · WR {wr*100:.0f}% ({st['closed']})")
        log(f"CLOSE {pos['side']} {coin} pnl {pnl:+.2f} bank {st['bank']:.2f}")

# ---------------- Telegram command handler ----------------
HELP = ("🤖 <b>HyperCopy paper bot</b>\n"
        "/status – bank, PnL, drawdown\n/positions – open paper trades\n/pnl – realized breakdown\n"
        "/wallets – how many targets tracked\n/strategy – show mode (growth/safe)\n"
        "/mode growth|safe – switch sizing mode\n/stop – pause new opens\n/resume – resume\n/help – this")

def handle_commands(st):
    upd = tg("getUpdates", {"offset": st.get("tg_offset", 0), "timeout": 0})
    if not upd.get("ok"):
        return
    for u in upd.get("result", []):
        st["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message") or {}
        cid = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not cid:
            continue
        if cid not in st.get("chat_ids", []):
            st.setdefault("chat_ids", []).append(cid)
        cmd = text.lower().split()[0] if text else ""
        if cmd in ("/start", "/help"):
            tg("sendMessage", {"chat_id": cid, "text": HELP + f"\n\nTracking {len(WALLETS)} wallets · bank ${st['bank']:,.2f} · mode {STRAT['mode']}", "parse_mode": "HTML"})
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
                lines = []
                for k, p in list(st["open"].items())[:30]:
                    lines.append(f"{p['side']} {p['coin']} ${p['notional']:,.0f} @ {p['entry']:g} ({p['wallet'][:8]}…)")
                tg("sendMessage", {"chat_id": cid, "text": "<b>Open ("+str(len(st['open']))+"):</b>\n"+"\n".join(lines), "parse_mode": "HTML"})
        elif cmd == "/pnl":
            gw = st.get("gross_win", 0); gl = st.get("gross_loss", 0)
            pf = gw / gl if gl > 0 else 0
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text":
                f"realized <b>${st['realized']:+,.2f}</b>\ngross win ${gw:,.0f} / gross loss ${gl:,.0f}\nprofit factor {pf:.2f} · trades {st['closed']}"})
        elif cmd == "/wallets":
            tg("sendMessage", {"chat_id": cid, "text": f"tracking {len(WALLETS)} vetted HL perp wallets (top-100 by strict copytrade filter)"})
        elif cmd == "/strategy":
            tg("sendMessage", {"chat_id": cid, "parse_mode": "HTML", "text":
                f"mode <b>{STRAT['mode']}</b>\nsize {STRAT['frac']*100:.0f}% of bank/trade (cap {STRAT['per_trade_cap']*100:.0f}%)\nmax concurrent {STRAT['max_concurrent']}\nround-trip cost {STRAT['cost']*100:.2f}%\nsafe-mode consensus k={STRAT['consensus_k']}"})
        elif cmd == "/mode":
            parts = text.split()
            if len(parts) > 1 and parts[1] in ("growth", "safe"):
                STRAT["mode"] = parts[1]
                tg("sendMessage", {"chat_id": cid, "text": f"mode set to {parts[1]}"})
            else:
                tg("sendMessage", {"chat_id": cid, "text": "usage: /mode growth|safe"})
        elif cmd == "/stop":
            st["paused"] = True; tg("sendMessage", {"chat_id": cid, "text": "⏸ paused — no new opens (existing positions still close)"})
        elif cmd == "/resume":
            st["paused"] = False; tg("sendMessage", {"chat_id": cid, "text": "▶️ resumed"})

# ---------------- main loop ----------------
def main():
    st = load_state()
    # first run: don't backfill history — start from now
    now_ms = int(time.time() * 1000)
    for w in WALLETS:
        st["last_ms"].setdefault(w, now_ms)
    save_state(st)
    log(f"copybot start: {len(WALLETS)} wallets, mode {STRAT['mode']}, bank ${st['bank']:.2f}")
    tg_send(f"🚀 <b>HyperCopy paper bot online</b>\n{len(WALLETS)} wallets · $1000 paper · mode {STRAT['mode']} (2%/trade)\nsend /start then /status")
    cycle = 0
    SLICE = CFG.get("slice", 25)          # wallets polled per cycle (HL rate-limit safe)
    off = 0
    while True:
        try:
            handle_commands(st)
            mids = get_mids()
            paused = st.get("paused", False)
            batch = WALLETS[off:off + SLICE]
            off = (off + SLICE) % max(len(WALLETS), 1)
            for w in batch:
                last = st["last_ms"].get(w, now_ms)
                fills = get_fills_since(w, last + 1)
                if fills:
                    fills = sorted(fills, key=lambda f: f.get("time", 0))
                    for f in fills:
                        t = int(f.get("time", 0))
                        if t <= last:
                            continue
                        if not paused or f.get("dir", "").startswith("Close"):
                            process_fill(st, mids, w, f)
                        st["last_ms"][w] = max(st["last_ms"].get(w, 0), t)
                time.sleep(0.2)
            save_state(st)
            cycle += 1
            if cycle % 20 == 0:
                log(f"cycle {cycle}: bank ${st['bank']:.2f} open {len(st['open'])} closed {st['closed']} off {off}")
        except Exception as e:
            log(f"loop error: {e}\n{traceback.format_exc()[:500]}")
            time.sleep(5)
        time.sleep(CFG.get("cycle_sleep", 30))

if __name__ == "__main__":
    main()
