## Context

The batch emitter sits at the right edge of the computation pipeline: `QuotingEngine → OrderDiffer → BatchEmitter → Hyperliquid API`. All upstream modules are pure (no I/O). The batch emitter is the only module that touches the exchange — it translates an `OrderDiff` into SDK batch calls while respecting the rate-limit budget model.

Existing modules provide the inputs:
- `order_differ.OrderDiff` contains `modifies`, `places`, and `cancels` lists
- `rate_limit.RateLimitBudget` provides `remaining()`, `is_emergency()`, and `on_request()`
- `order_state.OrderState` provides lifecycle notifications (`on_place_confirmed`, `on_modify_response`, `remove_ghost`)

The Hyperliquid SDK's `exchange` object is synchronous (runs on daemon threads). All calls must be wrapped with `asyncio.to_thread()`.

## Goals / Non-Goals

**Goals:**
- Execute OrderDiff mutations via SDK batch ops (bulk_cancel, bulk_modify, bulk_orders)
- Gate on budget: cancel-only mode when budget is low, trim by priority when over per-tick cap
- Process every response status and forward outcomes to order_state
- Track per-(coin, side) cooldowns for futile placement suppression
- Defensive cross-side modify assertion (order_differ already prevents this)

**Non-Goals:**
- Computing what orders to place (quoting_engine's job)
- Deciding what changed (order_differ's job)
- WebSocket event processing (ws_state's job)
- Tracking cumulative fill volume (rate_limit is updated by order_state via fill events)

## Decisions

### 1. Single `emit()` async entry point

`async emit(diff: OrderDiff, budget: RateLimitBudget) -> EmitResult`

The emitter receives the diff and budget snapshot, performs gating/trimming, executes batch calls, and returns a result summarizing what happened.

**Rationale**: One call per tick keeps the interface simple. The caller doesn't need to know about internal batching or priority ordering.

**Alternative considered**: Separate `emit_cancels()`, `emit_modifies()`, `emit_places()` — rejected because budget gating and priority trimming need a global view of all mutations.

### 2. Priority ordering: cancels > modifies > places

When budget is constrained, trim from lowest priority first (places, then modifies). Cancels are always emitted.

**Rationale**: Cancels free up margin and remove stale risk. Modifies update existing exposure. Places add new exposure — safest to drop.

### 3. Constants: SAFETY_MARGIN=100, MAX_MUTATIONS_PER_TICK=20

- `SAFETY_MARGIN=100`: Below this remaining budget, switch to cancel-only mode. Lower than rate_limit's `SAFETY_MARGIN=500` because the emitter's threshold is for cancel-only emergency mode, not general alerting.
- `MAX_MUTATIONS_PER_TICK=20`: Upper bound on total individual order mutations per tick. Since batch ops cost 1 regardless of size, this limits the number of orders inside the batches (not the number of API calls). At most 3 API calls per tick (one per batch type).

**Rationale**: These are conservative defaults matching the spec. The per-tick cap prevents a single tick from burning excessive budget when the book structure changes dramatically (e.g., reconnection placing dozens of orders).

### 4. Cooldown state as a dict[(coin, side)] -> expiry timestamp

When `bulk_orders` returns "Insufficient spot balance", cool down that side for 60s. When 3+ consecutive generic rejects occur, cool down for 10s. Cooldowns are checked before including a `DesiredOrder` in the places batch.

**Rationale**: Prevents futile retry loops that burn budget. Using a timestamp-based expiry (via `time.monotonic()`) is simpler than a counter-based approach and naturally handles variable tick intervals.

### 5. Wrapping SDK calls with asyncio.to_thread()

```python
result = await asyncio.to_thread(exchange.bulk_modify, reqs)
```

**Rationale**: The Hyperliquid SDK is synchronous. `asyncio.to_thread()` delegates to the default executor without blocking the event loop.

### 6. EmitResult dataclass for observability

```python
@dataclass(frozen=True)
class EmitResult:
    n_cancelled: int
    n_modified: int
    n_placed: int
    n_errors: int
    cancel_only_mode: bool
```

**Rationale**: The caller (state manager or main loop) needs to know what happened for logging and monitoring without parsing raw SDK responses.

### 7. Cross-side modify assertion

Assert that every modify in the diff has the same side as the existing tracked order. The order_differ already prevents cross-side modifies, but a defensive assertion at the emitter boundary catches bugs early.

**Rationale**: Hyperliquid silently rejects cross-side modifies. A local assertion gives a clear error message instead of mysterious exchange errors.

## Risks / Trade-offs

- **[Risk] SDK response format changes**: The emitter parses string statuses from SDK responses. → Mitigation: Centralize response parsing in helper methods so format changes only require updates in one place.
- **[Risk] asyncio.to_thread() contention**: Multiple ticks could overlap if emission takes longer than the tick interval. → Mitigation: The caller should gate on the previous emit completing before starting a new tick. The emitter itself is stateless per-call (except cooldowns).
- **[Risk] Cooldown too aggressive**: A 60s cooldown on "Insufficient spot balance" might miss legitimate placement opportunities. → Mitigation: Clear cooldown on successful placement. The 60s is a safe upper bound; fills will trigger new ticks that can re-evaluate.
- **[Risk] ALO rejections counted as errors**: ALO orders that would cross the spread are rejected — this is normal, not an error. → Mitigation: Parse for ALO-specific rejection text and exclude from the consecutive reject counter.
