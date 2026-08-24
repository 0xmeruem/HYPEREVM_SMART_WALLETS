#!/usr/bin/env python3
# simulate_copybot.py — deterministic unit/integration tests for copybot core (no network).
import os, tempfile, json
os.environ["COPYBOT_TEST"] = "1"
os.environ["COPYBOT_BASE"] = tempfile.mkdtemp(prefix="copybot_test_")
import importlib.util, sys
spec = importlib.util.spec_from_file_location("copybot", os.path.join(os.path.dirname(__file__), "copybot.py"))
cb = importlib.util.module_from_spec(spec); sys.modules["copybot"] = cb; spec.loader.exec_module(cb)

PASS = 0; FAIL = 0; FAILS = []
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1; FAILS.append(name); print(f"  FAIL: {name}")

def fresh():
    return {"bank": 1000.0, "realized": 0.0, "open": {}, "last_ms": {}, "closed": 0, "wins": 0,
            "chat_ids": [], "tg_offset": 0, "started": 0, "gross_win": 0.0, "gross_loss": 0.0,
            "peak": 1000.0, "maxdd": 0.0, "history": []}
_TID = [0]
def fill(coin, direction, sz, px, sp, t=1000, tid=None):
    if tid is None:
        _TID[0] += 1; tid = _TID[0]
    return {"coin": coin, "dir": direction, "sz": str(sz), "px": str(px), "startPosition": str(sp), "time": t, "tid": tid}
MIDS = {"BTC": "100", "ETH": "50", "HYPE": "10", "DOGE": "1", "A": "100", "B": "100", "C": "100", "D": "100"}

# reset module strategy to known defaults per test
def setmode(m): cb.STRAT["mode"] = m
def reset_strat():
    cb.STRAT.update({"mode": "growth", "frac": 0.02, "per_trade_cap": 0.25, "max_concurrent": 15,
                     "cost": 0.0007, "consensus_k": 2, "consensus_window": 3600, "min_notional_target": 50.0,
                     "coins_blocklist": [], "max_loss_mult": 1.0, "history_cap": 500})
    cb.recent_opens.clear()

# 1. open+close long, price up -> profit
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw1", fill("BTC", "Open Long", 10, 100, 0))
check("1a open long creates 1 pos", len(st["open"]) == 1 and st["open"]["0xw1:BTC"]["side"] == "LONG")
check("1b entry = mid(100)", abs(st["open"]["0xw1:BTC"]["entry"] - 100) < 1e-6)
check("1c notional = 2% of 1000 = 20", abs(st["open"]["0xw1:BTC"]["notional"] - 20) < 1e-6)
cb.process_fill(st, {"BTC": "110"}, "0xw1", fill("BTC", "Close Long", 10, 110, 10))
check("1d close removes pos", len(st["open"]) == 0)
check("1e pnl ~ 20*(110/100-1) - 20*0.0007 = 1.986", abs(st["realized"] - (20*0.1 - 20*0.0007)) < 1e-6)
check("1f closed=1 wins=1", st["closed"] == 1 and st["wins"] == 1)

# 2. open+close short, price down -> profit
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw2", fill("BTC", "Open Short", 10, 100, 0))
check("2a short opens", st["open"]["0xw2:BTC"]["side"] == "SHORT")
cb.process_fill(st, {"BTC": "90"}, "0xw2", fill("BTC", "Close Short", 10, 90, -10))
check("2b short profit = 20*(1-90/100)-fee", abs(st["realized"] - (20*0.1 - 20*0.0007)) < 1e-6)

# 3. partial close HOLDS, full close exits
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw3", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, MIDS, "0xw3", fill("BTC", "Close Long", 4, 100, 10))   # new_pos 6 -> still long
check("3a partial close holds position", len(st["open"]) == 1 and st["closed"] == 0)
cb.process_fill(st, {"BTC": "105"}, "0xw3", fill("BTC", "Close Long", 6, 105, 6))  # new_pos 0 -> flat
check("3b full close exits", len(st["open"]) == 0 and st["closed"] == 1)

