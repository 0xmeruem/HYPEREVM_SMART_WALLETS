#!/usr/bin/env python3
# backtest2.py — HONEST copytrade backtest with train/test split (removes survivorship) +
# realistic $1000 sizing (fixed-notional expectancy + capped fractional, no compounding fantasy).
import gzip, json, math, statistics as st
from collections import defaultdict

CLOSES = "/home/blessed/hypeevm/out/closes_top100.tsv.gz"
BANK0 = 1000.0
COST = 0.0007
MIN_NTL = 50.0
PCT_CAP = 1.5
SPLIT_TS = 1782000000   # ~2026-06-20 -> train before, test after (out-of-sample)

# aggregate partial closes into position exits (30-min bucket)
raw = defaultdict(lambda: [0.0, 0.0, None])
with gzip.open(CLOSES, "rt") as f:
    f.readline()
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 6: continue
        ts = int(p[0]); w = p[1]; coin = p[2]; d = p[3]; ntl = float(p[4]); pnl = float(p[5])
        k = (w, coin, d, ts // 1800)
        a = raw[k]; a[0] += ntl; a[1] += pnl
        if a[2] is None or ts < a[2]: a[2] = ts
allt = []
for (w, coin, d, hb), a in raw.items():
    ntl, pnl, ts = a
    if ntl < MIN_NTL: continue
    pct = max(-PCT_CAP, min(PCT_CAP, pnl / ntl))
    allt.append({"ts": ts, "w": w, "coin": coin, "dir": d, "ntl": ntl, "pct": pct})
allt.sort(key=lambda t: t["ts"])
train = [t for t in allt if t["ts"] < SPLIT_TS]
test = [t for t in allt if t["ts"] >= SPLIT_TS]
print(f"trades: {len(allt)} (train {len(train)} / test {len(test)})")
tspan = (test[-1]["ts"] - test[0]["ts"]) / 86400
print(f"test span {tspan:.0f} days")

# ---- select wallets on TRAIN ONLY (out-of-sample discipline) ----
tw = defaultdict(lambda: [0, 0, 0.0])  # wallet -> [n, wins, sum_pct]
for t in train:
    a = tw[t["w"]]; a[0] += 1; a[1] += 1 if t["pct"] > 0 else 0; a[2] += t["pct"]
sel = {}
for w, a in tw.items():
    n, wins, sp = a
    if n >= 15 and (wins / n) >= 0.5 and sp > 0:   # had real edge in-train
        sel[w] = {"win": wins / n, "avgpct": sp / n, "n": n}
print(f"wallets with TRAIN edge (>=15 trades, win>=0.5, sum_pct>0): {len(sel)}")
TOPSEL = set(sorted(sel, key=lambda w: -sel[w]["avgpct"] * sel[w]["win"])[:30])

# consensus map on test
byslot = defaultdict(set)
for t in test:
    byslot[(t["coin"], t["dir"], t["ts"] // 3600)].add(t["w"])

def eval_stream(events, size_fn, concurrency_cap=None):
    """size_fn(t, bank)-> notional$ for this trade (fixed or fractional). Concurrency cap limits open slots."""
    bank = BANK0; peak = BANK0; maxdd = 0.0
    daily = {}; wins = ntr = 0; fees = 0.0; pnl_sum = 0.0
    open_slots = []  # (release_ts) approximation: hold 6h
    for t in events:
        if t["w"] not in sel:
            continue
        # concurrency: release expired slots (assume 6h hold), skip if full
        if concurrency_cap is not None:
            open_slots = [r for r in open_slots if r > t["ts"]]
            if len(open_slots) >= concurrency_cap:
                continue
            open_slots.append(t["ts"] + 21600)
        ntl = size_fn(t, bank)
        if ntl <= 0: continue
        ntl = min(ntl, bank * 0.25)   # never risk >25% bank on one trade
        pnl = ntl * t["pct"] - ntl * COST
        fees += ntl * COST; bank += pnl; pnl_sum += pnl
        ntr += 1; wins += 1 if pnl > 0 else 0
        peak = max(peak, bank); maxdd = max(maxdd, (peak - bank) / peak)
        daily[t["ts"] // 86400] = bank
        if bank <= 5: break
    keys = sorted(daily); eq = [daily[k] for k in keys]
    rets = [eq[i]/eq[i-1]-1 for i in range(1, len(eq))]
    sharpe = (st.mean(rets)/st.pstdev(rets)*math.sqrt(365)) if len(rets) > 2 and st.pstdev(rets) > 0 else 0.0
    return {"final": round(bank, 2), "ret_pct": round(100*(bank/BANK0-1), 1), "sharpe": round(sharpe, 2),
            "maxdd_pct": round(100*maxdd, 1), "winrate": round(wins/ntr, 3) if ntr else 0,
            "trades": ntr, "fees": round(fees, 1), "avg_pnl_per_trade": round(pnl_sum/ntr, 3) if ntr else 0}

def consensus_ok(t, k=2):
    return len(byslot[(t["coin"], t["dir"], t["ts"] // 3600)]) >= k

STRATS = {
    # fixed-notional (no compounding) — realistic expectancy for a $1000 bank
    "F01_fixed_$20":            (lambda t, b: 20.0, 20),
    "F02_fixed_$40":            (lambda t, b: 40.0, 12),
    "F03_fixed_$25_consensus2": (lambda t, b: 25.0 if consensus_ok(t, 2) else 0.0, 20),
    "F04_fixed_$40_topsel":     (lambda t, b: 40.0 if t["w"] in TOPSEL else 0.0, 12),
    # capped fractional (% of bank, but per-trade<=25% and concurrency-capped)
    "R05_frac_1pct":            (lambda t, b: 0.01 * b, 20),
    "R06_frac_2pct":            (lambda t, b: 0.02 * b, 15),
    "R07_frac_2pct_consensus2": (lambda t, b: 0.02 * b if consensus_ok(t, 2) else 0.0, 15),
    "R08_frac_3pct_topsel":     (lambda t, b: 0.03 * b if t["w"] in TOPSEL else 0.0, 12),
    "R09_frac_1.5pct_conc10":   (lambda t, b: 0.015 * b, 10),
    "R10_frac_2pct_consensus3": (lambda t, b: 0.02 * b if consensus_ok(t, 3) else 0.0, 12),
}
res = {}
for name, (fn, cap) in STRATS.items():
    res[name] = eval_stream(test, fn, concurrency_cap=cap)

def score(r):
    if r["final"] <= 50: return -999
    return r["sharpe"] * 1.5 + math.log10(max(r["final"]/BANK0, 0.01)) * 4 - r["maxdd_pct"] / 25
ranked = sorted(res.items(), key=lambda kv: -score(kv[1]))
print(f"\n{'strategy':<28}{'final$':>10}{'ret%':>8}{'sharpe':>8}{'maxDD%':>8}{'win':>6}{'trades':>8}{'score':>7}")
for name, r in ranked:
    print(f"{name:<28}{r['final']:>10,.0f}{r['ret_pct']:>8}{r['sharpe']:>8}{r['maxdd_pct']:>8}{r['winrate']:>6}{r['trades']:>8}{score(r):>7.1f}")
json.dump({"results": res, "ranked": [n for n, _ in ranked], "test_days": round(tspan),
           "sel_wallets": len(sel), "test_trades": len(test)},
          open("/home/blessed/hypeevm/out/backtest2_results.json", "w"), indent=1)
print("\nBEST (out-of-sample):", ranked[0][0], ranked[0][1])
