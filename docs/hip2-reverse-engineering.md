# HIP-2 Hyperliquidity — Reverse Engineering

Reverse-engineered from live testnet/mainnet orderbooks, March 2025.

## Overview

HIP-2 is a **protocol-level CLOB AMM**. It places limit orders on a fixed geometric price ladder,
shifting inventory between bids and asks as fills occur. No external price reference — purely
inventory-driven.

**System address:** `0xffffffffffffffffffffffffffffffffffffffff`

## Deploy Parameters

| Parameter | Description | Examples observed |
|-----------|-------------|-------------------|
| `startPx` | Lowest price in the ladder | 0.020777, 1.000, 21.527 |
| `nOrders` | Total number of price levels | ~100 (typical) |
| `orderSz` | Size per full level | 100, 600, 700, 1000, 100000 |
| `nSeededLevels` | Initial bid-side levels | Varies (rest start as asks) |

## Price Ladder Formula

```
px_0 = startPx
px_i = round(px_{i-1} * multiplier, 5 significant figures)
```

| Era | Multiplier | Spread | Observed on |
|-----|-----------|--------|-------------|
| Current | **1.003** | ~30 bps/level | @37, @67, @125, most testnet tokens idx>50 |
| Legacy | **1.01** | ~100 bps/level | PURR/USDC (testnet), @3 (BREAD), @5 (KOGU) |

### Verified: @67 (BLOKED2) — perfect match, 40 visible levels

```
startPx = 0.020777, multiplier = 1.003, orderSz = 600
Level  0: 0.020777 (bid)     Level 20: 0.022060 (ask, partial 322.6)
Level  1: 0.020839 (bid)     Level 21: 0.022126 (ask)
Level  2: 0.020902 (bid)     ...
...                          Level 39: 0.023352 (ask)
Level 19: 0.021994 (bid)
```

All 40 prices match `round(px * 1.003, 5sf)` exactly.

### Verified: @37 (QUIZ) — 22 visible levels, ~100 total

```
startPx ≈ 1.0000, orderSz = 1000
Bid: 1.000, 1.003 (only 2 remaining — depleted by buys)
Ask: 1.006 (partial 941.26), 1.009, 1.012, ..., 1.0639 (20 levels visible)
Token hold: 97,941.26 → 97 full + 1 partial = 98 ask levels total (78 hidden beyond L2 cap)
```

## Rebalancing Algorithm

The spec says rebalancing occurs **every block where block time ≥ 3 seconds since last update**.

### Per-update logic:

```python
token_balance = available_tokens
usdc_balance  = available_usdc

# Ask side (sell tokens)
n_full_asks = floor(token_balance / orderSz)
partial_ask = token_balance % orderSz  # partial level at the cursor

# Place asks at the LOWEST available price levels (tightest spread)
# Place bids at remaining levels using USDC (HIGHEST remaining = tightest)
```

### What happens on fills:

| Event | Inventory change | Book effect |
|-------|-----------------|-------------|
| User buys (lifts ask) | Token ↓, USDC ↑ | Cursor moves UP (more bids, fewer asks) |
| User sells (hits bid) | Token ↑, USDC ↓ | Cursor moves DOWN (more asks, fewer bids) |

The price levels themselves **never move** — only the bid/ask assignment changes.
This is equivalent to a concentrated-liquidity AMM with fixed ticks on a CLOB.

## Orderbook Structure

```
                    startPx * 1.003^n
  ┌───────────────────────────────────────────────┐
  │  BIDS (USDC)      │ cursor │   ASKS (tokens)  │
  │  ← nSeededLevels   │       │  → remaining     │
  │                    │ ↕ ↕ ↕ │                   │
  │  Full levels       │partial│  Full levels      │
  │  at orderSz        │ level │  at orderSz       │
  └───────────────────────────────────────────────┘
  px_0                          px_{nOrders-1}
```

- **Spread** = 1 level spacing (~30 bps for 1.003, ~100 bps for 1.01)
- **Partial level** = the cursor between bids and asks (only level with fractional size)
- **L2 book** shows max **20 levels per side** — actual depth can be 50-100+ per side

## Key Observations

1. **Fixed ladder, no price tracking**: HIP-2 does NOT follow any oracle or reference price.
   It's purely a liquidity provision mechanism on static levels. If the market moves beyond
   the ladder range, HIP-2 becomes fully one-sided (all bids or all asks).

2. **~100 total levels typical**: From balance analysis:
   - @67: 100 ask levels (from 59,722.62 / 600)
   - @37: 98 ask levels (from 97,941.26 / 1000)
   - PURR mainnet: 100 ask levels (from 10,000,000 / 100,000)

