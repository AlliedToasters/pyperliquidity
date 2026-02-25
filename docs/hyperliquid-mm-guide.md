# Building a Rate-Limit-Efficient Market Maker on Hyperliquid

## 1. Understand the Budget Model

This is the single most important thing. Hyperliquid's rate limit is **not** requests-per-minute. It's a **cumulative budget**:

```
budget = 10,000 + cumulative_volume_usd - cumulative_requests
```

Every API mutation (place, modify, cancel) costs 1 from your budget. Every $1 of filled volume earns 1 back. You start with a 10,000 request buffer. When budget hits zero, you're rate-limited to **1 request per 10 seconds**.

Fetch your current state at startup:

```python
rate_limit = info.user_rate_limit(your_address)
cum_vlm = float(rate_limit.get("cumVlm", "0"))
n_used = int(rate_limit.get("nRequestsUsed", 0))
budget = 10_000 + cum_vlm - n_used
```

**Key insight**: Your utilization ratio (`cumulative_volume / cumulative_requests`) must stay >= 1.0 long-term. Every wasted request is a dollar of volume you need to earn back.

## 2. WebSocket-First Architecture (Zero REST Polling)

The info REST API has a separate **1,200 weight/minute** budget. Don't waste it.

Subscribe to everything via WebSocket:
- `allMids` — live mid prices for all markets
- `l2Book` per market — full order book
- `orderUpdates` — your order lifecycle (filled, canceled, resting)
- `userFills` — your fill confirmations
- `webData2` — account equity, positions, margin

The **only** REST calls you should make:
- At startup: `meta()`, `spot_meta()`, `open_orders()`, `user_state()`
- Periodically: `spot_user_state()` for spot balances (no WS feed exists for this)
- Once per minute: `open_orders()` for reconciliation (see section 7)

```python
# Subscribe to everything you need
info.subscribe({"type": "allMids"}, on_all_mids)
info.subscribe({"type": "l2Book", "coin": "@1434"}, on_book)
info.subscribe({"type": "orderUpdates", "user": addr}, on_order_update)
info.subscribe({"type": "userFills", "user": addr}, on_fills)
info.subscribe({"type": "webData2", "user": addr}, on_user_state)
```

## 3. Use `batch_modify`, Not Cancel-Replace

This is the biggest efficiency win. Most MMs do cancel -> place (2 requests per order update). Hyperliquid supports `bulk_modify` which does it in 1 request:

```python
# ONE request to modify multiple orders at once
reqs = [
    {
        "oid": existing_order_id,
        "order": {
            "a": asset_id,      # e.g. 11434 for spot
            "b": is_buy,        # True/False
            "p": str(new_price),
            "s": str(new_size),
            "r": False,         # reduce-only
            "t": {"limit": {"tif": "Alo"}},  # Add Liquidity Only
        },
    }
    for ...
]
result = exchange.bulk_modify(reqs)
```

Similarly, `bulk_orders` for batch placement and `bulk_cancel` for batch cancellation. **One API call = one request against your budget**, regardless of how many orders are in the batch.

**Critical gotcha**: You **cannot** modify an order from buy to sell or vice versa. Hyperliquid rejects cross-side modifications. Match modifies within the same side.

## 4. The Order Differ Pattern (Rate-Limit Conservation Core)

Don't recompute and replace all orders every tick. Instead, diff your desired state against current state and emit only the minimum mutations:

