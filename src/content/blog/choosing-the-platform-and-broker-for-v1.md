---
title: 'Choosing the Platform and Broker for V1'
description: 'Why the first implementation path starts with a direct broker API and keeps Wealthsimple plus SnapTrade as a fallback.'
pubDate: '2026-06-24T12:00:00-06:00'
heroImage: '../../assets/trade-in-public-hero.png'
---

The first platform decision for this project is simple: **use a direct broker API first, starting with IBKR Canada verification**.

Wealthsimple through SnapTrade stays on the board as a fallback because I already have a Wealthsimple account, but it should be treated as an execution/account-state path rather than a complete trading platform.

## Why Direct Broker API First

For V1, I care more about operational clarity than convenience. The system needs to place orders, read positions, understand order state, recover from failure, and explain what happened after the fact.

That pushes the first implementation path toward a broker with an official API, paper or simulated execution support, limit orders, broker-native stop handling, and reliable order lifecycle visibility.

## Why IBKR Canada Is the Baseline Candidate

IBKR Canada is the baseline candidate because it has an established API path, supports the kind of order handling this project needs, and is more suitable for a serious automation workflow than a consumer-first app with limited execution testing.

This does not mean the decision is final. It means IBKR is the first path worth verifying deeply.

## Where Wealthsimple and SnapTrade Fit

Wealthsimple through SnapTrade is still useful as a fallback lane. The important constraint is that Wealthsimple market quotes through SnapTrade are delayed, so this combination would need separate realtime market data for signal generation and execution decisions.

That split is acceptable architecturally: market data and broker execution do not have to come from the same system.

The bigger concerns are execution testing, stop-order behavior, idempotency, and how safely the app can recover from retries or partial failures.

## Current Decision

V1 starts with direct broker API verification, using IBKR Canada as the baseline. Wealthsimple plus SnapTrade remains a fallback, but only with external realtime data and extra order-safety design.

Personal build log. Not financial advice.
