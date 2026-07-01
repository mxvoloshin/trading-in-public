# SPY ORB Thesis Note

## Hypothesis

SPY 5-minute opening-range breakouts may provide a tradeable intraday edge when
the strategy waits for a completed-bar breakout, uses strict regular-session
rules, and keeps execution assumptions simple.

## Instrument / Timeframe / Session

- instrument: `SPY`
- timeframe: `5Min`
- market: `XNYS`
- session: `regular`

## Baseline Rules To Test First

- use only regular-session bars
- define the opening range from the first 30 minutes
- wait for a completed-bar breakout after `10:00` New York time
- fill at the next bar open
- cap new entries after `14:30` New York time
- force flat into the final regular-session bar
- start with midpoint-stop and opposite-stop baseline variants

## Why This May Work

- the opening range can act as a simple intraday structure boundary
- completed-bar confirmation can reduce false breakout noise
- a tight session window keeps the rules aligned with liquid regular trading
- the setup is simple enough to validate before adding filters

## Why This May Fail

- the edge may be highly dependent on one market window
- slippage can erase a small gross edge quickly
- breakouts may need stronger entry context than price alone
- a few large trades may dominate total PnL

## Kill Criteria

- baseline remains negative after costs
- the result collapses under basic slippage stress
- concentration risk is too high
- expanded validation does not hold up

## Next Implementation Step

Use `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1` as the working
baseline and test one improvement at a time from there.
