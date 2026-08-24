#!/usr/bin/env python3
# stress_copybot.py — fuzz/soak test: feed 20k adversarial fills, assert no crash + sane invariants.
import os, tempfile
os.environ["COPYBOT_TEST"] = "1"
os.environ["COPYBOT_BASE"] = tempfile.mkdtemp(prefix="copybot_stress_")
import importlib.util, sys
spec = importlib.util.spec_from_file_location("copybot", os.path.join(os.path.dirname(__file__), "copybot.py"))
cb = importlib.util.module_from_spec(spec); sys.modules["copybot"] = cb; spec.loader.exec_module(cb)

# deterministic PRNG (no Math.random dependency issues) — simple LCG
class R:
    def __init__(s, seed): s.x = seed
    def nxt(s): s.x = (s.x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1); return s.x
    def pick(s, seq): return seq[s.nxt() % len(seq)]
    def rng(s, a, b): return a + (s.nxt() % (b - a + 1))
rnd = R(12345)

cb.STRAT.update({"mode": "growth", "frac": 0.02, "per_trade_cap": 0.25, "max_concurrent": 15, "cost": 0.0007,
                 "min_notional_target": 50.0, "coins_blocklist": [], "max_loss_mult": 1.0, "history_cap": 500})
st = cb._default_state()
COINS = ["BTC", "ETH", "HYPE", "SOL", "DOGE", "xyz:SNDK", "WIF", "kPEPE"]
WAL = [f"0x{i:040x}" for i in range(30)]
DIRS = ["Open Long", "Open Short", "Close Long", "Close Short", "Long > Short", "Short > Long", "Buy", "Sell", "Funding"]

# maintain a "true" signed position per (wallet,coin) so we can craft realistic startPosition
truth = {}
def mids_for(t):
    # prices wander; occasionally drop a coin from mids
    m = {}
    for c in COINS:
        base = {"BTC": 100, "ETH": 50, "HYPE": 10, "SOL": 90, "DOGE": 1, "xyz:SNDK": 5, "WIF": 2, "kPEPE": 0.01}[c]
        wig = 1 + ((rnd.nxt() % 2000) - 1000) / 10000.0
        if rnd.nxt() % 20 != 0:   # 5% chance coin missing from mids
            m[c] = str(round(base * wig, 6))
    return m

tid = 0; t = 1_000_000_000_000
crashes = 0
for i in range(20000):
    tid += 1
    if rnd.nxt() % 3 == 0:
        t += rnd.rng(0, 3)      # cluster same/near ms
    else:
        t += rnd.rng(1, 5000)
    w = rnd.pick(WAL); coin = rnd.pick(COINS); direction = rnd.pick(DIRS)
    k = (w, coin)
    pos = truth.get(k, 0.0)
    sz = rnd.rng(1, 500) / 10.0
    # craft startPosition consistent with dir where possible
    d = cb.signed_delta(direction, sz)
    sp = pos
    fill = {"coin": coin, "dir": direction, "sz": str(sz), "px": str(rnd.rng(1, 100000) / 100.0),
            "startPosition": str(sp), "time": t, "tid": tid}
    # occasionally inject malformed fills
    r = rnd.nxt() % 40
    if r == 0: del fill["startPosition"]
    elif r == 1: fill["sz"] = "notanumber"
    elif r == 2: fill["px"] = None
    elif r == 3: del fill["coin"]
    elif r == 4: fill["tid"] = 0
    elif r == 5: fill["dir"] = "Weird Thing"
    mids = mids_for(t)
    try:
        cb.process_wallet_fills(st, mids, w, [fill])
    except Exception as e:
        crashes += 1
        if crashes <= 5:
            print("CRASH:", e, "on", fill)
    if d != 0 and "startPosition" in fill:
        truth[k] = pos + d

# invariants
ok = True
def inv(name, cond):
    global ok
    if not cond: ok = False; print("INVARIANT FAIL:", name)

inv("no crashes", crashes == 0)
inv("bank finite", st["bank"] == st["bank"] and abs(st["bank"]) < 1e12)
inv("bank not absurdly negative", st["bank"] > -1e6)
inv("open positions within cap", len(st["open"]) <= cb.STRAT["max_concurrent"])
inv("closed >= wins", st["closed"] >= st["wins"])
inv("history capped", len(st["history"]) <= cb.STRAT["history_cap"])
inv("every open pos well-formed", all(set(p) >= {"coin", "side", "entry", "notional", "wallet", "open_ts"} and p["entry"] > 0 and p["notional"] > 0 for p in st["open"].values()))
inv("gross_win/gross_loss non-negative", st["gross_win"] >= 0 and st["gross_loss"] >= 0)
inv("realized ~ bank-1000 within fp", abs(st["realized"] - (st["bank"] - 1000.0)) < 1.0)

# now reconcile everything to flat using a stub (target all flat) -> must not crash, closes all (2-strike)
cb.get_positions = lambda w: ({}, True)
try:
    cb.reconcile(st, mids_for(t), t + 1)      # strike 1
    cb.reconcile(st, mids_for(t), t + 2)      # strike 2 -> close
    inv("reconcile clears all to flat (2-strike)", len(st["open"]) == 0)
except Exception as e:
    ok = False; print("reconcile crash:", e)

# save/reload roundtrip
cb.save_state(st); st2 = cb.load_state()
inv("state roundtrips", abs(st2["bank"] - st["bank"]) < 1e-6)

print(f"\nprocessed 20000 adversarial fills · crashes={crashes} · final bank ${st['bank']:.2f} · closed {st['closed']}")
print("STRESS PASS" if ok else "STRESS FAIL")
sys.exit(0 if ok else 1)
