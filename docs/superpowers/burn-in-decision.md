# Graywind Phase 1 — Paper-Trading Burn-In Decision

**Date:** 2026-08-14

**Backtest results this decision is based on** (from `run_backtest`, Task 11 Step 5,
`scripts/task11_integration_run.py`):
- Sharpe Ratio: 5.209
- Max Drawdown: 0.014
- Win Rate: 0.667
- Total trades: 12
- Final equity: 10397.95
- Equity curve points: 260
- PDT compliance: True

**Decision:** the burn-in clock does not start yet. Before any burn-in period is counted,
Graywind must first run Task 12's live loop against **real Alpaca paper-trading
credentials** (real market data, real VIX/sentiment/earnings gate calls — not stubs) for
a minimum of **4 weeks of live paper trading, or 20 real trades, whichever comes later**,
with no PDT violations and no unhandled exceptions during that window. Only once that
real-data burn-in has run and produced its own trade log and equity curve should Phase 2
(ML) or Phase 3 (real capital) work begin — and even then, gated on that real-data
performance, not on the numbers above.

**Rationale:** The Sharpe (5.209), win rate (0.667), and trade count (12) above are not
evidence of trading edge and must not be treated as such. Three facts about how this run
was produced disqualify it as a performance signal: (1) it ran against a hand-constructed
synthetic oscillating price series, not real AAPL/SPY market data, so the trades reflect
how the strategy behaves against invented prices, not real market behavior; (2) the three
signal-augmentation gates (VIX, sentiment, earnings) were stubbed to always pass, since no
real FRED/Alpaca-News/Finnhub credentials were available, so this run says nothing about
how those gates would actually filter trades in production; (3) the equity curve is
realized-P&L-only (open positions are never marked to market), which compresses variance
and mechanically inflates annualized Sharpe — the 5.209 figure is best read as confirming
the earlier stats-scale bug is fixed, not as a risk-adjusted-return estimate. What Task 11
*did* genuinely prove — through two rounds of real bugs found and fixed by actually running
the code, not just reviewing it — is that the pipeline runs end-to-end, the PDT throttle is
correctly enforced, and the stop/target/position-sizing math is correct. That is a
mechanical-correctness result, not a trading-viability result. Trading viability can only be
assessed once the pipeline runs on real market data and real gate calls, which requires
Task 12's live loop with actual credentials. Hence the burn-in period is defined to start
only when that real-data run begins, sized to 4 weeks / 20 trades so it spans varied
day-to-day conditions rather than a lucky short window, and Phase 2/3 work is blocked until
that real-data burn-in — not the synthetic backtest — clears its own bar.
