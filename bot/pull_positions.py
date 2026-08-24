#!/usr/bin/env python3
# pull_positions.py — all PERP fills for train_universe over TEST window (box 167), for position reconstruction.
import urllib.request, urllib.parse, base64, gzip, datetime as dt
CH = "http://88.99.51.222:8123/"
AUTH = "Basic " + base64.b64encode(b"mcp_agent:09cb3d4fdebd87bf7f7a42260eb1a240bb0275f515c5a7c2").decode()
SET = {"max_execution_time": "280", "max_memory_usage": "5000000000", "max_threads": "3"}
IL = open("/home/blessed/hypeevm/out/train_inlist.txt").read().strip()
OUT = "/home/blessed/hypeevm/out/positions_test.tsv.gz"
TAB = "\t"; NL = "\n"

def q(sql):
    req = urllib.request.Request(CH + "?" + urllib.parse.urlencode(SET), data=sql.encode(), headers={"Authorization": AUTH})
    return urllib.request.urlopen(req, timeout=300).read().decode("utf-8", "replace")

start = dt.date(2026, 6, 20); end = dt.date(2026, 8, 16)   # test window (+1d lead to catch positions opened just before split)
f = gzip.open(OUT, "wt", encoding="utf-8")
f.write(TAB.join(["ts", "tid", "wallet", "coin", "dir", "sz", "px", "startpos", "ntl", "pnl"]) + NL)
total = 0; d = start
while d < end:
    d2 = min(d + dt.timedelta(days=3), end)
    sql = ("SELECT toUnixTimestamp(utc_event_dttm) ts, oid tid, wallet, coin, dir, "
           "sz, px, start_position startpos, round(notional,2) ntl, round(closed_pnl,4) pnl "
           "FROM cex_mcp.hl_fill "
           "WHERE wallet IN (" + IL + ") AND dir IN ('Open Long','Open Short','Close Long','Close Short','Long > Short','Short > Long') "
           "AND utc_event_dttm >= '" + str(d) + " 00:00:00' AND utc_event_dttm < '" + str(d2) + " 00:00:00' "
           "FORMAT TSVWithNames")
    try:
        txt = q(sql)
    except Exception as e:
        print("[" + str(d) + "] FAIL " + str(e)[:80], flush=True); d = d2; continue
    lines = txt.rstrip(NL).split(NL)
    if lines and lines[0].startswith("Code:"):
        print("[" + str(d) + "] ERR " + txt[:100], flush=True); d = d2; continue
    n = 0
    for ln in lines[1:]:
        if ln:
            f.write(ln + NL); n += 1
    total += n
    print("[" + str(d) + ".." + str(d2) + "] rows=" + str(n) + " total=" + str(total), flush=True)
    d = d2
f.close()
print("DONE total=" + str(total) + " -> " + OUT, flush=True)