```python
def compute_diff(desired_orders, current_orders, threshold_bps):
    # Step 1: DEAD ZONE — skip entirely if market hasn't moved enough
    current_mid = compute_mid(current_orders)
    desired_mid = compute_mid(desired_orders)
    drift_bps = abs(desired_mid - current_mid) / current_mid * 10_000
    if drift_bps < threshold_bps:
        return empty_diff  # No mutations needed!

    # Step 2: LEVEL-INDEX MATCHING — stable identity across ticks
    # Key each order by (side, level_index) not by price or OID
    current_by_key = {(o.is_buy, o.level_index): o for o in current_orders}

    modifies, places, cancels = [], [], []
    for desired in desired_orders:
        key = (desired.is_buy, desired.level_index)
        existing = current_by_key.get(key)
        if existing is None:
            places.append(desired)  # New level
        elif needs_update(existing, desired):
            modifies.append((existing.oid, desired))  # Modify in-place

    # Step 3: TOLERANCE — skip sub-bps price changes
    # Don't modify if price moved < 0.5 bps AND size changed < 5%
    ...

    # Cancel orders with no matching desired level
    for key, order in current_by_key.items():
        if key not in desired_keys:
            cancels.append(order.oid)

    return Diff(modifies, places, cancels)
```

**Level-index matching** is critical. Assign each order a stable identity (e.g., bid level 0, bid level 1, ..., ask level 0, ask level 1). When the fair value shifts, level 3 on the bid side stays as level 3 — you just modify its price. Without this, you'd cancel+replace everything on every tick.

**Dead zone** (`threshold_bps`): We recommend 10-20 bps on low-volume markets. If the mid hasn't drifted by that amount, the differ returns nothing. This alone can suppress 99% of would-be requotes when orders are resting.

**Per-order tolerance**: Even when the dead zone triggers, skip modifying individual orders that moved less than 0.5 bps in price and less than 5% in size.

## 5. Per-Tick Budget Caps and Priority

Even when you do need to requote, cap mutations per tick:

```python
MAX_REQUESTS_PER_TICK = 20

# Priority: cancels > modifies > places
# Cancels free up margin. Modifies update prices. Places are lowest priority.
if total_mutations > MAX_REQUESTS_PER_TICK:
    remaining = MAX_REQUESTS_PER_TICK
    cancels = cancels[:remaining]
    remaining -= len(cancels)
    modifies = modifies[:remaining]
    remaining -= len(modifies)
    places = places[:remaining]
```

Also maintain a **safety margin** — when budget drops below ~100, only emit cancels:

```python
budget = get_request_budget()
if budget < total_mutations + 100:
    # Only cancels — preserve budget
    emit_cancels(cancels)
    return
```

## 6. Use ALO (Add Liquidity Only) for Everything

All resting orders should use `{"limit": {"tif": "Alo"}}`. This ensures:
1. Your orders **only** rest on the book (maker fills)
2. Maker fills **replenish** your rate-limit budget ($1 volume = 1 request)
3. If your order would cross the spread, it's **rejected** instead of taking

The rejection is a feature, not a bug — it prevents you from accidentally taking liquidity and helps maintain your budget ratio > 1.0.

**Gotcha**: ALO rejections are common. When you place an order that would immediately cross the BBO, the exchange rejects it. Don't retry in a loop — just wait for the next tick.

## 7. State Reconciliation (Belt and Suspenders)

WebSocket feeds are your primary state source, but they can miss events (reconnections, race conditions). Every ~60 seconds, poll the exchange for the actual open orders and reconcile:

```python
async def reconcile():
    exchange_orders = info.open_orders(address)  # 1 REST call
    exchange_oids = {o["oid"] for o in exchange_orders}
    state_oids = {o.oid for o in my_tracked_orders}

    # Orphaned: on exchange but not in our state → cancel them
    orphaned = exchange_oids - state_oids
    if orphaned:
        bulk_cancel(orphaned)  # Leaked orders!

    # Ghost: in our state but not on exchange → remove from state
    ghost = state_oids - exchange_oids
    if ghost:
        remove_from_state(ghost)  # Stale entries
```

This catches order leaks that would otherwise silently accumulate and eat your budget.

## 8. Handle OID Swaps on Modify

When you `bulk_modify` an order, Hyperliquid **may assign a new OID**. If you don't track this, your state goes stale and you start trying to modify non-existent orders:

```python
result = exchange.bulk_modify(reqs)
statuses = result["response"]["data"]["statuses"]
for i, status in enumerate(statuses):
    if "resting" in status:
        new_oid = status["resting"]["oid"]
        if new_oid != original_oid:
            # OID changed! Update your state
            update_oid_in_state(original_oid, new_oid)
```

