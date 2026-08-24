#!/usr/bin/env python3
# backtest3.py v2 — RIGOROUS out-of-sample copytrade backtest (box 167). Fixes critic-E findings:
#  #1 heapq.heappop (was pop(0) on a heap -> stranded capital, garbage Sharpe/DD)
#  #2 position reconstruction in CONTRACTS via start_position (exact flat boundaries, no notional drift)
#  #3 full-calendar Sharpe padded SPLIT..test-end (not first..last exit)
#  #4 free-capital threshold fixed; latency haircut swept
#  survivorship removed (universe = train-only), capital-reserved sizing, positions entered post-SPLIT only.
import gzip, json, math, statistics as st, heapq
from collections import defaultdict

POS = "/home/blessed/hypeevm/out/positions_test.tsv.gz"
BANK0 = 1000.0
COST = 0.0007
MIN_NTL = 50.0
PCT_CAP = 1.5
SPLIT_TS = 1782000000    # 2026-06-21
EPS = 1e-9

def sdir(direction):
    if direction in ("Open Long", "Close Short", "Short > Long"): return +1
    if direction in ("Open Short", "Close Long", "Long > Short"): return -1
    return 0

# ---- load fills (ts,tid,wallet,coin,dir,sz,px,startpos,ntl,pnl) ----
fills = defaultdict(list)
with gzip.open(POS, "rt") as f:
    hdr = f.readline()
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 10:
            continue
        try:
            ts = int(p[0]); tid = int(p[1]) if p[1] not in ("", "\\N") else 0
            w = p[2]; coin = p[3]; direction = p[4]
            sz = float(p[5]); px = float(p[6]); sp = float(p[7]); pnl = float(p[9])
        except Exception:
            continue
        s = sdir(direction)
        if s == 0:
            continue
        fills[(w, coin)].append((ts, tid, s * sz, px, sp, pnl))

# ---- reconstruct episodes in CONTRACTS via start_position ----
positions = []   # {w, entry_ts, exit_ts, pct, entry_ntl}
for (w, coin), fl in fills.items():
    fl.sort(key=lambda x: (x[0], x[1]))
    entry_ts = None; entry_ntl = 0.0; realized = 0.0; open_ep = False
    for ts, tid, d, px, sp, pnl in fl:
        new = sp + d
        flat_before = abs(sp) < 1e-6
        flat_after = abs(new) < 1e-6
        reversal = (sp > 1e-6 and new < -1e-6) or (sp < -1e-6 and new > 1e-6)
        # (a) episode opens from flat
        if flat_before and not flat_after:
            entry_ts = ts; entry_ntl = abs(d) * px; realized = pnl; open_ep = True
            continue
        if not open_ep:
            # not tracking (started mid-position / opened before data window) — wait for a clean flat->open
            continue
        # (b) within an episode
        if reversal:
            realized += pnl                      # this fill closes the old side
            if entry_ntl >= MIN_NTL:
                positions.append({"w": w, "entry_ts": entry_ts, "exit_ts": ts,
                                  "pct": max(-3.0, min(PCT_CAP, realized / entry_ntl)), "entry_ntl": entry_ntl})
            # residual opens a new opposite episode
            entry_ts = ts; entry_ntl = abs(new) * px; realized = 0.0; open_ep = True
        elif flat_after:
            realized += pnl
            if entry_ntl >= MIN_NTL:
                positions.append({"w": w, "entry_ts": entry_ts, "exit_ts": ts,
                                  "pct": max(-3.0, min(PCT_CAP, realized / entry_ntl)), "entry_ntl": entry_ntl})
            entry_ts = None; entry_ntl = 0.0; realized = 0.0; open_ep = False
        else:
            realized += pnl
            if abs(new) > abs(sp):               # position grew -> add opening notional
                entry_ntl += abs(d) * px

positions = [p for p in positions if p["entry_ts"] >= SPLIT_TS]
positions.sort(key=lambda p: p["entry_ts"])
if not positions:
    print("NO test positions"); raise SystemExit(1)
