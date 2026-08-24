#!/usr/bin/env python3
# select_train.py — select copytrade universe using TRAIN-window stats ONLY (no survivorship).
import json, os, glob
BASE = "/home/blessed/hypeevm"
f = sorted(glob.glob(os.path.join(BASE, "hl", "smartmoney_2026-05-01_2026-06-20.tsv")))
assert f, "train smartmoney tsv missing"
TSV = f[0]
rows = []
with open(TSV) as fh:
    fh.readline()
    for ln in fh:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 12:
            continue
        w = p[0]; pnl = float(p[1]); vol = float(p[2]); fills = int(p[3]); wins = int(p[4]); loss = int(p[5])
        fees = float(p[6]); spotvol = float(p[7]); perpvol = float(p[8]); days = int(p[9])
        cw = wins + loss
        win = wins / cw if cw else 0
        avgfill = vol / fills if fills else 0
        fpd = fills / max(days, 1)
        spotpct = 100 * spotvol / vol if vol else 0
        # SAME strict filter, scaled to the ~51-day train window (pnl bar halved vs 108d full)
        if not (pnl > 25000): continue
        if not (days >= 20): continue
        if not (250 <= fills <= 20000): continue
        if not (fpd <= 300): continue
        if not (0.50 <= win <= 0.93): continue
        if fees < -50: continue
        if avgfill > 50000: continue
        if spotpct >= 70: continue
        freq_pen = 1.0 if fpd <= 120 else (0.85 if fpd <= 200 else 0.7)
        q = (pnl ** 0.5) * (0.6 + win) * min(days / 40, 1.6) * freq_pen
        rows.append({"w": w, "pnl": round(pnl), "win": round(win, 3), "days": days, "fills": fills,
                     "fpd": round(fpd), "spotpct": round(spotpct), "q": round(q)})
rows.sort(key=lambda r: -r["q"])
top = rows[:100]
json.dump(top, open(os.path.join(BASE, "out", "train_universe.json"), "w"), indent=0)
with open(os.path.join(BASE, "out", "train_inlist.txt"), "w") as fh:
    fh.write(",".join("'" + r["w"] + "'" for r in top))
print(f"train-window passed: {len(rows)}; kept top {len(top)}")
# overlap with the full-window (survivorship-biased) 100
try:
    full = {r["w"] for r in json.load(open(os.path.join(BASE, "out", "copytrade_universe.json")))}
    tset = {r["w"] for r in top}
    print(f"overlap train-selected vs full-window-selected: {len(tset & full)}/100")
except Exception:
    pass
