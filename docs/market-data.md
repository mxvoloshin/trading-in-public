# Market Data

This document explains how to prepare local historical market data for research
and backtests.

The source is Alpaca historical stock bars for U.S.-listed stocks and ETFs.
Real market data is stored only in a gitignored local `.data/` directory.

## Credentials

Create Alpaca API credentials in Alpaca, then export them in your shell:

```bash
export ALPACA_API_KEY_ID="your-key-id"
export ALPACA_API_SECRET_KEY="your-secret-key"
```

If you keep credentials in a local `.env` file, do not commit it. Load it at the shell level:

```bash
set -a
source .env
set +a
```

The project does not require `python-dotenv`.

## Fetch Historical Bars

Use the research app to fetch and normalize data:

```bash
uv run python -m trade_research_app market-data fetch \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

If `uv` is not on your `PATH`, use:

```bash
python3 -m uv run python -m trade_research_app market-data fetch \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

Date arguments are market-local inclusive dates. For `XNYS`, `2026-06-26` means the full New York market-local day.

## Local Files

Raw Alpaca JSON responses are saved by request and page:

```text
.data/
  alpaca/
    stock_bars/
      SPY/
        5Min/
          raw/
            2025-06-28_2026-06-27_feed-sip_adjustment-raw_page-001.json
```

Normalized project-owned bars are saved as daily JSONL partitions:

```text
.data/
  market_data/
    bars/
      SPY.US/
        5Min/
          XNYS/
            regular/
              2026-06-26.jsonl
```

Normalized bars contain provider-neutral data only:

```json
{"close":100.5,"high":101.0,"instrument_id":"SPY.US","low":99.5,"open":100.0,"session":"regular","timeframe":"5Min","timestamp_utc":"2026-06-26T13:30:00Z","volume":1234}
```

## Current Limitations

- Only Alpaca historical stock bars are implemented.
- `feed=sip`, `adjustment=raw`, and Alpaca pagination are used by default.
- `SPY` with `XNYS` maps to project instrument ID `SPY.US`.
- The market session calendar is lightweight: timezone, regular open/close, weekdays, and optional manually configured holidays.
- Automated tests use fake data and do not call Alpaca.

## Public Safety

Do not commit:

- Alpaca API keys or secrets
- `.env`
- `.data/`
- raw Alpaca API responses
- downloaded OHLCV data
- broker/account identifiers
- private financial data