TEST_END = max(p["exit_ts"] for p in positions)
tspan = (TEST_END - SPLIT_TS) / 86400
holds = [(p["exit_ts"] - p["entry_ts"]) / 60 for p in positions]
print(f"reconstructed test positions: {len(positions)}; span {tspan:.0f}d; "
      f"median hold {st.median(holds):.0f}min; base win-rate {sum(1 for p in positions if p['pct']>0)/len(positions):.2f}")

def simulate(frac, haircut, per_cap=0.25, max_conc=15):
    bank = BANK0; reserved = 0.0
    open_heap = []   # (exit_ts, notional, pct)
    daily = {}; wins = ntr = 0; peak = BANK0; maxdd = 0.0
    def release_until(now):
        nonlocal bank, reserved, wins, ntr, peak, maxdd
        while open_heap and open_heap[0][0] <= now:
            exit_ts, notional, pct = heapq.heappop(open_heap)
            pnl = notional * (pct - haircut - COST)
            bank += pnl; reserved -= notional
            ntr += 1; wins += 1 if pnl > 0 else 0
            peak = max(peak, bank); maxdd = max(maxdd, (peak - bank) / peak if peak > 0 else 0)
            daily[exit_ts // 86400] = bank
    for p in positions:
        release_until(p["entry_ts"])
        free = bank - reserved
        notional = min(frac * bank, per_cap * bank, free)
        if notional < 1 or len(open_heap) >= max_conc or bank <= 5:   # my paper position floor is $1, not the target's dust filter
            continue
        reserved += notional
        heapq.heappush(open_heap, (p["exit_ts"], notional, p["pct"]))
    release_until(TEST_END + 1)
    # full-calendar daily equity, padded SPLIT..TEST_END
    d0 = SPLIT_TS // 86400; d1 = TEST_END // 86400
    eq = []; last = BANK0
    for dd in range(d0, d1 + 1):
        if dd in daily: last = daily[dd]
        eq.append(last)
    rets = [eq[i]/eq[i-1]-1 for i in range(1, len(eq)) if eq[i-1] > 0]
    sharpe = (st.mean(rets)/st.pstdev(rets)*math.sqrt(365)) if len(rets) > 2 and st.pstdev(rets) > 0 else 0.0
    return {"final": round(bank, 2), "ret": round(100*(bank/BANK0-1), 1), "sharpe": round(sharpe, 2),
            "maxdd": round(100*maxdd, 1), "win": round(wins/ntr, 3) if ntr else 0, "trades": ntr}

print("\n=== 2%-of-bank (capital-reserved, heappop) — latency haircut sweep (OUT-OF-SAMPLE, train-selected) ===")
print(f"{'haircut':>8}{'final$':>9}{'ret%':>8}{'sharpe':>8}{'maxDD%':>8}{'win':>6}{'trades':>8}")
res = {}
for hc in [0.0, 0.0005, 0.0015, 0.003, 0.005]:
    r = simulate(0.02, hc); res[f"2pct_hc{int(hc*10000)}bps"] = r
    print(f"{hc*100:>7.2f}%{r['final']:>9,.0f}{r['ret']:>8}{r['sharpe']:>8}{r['maxdd']:>8}{r['win']:>6}{r['trades']:>8}")
print("\n=== sizing @ 15bps haircut ===")
print(f"{'frac':>8}{'final$':>9}{'ret%':>8}{'sharpe':>8}{'maxDD%':>8}{'win':>6}{'trades':>8}")
for fr in [0.01, 0.015, 0.02, 0.03]:
    r = simulate(fr, 0.0015); res[f"{int(fr*1000)}permil_hc15"] = r
    print(f"{fr*100:>7.1f}%{r['final']:>9,.0f}{r['ret']:>8}{r['sharpe']:>8}{r['maxdd']:>8}{r['win']:>6}{r['trades']:>8}")
json.dump({"results": res, "n_positions": len(positions), "span_days": round(tspan),
           "median_hold_min": round(st.median(holds))}, open("/home/blessed/hypeevm/out/backtest3_results.json", "w"), indent=1)
print("\nSaved backtest3_results.json")
