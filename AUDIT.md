# AUDIT — copytrade bot + backtest (2026-08-24)

Full audit-recycle of the system: a 50-assertion deterministic test suite (`simulate_copybot.py`) plus **three independent QA critic agents** (fresh context) attacking the code and methodology, then fix → re-test until clean. Every fix is covered by a test.

## Critic A — trading-logic bugs (copybot)
| # | Bug | Fix | Test |
|---|---|---|---|
| A1 | **Same-ms fills** sorted by time only → API newest-first order → phantom position that never closes | sort by **(time, tid)**; tid is monotonic | 28 |
| A2 | **Cross-poll same-ms split** skips the second fill (`last+1` query) | switched to **tid-based dedup** with time overlap | 29, 30 |
| A3 | Safe-mode consensus counted **rejected** opens | consensus now counts the **target's real open** (recorded in `process_fill`, gated on non-dust), independent of our mirror | 31 |
| A4 | Bot started **mid-position**: a partial close read as "target is LONG" → false entry as the target *exits* | open only on a real **open/reversal action**, never on a Close that merely leaves them in-position | 21, 24 |
| A5 | Reversal (Long↔Short) ignored → stuck position | position-tracking via `startPosition`: close+reopen on sign flip | 4, 23 |
| A6 | Errored fill consumed silently | per-fill try/except + orphan-reconcile backstop | — |

## Critic B — reliability / ops (copybot)
| # | Bug | Fix |
|---|---|---|
| B1 | No single-instance lock → watchdog could double-start (Telegram 409, state corruption) | **flock** pidfile; second instance exits |
| B2 | Corrupt `state.json` silently wiped bank to $1000 then overwrote | rolling **`.bak`**, corrupt file kept as `.bad`, never auto-default-then-overwrite (test 32) |
| B3 | Unbounded downtime backfill floods Telegram / re-enters stale trades | **30-min backfill cap** on restart |
| B4 | No 429 / backoff → retry storm → IP ban | detect HTTP 429, honor `Retry-After`, capped exponential backoff |
| B5 | One try wrapped the whole cycle → a poison update froze trading | independent try per stage; `save` failure alerts |
| B6 | Slow wallet stalls the single-thread loop | timeout 10 s, 2 tries |
| B7 | Log never rotated → shared-box disk fills | size-capped rotation |
| B8 | `recent_opens` lost on restart → safe mode blocks 1 h | persisted in state, restored on load |
| B9 | No fsync / bare `open()` | fsync on save, `with` everywhere |
| B10 | Unescaped HTML (coin/text) → Telegram 400 drops message | `html.escape` all dynamic fields |

## Critic C — backtest methodology (VERIFIED against ClickHouse)
| # | Flaw | Effect | Fix |
|---|---|---|---|
| C1 | **Survivorship**: universe selected on the FULL window (conditions on test outcome) | large up-bias | select on **train-only**, freeze, test — only **38/100** survive train selection |
| C2 | **No copy latency/slippage** — headline used the target's own price | can flip edge | latency haircut **sweep** |
| C3 | Closes-only / realized-pnl bias | moderate up-bias | position reconstruction; noted open-at-end exclusion |
| C4 | "Best strategy" via **degenerate Sharpe** (days-with-trades only) + multiple testing | fake Sharpe ~14 | **full-calendar** equity; report the pre-chosen 2% sizing, not a score winner |
| C5 | Concurrency cap didn't reserve capital → >100% deployed, 1,678 "trades" | big overstatement | **capital-reserved** sizing off free cash over real hold times → ~82 trades |

**Net effect:** corrected out-of-sample return dropped from a fantasy **+211%** to an honest **≈ +3.3% over ~53 days** (Sharpe ≈1.7, maxDD <1%). See `COPYTRADE.md`.

