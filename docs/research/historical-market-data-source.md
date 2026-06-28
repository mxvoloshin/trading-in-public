# Historical Market Data Source Decision

Date: 2026-06-28

Issue: [#8](https://github.com/mxvoloshin/trading-in-public/issues/8)

## Decision

Use **Alpaca historical stock bars** as the v1 historical market data source for U.S.-listed ETF backtesting.

The first implementation should fetch **5-minute raw SIP bars** for a U.S.-listed ETF such as `SPY`, cache raw provider responses locally, and normalize the data into a small project-owned bar shape for strategy research and future backtests.

## Decision Summary

- Provider: Alpaca historical stock bars
- Initial scope: U.S.-listed ETFs/stocks only
- First likely instrument: `SPY`
- Timeframe: `5Min`
- Feed: `sip`, not `iex`
- Adjustment: `raw`
- Session default: regular trading hours only
- Session/calendar behavior: configurable, not hard-coded to NYSE forever
- Access mode: direct HTTP API
- SDK dependency: do not add Alpaca SDK for v1 unless direct HTTP proves inadequate
- Storage: gitignored local `.data/` cache only
- Public repo rule: do not commit downloaded market data, raw provider payloads, or credentials

## Why Alpaca

The deciding project constraint is that v1 should be free and only needs enough recent intraday data for the first backtesting milestone. Alpaca is a better fit for that constraint than paid historical-data vendors.

Alpaca's historical stock bars endpoint supports direct HTTP access to stock bar data with parameters for symbols, timeframe, feed, adjustment, date range, and pagination. Alpaca's market data documentation also describes free access to historical SIP data when the requested end time is at least 15 minutes behind current time, which is acceptable for backtesting because the system does not need live recency for this milestone.

The v1 implementation should therefore optimize for:

- a small working historical-data path
- repeatable local API fetches
- enough recent intraday history for strategy experiments
- provider details isolated behind `trade_data`
- no public redistribution of real market data

## Why Not Massive / Polygon For V1

Massive/Polygon remains a credible paid fallback, especially if the project later needs a broader paid historical-data foundation, more history, or bulk download workflows.

It is not the selected v1 source because the current constraint is **free access** and about **one year of recent intraday data**, not maximum paid data quality or full-history depth.

## Why Not Alpha Vantage

Alpha Vantage has clear documentation and a useful demo endpoint, but historical intraday use is not the best fit for this project compared with Alpaca's free historical stock bars path. It is acceptable as a documentation or schema sanity-check source, but it should not be the canonical v1 data layer.

## Why Not EODHD

EODHD is inexpensive and broad, but its public materials describe pricing data as not exchange-feed data and aggregated from many sources. That weakens confidence for a repeatable backtesting foundation where volume and venue coverage matter.

## Why Not Tiingo

Tiingo's IEX-based intraday product is useful for some low-cost exploratory work, but IEX is a single venue. It is not a good canonical source for full-market ETF backtests where market-wide volume matters.

## Why Not IBKR Historical Data

IBKR historical data may be useful later for broker-parity checks, especially if live execution uses IBKR. It is not the v1 historical backtesting source because it adds account/session/API complexity and is not primarily a historical market data warehouse.

## Why Not Stooq Or yfinance

Stooq and yfinance can be useful for quick exploration or sanity checks, but they are not suitable as the canonical v1 source for one year of reliable 5-minute U.S. ETF backtesting data.

## TSX Scope

TSX historical data is deferred.

Alpaca's documented asset and market data coverage is centered on U.S. equities and related U.S. venues, not TSX/TSXV historical bars. The first implementation should not try to solve free one-year 5-minute TSX data. A later issue can choose a Canadian market data source when the strategy work needs TSX-listed ETFs.

The code should still keep market sessions and calendars configurable from day one, because future work may need different exchanges and holiday calendars.

Example configuration direction:

```yaml
market_sessions:
  xnas_or_xnys:
    timezone: America/New_York
    regular_open: "09:30"
    regular_close: "16:00"
  xtse:
    timezone: America/Toronto
    regular_open: "09:30"
    regular_close: "16:00"
```

## Data Semantics

The v1 fetch should explicitly request:

```text
feed=sip
timeframe=5Min
adjustment=raw
```

Use `sip` rather than `iex` because IEX is single-venue data. A full-market SIP feed is the better default for backtests that should represent U.S.-listed ETF trading more broadly.

Use `raw` bars because the first backtests should simulate prices as they traded at the time. Adjusted data can be useful for longer-term research, but adjusted OHLC prices may not represent executable historical prices. Corporate actions should be handled separately in a future issue if needed.

Use regular trading hours only by default. Extended-hours trading has different liquidity, spreads, and execution assumptions. The loader may classify or filter sessions, but strategy research should start with regular sessions.

## Strategy-Facing Bar Shape

Keep strategy inputs minimal and provider-neutral:

```python
Bar(
    instrument_id="SPY.US",
    timeframe="5Min",
    timestamp_utc="2026-06-26T19:55:00Z",
    open=...,
    high=...,
    low=...,
    close=...,
    volume=...,
    session="regular",
)
```

Provider details should stay outside the strategy-facing bar. They may exist in loader metadata or request metadata:

```python
BarSource(
    provider="alpaca",
    provider_symbol="SPY",
    feed="sip",
    adjustment_mode="raw",
    currency="USD",
)
```

Do not add strategy-facing `trade_count`, `vwap`, spread, dividend, split, or provider fields in v1 unless the first strategy proves that they are required.

## Local Cache And Repository Rules

The repo should include code, docs, configuration examples, and reproduction instructions. It should not include real downloaded market data.

Use a gitignored local cache such as:

```text
.data/
  alpaca/
    stock_bars/
      SPY/
        5Min/
          raw/
            2025-06-28_2026-06-27_feed-sip_adjustment-raw.json
```

Do not commit:

- Alpaca API keys or secrets
- `.env` files
- downloaded OHLCV data
- raw Alpaca API responses
- real provider cache files
- broker/account identifiers
- private financial data

Tests should use generated synthetic bars or small fake records created in code. Do not commit real provider data as test fixtures.

## Tiny Proof

The proof should use the selected v1 provider.

Example command shape:

```bash
curl -s \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY_ID" \
  -H "APCA-API-SECRET-KEY: $ALPACA_API_SECRET_KEY" \
  "https://data.alpaca.markets/v2/stocks/bars?symbols=SPY&timeframe=5Min&feed=sip&adjustment=raw&start=2025-06-28T00:00:00Z&end=2026-06-27T23:59:00Z&limit=1000" \
  | jq '.bars.SPY[0:3]'
```

The proof should demonstrate that the response can be mapped into the strategy-facing `Bar` shape without committing the response body.

## Follow-Up Implementation

Issue [#9](https://github.com/mxvoloshin/trading-in-public/issues/9) should implement the base market data layer using this decision.

The implementation should:

- call Alpaca historical stock bars through direct HTTP
- fetch at least `SPY`, `5Min`, `feed=sip`, `adjustment=raw`
- keep requested end time at least 15 minutes behind current time for free SIP historical access
- cache raw responses under `.data/`
- normalize provider responses into project-owned bars
- default to regular trading hours
- keep sessions/calendars configurable
- avoid committing real provider data
- avoid adding the Alpaca SDK unless direct HTTP proves inadequate

## Sources

- Alpaca historical bars endpoint: <https://docs.alpaca.markets/us/reference/stockbars>
- Alpaca market data FAQ: <https://docs.alpaca.markets/us/docs/market-data-faq>
- Alpaca market data overview: <https://alpaca.markets/data>
- Alpaca market data API documentation: <https://docs.alpaca.markets/us/docs/about-market-data-api>
- Alpaca assets endpoint: <https://docs.alpaca.markets/us/reference/get-v2-assets-1>
- Massive custom bars documentation: <https://massive.com/docs/rest/stocks/aggregates/custom-bars>
- Alpha Vantage documentation: <https://www.alphavantage.co/documentation/>
- Databento OHLCV documentation: <https://databento.com/docs/schemas-and-data-formats/ohlcv>
- EODHD intraday API documentation: <https://eodhd.com/financial-apis/intraday-historical-data-api>