# 4. reversal Long > Short => close long, open short
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw4", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, {"BTC": "100"}, "0xw4", fill("BTC", "Long > Short", 15, 100, 10))  # 10-15 = -5 short
check("4a reversal closed long", st["closed"] == 1)
check("4b reversal opened short", len(st["open"]) == 1 and st["open"]["0xw4:BTC"]["side"] == "SHORT")

# 5. scale-in doesn't double-open
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw5", fill("BTC", "Open Long", 10, 100, 0))
n1 = st["open"]["0xw5:BTC"]["notional"]
cb.process_fill(st, MIDS, "0xw5", fill("BTC", "Open Long", 5, 100, 10))  # new_pos 15, still long
check("5 scale-in no re-open", len(st["open"]) == 1 and st["open"]["0xw5:BTC"]["notional"] == n1 and st["closed"] == 0)

# 6. missing mid on open -> skip
reset_strat(); st = fresh()
cb.process_fill(st, {"ETH": "50"}, "0xw6", fill("BTC", "Open Long", 10, 100, 0))  # BTC not in mids
check("6 missing mid open skipped", len(st["open"]) == 0)

# 7. missing mid on close -> fill_px proxy
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw7", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, {}, "0xw7", fill("BTC", "Close Long", 10, 108, 10))  # empty mids -> uses fill_px 108
check("7 close uses fill_px proxy (pnl>0)", st["closed"] == 1 and st["realized"] > 0)

# 8. short loss floored at -notional
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw8", fill("BTC", "Open Short", 10, 100, 0))
cb.process_fill(st, {"BTC": "300"}, "0xw8", fill("BTC", "Close Short", 10, 300, -10))  # price 3x
# unfloored gross = 20*(1-3) = -40; floored at -20; pnl = -20 - fee
check("8 short loss floored ~ -20 - fee", abs(st["realized"] - (-20 - 20*0.0007)) < 1e-6)

# 9. concurrency cap
reset_strat(); st = fresh(); cb.STRAT["max_concurrent"] = 3
for i in range(5):
    cb.process_fill(st, MIDS, f"0xc{i}", fill("BTC", "Open Long", 10, 100, 0))
check("9 concurrency cap enforced (<=3)", len(st["open"]) == 3)

# 10. min notional filter
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw10", fill("BTC", "Open Long", 0.1, 100, 0))  # notional 10 < 50
check("10 dust target open skipped", len(st["open"]) == 0)

# 11. pause blocks opens, allows close
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw11", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, MIDS, "0xw11b", fill("ETH", "Open Long", 10, 50, 0), paused=True)
check("11a pause blocks new open", "0xw11b:ETH" not in st["open"])
cb.process_fill(st, {"BTC": "110"}, "0xw11", fill("BTC", "Close Long", 10, 110, 10), paused=True)
check("11b pause still closes existing", st["closed"] == 1)

# 12. spot fills ignored
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw12", fill("BTC", "Buy", 10, 100, 0))
cb.process_fill(st, MIDS, "0xw12", fill("BTC", "Sell", 10, 100, 0))
check("12 spot buy/sell ignored", len(st["open"]) == 0)

# 13. consensus safe mode
reset_strat(); st = fresh(); setmode("safe")
cb.process_fill(st, MIDS, "0xca", fill("BTC", "Open Long", 10, 100, 0, t=1000))
check("13a safe: single wallet no open", len(st["open"]) == 0)
cb.process_fill(st, MIDS, "0xcb", fill("BTC", "Open Long", 10, 100, 0, t=2000))  # 2nd wallet same coin/side
check("13b safe: consensus-2 opens", len(st["open"]) == 1)
setmode("growth")

# 14. PnL precision (already 1e). check maxdd + peak update
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw14", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, {"BTC": "80"}, "0xw14", fill("BTC", "Close Long", 10, 80, 10))  # loss
check("14 maxdd recorded>0 after loss", st["maxdd"] > 0 and st["bank"] < 1000)

# 15. restart resume: save + reload keeps open positions
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw15", fill("BTC", "Open Long", 10, 100, 0))
cb.save_state(st); st2 = cb.load_state()
check("15 state persists open pos", "0xw15:BTC" in st2["open"] and st2["bank"] == st["bank"])