## 9. Ghost Order Detection from Modify Errors

When you try to modify an order that was already filled (but the WS event hasn't arrived yet), you get a "Cannot modify" error. Remove it from state immediately rather than retrying:

```python
for i, status in enumerate(statuses):
    if "error" in status and "Cannot modify" in status["error"]:
        # Order no longer exists — remove from tracking
        remove_from_state(modifies[i].oid)
```

## 10. Rejection Cooldowns

If placements keep getting rejected (e.g., "Insufficient spot balance"), don't keep retrying every tick. Implement cooldowns:

```python
# After "Insufficient spot balance" → suppress that side for 60s
# After 3 consecutive generic rejections → suppress for 10s
if "Insufficient spot balance" in error:
    cooldown[(coin, side)] = now + 60
elif consecutive_rejects[(coin, side)] >= 3:
    cooldown[(coin, side)] = now + 10
```

Without this, a single missing token can burn hundreds of requests per minute on futile placements.

## 11. `orderUpdates` Format Gotcha

The status field is at the **top level** of the update, NOT inside the order object:

```python
# CORRECT
for update in data:
    status = update["status"]         # "filled", "canceled", "resting"
    order = update["order"]
    oid = order["oid"]
    coin = order["coin"]

# WRONG — this field doesn't exist
    status = update["order"]["status"]  # KeyError!
```

## 12. Fill Deduplication

On WebSocket reconnect, you may receive **replayed fills**. Deduplicate by trade ID (`tid`):

```python
seen_tids = set()

def on_fill(fill):
    tid = fill.get("tid")
    if tid in seen_tids:
        return  # Already processed
    seen_tids.add(tid)
    # Process fill...

    # Prune periodically to prevent unbounded growth
    if len(seen_tids) > 10_000:
        seen_tids = set(sorted(seen_tids)[5000:])  # Keep recent half
```

## 13. Thread-to-Async Bridge

The Hyperliquid Python SDK uses synchronous daemon threads for WebSocket callbacks. If your main loop is async, you need a bridge:

```python
def on_ws_message(msg):
    """Called from SDK's sync thread."""
    asyncio.run_coroutine_threadsafe(
        state.handle_update(msg),
        main_loop
    )
```

Also wrap all blocking SDK calls with `asyncio.to_thread()` so they don't block your tick loop:

```python
result = await asyncio.to_thread(exchange.bulk_modify, reqs)
```

## 14. Monitoring: The One Log Line You Need

Log this every minute:

```
Utilization: ratio=1.12 budget=70985 vol=$583479 reqs=522489
  state_orders=60 exchange_orders=60
```

- **ratio >= 1.0**: Healthy. You're earning more budget than spending.
- **ratio < 1.0**: Danger. Widen dead zones, reduce levels, or fix a leak.
- **state_orders != exchange_orders**: You have a state drift bug. Fix it before it drains your budget.

## 15. Asset ID Formula

For spot tokens, the asset ID is `spot_index + 10000`. Get the index from `spot_meta()["universe"]`:

```python
meta = info.spot_meta()
for entry in meta["universe"]:
    if entry["name"] == "@1434":  # THC
        asset_id = entry["index"] + 10000  # e.g. 11434
```

Don't hardcode these — fetch at startup.

---

## Recommended Architecture

```
WebSocket Feeds ──► StateManager ──► QuotingEngine ──► OrderDiffer ──► BatchEmitter ──► API
     ▲                (single source      (pure math,     (dead zone +     (budget-aware,   │
     │                 of truth)           no I/O)         level-index      prioritized)     │
     └──────────── orderUpdates / userFills / webData2 ──────────────────────────────────────┘
```

The key insight: **separate computation from I/O completely**. The quoting engine is pure math. The differ decides what changed. The emitter decides whether to actually send it based on budget. This separation makes each piece testable and the budget predictable.
