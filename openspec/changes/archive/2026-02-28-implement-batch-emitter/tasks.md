## 1. Data Model

- [x] 1.1 Implement EmitResult frozen dataclass (n_cancelled, n_modified, n_placed, n_errors, cancel_only_mode)
- [x] 1.2 Define constants: SAFETY_MARGIN=100, MAX_MUTATIONS_PER_TICK=20, BALANCE_COOLDOWN_S=60, REJECT_COOLDOWN_S=10, CONSECUTIVE_REJECT_THRESHOLD=3

## 2. BatchEmitter Core

- [x] 2.1 Implement BatchEmitter.__init__ accepting coin, asset_id, exchange, order_state, and optional clock callable (default time.monotonic)
- [x] 2.2 Implement budget gating logic: cancel-only mode when budget.remaining() < total_mutations + SAFETY_MARGIN
- [x] 2.3 Implement priority trimming: when total mutations > MAX_MUTATIONS_PER_TICK, trim places first, then modifies; never trim cancels
- [x] 2.4 Implement cooldown check: filter out DesiredOrder placements where (coin, side) cooldown has not expired

## 3. SDK Call Execution

- [x] 3.1 Implement _execute_cancels: build bulk_cancel request, call via asyncio.to_thread(), notify order_state.remove_ghost for each, call budget.on_request()
- [x] 3.2 Implement _execute_modifies: build bulk_modify request with ALO TIF, call via asyncio.to_thread(), parse each response for OID swap or "Cannot modify" error, forward to order_state.on_modify_response(), call budget.on_request()
- [x] 3.3 Implement _execute_places: build bulk_orders request with ALO TIF, call via asyncio.to_thread(), parse each response for "resting" (extract OID → on_place_confirmed), "Insufficient spot balance" (set 60s cooldown), ALO rejections (skip), generic rejects (track consecutive count → 10s cooldown), call budget.on_request()
- [x] 3.4 Implement cross-side modify assertion: before building modify request, assert each modify's desired side matches the tracked order's side

## 4. Main emit() Entry Point

- [x] 4.1 Implement async emit(diff, budget) orchestrating gating → trimming → cooldown filter → execute_cancels → execute_modifies → execute_places → return EmitResult

## 5. Tests

- [x] 5.1 Test budget gating: cancel-only mode suppresses modifies and places when budget is low
- [x] 5.2 Test priority trimming: places trimmed first, then modifies, cancels never trimmed
- [x] 5.3 Test emission ordering: cancels before modifies before places
- [x] 5.4 Test OID swap forwarding: bulk_modify response with new OID calls order_state.on_modify_response correctly
- [x] 5.5 Test ghost detection: "Cannot modify" error forwards to order_state
- [x] 5.6 Test bulk_orders response handling: "resting" calls on_place_confirmed, "Insufficient spot balance" sets cooldown
- [x] 5.7 Test cooldown suppresses placements for cooled-down side, clears on success
- [x] 5.8 Test ALO rejections not counted toward consecutive reject counter
- [x] 5.9 Test rate limit notification: budget.on_request() called once per batch API call
- [x] 5.10 Test cross-side modify raises AssertionError
- [x] 5.11 Test empty diff produces no API calls
- [x] 5.12 Test cancel errors still remove from order_state