# 16. bank ruin guard: tiny bank -> no open
reset_strat(); st = fresh(); st["bank"] = 3.0
cb.process_fill(st, MIDS, "0xw16", fill("BTC", "Open Long", 10, 100, 0))
check("16 ruin guard blocks open", len(st["open"]) == 0)

# 17. history cap
reset_strat(); st = fresh(); cb.STRAT["history_cap"] = 5
for i in range(10):
    cb.process_fill(st, MIDS, f"0xh{i}", fill("BTC", "Open Long", 10, 100, 0))
    cb.process_fill(st, {"BTC": "101"}, f"0xh{i}", fill("BTC", "Close Long", 10, 101, 10))
check("17 history capped at 5", len(st["history"]) == 5)

# 18. blocklist
reset_strat(); st = fresh(); cb.STRAT["coins_blocklist"] = ["DOGE"]
cb.process_fill(st, MIDS, "0xw18", fill("DOGE", "Open Long", 100, 1, 0))
check("18 blocklisted coin skipped", len(st["open"]) == 0)

# 19. two coins same wallet independent
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw19", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, MIDS, "0xw19", fill("ETH", "Open Short", 10, 50, 0))
check("19 same wallet two coins -> 2 pos", len(st["open"]) == 2)

# 20. close without open is no-op
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw20", fill("BTC", "Close Long", 10, 100, 10))
check("20 close with no open = no-op", st["closed"] == 0 and len(st["open"]) == 0)

# 21. bot started mid-position: first seen fill is a PARTIAL close (still long) -> must NOT open
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw21", fill("BTC", "Close Long", 4, 100, 10))  # startPos 10, new_pos 6 LONG, but no paper pos
check("21 partial close w/o our pos does NOT open (no false entry as target exits)", len(st["open"]) == 0 and st["closed"] == 0)

# 22. bot started mid-position: first seen is target ADD via Open Long (startPos already 5) -> we DO open
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw22", fill("BTC", "Open Long", 5, 100, 5))  # open action, new_pos 10
check("22 open-action while target already in pos -> we enter", len(st["open"]) == 1)

# 23. reversal at concurrency cap: close frees slot, reopen opposite succeeds
reset_strat(); st = fresh(); cb.STRAT["max_concurrent"] = 1
cb.process_fill(st, MIDS, "0xw23", fill("BTC", "Open Long", 10, 100, 0))
check("23a at cap 1 with 1 open", len(st["open"]) == 1)
cb.process_fill(st, {"BTC": "100"}, "0xw23", fill("BTC", "Long > Short", 15, 100, 10))  # reverse
check("23b reversal at cap: closed long AND opened short", st["closed"] == 1 and st["open"].get("0xw23:BTC", {}).get("side") == "SHORT")

# 24. over-close (sz>startPosition) labeled Close Long: close only, no auto-short
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw24", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, {"BTC": "100"}, "0xw24", fill("BTC", "Close Long", 15, 100, 10))  # new_pos -5 but Close dir
check("24 over-close closes, does NOT open short", st["closed"] == 1 and len(st["open"]) == 0)

# 25. sz=0 fill ignored
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xw25", fill("BTC", "Open Long", 0, 100, 0))
check("25 zero-size fill ignored", len(st["open"]) == 0)

# 26. reconcile closes orphan (target flat), keeps matched, fail-safe on API error
reset_strat(); st = fresh()
cb.process_fill(st, MIDS, "0xr1", fill("BTC", "Open Long", 10, 100, 0))
cb.process_fill(st, MIDS, "0xr2", fill("ETH", "Open Short", 10, 50, 0))
_orig = cb.get_positions
cb.get_positions = lambda w: (({}, True) if w == "0xr1" else ({"ETH": -10.0}, True))  # r1 flat, r2 still short
cb.reconcile(st, {"BTC": "100", "ETH": "50"}, 2000)
check("26a reconcile closed orphan r1", "0xr1:BTC" not in st["open"])
check("26b reconcile kept matched r2", "0xr2:ETH" in st["open"])
# fail-safe: API error -> keep
cb.get_positions = lambda w: ({}, False)
cb.reconcile(st, {"ETH": "50"}, 3000)
check("26c reconcile fail-safe keeps r2 on API error", "0xr2:ETH" in st["open"])
# orphan by reversal: target now opposite side -> close
cb.get_positions = lambda w: ({"ETH": +10.0}, True)  # r2 flipped to LONG, we hold SHORT
cb.reconcile(st, {"ETH": "50"}, 4000)
check("26d reconcile closes reversed orphan", "0xr2:ETH" not in st["open"])
cb.get_positions = _orig

