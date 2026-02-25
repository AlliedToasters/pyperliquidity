# Batch Emitter

## Purpose

Receive an OrderDiff and execute it against the Hyperliquid API, respecting rate-limit budget constraints and using batch operations for efficiency. This is the only module that performs exchange I/O for order management.

## Interface

```
async emit(diff: OrderDiff, budget: RateLimitBudget) -> EmitResult
```

## Batch Operations

All mutations use batch API calls (1 API request per batch, regardless of batch size):
- `bulk_modify(reqs)` — Modify existing orders (1 request)
- `bulk_orders(reqs)` — Place new orders (1 request)
- `bulk_cancel(reqs)` — Cancel orders (1 request)

A full diff execution costs at most 3 API requests (one per operation type).

## Emission Priority

When budget is constrained, prioritize:
1. **Cancels** — Free up margin, remove stale risk
2. **Modifies** — Update prices on existing orders
3. **Places** — Add new orders (lowest priority)

## Budget Gating

```
if budget.remaining < total_mutations + SAFETY_MARGIN:
    # Emergency mode: cancels only
    emit only cancels
    return

if total_mutations > MAX_REQUESTS_PER_TICK:
    # Trim by priority (cancels > modifies > places)
    trim to MAX_REQUESTS_PER_TICK
```

Recommended `SAFETY_MARGIN`: 100. Recommended `MAX_REQUESTS_PER_TICK`: 20.

## Order Parameters

All resting orders use ALO (Add Liquidity Only):
```python
{"limit": {"tif": "Alo"}}
```

Spot asset IDs: `asset_id = spot_index + 10000` (fetched from `spot_meta()` at startup).

## Response Handling

### bulk_modify responses
For each status in the response:
- `"resting"`: Check if OID changed → notify order_state to re-key
- `"error"` with `"Cannot modify"`: Order was filled → notify order_state to remove

### bulk_orders responses
- `"resting"`: Extract OID → notify order_state to track
- `"error"` with `"Insufficient spot balance"`: Suppress that side for 60s cooldown
- 3+ consecutive generic rejections: Suppress for 10s cooldown

### bulk_cancel responses
- Success: Notify order_state to remove
- Error: Order may have been filled — notify order_state to remove anyway

## Thread Safety

The Hyperliquid SDK uses synchronous calls. Wrap with `asyncio.to_thread()`:
```python
result = await asyncio.to_thread(exchange.bulk_modify, reqs)
```

## Invariants

1. Never more than `MAX_REQUESTS_PER_TICK` API requests per tick
2. Never emit when budget < `SAFETY_MARGIN` (except cancels)
3. All resting orders use ALO time-in-force
4. Response statuses are always processed and forwarded to order_state
5. Cooldowns prevent repeated futile placements

## Dependencies

- `order_state`: Notified of all response outcomes (OID changes, fills, removals)
- `rate_limit`: Queried for current budget before emission
- Hyperliquid SDK: `exchange.bulk_modify()`, `exchange.bulk_orders()`, `exchange.bulk_cancel()`
