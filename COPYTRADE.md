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

**Honest out-of-sample result — 2%-of-bank, capital-reserved, train-selected (test ≈53 days, 82 trades, ~1.5/day):**

| Latency haircut | Final $ | Return | Sharpe | maxDD | Winrate |
|---|---|---|---|---|---|
| 0.00% | $1,036 | +3.6% | 1.78 | 0.6% | 51% |
| **0.15% (realistic)** | **$1,033** | **+3.3%** | **1.68** | **0.7%** | 48% |
| 0.50% (harsh) | $1,027 | +2.7% | 1.43 | 0.8% | 35% |

Sizing sensitivity at 0.15% haircut: 1% → +1.7%, 1.5% → +2.5%, **2% → +3.3%**, 3% → +5.0% (maxDD 1.0%).

**The real edge is modest but positive and low-risk: ≈ +3% over ~2 months (~20%/yr), Sharpe ≈1.7, max drawdown <1%.** Not the +211% fantasy. Chosen: **`growth` = 2% of bank/trade** (your "enter every trade at %"), with **`safe`** (consensus-2) as an even more conservative option (`/mode safe`).

## Devil's advocate / pre-mortem

- **Why so much lower than the +211%?** That figure sequentially compounded 1,678 non-overlapping trades — impossible with $1k and 24 h holds — and used a winner pool chosen with hindsight. Both are removed here.
- **Regime.** Even this 53-day test leaned on a rising market. In chop/down, +3% can go negative. Sharpe 1.7 and <1% DD are reassuring but not a promise.
- **Capital constraint is the real limit.** With 24 h median holds, a $1,000 book fills its ~15 slots fast and skips most signals — the return is gated by capital, not by the wallets' skill. A bigger bank takes more trades (but then slippage grows).
- **Core data ends 2026-08-16**, so the backtest can't see blow-ups after that; the *live* bot has no such blind spot (it trades forward in real time).
- Mitigations: per-trade ≤25% bank, ≤15 concurrent, capital reserved off free cash, 0.95+ winrate & HFT/millions-tx wallets excluded, paper-only until you add a key.

## Bot mechanics (audited — see `AUDIT.md`)

- Position-tracking model via `startPosition`: mirrors the target's **net** perp position per coin — opens on their open, **holds through partial closes**, closes on full flat, and handles **reversals** (Long↔Short). tid-based dedup (no double-processing / same-ms phantom positions).
- Robustness: single-instance flock, atomic state with `.bak` recovery, 30-min backfill cap on restart, HTTP-429 backoff, per-stage error isolation, log rotation, orphan-reconcile safety net (closes paper positions the target no longer holds), HTML-escaped Telegram.
- 50-assertion test suite (`simulate_copybot.py`) — all green on the box.
- To go **live**: add an HL agent-wallet key and swap the paper open/close for `exchange.order(...)`; sizing/logic unchanged.

*Reproducible from `positions_test.tsv.gz` + `backtest3.py`; universe `train_universe`. Test window UTC 2026-06-20…08-13 (last 3 days dropped to a transient pull error — logged, not hidden).*
