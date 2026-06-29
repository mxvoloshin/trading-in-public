# IBKR Execution And Real-Time Data API Shape

Date: 2026-06-29

Issue: [#10](https://github.com/mxvoloshin/trading-in-public/issues/10)

## Decision

Use **IB Gateway or TWS locally with `ib_async`, against an IBKR paper account first**, as the v1 path for learning IBKR execution and live-state behavior.

This is a research decision, not a broker adapter implementation. The project should still stay backtest-first and keep the existing Alpaca historical data layer as the v1 backtesting source.

## Decision Summary

- Access path: TWS API through local TWS or IB Gateway.
- Python library for spikes: `ib_async`.
- Official fallback/reference: raw `ibapi` and IBKR's TWS API docs.
- First runtime: TWS while learning, because the UI helps inspect contracts, orders, account state, and market data behavior.
- Later runtime: IB Gateway for automation-like paper/live operation.
- First account mode: paper trading only.
- Market data expectation: delayed data may be enough for API-shape learning; live data depends on permissions, subscriptions, and paper/live login behavior.
- Historical data expectation: useful for small broker-side checks, not the v1 backtesting data source.
- Adapter implication: keep IBKR concepts inside `trade_brokers` until issue #11 decides the shared core boundary.

## Why This Path

IBKR's TWS API is a socket protocol exposed through either Trader Workstation or IB Gateway. IBKR documents that API clients connect to one of those local host platforms, and that TWS and IB Gateway expose the same API surface, with Gateway being lighter because it has no full trading UI ([IBKR Campus TWS API docs](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/)).

`ib_async` is the best v1 Python spike dependency because it keeps the work close to IBKR concepts while reducing the raw callback/threading burden. IBKR still advises direct TWS API usage where possible, but its docs note that original `ib_insync` is legacy/no longer updated and point users toward `ib_async` for a modernized implementation of that style ([IBKR Campus](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/), [`ib_async` docs](https://ib-api-reloaded.github.io/ib_async/)).

Raw `ibapi` remains the reference model for exact callback names, event ordering, request fields, and reconnect behavior. Use it to understand the broker surface, not as the first implementation path unless `ib_async` hides something important.

## Runtime Setup Shape

The normal TWS API path is not a direct cloud REST connection. A local process must be running:

- Trader Workstation, or
- IB Gateway.

Recommended learning sequence:

1. Run TWS in paper mode.
2. Enable socket/API access in TWS settings.
3. Use a unique client ID per local process.
4. Keep API access read-only until intentionally testing paper order submission.
5. Use `ib_async` for Python research scripts.
6. Move to IB Gateway only after the connection, market data, order, and reconnect shapes are understood.

IBKR notes that TWS/IB Gateway sessions require user authentication and are designed around periodic restarts/reauthentication rather than a simple always-on headless cloud service ([IBKR Campus TWS API docs](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/)). A future execution app must therefore treat broker connectivity as a runtime dependency with health checks, reconnect handling, and clear operator visibility.

## Paper Trading Scope

IBKR paper accounts can be used with the Web API and TWS API with minimal functional differences compared with live use, but paper trades are simulated by IBKR's simulator ([IBKR paper trading glossary](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/)).

Paper trading is appropriate for learning:

- connection readiness
- contract lookup
- market data permission behavior
- order submission mechanics
- order status callbacks/events
- execution/fill event shape
- commission report shape
- position and account query shape

Paper trading is not enough to validate:

- real fill quality
- real market impact
- live slippage
- all order-type behavior
- clearing or settlement behavior
- production reliability

IBKR documents paper limitations including unsupported order types, top-of-book simulated fills, limited combo behavior, and simulator differences for stops and complex order types ([IBKR paper trading glossary](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/)).

## Market Data Shape

### Live Market Data

IBKR live market data requires trading permissions, a funded account where applicable, and market data subscriptions for the requested username. IBKR also documents market data line limits, which matter for real-time top-of-book requests, market depth, and real-time bars ([IBKR market data docs](https://interactivebrokers.github.io/tws-api/market_data.html)).

Paper users can share live market data subscriptions from the live username, but IBKR documents restrictions around subscription sharing and simultaneous live/paper login use ([IBKR market data docs](https://interactivebrokers.github.io/tws-api/market_data.html)).

Project implication:

- Do not assume live IBKR market data exists in paper mode.
- Make the future IBKR spike report which data mode was received.
- Keep live market data permissions out of generic strategy code.

### Delayed Data

IBKR supports 10-15 minute delayed streaming data for many instruments without market data subscriptions. The API defaults to real-time market data mode; delayed mode is requested with `reqMarketDataType`, and live data is returned instead when live data is available ([IBKR delayed data docs](https://interactivebrokers.github.io/tws-api/delayed_data.html)).

Project implication:

- Delayed data is acceptable for API-shape learning.
- Delayed data is not a substitute for live execution logic.
- A future spike should explicitly log the requested and observed market data mode in redacted form.

### Real-Time Bars

IBKR real-time bars are requested through `reqRealTimeBars`. IBKR documents them as an active subscription returning one OHLC bar every five seconds, and the request can only use a five-second bar size ([IBKR real-time bars docs](https://interactivebrokers.github.io/tws-api/realtime_bars.html)).

Project implication:

- IBKR real-time bars are not the same shape as the existing 5-minute Alpaca historical bars.
- If the project needs live 5-minute bars later, it should aggregate broker live events into a project-owned live bar shape instead of pretending the broker provides the same stream as the backtest data source.

### Historical Bars

IBKR historical bars use `reqHistoricalData`, with request dimensions such as contract, end date/time, duration, bar size, data type such as `TRADES` or `MIDPOINT`, `useRTH`, date format, and `keepUpToDate` ([IBKR historical bars docs](https://interactivebrokers.github.io/tws-api/historical_bars.html)).

IBKR also documents historical data pacing limits, simultaneous request limits, step-size constraints, and explicitly advises specialized market data providers when a strategy's data requirements are not met by IBKR market data services ([IBKR historical limitations docs](https://interactivebrokers.github.io/tws-api/historical_limitations.html)).

Project implication:

- Keep Alpaca as the v1 backtesting historical data source.
- Use IBKR historical bars only for small broker-side sanity checks, short live lookbacks, or parity comparisons.
- Do not build broad intraday backfills on IBKR historical data.

### Timestamp And Session Implications

IBKR historical bars expose broker-specific timestamp/session behavior through request options such as `useRTH`, bar size, `whatToShow`, and historical schedule responses. The project should normalize broker timestamps into project-owned timezone-aware records before they cross an adapter boundary.

Project rule:

- IBKR timestamp strings and session flags must not leak into strategy-facing or backtest-facing models.
- If IBKR bars are used later, store source metadata separately from normalized project bars.

## Order Shape

### Submission

IBKR orders are submitted with `placeOrder`, a `Contract`, an `Order`, and an API order ID. IBKR documents that after correct submission, TWS sends order activity through `openOrder` and `orderStatus` callbacks/events ([IBKR order submission docs](https://interactivebrokers.github.io/tws-api/order_submission.html)).

For v1 stock/ETF research, the minimum contract fields to understand are:

- symbol
- security type, usually `STK`
- exchange/routing, often `SMART`
- currency, usually `USD`
- primary exchange when needed to disambiguate

The minimum order fields to understand are:

- action: `BUY` or `SELL`
- order type: `MKT`, `LMT`, `STP`, or `STP LMT`
- quantity
- limit price when applicable
- stop price when applicable
- time in force, for example `DAY` or `GTC`
- outside regular trading hours flag, if intentionally supported later

Do not start with advanced order types, options, combos, shorting, margin-specific flows, or broker algos.

### Identifiers

IBKR has several IDs that should not be collapsed into one project field:

- client ID: identifies the API client connection.
- API order ID: the client-side order sequence used with `placeOrder`.
- `permId`: a broker/TWS permanent order identifier.
- `execId`: an execution identifier for a fill or partial fill.
- request/ticker IDs: request-local correlation IDs for market data and other API calls.

IBKR documents `nextValidId` as the source for the next API order ID, notes that the identifier is persistent between TWS sessions, and shows order placement examples that increment the ID locally ([IBKR order submission docs](https://interactivebrokers.github.io/tws-api/order_submission.html)).

Project implication:

- A future adapter must persist both project-owned IDs and broker IDs.
- `permId` and `execId` are reconciliation facts, not backtesting concepts.
- Multiple API clients or manual TWS orders can complicate order ID behavior.

## Status, Fill, And Commission Shape

### Order Status

Active orders are returned through `openOrder`, `orderStatus`, and `openOrderEnd` events. IBKR documents that open-order queries cannot obtain cancelled or fully filled orders ([IBKR open orders docs](https://interactivebrokers.github.io/tws-api/open_orders.html)).

Project implication:

- Open-order query is not a complete recovery mechanism.
- The execution system must persist its own order state and reconcile broker facts later.
- A future normalized status model should be broker-informed but not a copy of IBKR status strings.

Likely project-owned status buckets for later design:

- pending submit
- submitted/open
- partially filled
- filled
- cancelled
- rejected/inactive
- unknown/reconcile needed

### Executions And Commissions

When an order fills fully or partially, IBKR delivers execution details and commission reports through separate events: `execDetails` and `commissionReport` ([IBKR executions and commissions docs](https://interactivebrokers.github.io/tws-api/executions_commissions.html)).

Project implication:

- A fill may exist before commission is known.
- Commission should be joined later by execution identity, not required at fill-record creation time.
- Execution handling must be idempotent by execution ID.
- A future persistence model should allow corrections or late-arriving fee data.

### Reconnect And Event Ordering

Important recovery concerns:

- API calls before readiness can be dropped or fail silently if the app assumes a connection is healthy too early.
- The Python API starts a reader thread after connection, but callback processing still depends on the client run loop and broker events ([IBKR connection docs](https://interactivebrokers.github.io/tws-api/connection.html)).
- `nextValidId` and `managedAccounts` are among the events received after connection completion ([IBKR connection docs](https://interactivebrokers.github.io/tws-api/connection.html)).
- Order status, execution, and commission are separate event streams.
- Fully filled and cancelled orders are not recovered by open-order queries.
- Real-time bar subscriptions may need to be recreated after reconnects or session resets.

Minimum state to persist before any serious paper/live execution:

- local order intent ID
- submitted contract identity
- submitted order parameters
- broker client ID
- API order ID
- `permId` when known
- latest known order status
- normalized status events
- execution IDs
- fill quantities, prices, and timestamps
- commission reports when received
- broker session metadata, excluding secrets

## Account And Portfolio Shape

IBKR exposes account summary, account update, and position subscription/query methods. The `reqAccountSummary` method returns selected account summary tags, while `reqAccountUpdates` and `reqPositions` provide account/portfolio and position updates ([IBKR EClient reference](https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClient.html)).

Sensitive account fields can include:

- account code
- cash balances
- buying power
- net liquidation
- margin values
- currency balances
- realized or unrealized P&L
- position quantities and values

Project implication:

- Account and position data are broker-reported current state, not the source of strategy history.
- Runtime risk checks may need account data later, but public logs must redact it aggressively.
- Never commit raw account summary, position, execution, or commission payloads.

## Public Safety Rules

Never commit:

- IBKR usernames or passwords
- account IDs or account aliases
- paper or live credentials
- API host/port/client ID values from a private machine
- raw account summary responses
- raw position snapshots
- raw order/execution/commission logs
- real or paper order IDs
- `permId` values
- `execId` values
- cash, buying power, net liquidation, margin, or holdings
- broker screenshots

Repo-safe configuration example:

```text
IBKR_MODE=paper
IBKR_HOST=127.0.0.1
IBKR_PORT=<local-port-from-user-env>
IBKR_CLIENT_ID=<local-client-id-from-user-env>
```

Commit `.env.example` only when a future issue actually adds an IBKR spike command. Do not commit `.env`.

## Boundary Implications

### Keep Inside `trade_brokers`

These are IBKR-specific and should stay behind a broker adapter:

- TWS/IB Gateway connection management
- socket host, port, and client ID
- `ib_async`, `ib_insync`, or raw `ibapi` objects
- IBKR `Contract`
- IBKR `Order`
- IBKR `Trade`
- callback/event types
- request IDs and ticker IDs
- API order ID sequencing
- `permId`
- `execId`
- raw commission report shape
- raw account summary tags
- market data subscription mode
- `useRTH`
- `whatToShow`
- market data line and pacing behavior
- reconnect and resubscribe mechanics

### Candidate Project-Owned Concepts

Issue #11 should decide whether these become shared domain concepts, broker-facing records, analytics records, or app-local types:

- `BrokerConnectionStatus`
- `BrokerAccountRef`, redacted in logs
- `InstrumentRef`
- `OrderIntent`
- `OrderRequest`
- `SubmittedOrder`
- `BrokerOrderId`
- `OrderStatusSnapshot`
- `OrderStatusEvent`
- `Fill`
- `Commission`
- `PositionSnapshot`
- `CashSnapshot`
- `BrokerClock`
- `BrokerMarketDataBar`
- `BrokerMarketDataTick`
- `ReconciliationResult`

### Do Not Share Directly With Backtesting

These should not become shared backtest concepts:

- IBKR order statuses
- IBKR order IDs
- `permId`
- `execId`
- raw commission reports
- TWS connection lifecycle
- client ID
- open-order recovery behavior
- paper/live account differences
- market data subscription modes
- broker pacing rules
- account summary tags
- raw live tick/update events

Backtesting should stay focused on:

- historical bars
- strategy decisions
- simulated order intents
- simulated fills
- deterministic portfolio/account state
- strategy evaluation metrics

Live execution must handle:

- broker connectivity
- order acceptance/rejection
- partial fills
- late commission data
- real account permissions
- broker-reported positions and cash
- runtime safety controls
- reconciliation against persisted intent

## Questions For Issue #11

Issue #11 should use this research to answer:

- What is the smallest shared concept between a backtest order and a live broker order?
- Should strategies emit `Signal`, `OrderIntent`, or broker-neutral `OrderRequest`?
- Should simulated fills and broker executions share one type, or map into a common reporting model later?
- Where should timestamp normalization happen?
- Should `Position` mean simulated position, broker-reported position, or two different concepts?
- What is the minimum interface between strategy and execution that does not leak broker lifecycle into backtests?
- How should backtest slippage/commission assumptions relate to real broker commissions?
- How should live reconciliation affect strategy state?
- What audit/event model preserves decision-to-fill traceability?
- What can be safely logged in a public repo?

## Recommended Follow-Up Issues

### Spike: Connect To IBKR Paper Account From Python

Scope:

- Install/run TWS or IB Gateway locally.
- Connect using `ib_async`.
- Verify connection readiness.
- Print redacted connection/account metadata only.
- Confirm paper vs live mode is visually obvious.
- Do not submit real trades.

### Spike: IBKR Contract Lookup For US Stocks/ETFs

Scope:

- Resolve basic stock/ETF contracts.
- Test SMART routing and primary exchange disambiguation.
- Store only public instrument metadata.
- Document failure cases for ambiguous symbols.

### Spike: IBKR Market Data Modes

Scope:

- Request delayed data.
- Request live data if subscriptions are available.
- Request historical bars for one or two symbols.
- Compare timestamp/session behavior.
- Confirm whether short 5-minute historical checks are available for the intended universe.
- Do not replace the existing Alpaca historical layer.

### Spike: Paper Order Lifecycle Event Capture

Scope:

- Submit tiny paper-only test orders only after Max explicitly approves that spike.
- Capture `openOrder`, `orderStatus`, `execDetails`, and `commissionReport`.
- Redact all account/order identifiers before committing examples.
- Document event ordering and partial-fill behavior if observed.
- Do not implement production trading.

### Design Note: Broker Execution Persistence Model

Scope:

- Define what must be persisted for order reconciliation.
- Include local order ID, broker order ID, `permId`, execution IDs, statuses, fills, and commission reports.
- Keep the design broker-informed but not IBKR-only.

### Safety Issue: Public Logging And Redaction Rules

Scope:

- Add logging rules for broker integrations.
- Define redaction helpers.
- Add tests that prevent account IDs, balances, order IDs, and execution IDs from appearing in logs.
- Document public-safe examples.

### Spike: Reconnect And Reconciliation Behavior

Scope:

- Disconnect/reconnect a paper session.
- Query open orders, executions, positions, and account state.
- Identify what is replayed versus missing.
- Define the minimum recovery flow.
- Do not build the final adapter yet.

## Source Notes

IBKR's older `interactivebrokers.github.io/tws-api` pages are marked as deprecated in favor of IBKR Campus, but they still expose useful method-level reference details for the TWS API. This research uses IBKR Campus for the current access-path guidance and uses the older reference pages only where method-level details are clearer.

Primary sources:

- IBKR Campus TWS API documentation: <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/>
- `ib_async` documentation: <https://ib-api-reloaded.github.io/ib_async/>
- IBKR live market data: <https://interactivebrokers.github.io/tws-api/market_data.html>
- IBKR delayed data: <https://interactivebrokers.github.io/tws-api/delayed_data.html>
- IBKR historical bars: <https://interactivebrokers.github.io/tws-api/historical_bars.html>
- IBKR historical data limitations: <https://interactivebrokers.github.io/tws-api/historical_limitations.html>
- IBKR real-time bars: <https://interactivebrokers.github.io/tws-api/realtime_bars.html>
- IBKR order submission: <https://interactivebrokers.github.io/tws-api/order_submission.html>
- IBKR open orders: <https://interactivebrokers.github.io/tws-api/open_orders.html>
- IBKR executions and commissions: <https://interactivebrokers.github.io/tws-api/executions_commissions.html>
- IBKR connection behavior: <https://interactivebrokers.github.io/tws-api/connection.html>
- IBKR EClient reference: <https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClient.html>
- IBKR paper trading glossary: <https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/>
