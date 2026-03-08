## MODIFIED Requirements

### Requirement: Default rounding uses 5 significant figures

The default `round_fn` SHALL round to 5 significant figures, matching observed HIP-2 ladder prices on Hyperliquid mainnet and testnet. This is verified against live orderbooks (@67 BLOKED2, @37 QUIZ, @929 SLTEST) where all visible prices match `round(px * 1.003, 5sf)` exactly.

The `round_fn` parameter remains configurable — callers MAY pass a custom rounding function. When omitted, the default 5sf rounding applies.

#### Scenario: Default rounding produces 5 significant figures
- **WHEN** a `PricingGrid` is constructed with `start_px=0.020777` and default `round_fn`
- **THEN** level 1 is `0.020839` (5sf of `0.020777 * 1.003 = 0.02083933...`)

#### Scenario: Grid matches verified HIP-2 market (@67 BLOKED2)
- **WHEN** `PricingGrid(start_px=0.020777, n_orders=40, tick_size=0.003)` is constructed with default rounding
- **THEN** level 20 price is `0.022060` and all 40 levels match the observed HIP-2 orderbook exactly

#### Scenario: Custom rounding overrides default
- **WHEN** `round_fn=lambda px: round(px, 4)` is passed
- **THEN** all levels are rounded to 4 decimal places instead of 5 significant figures
