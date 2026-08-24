# Copytrade bot — $1000 paper engine over 100 vetted Hyperliquid perp wallets

Live paper-trading bot that mirrors the trades of 100 hand-filtered HL perp traders into a **$1000 virtual bank**, sizing each copied trade as a % of bank and reporting every fill + running PnL to Telegram. Built 2026-08-24. No real orders are placed (add an HL agent-wallet key to go live — one function).

Telegram: **@Trewrwefdgbot** — send `/start`, then `/status`, `/positions`, `/pnl`, `/strategy`, `/mode growth|safe`, `/stop`, `/resume`.

---

## Wallet universe (`copytrade_wallets_100.csv`)

From the 473,899-wallet HL Core population, a **strict copytrade filter** (not the loose smart-money screen):
- realized PnL > $50k over 2026-05-01…08-16
- **≥30 active days** (sustained, not one lucky run)
- **500 ≤ fills ≤ 30,000** — not dust, and explicitly **NOT millions-of-tx HFT/snipers** (your rule)
- **≤300 fills/day** — real-time mirrorable frequency
- winrate 0.50–0.93 — excludes coinflips and 0.95+ martingales
- no rebate-farming (fees ≥ 0), block size < $50k avg, **< 70% spot** (directional perp)

655 wallets passed; **top 100 by quality** kept. **getCode bot-check: 0 contracts** — all 100 are clean EOAs (no smart-contract snipers/bots). None snipe-and-rug their own launches (they trade BTC/ETH/HYPE/SOL perps, not self-issued tokens). The Lazarus-linked SYN1 sniper syndicate and the 5 getCode-contract bots from the earlier hunt are **excluded**.

---

## Strategy selection — RIGOROUS out-of-sample backtest (audited, `backtest3.py`)

An earlier pass (`backtest2.py`) reported +211% — **that number was wrong** (survivorship + a compounding fantasy). Three independent QA critics tore it apart; this is the corrected, honest version. See `AUDIT.md`.

**What was fixed vs the naive backtest:**
1. **Survivorship removed.** The universe is now selected on **TRAIN-window stats only** (2026-05-01…06-20), frozen, then tested on the unseen window. Only **38 of the 100** full-window wallets survive train-only selection — the other 62 qualified partly *because* of test-period performance (look-ahead). We test the 100 train-selected wallets.
2. **Capital is reserved.** You cannot hold 1,678 overlapping positions with $1,000. Each position locks notional over its **real hold time** (median **~24 h**); new signals are skipped when capital is tied up. Result: ~**82** trades actually fit, not 1,678.
3. **Latency/slippage** haircut swept (you enter *after* the target, as a taker).
4. **Full-calendar daily equity** for Sharpe (carry bank on flat days) — kills the fake Sharpe ~14.

**Honest out-of-sample result — 2%-of-bank, capital-reserved, train-selected (test 56 days, 2,311 positions reconstructed, 432 trades actually fit ≈ 7.7/day, median hold ~12h):**

| Latency haircut | Final $ | Return | Sharpe | maxDD | Winrate |
|---|---|---|---|---|---|
| 0.00% | $1,047 | +4.7% | 5.42 | 1.5% | 61% |
| **0.15% (realistic)** | **$1,034** | **+3.4%** | **3.97** | **1.6%** | 55% |
| 0.30% | $1,020 | +2.0% | 2.46 | 1.7% | 46% |
| 0.50% (harsh) | $1,003 | +0.3% | 0.39 | 2.2% | 40% |

Sizing sensitivity at 0.15% haircut: 1% → +1.7%, 1.5% → +2.5%, **2% → +3.4%**, 3% → +5.1% (maxDD 2.4%).

**The real edge is modest, positive and low-risk: ≈ +3.4% over ~2 months (~25%/yr) at realistic execution, Sharpe ≈4, max drawdown <2%.** Not the +211% fantasy — that was a broken simulator (a heap-release bug stranded capital and a survivorship-biased pool). Chosen: **`growth` = 2% of bank/trade** (your "enter every trade at %"), with **`safe`** (consensus-2) as an even more conservative option (`/mode safe`).

**⚠️ Sharpe ~4 is optimistic.** The backtest assumes I capture each target's *exact realized %* with zero execution-noise variance — real fills add slippage variance that lowers the true Sharpe well below 4. Trust the **return** (~+3.4%, and conservative — wins are clipped, costs charged every trade); treat the Sharpe as a ceiling.

**⚠️ The edge is FRAGILE to execution quality** — at a harsh 0.5% round-trip cost it nearly vanishes (+0.3%, Sharpe 0.39). Copytrading these ~12h-hold swing traders works only if you enter close to their price; a bot that lags badly or trades illiquid alts loses the edge. Prefer their liquid-coin trades.

## Devil's advocate / pre-mortem

- **Why so much lower than the +211%?** That figure sequentially compounded 1,678 non-overlapping trades — impossible with $1k and multi-hour holds — and used a winner pool chosen with hindsight. Both removed here: capital-reserved sizing fits **432** trades of **2,311** reconstructed positions, on a **train-only** universe.
- **Regime.** The 56-day test leaned on a rising market. In chop/down, +3.4% can go negative. Sharpe ~4 and <2% DD are reassuring but not a promise.
- **Execution is the whole game.** At 0.15% round-trip the edge is +3.4%; at 0.5% it's +0.3%. If the bot lags the target or trades thin alts, you lose it. The ~12h median hold helps (you have time to enter well), but fast movers on illiquid coins are traps.
- **Capital constraint.** A $1,000 book fills its ~15 slots and skips signals; return is gated by capital, not just skill. A bigger bank takes more trades but moves the market.
- **Core data ends 2026-08-16**, so the backtest can't see blow-ups after that; the *live* bot has no such blind spot (it trades forward in real time).
- Mitigations: per-trade ≤25% bank, ≤15 concurrent, capital reserved off free cash, 0.95+ winrate & HFT/millions-tx wallets excluded, paper-only until you add a key.

## Bot mechanics (audited — see `AUDIT.md`)

- Position-tracking model via `startPosition`: mirrors the target's **net** perp position per coin — opens on their open, **holds through partial closes**, closes on full flat, and handles **reversals** (Long↔Short). tid-based dedup (no double-processing / same-ms phantom positions).
- Robustness: single-instance flock, atomic state with `.bak` recovery, 30-min backfill cap on restart, HTTP-429 backoff, per-stage error isolation, log rotation, orphan-reconcile safety net (closes paper positions the target no longer holds), HTML-escaped Telegram.
- 50-assertion test suite (`simulate_copybot.py`) — all green on the box.
- To go **live**: add an HL agent-wallet key and swap the paper open/close for `exchange.order(...)`; sizing/logic unchanged.

*Reproducible from `positions_test.tsv.gz` + `backtest3.py` (position reconstruction in contracts via `start_position`; capital-reserved sim with `heapq`); universe `train_universe`. Test window UTC 2026-06-21…08-16 (56 days, full).*
