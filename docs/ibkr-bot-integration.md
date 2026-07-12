# IBKR Bot Integration

This document is the reusable foundation for building Interactive Brokers (IBKR)
trading bots in this project. It covers how to connect, resolve contracts, read
market data, place and manage orders, and run a bot unattended — independent of
any specific strategy.

This is an engineering and learning project, not financial advice. Everything
below should be validated on a **paper account first**.

> Contains no account numbers, usernames, or credentials by design. Keep those in
> environment variables or the macOS Keychain, never in this repo.

## TL;DR — the recommended stack

| Concern | Choice | Why |
|---------|--------|-----|
| Gateway | **IB Gateway** (not TWS) | Headless, lightweight, built for API-only automated trading. |
| Auto login / restart | **[IBC](https://github.com/IbcAlpha/IBC)** | Automates the login form and IB's forced daily restart. No headless-browser scraping. |
| Python library | **`ib_async`** | Maintained fork of the (now end-of-life) `ib_insync`. Same API. |
| Supervision | **`Watchdog`** (ships with `ib_async`) | Starts IBC + Gateway, monitors the connection, reconnects, and restarts on failure. |
| Process manager | **launchd** (macOS) | Native, survives reboots, restarts on crash. Preferred over `nohup`/`tmux`/cron. |

Why not the alternatives:

- **TWS (the desktop GUI) + API** works, but the GUI is heavy and still needs a
  human for login/2FA. Use IB Gateway for bots.
- **Client Portal Web API (REST, port 5000)** is usable but its session expires
  daily and must be re-authenticated through a **browser login** — which forces a
  fragile headless-browser automation just to log in. Documented as a fallback in
  the appendix, not the primary path.

## 1. Ports and account types

Get this right first — a wrong port is the most common cause of a connection
"timeout."

| Application | Live port | Paper port |
|-------------|-----------|------------|
| **IB Gateway** | `4001` | **`4002`** |
| TWS (desktop) | `7496` | `7497` |

Default for bots: **IB Gateway paper = `127.0.0.1:4002`**. Only move to a live port
after a deliberate safety review.

## 2. One-time API configuration

In IB Gateway (or TWS) → **Configuration → API → Settings**:

- ✅ **Enable ActiveX and Socket Clients**
- ✅ Add `127.0.0.1` to **Trusted IPs**
- Set the **Socket port** to match the table above.
- Leave **Read-Only API** ✅ on until your bot is proven; turn it off only when you
  intend to actually place orders.
- Optionally ✅ **Allow connections from localhost only**.

If `connect()` hangs and times out, check these in order: wrong port → API not
enabled → IP not trusted → a stale connection already holding your `clientId`.

## 3. Install

```bash
uv add ib_async
# IBC is a separate download: https://github.com/IbcAlpha/IBC/releases
```

`ib_async` replaces the archived `ib_insync`. The import surface is the same, so
older `ib_insync` examples translate directly.

## 4. Headless login with IBC + Watchdog

IBC drives the Gateway login form and handles IB's mandatory daily restart. Store
credentials outside the repo. `Watchdog` ties IBC, the Gateway, and reconnection
together so a bot can run for days unattended.

```python
import os
from ib_async import IB, IBC, Watchdog

# Credentials come from the environment (or Keychain), never from source.
ibc = IBC(
    twsVersion=1030,           # your installed Gateway major version
    gateway=True,              # run IB Gateway, not the full TWS GUI
    tradingMode="paper",       # "paper" or "live"
    userid=os.environ["IB_USERNAME"],
    password=os.environ["IB_PASSWORD"],
)

ib = IB()
watchdog = Watchdog(ibc, ib, port=4002, clientId=1)
watchdog.start()   # launches Gateway via IBC, connects, and keeps reconnecting
ib.run()           # hand control to the event loop
```

Notes:
- **2FA:** IBKR enforces two-factor auth. Paper accounts can run without the mobile
  IB Key challenge; live accounts generally cannot be fully unattended. Plan live
  operations around a supervised login, not a screen-scraper.
- **Daily restart:** IB force-restarts the Gateway once a day. IBC re-logs-in and
  Watchdog reconnects automatically — this is the whole point of the stack.
- Read credentials from the macOS Keychain if you prefer:
  `security find-generic-password -a "$IB_USERNAME" -s "your-service" -w`.

## 5. Connect (without Watchdog, for tests)

For quick scripts or the test harness you can connect directly to an
already-running Gateway:

```python
from ib_async import IB

ib = IB()
ib.connect("127.0.0.1", 4002, clientId=1, timeout=15)
print(ib.isConnected(), ib.managedAccounts())
```

- **`clientId`** must be unique per concurrent connection. A "timeout" often means
  another process is holding the same id.
- Keep one long-lived connection per process; don't reconnect per request.

## 6. Contract resolution — never hardcode a conId

A hardcoded futures `conId` expires. Resolve the **front month dynamically** every
session so the bot rolls automatically.

```python
from ib_async import Future

def front_month_future(ib, symbol="MES", exchange="CME", currency="USD"):
    """Return the qualified nearest-expiry (front-month) futures contract.

    IBKR returns every listed expiry for a symbol; we pick the soonest one that
    has not yet expired so the bot rolls to the next contract on its own.
    """
    details = ib.reqContractDetails(
        Future(symbol, exchange=exchange, currency=currency)
    )
    # contractDetails are unordered; sort by expiry date string (YYYYMMDD).
    contracts = sorted(
        (d.contract for d in details),
        key=lambda c: c.lastTradeDateOrContractMonth,
    )
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    front = next(c for c in contracts if c.lastTradeDateOrContractMonth >= today)
    ib.qualifyContracts(front)  # fills in conId, multiplier, exchange
    return front
```

For stocks it's simpler:

```python
from ib_async import Stock
spy = ib.qualifyContracts(Stock("SPY", "SMART", "USD"))[0]
```

`qualifyContracts` is also the quickest connectivity smoke test: if it returns a
`conId`, your login and market-data entitlements are working.

## 7. Sessions and time — always use a real timezone

Do **not** hardcode a UTC offset like `timezone(timedelta(hours=-4))`. That is EDT
only; it silently breaks by one hour after the DST change and every
session-boundary decision (opening range, flatten time, bar filtering) goes wrong.

```python
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")   # handles EDT/EST automatically
def now_et():
    return datetime.now(ET)
```

Regular US equity/index-futures RTH is 09:30–16:00 ET. Let `zoneinfo` do the DST
math; convert bar timestamps into ET the same way.

## 8. Market data

```python
# Snapshot / streaming quote
ticker = ib.reqMktData(contract, "", snapshot=False)
ib.sleep(1)                      # let the first tick arrive
print(ticker.last, ticker.bid, ticker.ask)

# Historical bars (e.g. 5-min RTH bars for today)
bars = ib.reqHistoricalData(
    contract,
    endDateTime="",             # "" = up to now
    durationStr="1 D",
    barSizeSetting="5 mins",
    whatToShow="TRADES",
    useRTH=True,
    formatDate=1,
)
```

Gotchas:
- **Act on the last _completed_ bar, not the forming one.** With `keepUpToDate`
  off, the final element can still be the in-progress bar. Use the second-to-last
  bar, or filter by a closed timestamp, before evaluating a "candle close" signal.
- **Entitlements:** live quotes on futures/indices may need a market-data
  subscription. On paper you may see delayed data; call
  `ib.reqMarketDataType(3)` to explicitly request delayed if needed.
- Request a little **more history than you need** and filter locally — the first
  bars of a session can lag right after the open.

## 9. Orders — use brackets, not two loose orders

The single most important order rule: an entry with a stop and a target must be a
**bracket / OCA group** so that filling one exit cancels the other. Two independent
`STP` and `LMT` orders will leave a live order behind after one fills, which can
flip you into an unintended opposite position.

```python
# Bracket = parent entry + take-profit (LMT) + stop-loss (STP), all OCA-linked.
bracket = ib.bracketOrder(
    action="BUY",
    quantity=1,
    limitPrice=entry_price,      # parent entry
    takeProfitPrice=tp_price,
    stopLossPrice=sl_price,
)

# For a market entry instead of a limit entry:
bracket.parent.orderType = "MKT"
del bracket.parent.lmtPrice    # MKT parent carries no limit price

for order in bracket:          # parent, takeProfit, stopLoss
    ib.placeOrder(contract, order)
```

`bracketOrder` puts the two children in a shared OCA group and marks the parent as
non-transmitting until the children are attached, so IBKR treats them as one unit.

Simple one-off orders:

```python
from ib_async import MarketOrder, LimitOrder, StopOrder
trade = ib.placeOrder(contract, MarketOrder("BUY", 1))
# LimitOrder("SELL", 1, price) / StopOrder("SELL", 1, stopPrice)
```

## 10. Order and fill lifecycle

`placeOrder` returns a `Trade` object that updates in place. Wait on events rather
than polling and guessing field names.

```python
trade = ib.placeOrder(contract, MarketOrder("BUY", 1))

def on_fill(trade, fill):
    print("filled", fill.execution.shares, "@", fill.execution.price)

trade.fillEvent += on_fill
ib.sleep(2)
print(trade.orderStatus.status)     # 'Filled', 'Cancelled', 'Submitted', ...
print(trade.filled(), trade.remaining())
```

If a fill can't be confirmed, **do not invent a fill price** to size stops off of —
cancel/flatten and surface the error instead. A fabricated entry price silently
corrupts all downstream risk math.

## 11. Account and positions

```python
account = ib.managedAccounts()[0]

# Positions across the account
for p in ib.positions():
    print(p.contract.localSymbol, p.position, p.avgCost)

# Account values (net liq, buying power, etc.)
values = {v.tag: v.value for v in ib.accountSummary()}
print(values.get("NetLiquidation"), values.get("BuyingPower"))
```

On startup, **read existing positions before trading** and reconcile against your
own state so a restart doesn't double up (see §12).

## 12. Reliability patterns

- **State persistence.** Write a small JSON/SQLite state file keyed by date
  (e.g. `{"date": "2026-07-11", "trade_taken": true, "entry": 7530.25}`). On
  startup, load it *and* verify against live positions/orders. Don't rely on
  in-memory flags — a crash-restart resets them and can re-enter a trade.
- **Idempotent orders.** Set a stable client order id / `orderRef` so you can
  recognize your own orders after a restart instead of duplicating them.
- **Reconnection.** Use `Watchdog` (§4). Handle `ib.disconnectedEvent` /
  `ib.connectedEvent` if you need custom recovery.
- **Process supervision (macOS launchd).** Prefer a `launchd` agent over
  `nohup`/`tmux`/cron: it restarts on crash and survives reboot. Sketch:

  ```xml
  <!-- ~/Library/LaunchAgents/com.example.ibkr-bot.plist -->
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key>
  <array><string>/path/to/.venv/bin/python</string><string>/path/to/bot.py</string></array>
  ```

- **Holiday/half-day awareness.** A plain weekday schedule will run on exchange
  holidays. Gate on an exchange calendar, or have the bot no-op when the market is
  closed.

## 13. Safety gates (do these in order)

1. **Read-only first.** Run with the Gateway's Read-Only API on, or a
   `read_only` flag that logs intended orders without sending them.
2. **Paper account** (port `4002`) until the strategy and plumbing are proven.
3. **Preview margin/commission** with a what-if order before the first live order.
4. **Confirm trading permissions.** An account provisioned for stocks/options only
   (e.g. a `STKNOPT` permission profile) will have **futures orders rejected** on a
   live account even if paper appears to allow them. Verify permissions per
   instrument before going live.
5. **Kill switch + flatten-on-exit.** On shutdown/crash, cancel working orders and
   optionally flatten, so you never leave an unmanaged position.
6. **Live review.** Live credentials, storage, and 2FA deserve a separate review
   from paper.

## 14. Gotchas checklist

Hard-won items to check on every new bot:

- [ ] Port matches account type (paper Gateway = `4002`).
- [ ] "Enable ActiveX and Socket Clients" on; `127.0.0.1` trusted.
- [ ] Unique `clientId`.
- [ ] Timezone via `zoneinfo`, **not** a fixed UTC offset.
- [ ] Front-month contract resolved dynamically, not a hardcoded `conId`.
- [ ] Signals evaluated on the **closed** bar.
- [ ] Exits placed as a **bracket / OCA**, not two loose orders.
- [ ] No fabricated fill prices; fail safe instead.
- [ ] State persisted and reconciled against live positions on startup.
- [ ] Credentials in env/Keychain; no account IDs or secrets in the repo.

## Appendix — Reference Setup Log (macOS)

This is a concrete log of one real setup of the §1–§13 stack, kept so the same
setup can be reproduced quickly on another machine (e.g. a new VM). It records
what was actually installed and configured, not new guidance — for the
reasoning, see the sections above. No credentials or account-specific values
are recorded here; treat version numbers as "known good at time of writing" and
prefer whatever is current when repeating this.

### What's global vs. per-bot

Get this distinction right before starting: IBC keeps **one** Gateway process
alive and logged in on one port. Every bot is just a separate API client
(distinct `clientId`) connecting to that same instance — bots do not each get
their own Gateway/IBC.

| Component | Scope | Location used here |
|---|---|---|
| IB Gateway app | Global (one per machine) | `~/Applications/IB Gateway <version>/` |
| IBC | Global (one per machine/account) | `~/ibc/` — **not** nested inside any bot's project folder |
| Python env for `ib_async` | Per-bot project | `<bot-project>/.venv`, created with `uv` |
| Bot source, `config.yaml`, logs | Per-bot project | the bot's own repo/folder |

### 1. Install IB Gateway

- Download the standalone macOS installer (stable channel):
  `https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-macosx-x64.dmg`
- Mount the `.dmg` and run `IB Gateway <version> Installer.app`. It's an
  install4j GUI wizard — click through it (license, default install location).
  Default install path is `~/Applications/IB Gateway <version>/`.
- Verify: the app bundle exists at that path, and `~/Jts/jts.ini` (shared with
  TWS if installed) shows `tradingMode=p` for paper.
- Version installed here: **IB Gateway 10.45**.

### 2. Install IBC (global)

- Get the latest macOS release from
  `https://github.com/IbcAlpha/IBC/releases` (asset `IBCMacos-<version>.zip`).
- Extract to **`~/ibc`** — this is IBC's own documented default path, and
  keeping it there (not inside a bot's folder) is what makes it obviously
  shared infrastructure rather than owned by one bot.
- `chmod +x ~/ibc/*.sh ~/ibc/scripts/*.sh`
- `mkdir -p ~/ibc/logs`
- Version installed here: **IBC 3.24.1**.

### 3. Configure `~/ibc/config.ini`

The downloaded template ships with IBKR's public demo placeholder
(`IbLoginId=edemo` / `IbPassword=demouser`). Changes made:

| Setting | Value set | Why |
|---|---|---|
| `IbLoginId` / `IbPassword` | cleared to blank | Never store real credentials in this file from an automated session — fill these in by hand. IBC falls back to prompting in the normal login dialog if left blank. |
| `TradingMode` | `paper` | Matches the account being connected to. |
| `AcceptNonBrokerageAccountWarning` | `yes` | Auto-dismisses the paper-account disclaimer dialog so headless startup doesn't hang waiting for a click. |
| `AcceptIncomingConnectionAction` | `accept` | Auto-accepts the API incoming-connection popup so `ib_async` can connect without a manual click each time. |

### 4. Configure `~/ibc/gatewaystartmacos.sh`

Set these variables near the top of the script:

```bash
TWS_MAJOR_VRSN=10.45     # must match the installed Gateway's major version
IBC_INI=~/ibc/config.ini
TRADING_MODE=paper
TWOFA_TIMEOUT_ACTION=exit
IBC_PATH=~/ibc
TWS_PATH=~/Applications
LOG_PATH=~/ibc/logs
```

`TWS_MAJOR_VRSN` must match whatever Gateway version actually got installed —
check the folder name under `~/Applications`, or Gateway's own
Help → About once it's running.

### 5. Start it

```bash
~/ibc/gatewaystartmacos.sh
```

This opens a new Terminal window, starts Gateway, and IBC drives the login
form (or leaves it for manual entry if credentials are blank in `config.ini`).
Confirm it came up from another terminal:

```bash
lsof -iTCP -sTCP:LISTEN -P | grep 4002
```

### 6. Python environment for `ib_async`

`ib_async` requires Python **≥3.10** — don't assume the Python already used by
an existing bot script satisfies this (a bot originally written against
`ib_insync` may be running on an old system Python 3.9). Use `uv` to create an
isolated venv scoped to that bot project:

```bash
cd <bot-project-dir>
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ib_async pyyaml
```

Verify:

```bash
.venv/bin/python -c "from ib_async import IB; IB()"
```

### 7. Optional: launchd auto-start (not enabled by default)

`~/ibc/local.ibc-gateway.plist` is IBC's example launchd template. It's left
in place with paths filled in for this machine, but **not copied into
`~/Library/LaunchAgents` or loaded** — review its `StartCalendarInterval`
schedule before enabling anything. To activate it later:

```bash
cp ~/ibc/local.ibc-gateway.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/local.ibc-gateway.plist
```

## Appendix — Client Portal Web API (fallback)

Only if the socket API is unavailable. It speaks REST on `https://localhost:5000`
through the Client Portal Gateway, and its session must be re-authenticated via a
**browser login** roughly daily.

Field/behavior quirks observed in practice (they differ from the socket API):

- Responses mix **snake_case and camelCase** — read both, e.g.
  `item.get("order_id") or item.get("orderId")`, and
  `status.get("order_status") or status.get("orderStatus")`.
- Stop orders use the **`price`** field for the trigger, **not** `auxPrice`.
- Contract search returns the **index (IND)** conId for a futures symbol; resolve
  the tradable **FUT** conId via `/iserver/secdef/info` with the specific month.
- Snapshots can return empty on the first call — request again, and mind the
  numeric field ids you ask for vs. the ones you read back.
- **Order confirmation replies:** a placed order often returns a message
  (`{id, message:[...]}`) that must be confirmed with a POST to
  `/iserver/reply/{id}` before it transmits. Skipping this silently drops orders.
- **Rate limiting (HTTP 429):** throttle rapid calls; batch fewer snapshot fields.
- Keep the session alive with `/tickle`; watch `authenticated` / `established` /
  `connected` and re-auth when they drop, even if the web SSO still looks alive.

For anything new, prefer the socket-API path in §1–§13.
