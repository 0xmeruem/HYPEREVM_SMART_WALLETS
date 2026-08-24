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

## Strategy selection — honest out-of-sample backtest

**Data:** 336,748 real closing fills of the 100 wallets → aggregated to 6,577 position-level trades. A copied round-trip earns the same % return as the target (`closed_pnl / notional`) on my sized notional, minus a round-trip cost.

**Anti-survivorship:** wallets were **re-selected on a TRAIN window (to ~2026-06-20)**, then strategies were tested **only on the unseen TEST window (2026-06-20…08-16, 56 days, 2,889 trades)**. 57 of the 100 kept a real edge in-train and were traded out-of-sample. Compounding is bounded (per-trade ≤25% bank, concurrency-capped) — no fantasy numbers.

**12 strategies tested. Out-of-sample results (start $1000):**

| Strategy | Final $ | Return | maxDD | Winrate | Trades |
|---|---|---|---|---|---|
| **R06 — 2% of bank / trade, ≤15 concurrent** ⭐ | **$3,106** | **+211%** | 8.1% | 67% | 1,678 |
| F02 — fixed $40 / trade | $3,092 | +209% | 7.8% | 67% | 1,506 |
| R08 — 3% / trade, top-30 wallets only | $3,181 | +218% | 8.4% | 63% | 647 |
| R09 — 1.5% / trade, ≤10 concurrent | $2,078 | +108% | 4.8% | 67% | 1,365 |
| R05 — 1% / trade | $1,848 | +85% | 5.9% | 66% | 1,876 |
| F03 — $25 / trade, **consensus-2** | $1,221 | +22% | **0.7%** | 72% | 243 |
| R07 — 2% / trade, **consensus-2** | $1,164 | +16% | **0.7%** | 74% | 199 |
| R10 — 2% / trade, consensus-3 | $1,006 | +0.6% | 0.0% | 89% | 18 |

**Chosen — two modes:**
- **`growth` (default): 2% of bank per trade, ≤15 concurrent, per-trade cap 25%** (R06). Matches your "enter every trade at % of bank." Out-of-sample **+211%** over 56 days, maxDD 8%, 67% win. This is the aggressive mode.
- **`safe`: consensus-2** — only copy a coin/direction when **≥2 of the wallets** are aligned within an hour. **+16–26%**, maxDD **<1%**, 72–74% win. Far fewer, higher-conviction trades. Switch with `/mode safe`.

**Slippage stress (extra latency cost on top of fees):**

| Round-trip cost | growth-2% final | return | consensus-2 |
|---|---|---|---|
| 0.07% (base) | $3,106 | +211% | +26% |
| 0.20% | $2,973 | +197% | +25% |
| 0.40% | $2,780 | +178% | +23% |
| 0.70% (harsh) | $2,514 | +151% | +21% |

The edge **survives realistic slippage** — even at 0.7% round-trip it still returns +151% (growth) / +21% (safe) out-of-sample.

---

## Devil's advocate / pre-mortem (read this)

- **The 56-day test window was a rising market** — long-biased copiers were flattered. In a chop or down regime the growth mode's +211% would compress hard and the 8% drawdown would deepen. **Run `safe` mode if you don't know the regime.**
- **Modeled Sharpe (~14) is not real.** It ignores real-world entry latency vs the target (I detect fills on a ~2-min rotation, then enter at the live mid). The slippage stress above is the honest degradation; treat headline returns as an **upper bound**.
- **Survivorship isn't fully gone.** The 100 were pre-filtered on the full period; the train/test split mitigates it but the universe itself is winner-biased. A wallet that blows up after 2026-08-16 (where Core data ends) would still look perfect.
- **Sizing at scale breaks.** These returns assume the % per trade holds — true for $1000, false for $1M (you'd move the wallets you copy).
- Mitigations baked in: per-trade ≤25% bank, ≤15 concurrent, 0.95+ winrate wallets excluded, HFT/millions-tx wallets excluded, paper-only until you add a key.

---

## Bot mechanics

- Watches each wallet's HL `userFills` on a rotating ~2-min poll (rate-limit safe). On a target **Open Long/Short** it opens a paper position at the live HL mid, sized per strategy; on their **Close** it closes at the live mid and books PnL. Position-level (first open → first close), max 15 concurrent.
- State persists to `state.json` (survives restart); a 3-minute watchdog cron restarts it if it dies.
- Runs on box 167. To go **live**: drop in an HL agent-wallet key and swap the paper-fill functions for `exchange.order(...)` — the sizing/among logic is unchanged.

*Every number reproducible from `closes_top100.tsv.gz` + `backtest2.py`. Test window UTC 2026-06-20…08-16.*
