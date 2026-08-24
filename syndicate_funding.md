# SYN1 funding trace — on-chain confirmation of one operator

Traced first inbound **token** funding (USDC / USDT0 / WHYPE / UBTC / UETH) of the 20 SYN1 wallets over the last ~10 days (≈800k blocks). **Native HYPE transfers are NOT emitted as logs**, so gas-only funding is invisible here — 13 of 20 wallets show no token funding (funded in native HYPE, or before the window). Even so, the token trail alone confirms coordination:

## Direct links found

- **`0x4f82e73e…` was funded (WHYPE) by `0x8f10b468…`** — and `0x8f10b468` is the **smart-contract sniper BOT** (getCode ≠ 0x) at the core of SYN1. A bot directly funding another SYN1 wallet is a hard on-chain link, not just timing correlation.
- **Shared funder `0x23ebcd70…` funded TWO SYN1 wallets** (`0x8dd9433e…` and `0x05008c08…`) — one source bankrolling multiple cluster members = one operator.
- `0x8f10b468…` (the bot) itself was funded USDC by `0x7319ac5b…`.
- `0xca9d6973…` (the **Lazarus Group**-tagged wallet) was funded USDT0 by `0x1fa40f83…`.

## Reading

The co-entry graph already put these 20 wallets in one cluster (25 shared tight co-entries between the two cores). The funding trail **independently corroborates** it: a bot funding a sibling wallet, plus a shared bankroller across two more. Combined confidence that SYN1 is a single coordinated sniper operation (containing a contract bot and a Lazarus-tagged wallet): **high (≥0.85)**.

Caveat: only 7/20 links are visible because sniper wallets are gassed in native HYPE, which HyperEVM does not log. A full funder map needs native-transfer tracing (block-by-block `eth_getBlockByNumber` tx scan or a trace API) — out of scope here. The visible links are sufficient to corroborate; they are not the complete funding graph.

Machine record: `syn1_funding.json`.
