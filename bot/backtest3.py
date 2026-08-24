#!/usr/bin/env python3
# backtest3.py — RIGOROUS out-of-sample copytrade backtest (box 167), addressing critic-C findings:
#  - universe selected on TRAIN-only stats (no survivorship): input positions are for train_universe
#  - position reconstruction (entry/exit ts) from all perp fills; pct = target realized pnl / entry notional
#  - CAPITAL-RESERVED sizing: size off FREE capital, reservation held over the real hold interval
#  - LATENCY/slippage haircut sweep (I enter AFTER the target as a taker)
#  - FULL-CALENDAR daily equity for Sharpe (carry bank on flat days) — no days-with-trades-only inflation
#  - report the user's 2%-of-bank strategy on TEST; do not crown a strategy by a degenerate score
import gzip, json, math, statistics as st, datetime as dt
from collections import defaultdict

POS = "/home/blessed/hypeevm/out/positions_test.tsv.gz"
BANK0 = 1000.0
COST = 0.0007
MIN_NTL = 50.0
PCT_CAP = 1.5
SPLIT_TS = 1782000000   # 2026-06-21; test = fills strictly after this

# ---- load fills, reconstruct positions per wallet+coin (flat -> ... -> flat episodes) ----
def sdelta(direction, ntl):
    if direction in ("Open Long", "Close Short", "Short > Long"):
        return +ntl
    if direction in ("Open Short", "Close Long", "Long > Short"):
        return -ntl
    return 0.0

fills = defaultdict(list)   # (wallet,coin) -> [(ts,tid,dir,ntl,pnl)]
with gzip.open(POS, "rt") as f:
    f.readline()
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 7:
            continue
        ts = int(p[0]); tid = int(p[1]) if p[1] not in ("", "\\N") else 0
        w = p[2]; coin = p[3]; direction = p[4]
        try: ntl = float(p[5]); pnl = float(p[6])
        except Exception: continue
        fills[(w, coin)].append((ts, tid, direction, ntl, pnl))

positions = []   # {wallet, entry_ts, exit_ts, pct, entry_ntl}
for (w, coin), fl in fills.items():
    fl.sort(key=lambda x: (x[0], x[1]))
    pos_signed = 0.0     # signed notional proxy (using notional as size*px; sign only)
    entry_ts = None; entry_ntl = 0.0; realized = 0.0
    for ts, tid, direction, ntl, pnl in fl:
        d = sdelta(direction, ntl)
        if d == 0:
            continue
        was_flat = abs(pos_signed) < 1e-6
        if was_flat:
            entry_ts = ts; entry_ntl = 0.0; realized = 0.0
        # accumulate opening notional when increasing |position|
        if (pos_signed >= 0 and d > 0) or (pos_signed <= 0 and d < 0):
            entry_ntl += abs(d)
        realized += pnl
        prev = pos_signed
        pos_signed += d
        crossed_zero = (prev > 1e-6 and pos_signed <= 1e-6) or (prev < -1e-6 and pos_signed >= -1e-6) or (abs(pos_signed) < 1e-6)
        if crossed_zero and entry_ts is not None and entry_ntl >= MIN_NTL:
            pct = max(-PCT_CAP, min(PCT_CAP, realized / entry_ntl))
            positions.append({"w": w, "entry_ts": entry_ts, "exit_ts": ts, "pct": pct, "entry_ntl": entry_ntl})
            # if flipped (not exactly flat), start a new episode from the residual
            if abs(pos_signed) >= 1e-6:
                entry_ts = ts; entry_ntl = abs(pos_signed); realized = 0.0
            else:
                entry_ts = None; entry_ntl = 0.0; realized = 0.0

# keep positions ENTERED in the test window (out-of-sample)
positions = [p for p in positions if p["entry_ts"] >= SPLIT_TS]
positions.sort(key=lambda p: p["entry_ts"])
if not positions:
    print("NO test positions reconstructed"); raise SystemExit(1)
tspan = (positions[-1]["exit_ts"] - positions[0]["entry_ts"]) / 86400
print(f"reconstructed test positions: {len(positions)}; span {tspan:.0f}d; "
      f"median hold {st.median([(p['exit_ts']-p['entry_ts'])/60 for p in positions]):.0f}min; "
      f"win-rate {sum(1 for p in positions if p['pct']>0)/len(positions):.2f}")