3. **n=1 per level**: All HIP-2 levels show `n=1` (one order per level).
   User orders appear as separate `n>1` aggregated levels.

4. **Protocol-level orders**: HIP-2 orders for most markets do NOT appear in `openOrders` API.
   Only PURR/USDC shows in the 0xfff address open orders (100 orders visible there).

5. **No spread guarantee beyond static ladder**: The spec claims "0.3% spread every 3 seconds"
   but this only holds if HIP-2 has inventory on both sides. A fully depleted bid side
   (like @37 with only 2 bids) means the spread depends on whoever else is bidding.

## Live Experiment Results (March 2026)

Tested on @37 (QUIZ) with our testnet wallet. Script: `scripts/hip2_experiment.py`

### Experiment 1: Buy 50 QUIZ (partial level consumption)
```
Before: best ask = 1.006 x 941.26
After:  best ask = 1.006 x 891.26 (exactly -50)
Rebalancing: NONE — no cursor shift, just partial reduced
```

### Experiment 2: Buy 1900 QUIZ (push through 2 levels)
```
Fill: 891.26 @ 1.006 + 1000 @ 1.009 + 8.74 @ 1.012 = 1900 avg 1.0076
Immediately after: book UNCHANGED (L2 cache lag)
After 1.2 seconds: REBALANCE
  - Bids: 2 → 4 (1.006 and 1.009 flipped from ask → bid)
  - Best ask: 1.012 x 991.26 (partial = 1000 - 8.74)
  - 2 deep asks appeared (1.067, 1.0702) — were hidden beyond L2 20-level cap
```

### Experiment 3: Sell 1950 QUIZ (reverse the cursor)
```
Fill: 1000 @ 1.009 + 948.63 @ 1.006 = 1948.63 (IOC partial — insufficient bids)
After 2.4 seconds: REBALANCE
  - 1.009 flipped from bid → ask (full 1000)
  - 1.012 partial REPLENISHED from 991.26 → 1000 (topped up during rebalance)
  - Best bid: 1.006 x 51.37 (partial remaining)
  - Deep ask 1.0702 disappeared from visible range
```

### Experiment 4: Buy 5000 QUIZ (5 levels consumed)
```
Fill: 5 full levels @ 1.009-1.021, avg 1.015

TWO-PHASE REBALANCING:
  Phase 1 (+1.2s): Consumed asks removed from L2 book. Spread blows to 177 bps.
                   NO new bids yet — just stale book update.
  Phase 2 (+3.7s): Actual HIP-2 rebalance fires.
                   4 new bids (1.009-1.018), 1.006 partial replenished → 1000,
                   new partial ask at 1.021 (939.89). Spread returns to 30 bps.
```

### Experiment 5: Sell 5000 QUIZ back (mirror of exp 4)
```
Fill: 4996.5 (IOC partial), 5 bid levels consumed

  Phase 1 (+1.2s): Consumed bids removed. Spread 148 bps.
  Phase 2 (+3.6s): 4 new asks (1.009-1.018), spread returns to 30 bps.
```

### Confirmed Behavior
1. **Two-phase rebalancing** for large fills:
   - Phase 1 (~1s): L2 book reflects consumed levels. Wide spread. No new orders.
   - Phase 2 (~3-4s): HIP-2 rebalance — flips levels, replenishes partials, restores spread.
   - **2-3 second vulnerability window** with wide spread between phases.
2. **Levels flip sides** — price points are permanent, only bid/ask assignment changes
3. **Partials persist at cursor** — the transition point between bids and asks
4. **Filled levels get restocked** — during rebalance, consumed partials are topped up to orderSz
5. **IOC can partial fill** — if insufficient liquidity on target side
6. **Small fills (< 1 level)** rebalance in a single phase (~1.2s), no spread disruption

## Historical Trade Data (@37)

All visible HIP-2 trades execute at **exactly the ladder levels** (1.003 bid, 1.006 ask).
Non-HIP-2 trades (between users) can execute at arbitrary prices (e.g., 1.0048).

```
Jan  4 2026: user sells 12.73 @ 1.003 → HIP-2 buys (0xfff counterparty)
Dec 28 2025: user buys  12.74 @ 1.006 → HIP-2 sells (0xfff counterparty)
Dec 13 2025: user sells  3.31 @ 1.003 → HIP-2 buys
...
Jul 30 2025: user sells 133.89 @ 1.003 → HIP-2 buys
```