# 27. backfill cap logic: max(saved, now-30min)
now_ms = 100_000_000
floor = now_ms - 30*60*1000
check("27a old last_ms floored", max(floor, now_ms - 10**9) == floor)
check("27b recent last_ms kept", max(floor, now_ms - 1000) == now_ms - 1000)

# 28. LOOP: same-ms open+close given in REVERSE order -> tid restores chronological -> net flat
reset_strat(); st = fresh()
o = fill("BTC", "Open Long", 10, 100, 0, t=5000, tid=101)
c = fill("BTC", "Close Long", 10, 110, 10, t=5000, tid=102)   # same ms, higher tid = later
cb.process_wallet_fills(st, {"BTC": "110"}, "0xL1", [c, o])    # deliberately reversed order
check("28 same-ms reversed input -> tid sorts -> flat (no phantom)", len(st["open"]) == 0 and st["closed"] == 1)

# 29. LOOP: reprocessing the same batch (same tids) is idempotent
reset_strat(); st = fresh()
o = fill("ETH", "Open Long", 10, 50, 0, t=6000, tid=201)
cb.process_wallet_fills(st, MIDS, "0xL2", [o])
check("29a first process opens", len(st["open"]) == 1)
cb.process_wallet_fills(st, MIDS, "0xL2", [o])   # replay same tid
check("29b replay same tid = no double-open", len(st["open"]) == 1)

# 30. LOOP: cross-poll overlap — new fill with higher tid processed, old skipped
reset_strat(); st = fresh()
o = fill("ETH", "Open Long", 10, 50, 0, t=7000, tid=301)
c = fill("ETH", "Close Long", 10, 55, 10, t=7000, tid=302)
cb.process_wallet_fills(st, MIDS, "0xL3", [o])          # poll 1: only open indexed
check("30a poll1 opened", len(st["open"]) == 1)
cb.process_wallet_fills(st, {"ETH": "55"}, "0xL3", [o, c])  # poll2: overlap returns both; o skipped by tid, c closes
check("30b poll2 same-ms close applied via tid (not skipped)", len(st["open"]) == 0 and st["closed"] == 1)

# 31. consensus does NOT count a DUST target open (< min_notional), but counts real opens
reset_strat(); st = fresh(); setmode("safe")
cb.process_fill(st, MIDS, "0xcx1", fill("BTC", "Open Long", 0.1, 100, 0, t=1000))  # $10 dust -> not counted
cb.process_fill(st, MIDS, "0xcx2", fill("BTC", "Open Long", 10, 100, 0, t=2000))   # real; consensus={cx2}=1 <2
check("31a dust not counted -> only 1 real -> no open", len(st["open"]) == 0)
cb.process_fill(st, MIDS, "0xcx3", fill("BTC", "Open Long", 10, 100, 0, t=3000))   # consensus={cx2,cx3}=2 -> open
check("31b two real opens reach consensus-2 -> open", len(st["open"]) == 1)
setmode("growth")

# 32. state backup: corrupt state.json recovers from .bak
reset_strat(); st = fresh(); st["bank"] = 1234.5
cb.save_state(st)                 # writes state.json
st["bank"] = 5678.9; cb.save_state(st)   # rolls prev to .bak, writes new
open(cb.STATE_P, "w").write("{corrupt")  # corrupt primary
st3 = cb.load_state()
check("32 corrupt primary recovers from .bak", abs(st3["bank"] - 1234.5) < 1e-6)

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
if FAILS:
    print("FAILED:", FAILS); sys.exit(1)
print("ALL TESTS PASS")
