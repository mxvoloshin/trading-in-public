# SPY VWAP Range-Reversion Stop Validation

Repository: `mxvoloshin/trading-in-public`  
Validated on: `2026-06-30`  
Strategies checked:
- `spy-vwap-range-reversion-base`
- `spy-vwap-range-reversion-1-5atr-band`

## Why This Validation Was Needed

The original range-reversion implementation used the same VWAP-distance multiple for both:

- entry gating
- protective stop placement

For the `1.5 ATR` variant, that meant a long could enter at `close <= VWAP - 1.5 ATR` while the stop was also set to `VWAP - 1.5 ATR`. The short side had the same issue on the other side of VWAP.

That made the stop capable of landing at, or effectively inside, the entry level. Reported PnL from the earlier run should therefore not be trusted until the stop logic is corrected and rerun.

## Fix Applied

- Separated entry-band distance from stop distance.
- Corrected stop rule to be entry-relative:
  - long stop = `entry_price - 1.0 ATR`
  - short stop = `entry_price + 1.0 ATR`
- Added validation guards:
  - `invalid_long_stop_not_below_entry`
  - `invalid_short_stop_not_above_entry`
- Added regression coverage proving:
  - long stop is below entry
  - short stop is above entry
  - invalid stop placement is rejected
  - same-bar stop/target handling is conservative and stop-first unless the bar opens beyond the target

## Red-Capable Test Loop

```sh
python3 -m uv run pytest tests/trade_strategies/test_spy_vwap_pullback.py -k 'range_reversion and (stop or invalid)'
```

This loop failed before the fix and passes after the fix.

## Old vs Fixed Results

Trade counts below are from the costed comparison run. Gross and costed PnL are shown side by side for the same pre-fix vs fixed strategy variant.

### `spy-vwap-range-reversion-base`

| Version | Trades | Long | Short | Gross PnL | Costed PnL | PF | Exp/Trade | Max DD | Worst 6mo | Largest Trade % of Total PnL | Top 5 Abs % of Total PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre-fix | 169 | 75 | 94 | `$25.4191` | `$0.8790` | `1.0300` | `$0.0052` | `-$6.6481` | `-$5.4601` | `274.52%` | `1008.82%` |
| Fixed | 154 | 72 | 82 | `$2.3444` | `-$24.8627` | `0.6701` | `-$0.1614` | `-$24.8876` | `-$16.9455` | `-12.74%` | `-51.40%` |

Stress:

| Scenario | Pre-fix | Fixed |
|---|---:|---:|
| 2 bps slippage-only | `-$20.2811`, PF `0.5323` | `-$45.9548`, PF `0.4613` |
| 3 bps slippage-only | `-$43.1311`, PF `0.2891` | `-$72.8240`, PF `0.2821` |
| IBKR Canada fixed approximation | `-$335.4310`, PF `0.0015` | `-$331.3227`, PF `0.0085` |
| IBKR Canada tiered approximation | `-$115.7310`, PF `0.0648` | `-$131.1227`, PF `0.1304` |

### `spy-vwap-range-reversion-1-5atr-band`

| Version | Trades | Long | Short | Gross PnL | Costed PnL | PF | Exp/Trade | Max DD | Worst 6mo | Largest Trade % of Total PnL | Top 5 Abs % of Total PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre-fix | 111 | 50 | 61 | `$40.9584` | `$24.8321` | `10.8307` | `$0.2237` | `-$0.2858` | `$1.2210` | `9.72%` | `35.47%` |
| Fixed | 91 | 42 | 49 | `$6.3536` | `-$9.5115` | `0.7920` | `-$0.1045` | `-$12.2999` | `-$11.4066` | `-33.29%` | `-134.37%` |

Stress:

| Scenario | Pre-fix | Fixed |
|---|---:|---:|
| 2 bps slippage-only | `$10.9258`, PF `2.2557` | `-$20.7669`, PF `0.6065` |
| 3 bps slippage-only | `-$4.0905`, PF `0.7742` | `-$42.0164`, PF `0.3663` |
| IBKR Canada fixed approximation | `-$196.0579` | `-$190.6015`, PF `0.0146` |
| IBKR Canada tiered approximation | `-$51.7579` | `-$72.3015`, PF `0.2080` |

## Interpretation

- The earlier `1.5 ATR` result was materially overstated by the invalid stop logic.
- After the fix, the headline candidate no longer survives the base decision cost model.
- The strategy does not merely weaken; it flips from strongly positive to negative after costs.
- The base range-reversion variant also degrades from slightly positive after costs to clearly negative after costs.

## Final Decision

Decision: invalid candidate

- Treat the prior `spy-vwap-range-reversion-1-5atr-band` result as bugged and invalid for decision-making.
- Mark the previous result as `invalidated by stop-placement bug`.
- Do not trust the earlier reported PnL, PF, drawdown, or concentration claims from the pre-fix run.
- Do not advance either checked range-reversion variant to paper trading.
- Any future range-reversion research should start from the corrected stop logic only.