Net: HIP-2 is a net buyer of QUIZ (~172 tokens), consistent with the heavily
ask-skewed book (2 bids vs 98 asks).

## High Market Cap Experiments (March 2026)

Tested on @929 (SLTEST) — a $10M+ market cap HIP-2 market with orderSz=2500, price ~$44.

### Experiment 6: Pump @929 through 4 levels ($348k spent)

```
Bought 7,934 tokens in 4 batches, pushing through ask levels:
  Level 1: 2501 @ $43.699 = $109,291 → rebalance +1.3s (single phase)
  Level 2:  433 @ $43.699 = $18,922  → rebalance +1.3s/+2.5s (two phase, 60bps→30bps)
  Level 3: 2500 @ $43.830 = $109,575 → rebalance +1.3s (single phase)
  Level 4: 2500 @ $43.961 = $109,903 → rebalance +1.3s (single phase)

Price move: $43.634 → $44.026 (+0.90%)
3 levels flipped ask→bid, 3 new deep asks appeared, 3 bottom bids scrolled off
```

### Experiment 7: Sell back 7,928 tokens (unwind)

```
Sold 7,928 @ avg $43.816 — single-phase rebalance at +1.2s
All 3 levels flipped back to asks, bottom bids reappeared
Book restored to nearly original state
Round-trip cost: ~$1,050 (spread)
```

### Key Finding: Behavior is price-independent

HIP-2 rebalancing at $10M market cap is **identical** to $100k market cap:
- Same ~1.3s rebalance timing
- Same two-phase pattern for level-boundary fills
- Same 30bps spread restoration
- Always maintains 20+20 visible levels (scrolls deeper levels in/out)

## nOrders Varies Widely

Initial assumption of ~100 levels is WRONG for many markets:

| Market | orderSz | Estimated nOrders | Method |
|--------|---------|-------------------|--------|
| @37 (QUIZ) | 1,000 | ~100 | hold/orderSz = 97,000/1,000 |
| @67 (BLOKED2) | 600 | ~100 | hold/orderSz = 59,722/600 |
| @929 (SLTEST) | 2,500 | **~3,990** | hold/orderSz = 9,976,507/2,500 |
| PURR (mainnet) | 100,000 | ~100 | hold/orderSz = 10,000,000/100,000 |

@929 has ~4,000 levels — the ladder spans `1.003^4000 ≈ 162,000x` in price range.

## Balance API Does NOT Track Live HIP-2 State

The `spotClearinghouseState` for `0xfff...fff`:
- **USDC**: Aggregated across ALL HIP-2 markets ($675M total). Cannot isolate per-market.
- **Token balances**: Per-token but appear to be **static deployment amounts**, NOT live inventory.
  Tested: bought and sold 2500 SLTEST, SLTEST total/hold unchanged at exactly 197,676,507/9,976,507.
- **Conclusion**: HIP-2 inventory is protocol-internal validator state, not exposed via any API.
  The only way to observe HIP-2 state is from the orderbook itself (cursor position, partial level).

## HIP-2 is a Constant-Product AMM on a CLOB

### Mathematical equivalence

A geometric ladder with multiplier `m` and `orderSz` S has the same price impact as a
Uniswap V2 constant-product pool (x·y=k) with reserves `S / ln(m)` tokens per side.

```
HIP-2 price impact:    Δp/p = (Δx / S) · ln(m)
Uniswap V2 impact:     Δp/p = Δx / x_reserve

Set equal:  S / ln(m) = x_reserve
For m=1.003: x_reserve ≈ 333 · S
```

Verified empirically — formulas match to 3 decimal places for normal trade sizes:

```
Buy 100 tokens:   HIP-2 = 0.012%,  Uni V2 = 0.012%
Buy 2,500 tokens: HIP-2 = 0.300%,  Uni V2 = 0.300%
Buy 10,000 tokens: HIP-2 = 1.205%, Uni V2 = 1.213%  (diverges at large size)
```

The only difference: HIP-2 is a staircase (discrete 30bps steps), Uniswap is smooth.
With ~4,000 levels the staircase is effectively continuous.

### Scale comparison

| Pool | orderSz | Equiv. Uniswap depth/side | $1k trade impact |
|------|---------|--------------------------|-----------------|
| @929 HIP-2 | 2,500 @ $44 | $36.7M | 0.003% |
| @37 HIP-2 | 1,000 @ $1 | $334k | 0.05% |

Same mechanism. Same math. Different capital.

**Conclusion**: "HIP-2 grade" liquidity requires 90% of the token supply.