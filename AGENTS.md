## Development

Before implementation work, read the public architecture docs first:

- `docs/architecture/python-trading-system-foundation.md`
- `docs/architecture/service-map.md`
- `docs/architecture/implementation-principles.md`

## Python Workspace

Use the repo-level `uv` workspace for trading-system code.

Install/sync:

```
uv sync
```

Run tests:

```
uv run pytest
```

Run linting and formatting checks:

```
uv run ruff check .
uv run ruff format --check .
```

Format Python code:

```
uv run ruff format .
```

Run type checking:

```
uv run pyright
```

Package ownership:

- `packages/trade_core`: shared domain primitives only when later issues define them.
- `packages/trade_data`: market data ingestion and normalization boundaries.
- `packages/trade_strategies`: strategy definitions and decision modules.
- `packages/trade_analytics`: metrics, reporting, and reconciliation summaries.
- `packages/trade_brokers`: broker adapters and provider-specific integration.
- `apps/research`: research and backtesting entrypoint.
- `apps/execution`: paper/live execution entrypoint.
- `apps/reconcile`: planned-versus-actual reconciliation entrypoint.

Do not add trading behavior to scaffold packages without an implementation issue that defines the behavior. Keep private market data, broker exports, credentials, and backtest artifacts out of git.

## Astro Site

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