**Verified NOT guilty (so we didn't "fix" non-bugs):** `PCT_CAP=1.5` is inert (4/2889 trades clip); `pct = closed_pnl/notional` at 1× notional is the correct conservative copy return; the 30-min bucket dollar-weights partial closes correctly; concurrency cap frees a slot before a reversal re-opens (no false block); bank cannot go negative.

## Second pass — verification critics (D on the bot, E on the backtest)
Re-ran two fresh critics against the *fixed* code to confirm the fixes and catch regressions.

**Critic D (bot) — verified all 12 fixes correct, found 3 minor items, all fixed:**
- D1 reconcile trusted the coin string across 3 HL endpoints → verified HL is consistent (BTC/ETH identical in userFills/clearinghouseState/allMids); added a **2-strike** guard anyway (close an orphan only after 2 consecutive flat observations) — defends against any transient/naming false positive.
- D2 a non-numeric `time`/`tid` could throw in the batch sort and stall a wallet forever → all int coercions now go through a safe `_i()`; a self-test (26g) proved a malformed fill no longer crashes or stalls (this caught a real residual `int()` on the `last_ms` update).
- D3 `/mode Safe` case-sensitivity → lowercased.
- Confirmed sound: PnL/short-floor/bank, atomic save + `.bak` recovery (survives kill between the two renames), flock freed on kill-9, 429 backoff, HTML escaping.

**Critic E (backtest) — found a CRITICAL simulator bug; rebuilt:**
- E1 **`open_pos.pop(0)` on a `heapq` heap** didn't re-heapify → capital stranded, releases out of order → **only 82 of ~430 trades fit and Sharpe/DD were garbage.** Fixed to `heapq.heappop` → **432 trades** (matches E's independent ~422 estimate).
- E2 positions were tracked in **USD notional** (drifts with price) → episode boundaries wrong on multi-fill positions. Rebuilt reconstruction in **contracts via `start_position`** (exact flat crossings, correct reversals).
- E3 Sharpe calendar now padded SPLIT→test-end; E4 fixed the paper-notional floor ($1, not the target's $50 dust filter) and swept latency.
- Verified correct: OOS design (universe frozen on train-window tsv, tested on post-SPLIT entries), 2%-compounding can't explode, no fee double-count, train-window filter scaling ~proportional.

**Corrected honest result: +3.4% / 56 days at 15 bps latency (Sharpe ~4, maxDD 1.6%, 432 trades), fragile to execution (→ +0.3% at 0.5% cost).** See `COPYTRADE.md`.

## Stress / fuzz (`stress_copybot.py`) — 20,000 adversarial fills, PASS
Random reversals, same-ms clusters, and malformed fills (missing coin/sz/px/startPosition, non-numeric, unknown dir) fed through the fill pipeline: **0 crashes**, all invariants hold (bank finite & not absurdly negative, open ≤ concurrency cap, closed ≥ wins, history capped, every open position well-formed, realized ≈ bank−1000), reconcile clears all to flat, state round-trips.

## Test suite (`simulate_copybot.py`) — 53 assertions, all green
open/close long & short · partial-close-holds · full-close · reversal · reversal-at-cap · scale-in-no-double · missing-mid-open-skip · missing-mid-close-proxy · short loss floor · concurrency cap · min-notional · pause · spot-ignored · consensus (dust-excluded, bootstrap) · maxDD/peak · restart-resume · ruin guard · history cap · blocklist · two-coins-independent · close-without-open no-op · **same-ms ordering** · **tid idempotency** · **cross-poll overlap** · **corrupt-state `.bak` recovery** · **orphan reconcile (+ fail-safe on API error)**.

## Honest residual limitations
- Latency is modeled as a haircut, not a real price-at-(open+Δ) — I don't have an intra-position price series.
- Open-at-test-end positions and pure scratches are excluded from the reconstruction.
- Test window is ~53 days in a mostly-rising market; a down/chop regime is untested.
- Live bot uses the full-window-100 (correct for forward trading — no look-ahead forward); the backtest uses train-100 (correct for measuring edge).
