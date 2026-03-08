## 1. Pricing Grid

- [x] 1.1 Update pricing_grid spec to document 5sf default rounding (spec says 8sf, implementation already uses 5sf via `_default_round`)
- [x] 1.2 Remove standalone `generate_ask_levels` and `generate_bid_levels` functions from `pricing_grid.py` (replaced by `PricingGrid` usage in quoting engine)
- [x] 1.3 Update pricing_grid tests to verify 5sf rounding against known HIP-2 ladder values (@67 BLOKED2: start_px=0.020777, level 20=0.022060)

## 2. Quoting Engine (core rewrite)

- [x] 2.1 Rewrite `compute_desired_orders` interface: accept `(grid: PricingGrid, effective_token, effective_usdc, order_sz, min_notional)`, return `list[DesiredOrder]`. Remove `QuoteResult` class.
- [x] 2.2 Implement cursor derivation: `n_full_asks = floor(effective_token / order_sz)`, `partial = effective_token % order_sz`, `cursor = n_orders - total_ask_levels`
- [x] 2.3 Implement ask placement ascending from cursor: partial ask at cursor level (if remainder > 0), full asks ascending, truncate at grid max
- [x] 2.4 Implement bid placement descending from cursor-1: full bids funded by USDC, partial bid when USDC runs out, stop at level 0
- [x] 2.5 Implement min_notional filtering: exclude orders where `price * size < min_notional`
- [x] 2.6 Ensure `DesiredOrder.level_index` uses absolute grid positions (0 to n_orders-1)
- [x] 2.7 Rewrite quoting engine tests: cursor derivation, ask/bid placement, edge cases (all tokens sold, all USDC spent, both zero, grid overflow, partial orders, min_notional filtering)

## 3. CLI Configuration

- [x] 3.1 Add `strategy.start_px` as a required config field with positive-value validation
- [x] 3.2 Pass `start_px` to `WsState` constructor in `_build_ws_state`
- [x] 3.3 Update `n_orders` semantics: document/validate as total grid levels (not per-side)

## 4. WsState Wiring

- [x] 4.1 Add `start_px` parameter to `WsState.__init__`
- [x] 4.2 Construct `PricingGrid(start_px, n_orders)` in `_startup()`, store as `self.grid`
- [x] 4.3 Replace `_price_to_level_index` with `self.grid.level_for_price(px)` for startup order seeding (handle `None` return for orders outside grid range)
- [x] 4.4 Update `_tick()` to call `compute_desired_orders(self.grid, inv.effective_token, inv.effective_usdc, self.order_sz, self.min_notional)`
- [x] 4.5 Remove `_last_mid` field and floating-mid computation
- [x] 4.6 Update tick logging: replace mid_price with cursor-level price (`grid.price_at_level(cursor)`)
- [x] 4.7 Update `_handle_order_update` to use `self.grid.level_for_price(px)` for level index assignment on resting/open order updates

## 5. Order Differ

- [x] 5.1 Verify order_differ works with absolute grid-position level indices (no code changes expected — matching logic is index-agnostic, but confirm with tests)
- [x] 5.2 Update or add tests: level flip scenario (cursor shift causes side change at same level_index → cancel + place)

## 6. Integration

- [x] 6.1 Run full test suite, fix any import or interface breakage from QuoteResult removal and signature changes
- [x] 6.2 Verify end-to-end: construct PricingGrid → compute_desired_orders → compute_diff → emit pipeline with sample data matching reverse-engineered HIP-2 behavior