# ---- capital-reserved portfolio simulation with latency haircut ----
def simulate(frac, haircut, per_cap=0.25, max_conc=15):
    # event queue: (ts, kind, position)
    events = []
    for p in positions:
        events.append((p["entry_ts"], 0, p))   # entry
    events.sort(key=lambda e: (e[0], e[1]))
    bank = BANK0
    reserved = 0.0
    open_pos = []   # (exit_ts, notional, pct, id)
    daily = {}
    wins = ntr = 0
    peak = BANK0; maxdd = 0.0
    def release_until(now):
        nonlocal bank, reserved, wins, ntr, peak, maxdd
        while open_pos and open_pos[0][0] <= now:
            exit_ts, notional, pct, _ = open_pos.pop(0)
            pnl = notional * (pct - haircut - COST)   # haircut = latency+slippage, COST = fees
            bank += pnl; reserved -= notional
            ntr += 1; wins += 1 if pnl > 0 else 0
            peak = max(peak, bank); maxdd = max(maxdd, (peak - bank) / peak if peak > 0 else 0)
            daily[exit_ts // 86400] = bank
    import heapq
    for ts, kind, p in events:
        release_until(ts)
        free = bank - reserved
        notional = min(frac * bank, per_cap * bank, free)
        if notional < 1 or len(open_pos) >= max_conc or free < MIN_NTL * frac or bank <= 5:
            continue
        reserved += notional
        heapq.heappush(open_pos, (p["exit_ts"], notional, p["pct"], id(p)))
    # drain remaining
    last_ts = max((p["exit_ts"] for p in positions), default=SPLIT_TS)
    release_until(last_ts + 1)
    # full-calendar daily equity (carry forward on flat days) for honest Sharpe
    if daily:
        d0, d1 = min(daily), max(daily)
        eq = []; last = BANK0
        for dd in range(d0, d1 + 1):
            if dd in daily: last = daily[dd]
            eq.append(last)
        rets = [eq[i]/eq[i-1]-1 for i in range(1, len(eq)) if eq[i-1] > 0]
        sharpe = (st.mean(rets)/st.pstdev(rets)*math.sqrt(365)) if len(rets) > 2 and st.pstdev(rets) > 0 else 0.0
    else:
        sharpe = 0.0
    return {"final": round(bank, 2), "ret": round(100*(bank/BANK0-1), 1), "sharpe": round(sharpe, 2),
            "maxdd": round(100*maxdd, 1), "win": round(wins/ntr, 3) if ntr else 0, "trades": ntr}

print("\n=== 2%-of-bank (capital-reserved) — latency/slippage haircut sweep (OUT-OF-SAMPLE, train-selected) ===")
print(f"{'haircut':>8}{'final$':>9}{'ret%':>8}{'sharpe':>8}{'maxDD%':>8}{'win':>6}{'trades':>8}")
res = {}
for hc in [0.0, 0.0005, 0.0015, 0.003, 0.005]:
    r = simulate(0.02, hc)
    res[f"2pct_hc{int(hc*10000)}bps"] = r
    print(f"{hc*100:>7.2f}%{r['final']:>9,.0f}{r['ret']:>8}{r['sharpe']:>8}{r['maxdd']:>8}{r['win']:>6}{r['trades']:>8}")
print("\n=== sizing comparison at realistic 15bps haircut ===")
print(f"{'frac':>8}{'final$':>9}{'ret%':>8}{'sharpe':>8}{'maxDD%':>8}{'win':>6}{'trades':>8}")
for fr in [0.01, 0.015, 0.02, 0.03]:
    r = simulate(fr, 0.0015)
    res[f"{int(fr*1000)}permil_hc15"] = r
    print(f"{fr*100:>7.1f}%{r['final']:>9,.0f}{r['ret']:>8}{r['sharpe']:>8}{r['maxdd']:>8}{r['win']:>6}{r['trades']:>8}")
json.dump({"results": res, "n_positions": len(positions), "span_days": round(tspan)},
          open("/home/blessed/hypeevm/out/backtest3_results.json", "w"), indent=1)
print("\nSaved backtest3_results.json")
