# HYPEREVM_SMART_WALLETS

On-chain forensic hunt for 50 smart/useful wallets across **Hyperliquid Core (perps/spot)** and **HyperEVM (fresh memecoins)**, seeded from three user-supplied tokens + PURR spot, then expanded across the whole population. Built 2026-08-23/24 UTC.

Seed tokens: HYPURR `0xd6317538…64ad6`, EGG `0xb75d5ee1…65608`, PURR `0x9b498c3c…2b44e` (= HL spot PURR).

---

## TL;DR

- **Verifiable trading edge on Hyperliquid lives on the perp/Core side, not in fresh-meme sniping.** The 40 COPY_FIT wallets are directional HL perp traders with $550k–$5.2M realized PnL over ~3.5 months, sustained 40–108 active days, non-HFT, several tagged as real cross-chain veterans.
- **The strongest "early meme hunters" turned out to be a 20-wallet coordinated sniper SYNDICATE that includes a smart-contract bot and a wallet tagged by monolit as North-Korea's Lazarus Group.** It was excluded from the buy-list and is documented as a finding (`syndicate.md`). This is the answer to *"find one person's multi-wallet cluster / insiders."*
- Only **5 clean, non-syndicate early hunters** survive verification, at low confidence (0.45–0.6) — because most fresh-meme "wins" cannot be proven profitable in USD.
- **37 sub-$1M-mcap tokens** got mass allocation in the last 3 days (all today's hyperswap-v3 launches, +770%…+6248%, 150–820 buyers each) — the hunting ground, in `candidate_tokens.csv`.

**Final 50:** `wallets_final50.csv` / `wallets_final50.md` — 40 COPY_FIT + 5 EARLY_HUNTER + 5 SPOT_WHALE(insider-watch).

---

## Coverage report (what was actually checked)

| Layer | Source | Coverage |
|---|---|---|
| HL Core smart-money | `cex_mcp.hl_fill` day-by-day, 2026-05-01 … 08-16 (108 days) | **473,899 wallets**, 160,275 net-positive ($2.04B) — FULL population, not a sample |
| HyperEVM fresh memes | eth_getLogs Transfer/Swap sweep, 2 launch waves (Aug-04: 16 tokens, Aug-23: 157) | wave0823 + wave0804 **100%** (incl. HYPURR/EGG), 0 gaps |
| HyperEVM mid-caps | `actives`/`purr` sweeps from 2026-06-01 | **partial: actives ~44%, purr ~64%** (killed to free RPC — logged, not silent) |
| Spot memes | hypurrscan `/holders` snapshots | ~20 sub-$12M-mcap spot tokens |
| Entity/socials | monolit `wallet_tags_prod` | 73/252 shortlist tagged |
| Cross-chain | monolit `evm.swap_events` (eth/base/bsc/polygon) | 22 finalists probed |
| Bot check | HyperEVM `eth_getCode` + nonce | all 252 shortlist |

**Chains checked:** HyperEVM (chain 999, direct RPC), HyperCore (cex_mcp), Ethereum, Base, BSC, Polygon (monolit). Solana not in scope (no link surfaced).
**Freshness trap:** `hl_fill` ingest stops at **2026-08-16** — Core stats are blind to the last ~7 days; a wallet blown up after 08-17 still looks perfect here. HyperEVM RPC is live to now.

---

## Method (pipeline)

1. **Token universe** — GeckoTerminal (257 pools / 200 tokens) + HL `spotMetaAndAssetCtxs` (493 spot) + DexScreener. Two clear launch waves on hyperswap-v3.
2. **Core smart-money** — day-by-day per-wallet aggregation of `closed_pnl`, winrate, fills, spot/perp split, active-days (external group-by to dodge the shared-server 56 GB overcommit killer).
3. **EVM early-hunter reconstruction** — swept every Transfer log of the fresh tokens; rebuilt per-token holders, net balance, and **entry time vs pool-creation** (block→timestamp interpolation). "Early" = bought ≤2 h after the pool opened.
4. **Bot filter** — `eth_getCode` (contract wallet = bot/smart-wallet → excluded; caught the #1 "hunter" at win 20/20), high-nonce mechanical EOAs, same-block snipe ratio.
5. **Cluster / cabal** — union-find over tight co-entry pairs (both wallets buy the same fresh token within 20 min, ≥8 shared tokens = one operator).
6. **Enrichment** — monolit entity tags (Hyperliquid Trader / polymarket-owner-eoa / **hacker=Lazarus**), Twitter handles, cross-chain history.
7. **Adversarial critic pass** — a devil's-advocate agent attacked the list; its fixes are baked in (see Caveats).

---

## Buckets

### COPY_FIT (40) — directional HL perp traders, copytradeable
Net-positive realized PnL, sustained ≥20 (mostly 90–108) active days, **not** HFT/MM (fills/day capped, no rebate-farmers, winrate 0.5–0.97 band), spot share low. Highest confidence = the ones with a monolit `individual`/`polymarket-owner-eoa` tag **and** a multi-year eth/base/bsc history:
- `0xb798aef7…` — PM-owner+individual, eth since 2021 → **conf 0.8**
- `0x4cd80aa0…` — PM-owner+individual, eth since 2022 → **conf 0.8**
- `0xa4beb4fb…` **@jvpmamede** — OG since 2020 (eth+bsc), but winrate 0.96 = possible martingale
- `0xbe4e91ae…` — PM-owner, OG since 2020, winrate 0.97 = possible martingale

### EARLY_HUNTER (5) — fresh-meme early buyers, higher risk
Survivor-verified (≥1–3 early entries into tokens that are still >$100k mcap), non-syndicate, passed getCode. **Confidence 0.45–0.6** — fresh-meme "wins" are hard to prove in USD, and these are days-old signals. Best: `0xa2a85ea4…` (3 survivor entries, still holds ~$50k).

### SPOT_WHALE (5) — insider/whale distributors, WATCH don't copy
Spot-only wallets with $3.9M–$15.8M realized from **selling** accumulated HYPE/PURR inventory over a few days = distribution/insider signal, not directional alpha. Their selling is a **top-warning** on that asset.

Full per-wallet evidence, confidence and action: **`wallets_final50.csv`**.

---

## Marquee finding — the Lazarus-linked sniper syndicate (`syndicate.md`)

A **20-wallet cluster (SYN1)** repeatedly front-runs the same fresh HyperEVM memecoins within minutes of each other (25 shared tight co-entries between its two cores). It contains:
- a **smart-contract sniper bot** `0x8f10b468…` (getCode ≠ 0x, "win 20/20"),
- a wallet monolit tags **hacker / Lazarus Group** `0xca9d6973…`.

Guilt-by-tight-co-entry → the whole cluster is treated as one operator and **excluded** from the smart-wallet list. Three smaller sibling clusters (SYN2 6-wallet, SYN3/SYN4 pairs) are also documented. If you snipe fresh HyperEVM memes, you are trading against this book.

---

## Candidate tokens (`candidate_tokens.csv`)

37 tokens with **mcap < $1M, >$40k 24h volume, born ≤3 days, ≥150 buyers** — the mass-allocation set. All are today's hyperswap-v3 launches (TOFU, KORILA, EARNY, bugcat, HCAT, CHICKEN…), +770% to +6248% since launch. These are the arenas the syndicate above operates in — treat as high-variance scalps, not holds.

---

## Devil's advocate + pre-mortem

- **Bear case:** HL `closed_pnl` over a 108-day up-only tape rewards anyone who was net-long size; a market regime flip could expose the high-winrate names as martingale/averaging-down blowups (the 0.95+ winrate wallets especially). The freshness gap (no data after 08-16) hides exactly that.
- **"−100% in 30 days" story:** you copytrade the top perp names → they were levered long the HYPE/alt complex → a 30–40% HL drawdown liquidates the martingale wallets you mirrored, and the "early hunter" alerts you followed were the syndicate distributing into your buys. Mitigation: fixed-fraction sizing, hard per-trade stops, and never mirror a wallet whose winrate > 0.95 without seeing its loss distribution.

## Caveats (from the adversarial pass — read before trusting a number)

1. **EVM "win" ≠ verified USD profit.** A "win" credited on *sold ≥50%* can be a loss-dump. Early-hunter winrates are **upper bounds**; only the `cap>$100k` survivor count is verifiable. This is why the EARLY_HUNTER bucket is small and low-confidence.
2. **Survivorship + freshness.** Only currently-GT-listed pools were swept (dead-at-birth rugs and 429-dropped pages are missing → hunter winrates inflated); Aug-23 "wins" are hours old and can evaporate; `actives`/`purr` are 44%/64%; Core is blind after 2026-08-16.
3. **Cluster under-merge & interpolation.** Block→timestamp interpolation yields small negative lags (treated as noise ≤3 min); genuine pre-pool dev allocations may still hide among "early" buys. No copy-farmer / vault-leader check was run on the COPY_FIT set — verify live before scaling.

---

## Files
- `wallets_final50.csv` / `.md` — the 50 wallets, evidence, confidence, action
- `syndicate.md` — the 20-wallet Lazarus-linked cabal + sibling clusters
- `candidate_tokens.csv` — 37 sub-$1M fresh mass-allocation tokens
- `monolit_tags.csv` — entity/social tags for the shortlist
- `crosschain.json` — eth/base/bsc history of finalists
- `final50.json` — machine-readable full record

*Numbers are reproducible from `cex_mcp.hl_fill` (Core) and HyperEVM `eth_getLogs` (EVM); every wallet carries its own evidence string. Time = UTC.*
