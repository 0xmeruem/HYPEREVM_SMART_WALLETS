#!/usr/bin/env python3
# build_universe.py — strict copytrade-eligible perp wallets from smartmoney TSV (box 167).
import json, os
TSV = "/home/blessed/hypeevm/hl/smartmoney_2026-05-01_2026-08-16.tsv"
OUT = "/home/blessed/hypeevm/out"
os.makedirs(OUT, exist_ok=True)
rows = []
with open(TSV) as f:
    f.readline()
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 12:
            continue
        w = p[0]
        pnl = float(p[1]); vol = float(p[2]); fills = int(p[3]); wins = int(p[4]); loss = int(p[5])
        fees = float(p[6]); spotvol = float(p[7]); perpvol = float(p[8]); days = int(p[9]); buys = int(p[10]); sells = int(p[11])
        cw = wins + loss
        win = wins / cw if cw else 0
        avgfill = vol / fills if fills else 0
        fpd = fills / max(days, 1)
        spotpct = 100 * spotvol / vol if vol else 0
        # STRICT copytrade filter (user: not bot, not mega-sniper millions-tx, sustained, directional, mirrorable)
        if not (pnl > 50000): continue
        if not (days >= 30): continue                 # sustained, not a lucky short run
        if not (500 <= fills <= 30000): continue       # not dust, NOT millions-of-tx HFT
        if not (fpd <= 300): continue                  # real-time mirrorable frequency
        if not (0.50 <= win <= 0.93): continue         # exclude coinflip & martingale(>0.95)
        if fees < -50: continue                        # rebate = MM
        if avgfill > 50000: continue                   # whale/MM block size
        if spotpct >= 70: continue                     # directional perp, not spot distributor
        # quality score: pnl (sqrt), winrate, sustained days, penalize very high freq
        freq_pen = 1.0 if fpd <= 120 else (0.85 if fpd <= 200 else 0.7)
        q = (pnl ** 0.5) * (0.6 + win) * min(days / 60, 1.6) * freq_pen
        rows.append({"w": w, "pnl": round(pnl), "vol": round(vol), "fills": fills, "win": round(win, 3),
                     "days": days, "fpd": round(fpd), "avgfill": round(avgfill), "fees": round(fees),
                     "spotpct": round(spotpct), "buys": buys, "sells": sells, "q": round(q)})
rows.sort(key=lambda r: -r["q"])
top = rows[:150]
json.dump(top, open(os.path.join(OUT, "universe_candidates.json"), "w"), indent=0)
print(f"passed strict filter: {len(rows)}; kept top {len(top)}")
print("--- top 20 ---")
for r in top[:20]:
    print(f'{r["w"]} pnl=${r["pnl"]:,} win={r["win"]} d={r["days"]} fills={r["fills"]} fpd={r["fpd"]} spot={r["spotpct"]}% q={r["q"]}')
